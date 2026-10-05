# ai_verify.py
import asyncio
import hashlib
import json
import time

from astrbot.api import logger

from .config import SYSTEM_PROMPT, get_webui_config

_STATE_ATTR = "_group_auto_approve_ai_state"
_PROFILE_CACHE_MAX = 32
_STATS_LOG_INTERVAL = 50


def parse_question_answer(comment):
    """Parse the question and answer from an application comment."""
    question = None
    answer = None
    for line in comment.splitlines():
        if line.startswith("问题："):
            question = line.replace("问题：", "").strip()
        elif line.startswith("答案："):
            answer = line.replace("答案：", "").strip()
    return question, answer


async def verify_by_llm(
    context,
    comment,
    event,
    group_name="",
    group_notice="",
    group_notice_first="",
    applicant_id="",
    request_flag="",
):
    """Verify an application with a cached, group-specific AI context.

    The cache key covers everything that can change the verdict: the group, the
    applicant, the request flag and the current group profile. Two applicants who
    submit the same answer therefore never share one another's result, while a
    duplicate delivery of the same request reuses a single model call.

    Args:
        context: AstrBot plugin context.
        comment: Raw application comment.
        event: Current AstrBot event.
        group_name: Current group name.
        group_notice: Latest group notice.
        group_notice_first: Earliest group notice.
        applicant_id: QQ number of the applicant.
        request_flag: Unique flag of the join request when the platform sent one.

    Returns:
        A parsed verification result, or None when verification fails.
    """
    question, answer = parse_question_answer(comment)
    if not question or not answer:
        return None

    state = getattr(context, _STATE_ATTR, None)
    if state is None:
        state = {
            "cache": {},
            "profile_cache": {},
            "inflight": {},
            "lock": asyncio.Lock(),
            "stats": {"cache_hit": 0, "inflight_join": 0, "request": 0},
        }
        setattr(context, _STATE_ATTR, state)

    group_id = str(event.get_group_id() or "")
    raw_profile = " ".join(
        part
        for part in (
            f"群名称：{group_name.strip()}" if group_name.strip() else "",
            f"最新群公告：{group_notice.strip()}" if group_notice.strip() else "",
            f"历史群公告：{group_notice_first.strip()}"
            if group_notice_first.strip()
            else "",
        )
        if part
    )
    profile_limit = max(200, int(get_webui_config("profile_max_chars", 1000) or 1000))
    profile = raw_profile[:profile_limit]
    profile_key = hashlib.sha256(
        f"{group_id}\x1f{profile}".encode("utf-8")
    ).hexdigest()

    cache_ttl = max(1, int(get_webui_config("ai_cache_ttl", 600) or 600))
    cache_max = max(1, int(get_webui_config("ai_cache_max", 256) or 256))
    verify_key = hashlib.sha256(
        "\x1f".join(
            (
                group_id,
                str(applicant_id or ""),
                str(request_flag or ""),
                profile_key,
                question.strip(),
                answer.strip(),
            )
        ).encode("utf-8")
    ).hexdigest()

    now = time.monotonic()
    result = None
    async with state["lock"]:
        profile_cache = state["profile_cache"]
        if profile_key not in profile_cache:
            profile_cache[profile_key] = profile
            while len(profile_cache) > _PROFILE_CACHE_MAX:
                profile_cache.pop(next(iter(profile_cache)))

        cache = state["cache"]
        cached = cache.get(verify_key)
        if cached is not None and now - cached[0] < cache_ttl:
            state["stats"]["cache_hit"] += 1
            return cached[1]
        cache.pop(verify_key, None)

        task = state["inflight"].get(verify_key)
        if task is None:
            state["stats"]["request"] += 1
            if state["stats"]["request"] % _STATS_LOG_INTERVAL == 0:
                stats = state["stats"]
                logger.info(
                    f"AI 审核统计：缓存命中={stats['cache_hit']}，"
                    f"并发合并={stats['inflight_join']}，"
                    f"实际请求={stats['request']}"
                )
            task = asyncio.create_task(
                _call_verification_llm(
                    context,
                    event,
                    profile,
                    question,
                    answer,
                )
            )
            state["inflight"][verify_key] = task
        else:
            state["stats"]["inflight_join"] += 1

    try:
        result = await task
    finally:
        async with state["lock"]:
            if state["inflight"].get(verify_key) is task:
                state["inflight"].pop(verify_key, None)
                if result is not None:
                    cache[verify_key] = (time.monotonic(), result)
                    while len(cache) > cache_max:
                        cache.pop(next(iter(cache)))
    return result


async def _call_verification_llm(context, event, profile, question, answer):
    """Call the model with compact, group-specific verification context.

    Args:
        context: AstrBot plugin context.
        event: Current AstrBot event.
        profile: Cached context from the current group's name and notices.
        question: Parsed verification question.
        answer: Parsed applicant answer.

    Returns:
        A parsed verification result, or None when the model response is invalid.
    """
    try:
        provider_id = await context.get_current_chat_provider_id(
            event.unified_msg_origin
        )
    except Exception as error:
        logger.error(f"获取 provider 失败: {error}")
        return None

    prompt = (
        f"本群画像与公告摘要：<<<{profile}>>>\n\n"
        f"问题：<<<{question}>>>\n"
        f"申请人答案：<<<{answer}>>>"
    )
    try:
        llm_resp = await context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
        )
    except Exception as error:
        logger.error(f"入群验证调用大模型失败: {error}")
        return None

    text = (llm_resp.completion_text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict) or "correct" not in data:
        return None

    correct = data.get("correct")
    if isinstance(correct, str):
        correct = correct.strip().lower() == "true"
    if correct is True:
        return {"passed": True}

    reason = str(data.get("reason", "") or "验证未通过").strip()
    max_len = get_webui_config("reject_reason_max_len", 30)
    return {"passed": False, "reason": reason[:max_len]}
