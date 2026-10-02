from encodings.aliases import aliases
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

REQUEST_CONFIG = True

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
    #=================================
    #          事件监听
    #=================================
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def test_event(self, event: AstrMessageEvent):

        raw_event = event.message_obj.raw_message

        if raw_event.get('post_type') == 'request':
            if REQUEST_CONFIG == False:
                return
            user_id = raw_event['user_id']
            comment = raw_event['comment']
            timestamp = raw_event['time']
            request_time = datetime.fromtimestamp(timestamp)
            logger.info("触发事件")
            logger.info(event.message_obj.raw_message)

            yield event.plain_result(
                f"收到一条入群申请\n申请者:{user_id}\n申请时间: {request_time}\n{comment}"
            )
    @filter.command_group("Group Verify", alias={"群组验证", "验证"})
    def group_verify(self, event: AstrMessageEvent):
        pass
    # 注册指令的装饰器。指令名为 helloworld。注册成功后，发送 `/helloworld` 就会触发这个指令，并回复 `你好, {user_name}!`
    @group_verify.group("Receive", alias={"接收申请"})
    async def receive_choice(self, event: AstrMessageEvent):
        """"""
        pass
    @receive_choice.command("Open", alias={"开","开启", "open", "on", "On","ON"})
    async def open(self, event: AstrMessageEvent):
        message_chain = event.get_messages()  # 用户所发的消息的消息链 # from astrbot.api.message_components import *
        logger.info(message_chain)
        global REQUEST_CONFIG

        if REQUEST_CONFIG == False:
            yield event.plain_result("开启 接收申请 成功✅️")
            REQUEST_CONFIG = True
        elif REQUEST_CONFIG == True:
            yield event.plain_result("接收申请 目前已是开启状态,无法重复开启❌️")

    @receive_choice.command("Close", alias={"关", "关闭", "close", "off", "Off","OFF"})
    async def close(self, event: AstrMessageEvent):
        message_chain = event.get_messages()
        logger.info(message_chain)
        global REQUEST_CONFIG

        if REQUEST_CONFIG == True:
            yield event.plain_result("关闭 接收申请 成功✅️")
            REQUEST_CONFIG = False
        elif REQUEST_CONFIG == False:
            yield event.plain_result("接收申请 目前已是关闭状态,无法重复关闭❌️")

    @receive_choice.command("help", alias={"帮助"})
    async def config_help(self, event):
        """
        查看验证配置说明
        """
        yield event.plain_result(
            "群组验证配置指令:\n"
            "/群组验证 接收申请 开 - 开启审核\n"
            "/群组验证 接收申请 关 - 关闭审核"
        )

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
