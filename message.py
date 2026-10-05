import base64
import html
import io
import mimetypes
import time
from pathlib import Path

from PIL import Image as PILImage
from astrbot.api import html_renderer, logger
from astrbot.api.message_components import Image, Plain

CARD_TEMPLATE = """
<html>
<head>
  <meta charset="UTF-8">
  <style>
    * { box-sizing: border-box; }
    html,
    body {
      margin: 0;
      padding: 0;
      background: transparent;
      height: fit-content;
      min-height: 0;
    }
    body {
      width: fit-content;
      padding: 8px;
      color: #20314a;
      font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }
    .card {
      width: 680px;
      height: fit-content;
      overflow: hidden;
      border-radius: 24px;
      background: #ffffff;
      box-shadow: 0 18px 46px rgba(43, 66, 102, 0.14);
    }
    .hero {
      position: relative;
      min-height: 124px;
      padding: 28px 116px 26px 30px;
      color: #ffffff;
      background: linear-gradient(135deg, #5a82ff 0%, #7e9cff 100%);
    }
    .eyebrow {
      margin: 0 0 7px;
      font-size: 12px;
      letter-spacing: 0.14em;
      opacity: 0.82;
    }
    h1 {
      margin: 0;
      font-size: 25px;
      font-weight: 500;
      letter-spacing: 0.03em;
    }
    .group-avatar {
      position: absolute;
      top: 27px;
      right: 30px;
      width: 70px;
      height: 70px;
      border: 4px solid rgba(255, 255, 255, 0.8);
      border-radius: 22px;
      object-fit: cover;
      background: #d9e3ff;
    }
    .content { padding: 26px 30px 24px; }
    .person {
      display: flex;
      align-items: center;
      gap: 15px;
      padding-bottom: 22px;
      border-bottom: 1px solid #e8edf5;
    }
    .avatar {
      width: 58px;
      height: 58px;
      flex: 0 0 auto;
      border-radius: 18px;
      object-fit: cover;
      background: #d9e3ff;
    }
    .identity { min-width: 0; }
    .nickname {
      margin: 0 0 4px;
      font-size: 18px;
      font-weight: 500;
      overflow-wrap: anywhere;
    }
    .qq, .time {
      color: #738198;
      font-size: 13px;
    }
    .status {
      margin-left: auto;
      padding: 7px 11px;
      border-radius: 999px;
      color: {{ status_color }};
      background: {{ status_background }};
      font-size: 13px;
      white-space: nowrap;
    }
    .label {
      margin: 22px 0 9px;
      color: #738198;
      font-size: 12px;
      letter-spacing: 0.08em;
    }
    .reason {
      margin: 0;
      padding: 15px 17px;
      border-radius: 14px;
      background: #f7f9fd;
      color: #34445d;
      font-size: 15px;
      line-height: 1.7;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .reject {
      margin-top: 14px;
      padding: 13px 17px;
      border-left: 3px solid #e46b78;
      border-radius: 0 12px 12px 0;
      background: #fff3f4;
      color: #9f3f4b;
      font-size: 14px;
      line-height: 1.6;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .reject-title {
      display: block;
      margin-bottom: 3px;
      color: #b24654;
      font-size: 12px;
      font-weight: 500;
      letter-spacing: 0.08em;
    }
    .footer {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      margin-top: 22px;
      color: #738198;
      font-size: 12px;
    }
    .brand { color: #4f7cff; font-weight: 500; }
  </style>
</head>
<body>
  <div class="card">
    <div class="hero">
      <p class="eyebrow">ASTRBOT · GROUP REVIEW</p>
      <h1>新的入群申请</h1>
      <img class="group-avatar" src="{{ group_avatar_data }}" alt="群头像">
    </div>
    <div class="content">
      <div class="person">
        <img class="avatar" src="{{ avatar_data }}" alt="申请者头像">
        <div class="identity">
          <p class="nickname">{{ nickname }}</p>
          <div class="qq">QQ：{{ user_id }}</div>
        </div>
        <span class="status">{{ status }}</span>
      </div>
      <p class="label">申请理由</p>
      <p class="reason">{{ reason }}</p>
      {% if reject_reason %}
      <div class="reject"><span class="reject-title">拒绝理由</span>{{ reject_reason }}</div>
      {% endif %}
      <div class="footer">
        <span class="time">{{ request_time }}</span>
        <span class="brand">QQ群自动审核</span>
      </div>
    </div>
  </div>
</body>
</html>
"""

LEAVE_TEMPLATE = """
<html>
<head>
  <meta charset="UTF-8">
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: transparent; height: fit-content; min-height: 0; }
    body {
      width: fit-content;
      padding: 8px;
      color: #24324a;
      font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }
    .card {
      width: 680px;
      overflow: hidden;
      border-radius: 24px;
      background: #ffffff;
      box-shadow: 0 18px 46px rgba(43, 66, 102, 0.16);
    }
    .header {
      padding: 28px 32px 26px;
      color: #ffffff;
      background: linear-gradient(135deg, #667eea 0%, #8b9cf6 100%);
    }
    .eyebrow { margin: 0 0 8px; font-size: 12px; letter-spacing: .14em; opacity: .82; }
    h1 { margin: 0; font-size: 26px; font-weight: 500; }
    .header-desc { margin: 9px 0 0; color: #eaf0ff; font-size: 14px; }
    .content { padding: 30px 32px 28px; }
    .person { display: flex; align-items: center; gap: 18px; padding-bottom: 24px; border-bottom: 1px solid #e8edf5; }
    .avatar { width: 76px; height: 76px; flex: 0 0 auto; border-radius: 22px; object-fit: cover; background: #e4eaff; }
    .identity { min-width: 0; }
    .nickname { margin: 0 0 8px; font-size: 23px; font-weight: 500; }
    .qq { color: #7a879b; font-size: 14px; }
    .status { margin-left: auto; padding: 9px 14px; border-radius: 999px; color: {{ status_color }}; background: {{ status_background }}; font-size: 14px; white-space: nowrap; }
    .info-title { margin: 24px 0 10px; color: #7a879b; font-size: 12px; letter-spacing: .1em; }
    .time-box { padding: 16px 18px; border-radius: 14px; background: #f7f9fd; color: #34445d; font-size: 16px; }
    .operator { margin-top: 14px; padding: 14px 18px; border-left: 3px solid #e46b78; border-radius: 0 12px 12px 0; background: #fff1f3; color: #9f3f4b; font-size: 14px; }
    .footer { display: flex; justify-content: space-between; margin-top: 24px; color: #7a879b; font-size: 12px; }
    .brand { color: #5d7df2; font-weight: 500; }
  </style>
</head>
<body>
  <section class="card">
    <header class="header">
      <p class="eyebrow">ASTRBOT · GROUP NOTICE</p>
      <h1>群成员离开了群聊</h1>
      <p class="header-desc">群组成员变动通知</p>
    </header>
    <main class="content">
      <div class="person">
        <img class="avatar" src="{{ avatar_data }}" alt="退群者头像">
        <div class="identity">
          <p class="nickname">{{ nickname }}</p>
          <div class="qq">QQ：{{ user_id }}</div>
        </div>
        <span class="status">{{ event_label }}</span>
      </div>
      <p class="info-title">退群时间</p>
      <div class="time-box">{{ leave_time }}</div>
      {% if operator_id %}
      <div class="operator">操作人 QQ：{{ operator_id }}<br>该成员被管理员移出群聊</div>
      {% endif %}
      <div class="footer"><span>群号：{{ group_id }}</span><span class="brand">QQ群自动管理</span></div>
    </main>
  </section>
</body>
</html>
"""


def _escape(value) -> str:
    return html.escape(str(value or ""), quote=True)


def build_verify_chain(result, verify_result=None):
    """Build the original text and applicant-avatar review message chain.

    Args:
        result: Parsed group application data.
        verify_result: Optional review result returned by the AI verifier.

    Returns:
        A message component chain containing text and the applicant avatar.
    """
    chain = [Plain("收到一条入群申请")]
    if result.get("avatar"):
        chain.append(Image.fromFileSystem(result.get("avatar")))
    chain.append(
        Plain(
            f"申请者: {result.get('nickname')}\n"
            f"QQ: {result.get('user_id')}\n"
            f"等级: {result.get('level')}\n"
            f"申请时间: {result.get('time')}\n\n"
            f"{result.get('comment')}"
        )
    )
    if verify_result is not None:
        if verify_result.get("passed") is True:
            chain.append(Plain("\n\n审核结果：✅ 通过"))
        elif verify_result.get("status") == "skipped":
            chain.append(
                Plain(
                    "\n\n审核结果：⏭️ 跳过\n"
                    f"跳过理由：{verify_result.get('reason', '验证服务暂时不可用')}"
                )
            )
        else:
            reason = verify_result.get("reason", "验证未通过")
            chain.append(
                Plain(f"\n\n审核结果：❌ 拒绝\n拒绝理由：{reason}")
            )
    return chain


def build_leave_text(result):
    """Build a text notification for a group member decrease event.

    Args:
        result: Normalized group member decrease data.

    Returns:
        A message component chain containing the leave notification.
    """
    lines = [
        "-------------------------",
        "群成员离开了群聊",
        "",
        f"退群类型: {result['event_label']}",
        f"退群者昵称: {result['nickname']}",
        f"退群者QQ: {result['user_id']}",
    ]
    if result.get("operator_id"):
        lines.append(f"操作人QQ: {result['operator_id']}")
    lines.extend(
        [
            f"退群时间: {result['leave_time']}",
            "-------------------------",
        ]
    )
    return [Plain("\n".join(lines))]


async def build_leave_message(result):
    """Render a group member decrease notification as an image.

    Args:
        result: Normalized group member decrease data with avatar data.

    Returns:
        A message component chain containing the rendered image or text fallback.
    """
    avatar_data = ""
    avatar_path = result.get("avatar_path")
    if avatar_path:
        try:
            avatar_file = Path(avatar_path)
            mime_type = mimetypes.guess_type(avatar_file.name)[0] or "image/png"
            encoded_avatar = base64.b64encode(avatar_file.read_bytes()).decode("ascii")
            avatar_data = f"data:{mime_type};base64,{encoded_avatar}"
        except (OSError, ValueError) as error:
            logger.warning(f"读取退群者头像失败，将使用文字消息回退: {error}")
    if not avatar_data:
        return build_leave_text(result)
    try:
        image_path = await html_renderer.render_custom_template(
            LEAVE_TEMPLATE,
            {
                "avatar_data": avatar_data,
                "nickname": _escape(result["nickname"]),
                "user_id": _escape(result["user_id"]),
                "group_id": _escape(result["group_id"]),
                "leave_time": _escape(result["leave_time"]),
                "event_label": _escape(result["event_label"]),
                "operator_id": _escape(result.get("operator_id", "")),
                "status_color": result["status_color"],
                "status_background": result["status_background"],
            },
            return_url=False,
            options={
                "full_page": True,
                "omit_background": True,
                "viewport_width": 704,
                "viewport_height": 500,
                "type": "png",
                "quality": 90,
            },
        )
        rendered_image_file = Path(image_path)
        try:
            rendered_bytes = rendered_image_file.read_bytes()
        finally:
            rendered_image_file.unlink(missing_ok=True)
        with PILImage.open(io.BytesIO(rendered_bytes)) as rendered_image:
            rendered_image = rendered_image.convert("RGBA")
            alpha_box = rendered_image.getchannel("A").getbbox()
            if alpha_box:
                rendered_image = rendered_image.crop(alpha_box)
            background = PILImage.new("RGB", rendered_image.size, "#ffffff")
            background.paste(rendered_image, mask=rendered_image.getchannel("A"))
            output = io.BytesIO()
            background.save(output, format="JPEG", quality=65, optimize=True)
            return [Image.fromBytes(output.getvalue())]
    except Exception as error:
        logger.warning(f"渲染退群通知图片失败，将使用文字消息回退: {error}")
        return build_leave_text(result)


async def build_verify_message(context, result, verify_result=None):
    """Build an image-based review message with a text fallback.

    Args:
        context: AstrBot plugin context that provides the HTML renderer.
        result: Parsed group application data.
        verify_result: Optional review result returned by the AI verifier.

    Returns:
        A message component chain containing the rendered card or fallback text.
    """
    pipeline_started_at = time.perf_counter()
    user_id = result.get("user_id")
    logger.info(f"[图片节点] 入群审核图片流程开始，QQ={user_id}")
    passed = verify_result is not None and verify_result.get("passed") is True
    skipped = verify_result is not None and verify_result.get("status") == "skipped"
    reject_reason = "" if passed or skipped else (verify_result or {}).get(
        "reason", "验证未通过"
    )

    if skipped:
        status = "审核跳过"
        status_color = "#8a6418"
        status_background = "#fff4d6"
    elif passed:
        status = "审核通过"
        status_color = "#1b9a73"
        status_background = "#e7f8f1"
    else:
        status = "审核未通过"
        status_color = "#b24654"
        status_background = "#fff0f2"

    avatar_path = result.get("avatar")
    avatar_data = ""
    if avatar_path:
        try:
            avatar_file = Path(avatar_path)
            mime_type = mimetypes.guess_type(avatar_file.name)[0] or "image/png"
            encoded_avatar = base64.b64encode(avatar_file.read_bytes()).decode("ascii")
            avatar_data = f"data:{mime_type};base64,{encoded_avatar}"
            logger.info(
                f"[图片节点] 申请者头像读取完成，QQ={user_id}，"
                f"大小={avatar_file.stat().st_size / 1024:.1f}KB"
            )
        except (OSError, ValueError) as error:
            logger.warning(f"读取申请者头像失败，将使用文字消息回退: {error}")

    group_avatar_path = result.get("group_avatar")
    group_avatar_data = ""
    if group_avatar_path:
        try:
            group_avatar_file = Path(group_avatar_path)
            group_mime_type = (
                mimetypes.guess_type(group_avatar_file.name)[0] or "image/png"
            )
            encoded_group_avatar = base64.b64encode(
                group_avatar_file.read_bytes()
            ).decode("ascii")
            group_avatar_data = f"data:{group_mime_type};base64,{encoded_group_avatar}"
            logger.info(
                f"[图片节点] 群头像读取完成，QQ={user_id}，"
                f"大小={group_avatar_file.stat().st_size / 1024:.1f}KB"
            )
        except (OSError, ValueError) as error:
            logger.warning(f"读取群头像失败，将使用文字消息回退: {error}")

    if avatar_data and group_avatar_data:
        template_data = {
            "avatar_data": avatar_data,
            "group_avatar_data": group_avatar_data,
            "nickname": _escape(result.get("nickname", "未知用户")),
            "user_id": _escape(result.get("user_id", "未知")),
            "status": _escape(status),
            "status_color": status_color,
            "status_background": status_background,
            "reason": _escape(result.get("comment", "")),
            "reject_reason": _escape(reject_reason),
            "request_time": _escape(result.get("time", "获取失败")),
        }
        try:
            render_started_at = time.perf_counter()
            logger.info(f"[图片节点] 开始渲染入群审核图片，QQ={user_id}")
            image_path = await html_renderer.render_custom_template(
                CARD_TEMPLATE,
                template_data,
                return_url=False,
                options={
                    "full_page": True,
                    "omit_background": True,
                    "viewport_width": 704,
                    "viewport_height": 500,
                    "type": "png",
                    "quality": 90,
                },
            )
            logger.info(
                f"[图片节点] 入群审核图片渲染完成，QQ={user_id}，"
                f"耗时={time.perf_counter() - render_started_at:.3f}s，path={image_path}"
            )
            rendered_image_file = Path(image_path)
            try:
                rendered_bytes = rendered_image_file.read_bytes()
            finally:
                rendered_image_file.unlink(missing_ok=True)
            original_size = len(rendered_bytes)
            with PILImage.open(io.BytesIO(rendered_bytes)) as rendered_image:
                rendered_image = rendered_image.convert("RGBA")
                original_dimensions = rendered_image.size
                alpha_box = rendered_image.getchannel("A").getbbox()
                if alpha_box:
                    rendered_image = rendered_image.crop(alpha_box)
                logger.info(
                    f"[图片节点] 入群审核图片裁剪完成，QQ={user_id}，"
                    f"原尺寸={original_dimensions}，新尺寸={rendered_image.size}，"
                    f"裁剪框={alpha_box}"
                )
                background = PILImage.new("RGB", rendered_image.size, "#ffffff")
                background.paste(
                    rendered_image,
                    mask=rendered_image.getchannel("A"),
                )
                output = io.BytesIO()
                background.save(output, format="JPEG", quality=65, optimize=True)
                rendered_bytes = output.getvalue()
            logger.info(
                f"[图片节点] 入群审核图片压缩完成，QQ={user_id}，"
                f"原始大小={original_size / 1024:.1f}KB，"
                f"压缩后大小={len(rendered_bytes) / 1024:.1f}KB"
            )
            logger.info(
                f"[图片节点] 入群审核图片消息链创建完成，QQ={user_id}，"
                f"总耗时={time.perf_counter() - pipeline_started_at:.3f}s，准备交给AstrBot发送"
            )
            return [Image.fromBytes(rendered_bytes)]
        except Exception as error:
            logger.warning(
                f"渲染入群申请图片失败，将使用文字消息回退，QQ={user_id}，"
                f"已耗时={time.perf_counter() - pipeline_started_at:.3f}s，错误={error}"
            )

    if group_avatar_path:
        try:
            Path(group_avatar_path).unlink(missing_ok=True)
        except OSError as error:
            logger.warning(f"删除临时群头像失败: {error}")

    message = (
        f"申请者：{result.get('nickname')}\n"
        f"QQ：{result.get('user_id')}\n"
        f"等级：{result.get('level')}\n"
        f"申请时间：{result.get('time')}\n\n"
        f"{result.get('comment')}\n\n"
        f"审核结果：{status}"
    )
    if reject_reason:
        message += f"\n拒绝理由：{reject_reason}"
    return [Plain(message)]
