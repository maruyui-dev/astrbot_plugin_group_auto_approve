from datetime import datetime
from astrbot.api import logger
import aiohttp
import os

async def handle_group_request(event):

    raw_event = event.message_obj.raw_message
    # 不是请求事件，不处理
    if raw_event.get("post_type") != "request":
        return None
    # 不是群申请，不处理
    if raw_event.get("request_type") != "group":
        return None

    user_id = raw_event.get("user_id")
    group_id = raw_event.get("group_id")

    # 是群申请，但是数据缺失
    if not user_id:
        return {
            "success": False,
            "error": "无法获取申请者QQ号"
        }

    comment = (
        raw_event.get("comment")
        or "获取失败"
    )

    timestamp = raw_event.get("time")

    if timestamp:
        request_time = datetime.fromtimestamp(
            timestamp
        ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    else:
        request_time = "获取失败"

    # 获取用户信息
    try:
        user_info = await event.bot.call_action(
            "get_stranger_info",
            user_id=user_id
        )
        avatar_path = await download_avatar(user_id)

    except Exception as e:

        logger.error(
            f"获取用户信息失败: {e}"
        )

        return {
            "success": False,
            "error": "获取申请者信息失败"
        }

    user_name = (
        user_info.get("nickname")
        or user_info.get("nick")
        or "未知用户"
    )

    user_level = (
            user_info.get("qqLevel")
            or user_info.get("qq_level")
            or 0
    )

    # 获取群名称
    group_name = ""
    try:
        group_info = await event.bot.call_action(
            "get_group_info",
            group_id=group_id
        )
        group_name = group_info.get("group_name", "")
    except Exception as e:
        logger.error(f"获取群信息失败: {e}")

    # 获取群公告
    group_notice = ""  # 最新一条公告
    group_notice_first = ""  # 最早一条公告
    try:
        notices = await event.bot.call_action(
            "_get_group_notice",
            group_id=group_id
        )
        logger.info(f"群公告原始返回: {notices!r}")

        if notices:
            # 按 publish_time 升序排序：索引 0 是最早，最后是最新
            sorted_notices = sorted(
                notices,
                key=lambda n: n.get("publish_time", 0)
            )

            earliest = sorted_notices[0]
            latest = sorted_notices[-1]

            # 最新公告
            group_notice = latest.get("message", {}).get("text", "")
            group_notice = group_notice.replace("&nbsp;", " ")
            group_notice = group_notice[:500]

            # 最早公告
            group_notice_first = earliest.get("message", {}).get("text", "")
            group_notice_first = group_notice_first.replace("&nbsp;", " ")
            group_notice_first = group_notice_first[:500]

            # 如果只有一条，避免两条内容重复
            if len(sorted_notices) == 1:
                group_notice_first = ""

    except Exception as e:
        logger.error(f"获取群公告失败: {e}")

    logger.info(f"群名称: {group_name!r}")
    logger.info(f"最新群公告: {group_notice!r}")
    logger.info(f"最早群公告: {group_notice_first!r}")

    return {
        "success": True,
        "user_id": user_id,
        "nickname": user_name,
        "level": user_level,
        "comment": comment,
        "time": request_time,
        "flag": raw_event.get("flag"),
        "avatar": avatar_path,
        "row_event": raw_event,
        "group_id": group_id,
        "group_name": group_name,
        "group_notice": group_notice,
        "group_notice_first": group_notice_first
    }

#获取头像url并保存到文件夹函数
async def download_avatar(user_id):
    avatar_url = (
        f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
    )

    # 保存一个绝对路径到plugin_path变量
    plugin_path = os.path.dirname(os.path.abspath(__file__))
    # 在这个绝对路径下创建一个avatar文件夹
    avatar_dir = os.path.join(plugin_path, "avatar") #使用os.path.join可以根据操作系统自动分配/ 和 \

    # 不存在则创建
    os.makedirs(avatar_dir, exist_ok=True)#exist_ok=True的作用是发现已经存在,就不报错

    avatar_path = os.path.join(avatar_dir, f"{user_id}.png")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as response:
                if response.status == 200:
                    data = await response.read()
                    with open(avatar_path, "wb") as f:
                        f.write(data)
                    return avatar_path
    except Exception as e:
        logger.error(
            f"下载头像失败:{e}"
        )
    return None