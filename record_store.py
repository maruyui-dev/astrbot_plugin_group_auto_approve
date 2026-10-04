import json
from datetime import datetime
from pathlib import Path

from astrbot.api import logger

RECORD_FILE: Path | None = None


def set_record_data_dir(data_dir: str | Path):
    """Set the AstrBot-managed directory used for review records.

    Args:
        data_dir: Directory where the review record file should be stored.
    """
    global RECORD_FILE
    RECORD_FILE = Path(data_dir) / "review_records.json"
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_records() -> dict[str, list[dict]]:
    if RECORD_FILE is None or not RECORD_FILE.exists():
        return {}

    try:
        with RECORD_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as error:
        logger.error(f"读取审核记录失败: {error}")
        return {}


def _save_records(records: dict[str, list[dict]]):
    if RECORD_FILE is None:
        logger.error("审核记录目录尚未初始化")
        return

    try:
        with RECORD_FILE.open("w", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)
    except OSError as error:
        logger.error(f"保存审核记录失败: {error}")


def save_review_record(
    group_id,
    nickname,
    user_id,
    reason,
    status,
    reject_reason,
    limit,
    request_time=None,
):
    """Save one review record and remove the oldest records over the limit.

    Args:
        group_id: QQ group ID that received the application.
        nickname: Applicant nickname.
        user_id: Applicant QQ ID.
        reason: Application reason.
        status: Review status, such as passed, rejected, or skipped.
        reject_reason: Rejection reason, if any.
        limit: Maximum number of records to keep for this group.
        request_time: Original request time, when available.
    """
    limit = max(0, int(limit))
    if limit <= 0:
        return

    records = _load_records()
    group_records = records.setdefault(str(group_id), [])
    group_records.append(
        {
            "nickname": str(nickname or "未知用户"),
            "user_id": str(user_id),
            "reason": str(reason or ""),
            "status": status,
            "reject_reason": str(reject_reason or ""),
            "time": request_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    records[str(group_id)] = group_records[-limit:]
    _save_records(records)


def get_review_records(group_id, page=1, page_size=5):
    """Return one page of the newest review records for a group.

    Args:
        group_id: QQ group ID to query.
        page: One-based page number.
        page_size: Maximum number of records in one page.

    Returns:
        A tuple containing records for the requested page and total page count.
    """
    records = _load_records().get(str(group_id), [])
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    ordered_records = list(reversed(records))
    total_pages = (len(ordered_records) + page_size - 1) // page_size
    start = (page - 1) * page_size
    return ordered_records[start : start + page_size], total_pages
