#导入Astrbot模块以及第三方模块
from encodings.aliases import aliases
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import aiohttp
#导入项目内部模块
from .action import approve_group_request
from .message import build_verify_message
from .request import handle_group_request
from . import config
from .ai_verify import verify_by_llm


@register(
    "group_verify",
    "MaruYui",
    "QQ群自动入群审核插件",
    "1.0.0"
)
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        pass
    #=====================================================#
    #               事      件     监      听              #
    #=====================================================#
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def listen_event(self, event: AstrMessageEvent):
        # 接收申请开关关闭时，直接忽略
        if not config.REQUEST_CONFIG:
            return

        result = await handle_group_request(event)
        # 不是入群申请
        if result is None:
            return

        # 是入群申请，但是处理失败
        if not result.get("success"):
            yield event.plain_result(
                f"处理失败:{result.get('error')}"
            )
            return
        # 正常情况
        # --- 新增：调用 AI 判断 ---
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

        # AI 调用失败：不处理申请，只在群里发通知
        if verify_result is None:
            yield event.plain_result(
                "⚠️ AI 验证服务暂时不可用，已跳过本次入群申请处理，请管理员手动审核。"
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
            yield event.chain_result(
                build_verify_message(result, verify_result)
            )
        else:
            yield event.plain_result("处理入群申请失败")

    @filter.command_group("Group Verify", alias={"群组验证", "验证"})
    def group_verify(self, event: AstrMessageEvent):
        pass
    # 注册指令的装饰器。指令名为 helloworld。注册成功后，发送 `/helloworld` 就会触发这个指令，并回复 `你好, {user_name}!`
    @group_verify.group("Receive", alias={"接收申请"})
    async def receive_choice(self, event: AstrMessageEvent):
        """"""
        pass

    @receive_choice.command("Switch", alias={"切换", "开关", "switch"})
    async def switch(self, event: AstrMessageEvent):
        """
        /群组验证 接收申请 切换 开
        /群组验证 接收申请 切换 关
        """
        args = event.message_str.strip().split()

        if "切换" in args:
            idx = args.index("切换")
            action = args[idx + 1].lower() if idx + 1 < len(args) else ""
        else:
            action = args[-1].lower() if args else ""

        if not action:
            state = "开启" if config.REQUEST_CONFIG else "关闭"
            yield event.plain_result(
                f"当前 接收申请 状态：{state}\n"
                f"用法：/群组验证 接收申请 切换 开|关"
            )
            return

        if action in ("开", "开启", "open", "on", "true", "1"):
            if config.REQUEST_CONFIG:
                yield event.plain_result("接收申请 目前已是开启状态,无法重复开启❌️")
            else:
                config.REQUEST_CONFIG = True
                yield event.plain_result("开启 接收申请 成功✅️")

        elif action in ("关", "关闭", "close", "off", "false", "0"):
            if not config.REQUEST_CONFIG:
                yield event.plain_result("接收申请 目前已是关闭状态,无法重复关闭❌️")
            else:
                config.REQUEST_CONFIG = False
                yield event.plain_result("关闭 接收申请 成功✅️")

        else:
            yield event.plain_result(
                f"无法识别的参数：{action}\n"
                f"用法：/群组验证 接收申请 切换 开|关"
            )

    @receive_choice.command("help", alias={"帮助"})
    async def config_help(self, event):
        """
        查看验证配置说明
        """
        logger.info(f"message_str = {event.message_str!r}")
        state = "开启" if config.REQUEST_CONFIG else "关闭"
        yield event.plain_result(
            f"群组验证配置指令（当前接收申请：{state}）:\n"
            f"/群组验证 接收申请 切换 开 - 开启审核\n"
            f"/群组验证 接收申请 切换 关 - 关闭审核"
        )

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
