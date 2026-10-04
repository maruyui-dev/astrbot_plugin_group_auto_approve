from astrbot.api.message_components import Plain, Image
from astrbot.api import logger

def build_verify_message(result, verify_result=None):

    chain = [
        Plain("收到一条入群申请")
    ]

    if result.get("avatar"):
        chain.append(
            Image.fromFileSystem(
                result.get("avatar")
            )
        )

    chain.append(
        Plain(
            f"申请者: {result.get('nickname')}\n"
            f"QQ: {result.get('user_id')}\n"
            f"等级: {result.get('level')}\n"
            f"申请时间: {result.get('time')}\n\n"
            f"{result.get('comment')}"
        )
    )

    # 追加 AI 审核结果
    if verify_result is not None:
        if verify_result.get("passed") is True:
            chain.append(Plain("\n\n审核结果：✅ 通过"))
        else:
            reason = verify_result.get("reason", "验证未通过")
            chain.append(
                Plain(
                    f"\n\n审核结果：❌ 拒绝\n"
                    f"拒绝理由：{reason}"
                )
            )

    logger.info(result.get("row_event"))

    return chain