from collections.abc import Awaitable, Callable

from astrbot.api import FunctionTool, logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.core.message.message_event_result import MessageChain

from .ai_verify import get_effective_group_profile
from .config import (
    get_group_cfg,
    get_webui_config,
    save_all,
    add_to_list,
    remove_from_list,
)
from .record_store import clear_review_records, get_review_records
from .record_message import build_review_records_message, build_review_records_text
from .request import download_group_avatar


async def _is_group_admin(event) -> bool:
    group_id = event.get_group_id()
    user_id = event.get_sender_id()
    if not group_id or not user_id:
        return False
    try:
        info = await event.bot.call_action(
            "get_group_member_info",
            group_id=group_id,
            user_id=user_id
        )
        role = info.get("role", "member")
        return role in ("owner", "admin")
    except Exception as e:
        logger.error(f"获取群成员信息失败: {e}")
        return False


class SetVerifySwitchTool(FunctionTool):
    """开启或关闭当前群的入群验证。"""

    def __init__(self):
        super().__init__(
            name="set_group_verify_switch",
            description="开启或关闭当前群的入群验证。enabled为true表示开启，false表示关闭。",
            parameters={
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean", "description": "True开启，False关闭"}
                },
                "required": ["enabled"]
            }
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        cfg["REQUEST_CONFIG"] = kwargs["enabled"]
        save_all()
        return f"已{'开启' if kwargs['enabled'] else '关闭'}本群入群验证。"


class SetGroupProfileNoticeRefreshTool(FunctionTool):
    """Control whether group announcements refresh the automatic review profile."""

    def __init__(self):
        super().__init__(
            name="set_group_profile_notice_refresh",
            description=(
                "开启或关闭本群的群画像随群公告自动更新。开启后跟随最新群公告，"
                "关闭后保留当前自动画像。手动画像始终优先。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "true 开启公告自动更新，false 关闭。",
                    },
                },
                "required": ["enabled"],
            },
        )

    async def call(self, context, **kwargs):
        """Apply the switch requested by the agent.

        Args:
            context: Agent context containing the original group event.
            **kwargs: Tool arguments containing the requested enabled state.

        Returns:
            The switch result for the agent.
        """
        return await self.set_enabled(context.context.event, kwargs.get("enabled"))

    @staticmethod
    async def set_enabled(event, enabled: bool | None) -> str:
        """Save the current group's setting for either entry point.

        Args:
            event: Group event that identifies the caller and target group.
            enabled: Whether to follow announcements, or None for invalid input.

        Returns:
            A save confirmation or a message describing why no setting was saved.
        """
        group_id = event.get_group_id()
        if not group_id:
            return "该指令只能在群聊中使用。"
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能使用此指令。"
        if not isinstance(enabled, bool):
            return "用法：/群画像公告更新 开 或 /群画像公告更新 关"

        frozen_profile = None
        if not enabled:
            frozen_profile, _ = await get_effective_group_profile(
                event, automatic_only=True
            )

        group_cfg = get_group_cfg(group_id)
        previous = group_cfg.pop("FROZEN_AUTO_PROFILE", None)
        if frozen_profile is not None:
            group_cfg["FROZEN_AUTO_PROFILE"] = frozen_profile
        if frozen_profile != previous and not save_all():
            if previous is None:
                group_cfg.pop("FROZEN_AUTO_PROFILE")
            else:
                group_cfg["FROZEN_AUTO_PROFILE"] = previous
            return "保存失败，本群的公告自动更新设置未修改。"

        return (
            "已开启公告自动更新，本群自动画像将跟随群公告。"
            if enabled
            else "已关闭公告自动更新，保留本群当前的自动画像。"
        )


class StartGroupProfileUploadTool(FunctionTool):
    """Prompt the current administrator for a group review rubric."""

    def __init__(
        self,
        start_upload: Callable[[AstrMessageEvent], Awaitable[MessageEventResult]],
    ):
        super().__init__(
            name="start_group_profile_upload",
            description=(
                "用户要求上传、修改或更换本群的群画像或审核标准时，"
                "发送等待提示，让管理员下一条群消息直接提交审核标准。"
            ),
            parameters={"type": "object", "properties": {}},
        )
        self.start_upload = start_upload

    async def call(self, context, **kwargs) -> str:
        """Start the upload and send its prompt in the current group.

        Args:
            context: Agent context containing the original group event.
            **kwargs: Unused tool arguments.

        Returns:
            The message sent to the group.
        """
        event = context.context.event
        reply = await self.start_upload(event)
        await event.send(reply)
        event.stop_event()
        return reply.get_plain_text()


class ShowGroupProfileTool(FunctionTool):
    """Send the current group's review rubric as copyable text."""

    def __init__(self):
        super().__init__(
            name="show_group_profile",
            description="查看本群正在使用的群画像、入群审核标准和公告自动更新状态。",
            parameters={"type": "object", "properties": {}},
        )

    async def call(self, context, **kwargs) -> str:
        """Send the rubric to the group that requested it.

        Args:
            context: Agent context containing the original group event.
            **kwargs: Unused tool arguments.

        Returns:
            The result of sending the group reply.
        """
        event = context.context.event
        await event.send(await self.get_reply(event))
        event.stop_event()
        return "已在群内发送回复。"

    @staticmethod
    async def get_reply(event: AstrMessageEvent) -> MessageEventResult:
        """Build the same profile reply for the command and agent.

        Args:
            event: Incoming request that identifies the group and sender.

        Returns:
            The effective rubric and its source, or a permission message.
        """
        reply = event.make_result().use_t2i(False).use_markdown(False)
        group_id = event.get_group_id()
        if not group_id:
            return reply.message("该指令只能在群聊中使用。")
        if not await _is_group_admin(event):
            return reply.message("权限不足：只有群管理员或群主才能使用此指令。")

        profile, revision = await get_effective_group_profile(event)
        source = "手动上传" if revision else "自动生成"
        refresh_state = (
            "关闭"
            if get_group_cfg(group_id).get("FROZEN_AUTO_PROFILE") is not None
            else "开启"
        )
        return reply.message(
            f"本群 AI 审核标准（{source}，公告自动更新：{refresh_state}）\n{profile}"
        )


class SetMinLevelTool(FunctionTool):
    """设置当前群的等级限制最低等级。"""

    def __init__(self):
        super().__init__(
            name="set_group_min_level",
            description="设置当前群入群申请的最低QQ等级限制。会自动开启等级限制。",
            parameters={
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "最低等级，例如5"}
                },
                "required": ["level"]
            }
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        cfg["MIN_LEVEL"] = int(kwargs["level"])
        cfg["LEVEL_REQUIRED_CONFIG"] = True
        save_all()
        return f"已开启本群等级限制，最低等级设为 {kwargs['level']}。"


class SetLevelRequiredTool(FunctionTool):
    """开启或关闭当前群的等级限制。"""

    def __init__(self):
        super().__init__(
            name="set_level_required",
            description="开启或关闭当前群的入群等级限制。enabled为true表示开启，false表示关闭。",
            parameters={
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean", "description": "True开启，False关闭"}
                },
                "required": ["enabled"]
            }
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        cfg["LEVEL_REQUIRED_CONFIG"] = kwargs["enabled"]
        save_all()
        return f"已{'开启' if kwargs['enabled'] else '关闭'}本群等级限制（最低等级 {cfg['MIN_LEVEL']}）。"


class AddBlacklistTool(FunctionTool):
    """将指定QQ加入当前群的黑名单。"""

    def __init__(self):
        super().__init__(
            name="add_blacklist",
            description="将指定QQ号加入当前群的黑名单，该QQ将被直接拒绝入群。",
            parameters={
                "type": "object",
                "properties": {
                    "qq": {"type": "string", "description": "QQ号"}
                },
                "required": ["qq"]
            }
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        add_to_list(cfg, "BLACKLIST", kwargs["qq"])
        save_all()
        return f"已将 {kwargs['qq']} 加入本群黑名单。"


class RemoveBlacklistTool(FunctionTool):
    """将指定QQ移出当前群的黑名单。"""

    def __init__(self):
        super().__init__(
            name="remove_blacklist",
            description="将指定QQ号移出当前群的黑名单。",
            parameters={
                "type": "object",
                "properties": {
                    "qq": {"type": "string", "description": "QQ号"}
                },
                "required": ["qq"]
            }
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        remove_from_list(cfg, "BLACKLIST", kwargs["qq"])
        save_all()
        return f"已将 {kwargs['qq']} 移出本群黑名单。"


class ClearBlacklistTool(FunctionTool):
    """清空当前群的黑名单。"""

    def __init__(self):
        super().__init__(
            name="clear_blacklist",
            description="清空当前群的黑名单。",
            parameters={"type": "object", "properties": {}}
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        cfg["BLACKLIST"] = []
        save_all()
        return "已清空本群黑名单。"


class AddWhitelistTool(FunctionTool):
    """将指定QQ加入当前群的白名单。"""

    def __init__(self):
        super().__init__(
            name="add_whitelist",
            description="将指定QQ号加入当前群的白名单，该QQ将被直接同意入群。",
            parameters={
                "type": "object",
                "properties": {
                    "qq": {"type": "string", "description": "QQ号"}
                },
                "required": ["qq"]
            }
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        add_to_list(cfg, "WHITELIST", kwargs["qq"])
        save_all()
        return f"已将 {kwargs['qq']} 加入本群白名单。"


class RemoveWhitelistTool(FunctionTool):
    """将指定QQ移出当前群的白名单。"""

    def __init__(self):
        super().__init__(
            name="remove_whitelist",
            description="将指定QQ号移出当前群的白名单。",
            parameters={
                "type": "object",
                "properties": {
                    "qq": {"type": "string", "description": "QQ号"}
                },
                "required": ["qq"]
            }
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        remove_from_list(cfg, "WHITELIST", kwargs["qq"])
        save_all()
        return f"已将 {kwargs['qq']} 移出本群白名单。"


class ClearWhitelistTool(FunctionTool):
    """清空当前群的白名单。"""

    def __init__(self):
        super().__init__(
            name="clear_whitelist",
            description="清空当前群的白名单。",
            parameters={"type": "object", "properties": {}}
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        cfg["WHITELIST"] = []
        save_all()
        return "已清空本群白名单。"


class GetListsTool(FunctionTool):
    """查看当前群的黑名单和白名单。"""

    def __init__(self):
        super().__init__(
            name="get_lists",
            description="查看当前群的黑名单和白名单内容。",
            parameters={"type": "object", "properties": {}}
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        black = cfg.get("BLACKLIST", [])
        white = cfg.get("WHITELIST", [])
        black_text = "\n".join(black) if black else "（空）"
        white_text = "\n".join(white) if white else "（空）"
        return (
            f"本群名单\n"
            f"【黑名单】共 {len(black)} 个\n{black_text}\n\n"
            f"【白名单】共 {len(white)} 个\n{white_text}"
        )


class GetConfigTool(FunctionTool):
    """查看当前群的入群验证配置。"""

    def __init__(self):
        super().__init__(
            name="get_config",
            description="查看当前群的入群验证配置：审核开关、等级限制、最低等级、黑白名单数量。",
            parameters={"type": "object", "properties": {}}
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        cfg = get_group_cfg(group_id)
        request_state = "开启" if cfg["REQUEST_CONFIG"] else "关闭"
        level_state = "开启" if cfg["LEVEL_REQUIRED_CONFIG"] else "关闭"
        return (
            f"本群配置\n"
            f"接收申请：{request_state}\n"
            f"等级限制：{level_state}（最低等级 {cfg['MIN_LEVEL']}）\n"
            f"黑名单：{len(cfg.get('BLACKLIST', []))} 个\n"
            f"白名单：{len(cfg.get('WHITELIST', []))} 个"
        )


class GetReviewRecordsTool(FunctionTool):
    """查询当前群的入群审核记录。"""

    def __init__(self):
        super().__init__(
            name="get_review_records",
            description="查询当前群的入群审核记录，并以图片发送，每页最多5条，page从1开始。",
            parameters={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "页码，从1开始，默认第1页",
                    }
                },
                "required": [],
            },
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        group_id = event.get_group_id()
        if not group_id:
            return "该功能只能在群聊中使用。"

        page = max(1, int(kwargs.get("page", 1)))
        records, total_pages = get_review_records(
            group_id,
            page=page,
            page_size=5,
        )
        if not records:
            return "没有找到对应页码的审核记录。"

        if get_webui_config("send_images", True):
            group_avatar_path = await download_group_avatar(group_id)
            message_chain = await build_review_records_message(
                records,
                group_avatar_path,
                page,
                total_pages,
            )
        else:
            message_chain = build_review_records_text(records, page, total_pages)
        await event.send(MessageChain(chain=message_chain, type="tool_direct_result"))
        return "审核记录已发送。"


class ClearReviewRecordsTool(FunctionTool):
    """Clear the current group's review records."""

    def __init__(self):
        super().__init__(
            name="clear_review_records",
            description="清空当前群的全部入群审核记录及其申请者头像，仅限群主或管理员。",
            parameters={"type": "object", "properties": {}},
        )

    async def call(self, context, **kwargs):
        event = context.context.event
        if not await _is_group_admin(event):
            return "权限不足：只有群管理员或群主才能执行此操作。"
        group_id = event.get_group_id()
        if not group_id:
            return "该操作只能在群聊中使用。"
        count = clear_review_records(group_id)
        return f"已清空本群 {count} 条审核记录及其头像。"
