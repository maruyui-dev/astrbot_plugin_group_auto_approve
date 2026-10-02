from astrbot.api.message_components import Plain, Image


def build_verify_message(result):

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
    return chain