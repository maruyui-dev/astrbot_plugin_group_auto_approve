from datetime import datetime
from pathlib import Path
import time

import aiohttp
from astrbot.api import logger

AVATAR_DIR: Path | None = None


def set_avatar_dir(data_dir: str | Path):
    """Set the AstrBot-managed directory used for downloaded avatars.

    Args:
        data_dir: Directory where avatar files should be stored.
    """
    global AVATAR_DIR
    AVATAR_DIR = Path(data_dir) / "avatar"
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)


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
        group_avatar_path = await download_group_avatar(group_id)

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
        "group_avatar": group_avatar_path,
        "row_event": raw_event,
        "group_id": group_id,
        "group_name": group_name,
        "group_notice": group_notice,
        "group_notice_first": group_notice_first
    }

async def download_avatar(user_id):
    started_at = time.perf_counter()
    logger.info(f"[图片节点] 开始下载申请者头像，QQ={user_id}")
    avatar_url = (
        f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
    )

    if AVATAR_DIR is None:
        logger.error("Avatar directory has not been initialized")
        return None

    avatar_path = AVATAR_DIR / f"{user_id}.png"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as response:
                if response.status == 200:
                    data = await response.read()
                    with avatar_path.open("wb") as f:
                        f.write(data)
                    logger.info(
                        f"[图片节点] 申请者头像下载完成，QQ={user_id}，"
                        f"状态码={response.status}，大小={len(data) / 1024:.1f}KB，"
                        f"耗时={time.perf_counter() - started_at:.3f}s"
                    )
                    return avatar_path
                logger.warning(
                    f"[图片节点] 申请者头像下载失败，QQ={user_id}，"
                    f"状态码={response.status}，耗时={time.perf_counter() - started_at:.3f}s"
                )
    except Exception as e:
        logger.error(
            f"下载头像失败:{e}"
        )
    return None


async def download_group_avatar(group_id):
    """Download a group avatar into the plugin avatar directory.

    Args:
        group_id: QQ group ID whose avatar should be downloaded.

    Returns:
        The downloaded avatar path, or None when the download fails.
    """
    if AVATAR_DIR is None:
        logger.error("Avatar directory has not been initialized")
        return None

    started_at = time.perf_counter()
    logger.info(f"[图片节点] 开始下载群头像，群号={group_id}")
    avatar_url = f"https://p.qlogo.cn/gh/{group_id}/{group_id}/640/"
    avatar_path = AVATAR_DIR / f"group_{group_id}.png"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as response:
                if response.status == 200:
                    data = await response.read()
                    avatar_path.write_bytes(data)
                    logger.info(
                        f"[图片节点] 群头像下载完成，群号={group_id}，"
                        f"状态码={response.status}，大小={len(data) / 1024:.1f}KB，"
                        f"耗时={time.perf_counter() - started_at:.3f}s"
                    )
                    return avatar_path
                logger.warning(
                    f"[图片节点] 群头像下载失败，群号={group_id}，"
                    f"状态码={response.status}，耗时={time.perf_counter() - started_at:.3f}s"
                )
    except Exception as error:
        logger.warning(f"下载群头像失败: {error}")
    return None
