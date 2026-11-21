import asyncio
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



async def get_group_review_context(event, group_id):
    """Fetch the group name and the notices used for the automatic profile.

    Args:
        event: Current OneBot event.
        group_id: QQ group ID.

    Returns:
        The group name, latest notice and earliest distinct notice.
    """
    group_name = ""
    try:
        group_info = await event.bot.call_action("get_group_info", group_id=group_id)
        group_name = group_info.get("group_name", "")
    except Exception as error:
        logger.error(f"Failed to get group info: {error}")

    cleaned_notices = []
    try:
        notices = await event.bot.call_action("_get_group_notice", group_id=group_id)
        sorted_notices = sorted(
            notices or (), key=lambda notice: notice.get("publish_time", 0)
        )
        for notice in reversed(sorted_notices):
            text = _clean_notice(notice.get("message", {}).get("text", ""))
            if text and text not in cleaned_notices:
                cleaned_notices.append(text)
    except Exception as error:
        logger.error(f"Failed to get group notices: {error}")
        cleaned_notices.clear()

    group_notice = cleaned_notices[0] if cleaned_notices else ""
    group_notice_first = cleaned_notices[-1] if len(cleaned_notices) > 1 else ""
    return group_name, group_notice, group_notice_first


async def _lookup_invitation_inviter(
    event, group_id, invitee_id
) -> tuple[int | None, str]:
    """Find the inviter explicitly identified by the matching OneBot request.

    Args:
        event: OneBot group request event.
        group_id: QQ group receiving the request.
        invitee_id: Prospective member's QQ number.

    Returns:
        The inviter's QQ number and system nickname, if available.
    """
    raw_event = event.message_obj.raw_message
    group = str(group_id)
    invitee = str(invitee_id)
    flag = str(raw_event.get("flag") or "")
    request_id = str(raw_event.get("request_id") or "")
    if not request_id:
        parts = flag.split("|")
        if flag.isdecimal():
            request_id = flag
        elif len(parts) in (3, 4) and parts[0] == group and parts[1].isdecimal():
            request_id = parts[1]
    if not flag and not request_id:
        return None, ""

    try:
        rows = await asyncio.wait_for(
            event.bot.call_action("get_group_system_msg"), timeout=5
        )
    except Exception as error:
        logger.debug(f"Could not look up group system messages for {group_id}: {error}")
        return None, ""

    if isinstance(rows, dict):
        rows = rows.get("join_requests")
    if not isinstance(rows, list):
        return None, ""

    matches: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict) or str(row.get("group_id")) != group:
            continue
        if not (
            (flag and flag == str(row.get("flag") or ""))
            or (request_id and request_id == str(row.get("request_id") or ""))
        ):
            continue
        target = str(row.get("target_uin") or "")
        if target in ("", "0"):
            target = str(row.get("requester_uin") or "")
        if target not in ("", "0", invitee):
            continue
        # The actor or operator can be the administrator who reviewed the request.
        inviter = str(row.get("invitor_uin") or "")
        inviter_id = int(inviter) if inviter.isdecimal() else 0
        if inviter_id and str(inviter_id) != invitee:
            matches[inviter_id] = row.get("invitor_nick") or matches.get(inviter_id, "")
    if len(matches) == 1:
        return next(iter(matches.items()))
    return None, ""


async def read_group_invitation(
    event, group_id, inviter_id, invitee_id, is_invitation: bool, send_images: bool
):
    """Enrich a pending invitation with the available OneBot identities.

    Args:
        event: OneBot group request event.
        group_id: QQ group receiving the request.
        inviter_id: Inviting member's QQ number, when reported.
        invitee_id: Prospective member's QQ number, when reported.
        is_invitation: Whether the event identifies a member invitation.
        send_images: Whether to download avatars for the group notification.

    Returns:
        The group, participants and timestamp for the pending notification.
    """
    group_name = ""
    try:
        group = await event.bot.call_action("get_group_info", group_id=group_id)
        group_name = group.get("group_name", "")
    except Exception as error:
        logger.warning(f"Could not look up the invitation group {group_id}: {error}")

    system_inviter_name = ""
    if not inviter_id and invitee_id:
        inviter_id, system_inviter_name = await _lookup_invitation_inviter(
            event, group_id, invitee_id
        )

    result = {
        "group_name": group_name,
        "is_invitation": is_invitation or bool(inviter_id),
        "inviter_id": inviter_id,
        "invitee_id": invitee_id,
    }
    timestamp = event.message_obj.raw_message.get("time")
    if timestamp:
        result["invite_time"] = datetime.fromtimestamp(timestamp).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    participants = [
        (role, user_id)
        for role, user_id in (("inviter", inviter_id), ("invitee", invitee_id))
        if user_id
    ]
    for role, user_id in participants:
        nickname = ""
        if role == "inviter":
            try:
                member = await event.bot.call_action(
                    "get_group_member_info", group_id=group_id, user_id=user_id
                )
                nickname = member.get("card") or member.get("nickname")
            except Exception as error:
                logger.debug(
                    f"Could not look up inviting group member {user_id}: {error}"
                )
            nickname = nickname or system_inviter_name
        if not nickname:
            try:
                user = await event.bot.call_action("get_stranger_info", user_id=user_id)
                nickname = user.get("nickname") or user.get("nick")
            except Exception as error:
                logger.warning(
                    f"Could not look up invitation participant {user_id}: {error}"
                )
        result[f"{role}_name"] = nickname

    if send_images:
        avatars = await asyncio.gather(
            *(download_avatar(user_id) for _, user_id in participants)
        )
        for (role, _), avatar in zip(participants, avatars):
            result[f"{role}_avatar_path"] = avatar
    return result


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

    group_name, group_notice, group_notice_first = await get_group_review_context(
        event, group_id
    )

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
