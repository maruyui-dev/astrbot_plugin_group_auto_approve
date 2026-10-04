#导入Astrbot模块以及第三方模块
from encodings.aliases import aliases
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
    _is_group_admin
)
#导入项目内部模块
from .action import approve_group_request
from .message import build_verify_message
from .request import handle_group_request, set_avatar_dir
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
from .record_store import get_review_records, save_review_record, set_record_data_dir


@register(
    "group_verify",
    "MaruYui",
    "QQ群自动入群审核插件",
    "1.4.0"
)
class MyPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self.plugin_config = config or {}

    async def initialize(self):
        from .config import set_webui_config
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
                    await build_verify_message(
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
                    await build_verify_message(
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
                        await build_verify_message(
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
                group_notice_first=result.get("group_notice_first", "")
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
                        await build_verify_message(
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
                    await build_verify_message(
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
                await build_verify_message(self.context, result, verify_result)
            )
        else:
            yield event.plain_result("处理入群申请失败")

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def agent_listener(self, event: AstrMessageEvent):
        if not event.is_at_or_wake_command:
            return

        text = event.message_str.strip()
        if text.startswith(("/", "验证", "群组验证", "接收申请", "名单")):
            return

        is_admin = await _is_group_admin(event)
        record_query_requested = any(
            keyword in text for keyword in ("审核记录", "申请记录", "查看记录")
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

        provider_id = await self.context.get_current_chat_provider_id(
            event.unified_msg_origin
        )

        tools = ToolSet([
            SetVerifySwitchTool(),
            SetMinLevelTool(),
            SetLevelRequiredTool(),
            AddBlacklistTool(),
            RemoveBlacklistTool(),
            ClearBlacklistTool(),
            AddWhitelistTool(),
            RemoveWhitelistTool(),
            ClearWhitelistTool(),
            GetListsTool(),
            GetConfigTool(),
            GetReviewRecordsTool(),
        ])

        llm_resp = await self.context.tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=text,
            system_prompt=(
                "你是群管助手。根据用户的要求调用合适的工具。"
                "审核记录查询允许所有群成员使用，其他配置和名单管理操作仅限管理员。"
                "只使用提供的工具，不要编造不存在的功能。"
            ),
            tools=tools,
            max_steps=10,
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

    @group_verify.command("记录", alias={"records", "Record"})
    async def review_records(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用")
            return

        page = 1
        args = event.message_str.strip().split()
        if len(args) >= 3:
            try:
                page = max(1, int(args[2]))
            except ValueError:
                yield event.plain_result("页码必须是数字，例如：/验证 记录 2")
                return

        records, total_pages = get_review_records(group_id, page=page, page_size=5)
        if not records:
            yield event.plain_result("没有找到对应页码的审核记录。")
            return

        lines = [f"本群审核记录（第 {page}/{total_pages} 页）"]
        for record in records:
            lines.append(
                f"昵称：{record['nickname']}\n"
                f"QQ：{record['user_id']}\n"
                f"申请理由：{record['reason']}\n"
                f"审核状态：{record['status']}\n"
                f"拒绝理由：{record.get('reject_reason') or '无'}\n"
                f"时间：{record['time']}"
            )

        if page < total_pages:
            lines.append(f"使用 /验证 记录 {page + 1} 查看下一页")
        else:
            lines.append("已经是最后一页")

        yield event.plain_result("\n\n".join(lines))

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
