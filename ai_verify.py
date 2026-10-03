# ai_verify.py
import json
from astrbot.api import logger
from .config import SYSTEM_PROMPT


def parse_question_answer(comment):
    """
    纯文本解析
    """
    question = None
    answer = None

    for line in comment.splitlines():

        if line.startswith("问题："):
            question = line.replace(
                "问题：",
                ""
            ).strip()

        elif line.startswith("答案："):
            answer = line.replace(
                "答案：",
                ""
            ).strip()

    return question, answer

async def verify_by_llm(
    context,
    comment,
    event,
    group_name="",
    group_notice="",
    group_notice_first=""
):
    """
    返回：
    {"passed": True}                        AI 判定通过
    {"passed": False, "reason": "..."}      AI 判定不通过
    None                                    调用失败 / 解析失败，调用方不应处理申请
    """
    question, answer = parse_question_answer(comment)
    if not question or not answer:
        logger.info("入群验证：无法解析问题或答案")
        return None

    try:
        provider_id = await context.get_current_chat_provider_id(
            event.unified_msg_origin
        )
    except Exception as e:
        logger.error(f"获取 provider 失败:{e}")
        return None

    prompt = (
        f"群名称：<<<{group_name}>>>\n"
        f"最新群公告：<<<{group_notice}>>>\n"
        f"最早群公告：<<<{group_notice_first}>>>\n\n"
        f"问题：<<<{question}>>>\n"
        f"申请人答案：<<<{answer}>>>"
    )

    try:
        llm_resp = await context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT
        )
    except Exception as e:
        logger.error(f"入群验证调用大模型失败:{e}")
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
        logger.info(f"入群验证：模型输出无法解析为 JSON，原文为 {text!r}")
        return None

    if not isinstance(data, dict) or "correct" not in data:
        logger.info(f"入群验证：模型输出缺少 correct 字段，原文为 {text!r}")
        return None

    correct = data.get("correct")
    if isinstance(correct, str):
        correct = correct.strip().lower() == "true"

    if correct is True:
        return {"passed": True}

    reason = data.get("reason", "") or "验证未通过"
    reason = str(reason).strip()
    if len(reason) > 30:
        reason = reason[:30]

    return {"passed": False, "reason": reason}