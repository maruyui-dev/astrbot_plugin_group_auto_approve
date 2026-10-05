import asyncio
import time

#导入Astrbot模块以及第三方模块
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import aiohttp
from astrbot.api import ToolSet
from .agent_tools import (
    SetVerifySwitchTool,
    SetMinLevelTool,
    SetLevelRequiredTool,
    AddBlacklistTool,
    RemoveBlacklistTool,
    ClearBlacklistTool,
    AddWhitelistTool,
    RemoveWhitelistTool,
    ClearWhitelistTool,
    GetListsTool,
    GetConfigTool,
    GetReviewRecordsTool,
    ClearReviewRecordsTool,
    _is_group_admin
)
#导入项目内部模块
from .action import approve_group_request
from .message import (
    build_leave_message,
    build_leave_text,
    build_verify_chain,
    build_verify_message,
)
from .request import (
    download_avatar,
    download_group_avatar,
    handle_group_request,
    set_avatar_dir,
)
from .ai_verify import verify_by_llm
from .config import (
    get_group_cfg,
    save_all,
    init_config,
    set_webui_config,
    get_webui_config,
    in_blacklist,
    in_whitelist,
    add_to_list,
    remove_from_list,
    set_plugin_data_dir,
)
from .record_store import (
    clear_review_records,
    get_review_records,
    save_review_record,
    set_record_data_dir,
)
from .record_message import build_review_records_message, build_review_records_text

_DEDUP_CONTEXT_KEY = "_group_auto_approve_event_dedup_state"
_KICK_BATCH_CONTEXT_KEY = "_group_auto_approve_kick_batch_state"
_DEDUP_STATS_LOG_INTERVAL = 100
_RECORD_QUERY_KEYWORDS = ("审核记录", "申请记录", "查看记录")
# 出现这些词说明用户在改配置或名单，不能走固定格式的快捷回复
_CONFIG_QUERY_KEYWORDS = (
    "黑名单",
    "白名单",
    "名单",
    "等级",
    "开关",
    "开启",
    "关闭",
    "切换",
    "清空",
    "删除",
    "移除",
    "设置",
    "添加",
    "配置",
    "帮助",
    "help",
)


async def build_application_message(context, result, verify_result=None):
    """Build an application notification according to the image setting.

    Args:
        context: AstrBot plugin context.
        result: Parsed group application data.
        verify_result: Optional review result.

    Returns:
        A message component chain for the configured output mode.
    """
    if get_webui_config("send_images", True):
        return await build_verify_message(context, result, verify_result)
    return build_verify_chain(result, verify_result)


@register(
    "group_verify",
    "MaruYui",
    "QQ群自动入群审核插件",
    "1.8.0"
)
class MyPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self.plugin_config = config or {}
        dedup_state = getattr(context, _DEDUP_CONTEXT_KEY, None)
        if dedup_state is None:
            dedup_state = {
                "seen": {},
                "lock": asyncio.Lock(),
                "stats": {},
            }
            setattr(context, _DEDUP_CONTEXT_KEY, dedup_state)
        self._dedup_state = dedup_state
        batch_state = getattr(context, _KICK_BATCH_CONTEXT_KEY, None)
        if batch_state is None:
            batch_state = {"groups": {}, "lock": asyncio.Lock()}
            setattr(context, _KICK_BATCH_CONTEXT_KEY, batch_state)
        self._kick_batch_state = batch_state

    async def _is_duplicate_event(self, event: AstrMessageEvent, scope: str) -> bool:
        """Return whether an event was already handled recently.

        Args:
            event: AstrBot event to identify.
            scope: Independent handler scope, such as ``main`` or ``agent``.

        Returns:
            True when the same platform event was already seen in this scope.
        """
        raw_event = event.message_obj.raw_message
        now = time.monotonic()
        event_id = (
            raw_event.get("message_id")
            or raw_event.get("message_seq")
            or raw_event.get("request_id")
            or raw_event.get("flag")
        )
        event_keys = [
            (
                f"{scope}:content:{event.get_platform_id()}:"
                f"{raw_event.get('self_id')}:{event.get_group_id()}:"
                f"{event.get_sender_id()}:{raw_event.get('post_type')}:"
                f"{raw_event.get('request_type') or raw_event.get('notice_type')}:"
                f"{raw_event.get('sub_type')}:{raw_event.get('user_id')}:"
                f"{raw_event.get('operator_id')}:{raw_event.get('time')}:"
                f"{event.message_str.strip()}",
                5,
            )
        ]
        if event_id is not None:
            event_keys.append(
                (
                    f"{scope}:id:{event.get_platform_id()}:"
                    f"{raw_event.get('self_id')}:{event_id}",
                    60,
                )
            )

        async with self._dedup_state["lock"]:
            seen_events = self._dedup_state["seen"]
            seen_events = {
                key: (timestamp, ttl)
                for key, (timestamp, ttl) in seen_events.items()
                if now - timestamp < ttl
            }
            if any(
                (previous_event := seen_events.get(event_key))
                and now - previous_event[0] < previous_event[1]
                for event_key, _ in event_keys
            ):
                stats = self._dedup_state.setdefault("stats", {})
                stats[scope] = stats.get(scope, 0) + 1
                if stats[scope] % _DEDUP_STATS_LOG_INTERVAL == 0:
                    logger.info(
                        f"事件去重统计：{scope} 已拦截 {stats[scope]} 次重复事件"
                    )
                return True
            for event_key, dedup_ttl in event_keys:
                seen_events[event_key] = (now, dedup_ttl)
            self._dedup_state["seen"] = seen_events
        return False

    async def _queue_kick_event(self, event: AstrMessageEvent, raw_event: dict):
        """Collect nearby kick events and build one notification.

        Args:
            event: The first AstrBot event in the current batch.
            raw_event: Raw OneBot group decrease event.

        Returns:
            A message chain for the batch leader, or None for later events.
        """
        group_id = str(raw_event["group_id"])
        item = {
            "user_id": str(raw_event["user_id"]),
            "operator_id": str(raw_event.get("operator_id") or ""),
            "time": datetime.fromtimestamp(raw_event.get("time", 0)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }
        async with self._kick_batch_state["lock"]:
            batch = self._kick_batch_state["groups"].get(group_id)
            is_leader = batch is None
            if batch is None:
                batch = {
                    "count": 0,
                    "first_item": item,
                    "last_time": item["time"],
                    "operator_ids": set(),
                }
                self._kick_batch_state["groups"][group_id] = batch
            batch["count"] += 1
            batch["last_time"] = item["time"]
            if item["operator_id"]:
                batch["operator_ids"].add(item["operator_id"])

        if not is_leader:
            return None

        await asyncio.sleep(3)
        async with self._kick_batch_state["lock"]:
            batch = self._kick_batch_state["groups"].pop(group_id, None)
        if not batch:
            return None

        count = batch["count"]
        operator_ids = batch["operator_ids"]
        operator_id = next(iter(operator_ids), "")
        operator_nickname = ""
        if operator_id:
            try:
                operator_info = await event.bot.call_action(
                    "get_stranger_info",
                    user_id=operator_id,
                )
                operator_nickname = (
                    operator_info.get("nickname")
                    or operator_info.get("nick")
                    or operator_id
                )
            except Exception as error:
                logger.warning(f"获取批量移出操作人信息失败: {error}")
                operator_nickname = operator_id

        if count == 1:
            user_id = batch["first_item"]["user_id"]
            try:
                user_info = await event.bot.call_action(
                    "get_stranger_info",
                    user_id=user_id,
                )
            except Exception as error:
                logger.warning(f"获取退群者信息失败，将使用QQ号作为昵称: {error}")
                user_info = {}
            result = {
                "nickname": user_info.get("nickname")
                or user_info.get("nick")
                or user_id,
                "user_id": user_id,
                "group_id": group_id,
                "leave_time": batch["first_item"]["time"],
                "event_label": "被管理员移出",
                "operator_id": operator_id,
                "operator_nickname": operator_nickname,
                "status_color": "#c64d5c",
                "status_background": "#fff0f2",
            }
            if get_webui_config("send_images", True):
                result["avatar_path"] = await download_avatar(user_id)
                return await build_leave_message(result)
            return build_leave_text(result)

        result = {
            "group_id": group_id,
            "leave_time": batch["last_time"],
            "event_label": "批量移出",
            "operator_id": operator_id,
            "operator_nickname": operator_nickname,
            "status_color": "#c64d5c",
            "status_background": "#fff0f2",
            "is_batch": True,
            "count": count,
        }
        if get_webui_config("send_images", True):
            return await build_leave_message(result)
        return build_leave_text(result)

    async def initialize(self):
        plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_group_auto_approve")
        set_plugin_data_dir(plugin_data_dir)
        set_avatar_dir(plugin_data_dir)
        set_record_data_dir(plugin_data_dir)
        set_webui_config(self.plugin_config)
        init_config()
        logger.info(f"群组验证配置已加载，WebUI 配置：{self.plugin_config}")

    #=====================================================#
    #               事      件     监      听              #
    #=====================================================#
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def listen_event(self, event: AstrMessageEvent):
        if await self._is_duplicate_event(event, "main"):
            return
        raw_event = event.message_obj.raw_message
        if (
            raw_event.get("post_type") == "notice"
            and raw_event.get("notice_type") == "group_decrease"
        ):
            group_id = raw_event.get("group_id")
            user_id = raw_event.get("user_id")
            if not group_id or not user_id:
                logger.warning("退群事件缺少群号或用户QQ，无法生成退群通知")
                return

            if raw_event.get("sub_type") == "kick":
                message_chain = await self._queue_kick_event(event, raw_event)
                if message_chain:
                    yield event.chain_result(message_chain)
                return

            try:
                user_info = await event.bot.call_action(
                    "get_stranger_info",
                    user_id=user_id,
                )
            except Exception as error:
                logger.warning(f"获取退群者信息失败，将使用QQ号作为昵称: {error}")
                user_info = {}

            # sub_type 为 kick 的事件已在上方分支返回，这里只可能是自主退群
            leave_result = {
                "nickname": user_info.get("nickname")
                or user_info.get("nick")
                or str(user_id),
                "user_id": str(user_id),
                "group_id": str(group_id),
                "leave_time": datetime.fromtimestamp(
                    raw_event.get("time", 0)
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "event_label": "自主退群",
                "operator_id": "",
                "operator_nickname": "",
                "status_color": "#65758b",
                "status_background": "#eef1f5",
            }
            if get_webui_config("send_images", True):
                leave_result["avatar_path"] = await download_avatar(user_id)
                yield event.chain_result(await build_leave_message(leave_result))
            else:
                yield event.chain_result(build_leave_text(leave_result))
            return

        result = await handle_group_request(event)
        if result is None:
            return
        if not result.get("success"):
            yield event.plain_result(f"处理失败:{result.get('error')}")
            return

        group_id = result.get("group_id")
        group_cfg = get_group_cfg(group_id)

        # 本群接收申请开关
        if not group_cfg["REQUEST_CONFIG"]:
            return
        user_id = result.get("user_id")

        # 黑名单：直接拒绝，不走 AI
        if in_blacklist(group_cfg, user_id):
            reject_reason = "你在本群黑名单中"
            success = await approve_group_request(
                event,
                result.get("flag"),
                result.get("avatar"),
                approve=False,
                reason=reject_reason
            )
            if success:
                save_review_record(
                    group_id,
                    result.get("nickname"),
                    user_id,
                    result.get("comment"),
                    "未通过",
                    reject_reason,
                    get_webui_config("record_limit", 5),
                    result.get("time"),
                )
                yield event.chain_result(
                    await build_application_message(
                        self.context,
                        result,
                        {"passed": False, "reason": reject_reason}
                    )
                )
            else:
                yield event.plain_result("处理入群申请失败")
            return

        # 白名单：直接同意，不走 AI
        if in_whitelist(group_cfg, user_id):
            success = await approve_group_request(
                event,
                result.get("flag"),
                result.get("avatar"),
                approve=True
            )
            if success:
                save_review_record(
                    group_id,
                    result.get("nickname"),
                    user_id,
                    result.get("comment"),
                    "通过",
                    "",
                    get_webui_config("record_limit", 5),
                    result.get("time"),
                )
                yield event.chain_result(
                    await build_application_message(
                        self.context,
                        result,
                        {"passed": True}
                    )
                )
            else:
                yield event.plain_result("处理入群申请失败")
            return

        # 本群等级限制
        if group_cfg["LEVEL_REQUIRED_CONFIG"]:
            user_level = result.get("level", 0)
            min_level = group_cfg["MIN_LEVEL"]
            if user_level < min_level:
                reject_reason = f"等级不足，需 {min_level} 级以上"
                success = await approve_group_request(
                    event,
                    result.get("flag"),
                    result.get("avatar"),
                    approve=False,
                    reason=reject_reason
                )
                if success:
                    save_review_record(
                        group_id,
                        result.get("nickname"),
                        user_id,
                        result.get("comment"),
                        "未通过",
                        reject_reason,
                        get_webui_config("record_limit", 5),
                        result.get("time"),
                    )
                    yield event.chain_result(
                        await build_application_message(
                            self.context,
                            result,
                            {"passed": False, "reason": reject_reason}
                        )
                    )
                else:
                    yield event.plain_result("处理入群申请失败")
                return

        # AI 验证
        comment = result.get("comment", "")
        try:
            verify_result = await verify_by_llm(
                self.context,
                comment,
                event,
                group_name=result.get("group_name", ""),
                group_notice=result.get("group_notice", ""),
                group_notice_first=result.get("group_notice_first", ""),
                applicant_id=str(result.get("user_id") or ""),
                request_flag=str(result.get("flag") or "")
            )
        except Exception as e:
            logger.error(f"调用 AI 验证异常: {e}")
            verify_result = None

        if verify_result is None:
            behavior = get_webui_config("ai_fail_behavior", "skip")
            if behavior == "reject":
                reject_reason = "AI 验证服务暂时不可用"
                success = await approve_group_request(
                    event,
                    result.get("flag"),
                    result.get("avatar"),
                    approve=False,
                    reason=reject_reason
                )
                if success:
                    save_review_record(
                        group_id,
                        result.get("nickname"),
                        user_id,
                        comment,
                        "未通过",
                        reject_reason,
                        get_webui_config("record_limit", 5),
                        result.get("time"),
                    )
                    yield event.chain_result(
                        await build_application_message(
                            self.context,
                            result,
                            {"passed": False, "reason": reject_reason}
                        )
                    )
                else:
                    yield event.plain_result("处理入群申请失败")
            else:
                save_review_record(
                    group_id,
                    result.get("nickname"),
                    user_id,
                    comment,
                    "跳过",
                    "AI 验证服务暂时不可用",
                    get_webui_config("record_limit", 5),
                    result.get("time"),
                )
                yield event.chain_result(
                    await build_application_message(
                        self.context,
                        result,
                        {
                            "status": "skipped",
                            "reason": "AI 验证服务暂时不可用，请管理员手动审核",
                        },
                    )
                )
            return

        if verify_result.get("passed") is True:
            success = await approve_group_request(
                event,
                result.get("flag"),
                result.get("avatar"),
                approve=True
            )
        else:
            reason = verify_result.get("reason", "验证未通过")
            success = await approve_group_request(
                event,
                result.get("flag"),
                result.get("avatar"),
                approve=False,
                reason=reason
            )

        if success:
            save_review_record(
                group_id,
                result.get("nickname"),
                user_id,
                comment,
                "通过" if verify_result.get("passed") is True else "未通过",
                "" if verify_result.get("passed") is True else reason,
                get_webui_config("record_limit", 5),
                result.get("time"),
            )
            yield event.chain_result(
                await build_application_message(self.context, result, verify_result)
            )
        else:
            yield event.plain_result("处理入群申请失败")

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def agent_listener(self, event: AstrMessageEvent):
        if not event.is_at_or_wake_command:
            return

        if await self._is_duplicate_event(event, "agent"):
            return

        text = event.message_str.strip()
        if text.startswith(("/", "验证", "群组验证", "接收申请", "名单")):
            return

        is_admin = await _is_group_admin(event)
        record_query_requested = any(
            keyword in text for keyword in _RECORD_QUERY_KEYWORDS
        )
        if not is_admin and not record_query_requested:
            yield event.plain_result("权限不足：只有群管理员或群主才能使用此功能。")
            return

        if "帮助" in text or "help" in text.lower():
            yield event.plain_result(
                "我是群管助手。你可以直接对我说：\n"
                "· 查看黑名单\n"
                "· 把 123456 加入黑名单\n"
                "· 关闭入群验证\n"
                "· 设置最低等级 5\n"
                "· 查看审核记录或查看第 2 页审核记录\n"
                "也可以使用 /验证 帮助 查看完整指令。"
            )
            return

        # 固定格式的查记录请求直接复用指令逻辑，完全不需要进入 Agent
        if record_query_requested and not any(
            keyword in text for keyword in _CONFIG_QUERY_KEYWORDS
        ):
            page = 1
            for token in text.replace("第", " ").split():
                if token.isdigit():
                    page = max(1, int(token))
                    break
            reply = await self._review_records_reply(event, page)
            if reply is not None:
                yield reply
            return

        provider_id = await self.context.get_current_chat_provider_id(
            event.unified_msg_origin
        )

        # 只发送与当前权限相关的工具定义，每少一个工具就少一份固定的输入 Token
        tools = [GetListsTool(), GetConfigTool(), GetReviewRecordsTool()]
        if is_admin:
            tools.extend(
                [
                    SetVerifySwitchTool(),
                    SetMinLevelTool(),
                    SetLevelRequiredTool(),
                    AddBlacklistTool(),
                    RemoveBlacklistTool(),
                    ClearBlacklistTool(),
                    AddWhitelistTool(),
                    RemoveWhitelistTool(),
                    ClearWhitelistTool(),
                    ClearReviewRecordsTool(),
                ]
            )

        max_steps = max(1, int(get_webui_config("agent_max_steps", 3) or 3))
        llm_resp = await self.context.tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=text,
            system_prompt=(
                "你是群管助手。根据用户的要求调用合适的工具，一次只调用必要的工具。"
                "工具已经返回结果或者已经直接发送内容时，本轮任务就结束了，"
                "不要再复述工具结果、不要再调用工具、也不要编造不存在的功能。"
                "审核记录查询允许所有群成员使用，其他配置和名单管理操作仅限管理员。"
            ),
            tools=ToolSet(tools),
            max_steps=max_steps,
        )

        if llm_resp and llm_resp.completion_text:
            yield event.plain_result(llm_resp.completion_text)


    @filter.command_group("Group Verify", alias={"群组验证", "验证"})
    def group_verify(self, event: AstrMessageEvent):
        pass

    @group_verify.command("help", alias={"帮助"})
    async def config_help(self, event):
        if not await _is_group_admin(event):
            yield event.plain_result("权限不足：只有群管理员或群主才能使用此指令。")
            return
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用")
            return

        group_cfg = get_group_cfg(group_id)
        request_state = "开启" if group_cfg["REQUEST_CONFIG"] else "关闭"
        level_state = "开启" if group_cfg["LEVEL_REQUIRED_CONFIG"] else "关闭"

        yield event.plain_result(
            f"群组验证配置指令（本群）\n"
            f"接收申请：{request_state}\n"
            f"等级限制：{level_state}（最低等级 {group_cfg['MIN_LEVEL']}）\n"
            f"黑名单：{len(group_cfg.get('BLACKLIST', []))} 个\n"
            f"白名单：{len(group_cfg.get('WHITELIST', []))} 个\n\n"
            f"/群组验证 接收申请 切换 开 - 开启本群审核\n"
            f"/群组验证 接收申请 切换 关 - 关闭本群审核\n"
            f"/群组验证 接收申请 等级 开 - 开启本群等级限制\n"
            f"/群组验证 接收申请 等级 关 - 关闭本群等级限制\n"
            f"/群组验证 接收申请 等级 设置 <数字> - 设置本群最低等级\n"
            f"/群组验证 名单 - 查看本群黑白名单\n"
            f"/群组验证 名单 黑 添加 <QQ> - 加入本群黑名单\n"
            f"/群组验证 名单 白 添加 <QQ> - 加入本群白名单\n"
            f"/群组验证 名单 黑 清空 - 清空本群黑名单\n"
            f"/群组验证 名单 白 清空 - 清空本群白名单\n"
            f"/群组验证 记录 - 查看第1页审核记录（每页5条）\n"
            f"/群组验证 记录 <页码> - 查看指定页审核记录\n"
            f"/群组验证 清空记录 - 清空本群全部审核记录（仅管理员）\n"
            "PS: 加入白名单的人会不用通过AI 审核,直接进群,谨慎加白名单❗"
        )

    @group_verify.command("名单", alias={"List", "黑白名单", "list"})
    async def list_switch(self, event: AstrMessageEvent):
        if not await _is_group_admin(event):
            yield event.plain_result("权限不足：只有群管理员或群主才能使用此指令。")
            return
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用")
            return

        group_cfg = get_group_cfg(group_id)
        args = event.message_str.strip().split()

        black = group_cfg.get("BLACKLIST", [])
        white = group_cfg.get("WHITELIST", [])

        # 不带参数：直接输出黑白名单合集
        if len(args) < 4:
            black_text = "\n".join(black) if black else "（空）"
            white_text = "\n".join(white) if white else "（空）"
            yield event.plain_result(
                f"本群名单\n"
                f"【黑名单】共 {len(black)} 个\n{black_text}\n\n"
                f"【白名单】共 {len(white)} 个\n{white_text}\n\n"
                f"用法：\n"
                f"/群组验证 名单 黑 添加 <QQ>\n"
                f"/群组验证 名单 黑 删除 <QQ>\n"
                f"/群组验证 名单 黑 清空\n"
                f"/群组验证 名单 白 添加 <QQ>\n"
                f"/群组验证 名单 白 删除 <QQ>\n"
                f"/群组验证 名单 白 清空"
            )
            return

        kind = args[2]
        op = args[3]

        if kind in ("黑", "黑名单", "black", "Black", "BLACK"):
            key = "BLACKLIST"
            label = "黑名单"
        elif kind in ("白", "白名单", "white", "White", "WHITE"):
            key = "WHITELIST"
            label = "白名单"
        else:
            yield event.plain_result(f"无法识别的名单类型：{kind}")
            return

        if op in ("添加", "add", "Add", "ADD"):
            if len(args) < 5:
                yield event.plain_result("请提供要添加的 QQ 号")
                return
            target = args[4]
            add_to_list(group_cfg, key, target)
            save_all()
            yield event.plain_result(f"已添加 {target} 到本群{label}")
            return

        if op in ("删除", "移除", "remove", "del", "Delete", "DELETE"):
            if len(args) < 5:
                yield event.plain_result("请提供要删除的 QQ 号")
                return
            target = args[4]
            remove_from_list(group_cfg, key, target)
            save_all()
            yield event.plain_result(f"已从本群{label}删除 {target}")
            return

        if op in ("清空", "clear", "Clear", "CLEAR"):
            group_cfg[key] = []
            save_all()
            yield event.plain_result(f"已清空本群{label}")
            return

        yield event.plain_result(f"无法识别的操作：{op}")

    async def _review_records_reply(self, event: AstrMessageEvent, page: int):
        """Build one page of review records for the current group.

        Args:
            event: Current AstrBot event.
            page: One-based page number to render.

        Returns:
            A message event result holding the rendered image or the text
            fallback, or None when the group is unknown.
        """
        group_id = event.get_group_id()
        if not group_id:
            return event.plain_result("该指令只能在群聊中使用")

        records, total_pages = get_review_records(group_id, page=page, page_size=5)
        if not records:
            return event.plain_result("没有找到对应页码的审核记录。")

        if get_webui_config("send_images", True):
            group_avatar_path = await download_group_avatar(group_id)
            return event.chain_result(
                await build_review_records_message(
                    records,
                    group_avatar_path,
                    page,
                    total_pages,
                )
            )
        return event.chain_result(
            build_review_records_text(records, page, total_pages)
        )

    @group_verify.command("记录", alias={"records", "Record"})
    async def review_records(self, event: AstrMessageEvent):
        page = 1
        args = event.message_str.strip().split()
        if len(args) >= 3:
            try:
                page = max(1, int(args[2]))
            except ValueError:
                yield event.plain_result("页码必须是数字，例如：/验证 记录 2")
                return

        reply = await self._review_records_reply(event, page)
        if reply is not None:
            yield reply

    @group_verify.command("清空记录", alias={"clear_records", "ClearRecords"})
    async def clear_records(self, event: AstrMessageEvent):
        if not await _is_group_admin(event):
            yield event.plain_result("权限不足：只有群管理员或群主才能使用此指令。")
            return
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用")
            return
        count = clear_review_records(group_id)
        yield event.plain_result(f"已清空本群 {count} 条审核记录及其头像。")

    @group_verify.group("Receive", alias={"接收申请"})
    async def receive_choice(self, event: AstrMessageEvent):
        """"""
        pass

    @receive_choice.command("Switch", alias={"切换", "开关", "switch"})
    async def switch(self, event: AstrMessageEvent):
        if not await _is_group_admin(event):
            yield event.plain_result("权限不足：只有群管理员或群主才能使用此指令。")
            return
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用")
            return

        group_cfg = get_group_cfg(group_id)

        args = event.message_str.strip().split()
        if "切换" in args:
            idx = args.index("切换")
            action = args[idx + 1].lower() if idx + 1 < len(args) else ""
        else:
            action = args[-1].lower() if args else ""

        if not action:
            state = "开启" if group_cfg["REQUEST_CONFIG"] else "关闭"
            yield event.plain_result(
                f"本群 接收申请 状态：{state}\n"
                f"用法：/群组验证 接收申请 切换 开|关"
            )
            return

        if action in ("开", "开启", "open", "on", "true", "1"):
            if group_cfg["REQUEST_CONFIG"]:
                yield event.plain_result("本群 接收申请 目前已是开启状态❌️")
            else:
                group_cfg["REQUEST_CONFIG"] = True
                save_all()
                yield event.plain_result("开启 本群接收申请 成功✅️")

        elif action in ("关", "关闭", "close", "off", "false", "0"):
            if not group_cfg["REQUEST_CONFIG"]:
                yield event.plain_result("本群 接收申请 目前已是关闭状态❌️")
            else:
                group_cfg["REQUEST_CONFIG"] = False
                save_all()
                yield event.plain_result("关闭 本群接收申请 成功✅️")

        else:
            yield event.plain_result(
                f"无法识别的参数：{action}\n"
                f"用法：/群组验证 接收申请 切换 开|关"
            )

    @receive_choice.command("Level", alias={"等级", "等级限制"})
    async def level_switch(self, event: AstrMessageEvent):
        if not await _is_group_admin(event):
            yield event.plain_result("权限不足：只有群管理员或群主才能使用此指令。")
            return
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用")
            return

        group_cfg = get_group_cfg(group_id)
        args = event.message_str.strip().split()

        if "设置" in args:
            idx = args.index("设置")
            if idx + 1 < len(args):
                try:
                    new_level = int(args[idx + 1])
                    group_cfg["MIN_LEVEL"] = new_level
                    save_all()
                    yield event.plain_result(f"本群最低等级已设置为 {new_level}")
                except ValueError:
                    yield event.plain_result("等级必须是数字")
            else:
                yield event.plain_result(
                    f"本群当前最低等级：{group_cfg['MIN_LEVEL']}\n"
                    f"用法：/群组验证 接收申请 等级 设置 <数字>"
                )
            return

        if "开" in args or "开启" in args or "on" in args:
            group_cfg["LEVEL_REQUIRED_CONFIG"] = True
            save_all()
            yield event.plain_result(
                f"已开启本群等级限制，最低等级 {group_cfg['MIN_LEVEL']}"
            )

        elif "关" in args or "关闭" in args or "off" in args:
            group_cfg["LEVEL_REQUIRED_CONFIG"] = False
            save_all()
            yield event.plain_result("已关闭本群等级限制")

        else:
            state = "开启" if group_cfg["LEVEL_REQUIRED_CONFIG"] else "关闭"
            yield event.plain_result(
                f"本群等级限制：{state}\n"
                f"最低等级：{group_cfg['MIN_LEVEL']}\n"
                f"用法：\n"
                f"/群组验证 接收申请 等级 开\n"
                f"/群组验证 接收申请 等级 关\n"
                f"/群组验证 接收申请 等级 设置 <数字>"
            )



    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
