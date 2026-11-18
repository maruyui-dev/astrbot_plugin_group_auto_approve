import asyncio
import re
import time

#导入Astrbot模块以及第三方模块
from datetime import datetime
from uuid import uuid4
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import aiohttp
from astrbot.api import ToolSet
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.regex import RegexFilter
from .agent_tools import (
    SetVerifySwitchTool,
    SetGroupProfileNoticeRefreshTool,
    ShowGroupProfileTool,
    StartGroupProfileUploadTool,
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
    build_invitation_message,
    build_invitation_text,
    build_leave_message,
    build_leave_text,
    build_verify_chain,
    build_verify_message,
)
from .request import (
    download_avatar,
    download_group_avatar,
    handle_group_request,
    read_group_invitation,
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
_PROFILE_UPLOAD_TIMEOUT = 300
_PROFILE_SUBJECT = r"(?:(?:本群|当前群|这个群)的?)?(?:群画像|(?:入群|AI\s*)?审核标准)"
_PROFILE_ACTION = (
    r"(?:查看|查询|看看|看(?:一下|下|一眼)|显示|发(?:一下|给我|我)|"
    r"上传|提交|更新|修改|更换|换(?:一下|下)?|改(?:一下|下)?|编辑|设置|重设|"
    r"开启|打开|启用|关闭|关掉|停用|暂停|停止|恢复)"
)
_PROFILE_REQUEST = re.compile(
    r"^(?:(?:请(?:你|帮我)?|帮我|麻烦(?:你|帮我)?|我想(?:要)?|我要|"
    r"能不能(?:帮我)?|能否(?:帮我)?|可以(?:帮我)?|给我)[\s，,]*){0,3}"
    rf"(?:{_PROFILE_ACTION}(?:一下|下)?\s*{_PROFILE_SUBJECT}"
    rf"|(?:把|让)\s*{_PROFILE_SUBJECT}[^\n]*?{_PROFILE_ACTION}"
    rf"|{_PROFILE_SUBJECT}的?公告(?:自动)?更新(?:能不能|能否|可以){_PROFILE_ACTION})",
    re.IGNORECASE,
)
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
    "1.8.8"
)
class MyPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self.plugin_config = config or {}
        self._pending_profile_uploads: dict[tuple[str, str, str, str], float] = {}
        dedup_state = getattr(context, _DEDUP_CONTEXT_KEY, None)
        if not isinstance(dedup_state, dict) or "lock" not in dedup_state:
            dedup_state = {"lock": asyncio.Lock()}
            setattr(context, _DEDUP_CONTEXT_KEY, dedup_state)
        # 插件热重载后 context 上可能残留旧版本写入的状态，这里补齐缺失的键
        dedup_state.setdefault("seen", {})
        dedup_state.setdefault("stats", {})
        self._dedup_state = dedup_state
        batch_state = getattr(context, _KICK_BATCH_CONTEXT_KEY, None)
        if not isinstance(batch_state, dict) or "lock" not in batch_state:
            batch_state = {"lock": asyncio.Lock()}
            setattr(context, _KICK_BATCH_CONTEXT_KEY, batch_state)
        batch_state.setdefault("groups", {})
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
        if raw_event.get("post_type") == "message":
            reply = await self._receive_group_profile(event)
            if reply is not None:
                yield reply
                event.stop_event()
            return

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

        if (
            raw_event.get("post_type") != "request"
            or raw_event.get("request_type") != "group"
        ):
            return
        group_id = raw_event.get("group_id")
        if not group_id:
            return
        group_cfg = get_group_cfg(group_id)
        if not group_cfg["REQUEST_CONFIG"]:
            return

        subtype = raw_event.get("sub_type", "add")
        # Older NapCat builds used a typed flag and reported the inviter as user_id.
        flag_parts = str(raw_event.get("flag") or "").split("|")
        typed_flag = (
            len(flag_parts) in (3, 4)
            and flag_parts[0] == str(group_id)
            and flag_parts[1].isdigit()
        )
        legacy_invite = typed_flag and flag_parts[2] == "5"
        if subtype != "add" and not (subtype == "invite" and legacy_invite):
            return

        inviter_id = raw_event.get("invitor_id") or raw_event.get("inviter_id")
        invitee_id = raw_event.get("user_id")
        if subtype == "invite":
            inviter_id, invitee_id = invitee_id, None
        if str(inviter_id) in ("0", str(invitee_id)):
            inviter_id = None
        is_invitation = bool(
            inviter_id or legacy_invite or (typed_flag and flag_parts[2] == "22")
        )
        # An empty request without an inviter field can be an invitation on NapCat.
        unknown_source = (
            "invitor_id" not in raw_event
            and "inviter_id" not in raw_event
            and not typed_flag
            and bool(invitee_id)
            and not str(raw_event.get("comment") or "").strip()
        )
        if is_invitation or unknown_source:
            send_images = get_webui_config("send_images", True)
            invitation = await read_group_invitation(
                event, group_id, inviter_id, invitee_id, is_invitation, send_images
            )
            chain = (
                await build_invitation_message(invitation)
                if send_images
                else build_invitation_text(invitation)
            )
            yield event.chain_result(chain).use_t2i(False).use_markdown(False)
            return

        result = await handle_group_request(event)
        if result is None:
            return
        if not result.get("success"):
            yield event.plain_result(f"处理失败:{result.get('error')}")
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
    @filter.command("群管助手")
    async def agent_listener(self, event: AstrMessageEvent):
        """Handle an explicit request to the current group's management agent.

        Args:
            event: Incoming group command.

        Yields:
            The result of the requested operation or a permission message.
        """
        # Give another matched command or regex handler priority.
        for handler in event.get_extra("activated_handlers") or ():
            if (
                handler.handler_module_path == __name__
                and handler.handler_name == "agent_listener"
            ):
                continue
            if any(
                isinstance(
                    event_filter, (CommandFilter, CommandGroupFilter, RegexFilter)
                )
                for event_filter in handler.event_filters or ()
            ):
                return

        if await self._is_duplicate_event(event, "agent"):
            return

        parts = event.get_message_str().split(maxsplit=1)
        text = parts[1] if len(parts) > 1 else ""
        record_query_requested = any(
            keyword in text for keyword in _RECORD_QUERY_KEYWORDS
        )

        # Record queries are public and do not require an agent call.
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

        if not await _is_group_admin(event):
            yield event.plain_result("权限不足：只有群管理员或群主才能使用此功能。")
            return

        if not text or "帮助" in text or "help" in text.lower():
            yield event.plain_result(
                "可以用以下指令管理本群\n"
                "· /群管助手 查看黑名单\n"
                "· /群管助手 把 123456 加入黑名单\n"
                "· /群管助手 关闭入群验证\n"
                "· /群管助手 关闭群画像公告自动更新\n"
                "· /群管助手 我要上传群画像\n"
                "· /群管助手 设置最低等级 5\n"
                "· /群管助手 查看第 2 页审核记录\n"
                "也可以使用 /验证 帮助 查看完整指令。"
            )
            return

        reply = await self._run_group_agent(event, text)
        if reply is not None:
            yield reply

    async def _run_group_agent(
        self, event: AstrMessageEvent, text: str, *, profile_only: bool = False
    ) -> MessageEventResult | None:
        """Run the agent after the caller has checked group permissions.

        Args:
            event: Incoming group request.
            text: Operation requested in the message.
            profile_only: Whether to expose only group profile operations.

        Returns:
            A text result when the agent has a reply to send.
        """
        tools = [
            ShowGroupProfileTool(),
            SetGroupProfileNoticeRefreshTool(),
            StartGroupProfileUploadTool(self._handle_group_profile_upload),
        ]
        system_prompt = (
            "你是群管助手。根据用户的要求调用合适的工具，一次只调用必要的工具。"
            "工具已直接发送回复时结束。工具只返回操作结果时，简短告知用户结果后结束。"
            "只处理当前群。遇到其他群或未明确要求执行操作的问题，先确认用户意图。"
        )
        if not profile_only:
            tools.extend(
                [
                    GetListsTool(),
                    GetConfigTool(),
                    GetReviewRecordsTool(),
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
        provider_id = await self.context.get_current_chat_provider_id(
            event.unified_msg_origin
        )
        max_steps = max(1, int(get_webui_config("agent_max_steps", 3) or 3))
        llm_resp = await self.context.tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=text,
            system_prompt=system_prompt,
            tools=ToolSet(tools),
            max_steps=max_steps,
        )

        if llm_resp and llm_resp.completion_text and not event.is_stopped():
            reply = event.plain_result(llm_resp.completion_text)
            if profile_only:
                reply.use_t2i(False).use_markdown(False)
            return reply
        return None

    @filter.command("群画像")
    async def show_group_profile(self, event: AstrMessageEvent):
        """Show the current group's effective AI review rubric.

        Args:
            event: Incoming command event.

        Yields:
            The rubric and its source, or a permission message.
        """
        yield await ShowGroupProfileTool.get_reply(event)

    @filter.command("群画像公告更新")
    async def set_group_profile_notice_refresh(self, event: AstrMessageEvent):
        """Toggle whether announcements refresh this group's automatic rubric.

        Args:
            event: Incoming command event.

        Yields:
            The saved setting, usage instructions, or a permission message.
        """
        reply = event.make_result().use_t2i(False).use_markdown(False)
        args = event.get_message_str().split()[1:]
        enabled = {"开": True, "关": False}.get(args[0]) if len(args) == 1 else None
        yield reply.message(
            await SetGroupProfileNoticeRefreshTool.set_enabled(event, enabled)
        )

    @filter.command("上传群画像")
    async def upload_group_profile(self, event: AstrMessageEvent):
        """Start a group profile upload or save text included in the command.

        Args:
            event: Incoming command event.

        Yields:
            The waiting prompt, save result, or a permission message.
        """
        # CommandFilter normalizes whitespace in its arguments.
        parts = event.get_message_str().split(maxsplit=1)
        profile = parts[1] if len(parts) > 1 else ""
        yield await self._handle_group_profile_upload(event, profile)

    async def _receive_group_profile(
        self, event: AstrMessageEvent
    ) -> MessageEventResult | None:
        """Route a profile request or the pending administrator's next text.

        Args:
            event: Incoming OneBot message.

        Returns:
            A reply to send through the message pipeline, if any.
        """
        group_id = event.get_group_id()
        text = event.get_message_str().strip()
        if not group_id or not text:
            return None
        if text != (event.message_obj.message_str or "").strip():
            return None

        messages = event.get_messages()
        plain = all(isinstance(component, Comp.Plain) for component in messages)
        start_upload = plain and text == "上传群画像"
        pending_upload = False
        if plain and not start_upload and self._pending_profile_uploads:
            key = (
                event.get_platform_id(),
                event.get_self_id(),
                group_id,
                event.get_sender_id(),
            )
            deadline = self._pending_profile_uploads.get(key)
            if deadline is not None:
                pending_upload = deadline > time.monotonic()
                if not pending_upload:
                    self._pending_profile_uploads.pop(key)

        natural_request = _PROFILE_REQUEST.match(text) and all(
            isinstance(component, Comp.Plain)
            or (
                isinstance(component, Comp.At)
                and str(component.qq) == str(event.get_self_id())
            )
            for component in messages
        )
        if not (start_upload or pending_upload or natural_request):
            return None
        if any(
            isinstance(event_filter, (CommandFilter, CommandGroupFilter, RegexFilter))
            for handler in event.get_extra("activated_handlers") or ()
            for event_filter in handler.event_filters or ()
        ):
            return None

        if start_upload or pending_upload:
            return await self._handle_group_profile_upload(
                event, "" if start_upload else text
            )
        if not await _is_group_admin(event):
            return event.plain_result(
                "权限不足：只有群管理员或群主才能使用此指令。"
            ).use_t2i(False)
        return await self._run_group_agent(event, text, profile_only=True)

    async def _handle_group_profile_upload(
        self, event: AstrMessageEvent, profile: str = ""
    ) -> MessageEventResult:
        """Start waiting or save a review rubric through any upload entry point.

        Args:
            event: Group event that identifies the caller and target group.
            profile: Rubric to save, or an empty string to begin waiting.

        Returns:
            The waiting prompt, save result, or a permission message.
        """
        reply = event.make_result().use_t2i(False).use_markdown(False)
        group_id = event.get_group_id()
        if not group_id:
            return reply.message("该指令只能在群聊中使用。")

        key = (
            event.get_platform_id(),
            event.get_self_id(),
            group_id,
            event.get_sender_id(),
        )
        if profile:
            # Claim the pending upload before checking the role over the network.
            self._pending_profile_uploads.pop(key, None)
        if not await _is_group_admin(event):
            return reply.message("权限不足：只有群管理员或群主才能使用此指令。")
        if not profile:
            now = time.monotonic()
            self._pending_profile_uploads = {
                pending_key: deadline
                for pending_key, deadline in self._pending_profile_uploads.items()
                if deadline > now
            }
            self._pending_profile_uploads[key] = now + _PROFILE_UPLOAD_TIMEOUT
            return reply.message(
                f"正在等待发送审核标准。请在 {_PROFILE_UPLOAD_TIMEOUT // 60} 分钟内直接发送文本，"
                "支持同一条消息内换行。"
            )

        group_cfg = get_group_cfg(group_id)
        previous = group_cfg.get("MANUAL_PROFILE")
        group_cfg["MANUAL_PROFILE"] = {"text": profile, "revision": uuid4().hex}
        if not save_all():
            if previous is None:
                group_cfg.pop("MANUAL_PROFILE")
            else:
                group_cfg["MANUAL_PROFILE"] = previous
            return reply.message("保存失败，本群审核标准未修改。")
        return reply.message("审核标准更新成功，已保存为本群手动画像。")

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
            "/群画像 - 查看本群 AI 审核标准\n"
            "/上传群画像 - 等待你发送新的审核标准\n"
            "/群画像公告更新 开|关 - 设置自动画像是否跟随公告\n"
            "/群管助手 <操作> - 用自然语言管理本群\n"
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
