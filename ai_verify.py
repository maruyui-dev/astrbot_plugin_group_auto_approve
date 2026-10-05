# ai_verify.py
import asyncio
import hashlib
import json
import time

from astrbot.api import logger

from .config import SYSTEM_PROMPT, get_webui_config


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
):
    """Verify an application with a cached, group-specific AI context.

    Args:
        context: AstrBot plugin context.
        comment: Raw application comment.
        event: Current AstrBot event.
        group_name: Current group name.
        group_notice: Latest group notice.
        group_notice_first: Earliest group notice.

    Returns:
        A parsed verification result, or None when verification fails.
    """
    question, answer = parse_question_answer(comment)
    if not question or not answer:
        return None

    state = getattr(context, "_group_auto_approve_ai_state", None)
    if state is None:
        state = {
            "cache": {},
            "profile_cache": {},
            "inflight": {},
            "lock": asyncio.Lock(),
        }
        setattr(context, "_group_auto_approve_ai_state", state)

    raw_profile = "\n".join(
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
    profile_key = hashlib.sha256(
        f"{event.get_group_id() or ''}\x1f{raw_profile}".encode("utf-8")
    ).hexdigest()
    async with state["lock"]:
        profile = state["profile_cache"].get(profile_key)
        if profile is None:
            profile = " ".join(raw_profile.split())[:1200]
            state["profile_cache"] = {profile_key: profile}

    verify_key = hashlib.sha256(
        "\x1f".join(
            (
                str(event.get_group_id() or ""),
                profile,
                question.strip(),
                answer.strip(),
            )
        ).encode("utf-8")
    ).hexdigest()
    now = time.monotonic()
    async with state["lock"]:
        cached = state["cache"].get(verify_key)
        if cached and now - cached[0] < 600:
            return cached[1]
        task = state["inflight"].get(verify_key)
        if task is None:
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

    try:
        result = await task
    finally:
        async with state["lock"]:
            if state["inflight"].get(verify_key) is task:
                state["inflight"].pop(verify_key, None)
                if "result" in locals() and result is not None:
                    state["cache"][verify_key] = (time.monotonic(), result)
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
