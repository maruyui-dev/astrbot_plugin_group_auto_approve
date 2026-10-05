import re
from datetime import datetime
from pathlib import Path

import aiohttp
from astrbot.api import logger

from .config import get_webui_config

AVATAR_DIR: Path | None = None
AVATAR_MAX_BYTES = 5 * 1024 * 1024
AVATAR_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5, sock_read=8)
NOTICE_MAX_CHARS = 400

_NOTICE_TAG_RE = re.compile(r"<[^>]+>")
_NOTICE_URL_RE = re.compile(r"(?:https?://|www\.)\S+")
_NOTICE_SPACE_RE = re.compile(r"[\s\u200b\u200c\u200d\ufeff]+")


def set_avatar_dir(data_dir: str | Path):
    """Set the AstrBot-managed directory used for downloaded avatars.

    Args:
        data_dir: Directory where avatar files should be stored.
    """
    global AVATAR_DIR
    AVATAR_DIR = Path(data_dir) / "avatar"
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)


def _clean_notice(text) -> str:
    """Normalise a group notice so it costs less while staying readable.

    Args:
        text: Raw notice text, which may carry HTML tags and filler links.

    Returns:
        A single-line notice with markup and links removed, truncated to the
        configured limit.
    """
    cleaned = _NOTICE_TAG_RE.sub(" ", str(text or ""))
    cleaned = (
        cleaned.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    cleaned = _NOTICE_URL_RE.sub(" ", cleaned)
    cleaned = _NOTICE_SPACE_RE.sub(" ", cleaned).strip()
    limit = max(
        50,
        int(get_webui_config("notice_max_chars", NOTICE_MAX_CHARS) or NOTICE_MAX_CHARS),
    )
    return cleaned[:limit]



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
    group_notice = ""  # 最新一条有效公告
    group_notice_first = ""  # 最早一条有效公告
    try:
        notices = await event.bot.call_action(
            "_get_group_notice",
            group_id=group_id
        )
        if notices:
            # 按 publish_time 升序排序：索引 0 是最早，最后是最新
            sorted_notices = sorted(
                notices,
                key=lambda n: n.get("publish_time", 0)
            )

            # 从新到旧清洗，去掉重复和空公告，只保留有效内容
            cleaned_notices = []
            for notice in reversed(sorted_notices):
                text = _clean_notice(notice.get("message", {}).get("text", ""))
                if text and text not in cleaned_notices:
                    cleaned_notices.append(text)

            if cleaned_notices:
                group_notice = cleaned_notices[0]
                # 只有一条有效公告时不再重复发送历史公告
                if len(cleaned_notices) > 1:
                    group_notice_first = cleaned_notices[-1]

    except Exception as e:
        logger.error(f"获取群公告失败: {e}")

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
    if not str(user_id).isdigit():
        logger.warning(f"申请者QQ号格式异常，跳过头像下载: {user_id!r}")
        return None
    avatar_url = (
        f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
    )

    if AVATAR_DIR is None:
        logger.error("Avatar directory has not been initialized")
        return None

    avatar_path = AVATAR_DIR / f"{user_id}.png"

    try:
        async with aiohttp.ClientSession(timeout=AVATAR_TIMEOUT) as session:
            async with session.get(avatar_url) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if content_type and not content_type.lower().startswith("image/"):
                        logger.warning(f"申请者头像返回类型异常，QQ={user_id}")
                        return None
                    data = await response.read()
                    if len(data) > AVATAR_MAX_BYTES:
                        logger.warning(f"申请者头像超过大小限制，QQ={user_id}")
                        return None
                    with avatar_path.open("wb") as f:
                        f.write(data)
                    return avatar_path
                logger.warning(
                    f"申请者头像下载失败，QQ={user_id}，状态码={response.status}"
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
    if not str(group_id).isdigit():
        logger.warning(f"群号格式异常，跳过群头像下载: {group_id!r}")
        return None

    avatar_url = f"https://p.qlogo.cn/gh/{group_id}/{group_id}/640/"
    avatar_path = AVATAR_DIR / f"group_{group_id}.png"

    try:
        async with aiohttp.ClientSession(timeout=AVATAR_TIMEOUT) as session:
            async with session.get(avatar_url) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if content_type and not content_type.lower().startswith("image/"):
                        logger.warning(f"群头像返回类型异常，群号={group_id}")
                        return None
                    data = await response.read()
                    if len(data) > AVATAR_MAX_BYTES:
                        logger.warning(f"群头像超过大小限制，群号={group_id}")
                        return None
                    avatar_path.write_bytes(data)
                    return avatar_path
                logger.warning(
                    f"群头像下载失败，群号={group_id}，状态码={response.status}"
                )
    except Exception as error:
        logger.warning(f"下载群头像失败: {error}")
    return None
