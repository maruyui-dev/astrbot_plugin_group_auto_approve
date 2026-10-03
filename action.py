import os
import asyncio
from astrbot.api import logger


# 后台删除头像任务
async def delete_avatar_later(avatar_path):
    # 等待消息发送完成
    await asyncio.sleep(300)  # 5分钟后删除
    try:
        if os.path.exists(avatar_path):
            os.remove(avatar_path)
            logger.info(
                f"删除头像成功:{avatar_path}"
            )
    except Exception as e:
        logger.error(
            f"删除头像失败:{e}"
        )
# 处理入群申请
async def approve_group_request(
        event,
        flag,
        avatar_path=None,
        approve=True,          # 新增：是否同意
        reason=""              # 新增：拒绝理由
):
    success = False
    try:
        params = {
            "flag": flag,
            "approve": approve
        }
        if not approve and reason:
            params["reason"] = reason

        result = await event.bot.call_action(
            "set_group_add_request",
            **params
        )
        logger.info(f"{'同意' if approve else '拒绝'}入群返回:{result}")
        success = True

    except Exception as e:
        logger.error(f"处理入群申请失败:{e}")
    # 启动后台删除任务
    if avatar_path:
        asyncio.create_task(
            delete_avatar_later(
                avatar_path
            )
        )
    return success