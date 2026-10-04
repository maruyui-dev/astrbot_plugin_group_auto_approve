import base64
import html
import io
import mimetypes
import time
from pathlib import Path

from PIL import Image as PILImage
from astrbot.api import html_renderer, logger
from astrbot.api.message_components import Image, Plain
from .record_store import get_record_avatar_path

RECORDS_TEMPLATE = """
<html>
<head>
  <meta charset="UTF-8">
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: transparent; }
    body {
      width: fit-content;
      padding: 8px;
      color: #20314a;
      font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }
    .card {
      width: 760px;
      overflow: hidden;
      border-radius: 24px;
      background: #ffffff;
      box-shadow: 0 18px 46px rgba(43, 66, 102, 0.14);
    }
    .hero {
      position: relative;
      min-height: 124px;
      padding: 26px 120px 23px 30px;
      color: #ffffff;
      background: linear-gradient(135deg, #5a82ff 0%, #7e9cff 100%);
    }
    .eyebrow { margin: 0 0 6px; color: #e9efff; font-size: 12px; letter-spacing: .14em; }
    h1 { margin: 0; font-size: 24px; font-weight: 500; }
    .subtitle { margin: 8px 0 0; color: #e5ebff; font-size: 13px; }
    .group-avatar {
      position: absolute;
      top: 27px;
      right: 30px;
      width: 70px;
      height: 70px;
      border: 4px solid rgba(255,255,255,.8);
      border-radius: 22px;
      object-fit: cover;
      background: #d9e3ff;
    }
    .records { padding: 9px 22px 17px; }
    .record {
      display: grid;
      grid-template-columns: 48px minmax(0, 1fr) auto;
      gap: 13px;
      align-items: start;
      padding: 17px 8px;
      border-bottom: 1px solid #e8edf5;
    }
    .record:last-child { border-bottom: 0; }
    .applicant-avatar {
      display: grid;
      place-items: center;
      width: 48px;
      height: 48px;
      overflow: hidden;
      border-radius: 15px;
      background: linear-gradient(145deg, #d9e3ff, #9bb4ff);
      color: #ffffff;
      font-size: 18px;
      font-weight: 500;
    }
    img.applicant-avatar { object-fit: cover; }
    .identity { min-width: 0; }
    .name-line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 9px; }
    .name { font-size: 16px; font-weight: 500; }
    .qq, .time { color: #738198; font-size: 12px; }
    .reason { margin: 8px 0 0; color: #34445d; font-size: 13px; line-height: 1.55; overflow-wrap: anywhere; }
    .status { padding: 6px 9px; border-radius: 999px; font-size: 12px; white-space: nowrap; }
    .passed { color: #1b9a73; background: #e7f8f1; }
    .rejected { color: #b24654; background: #fff0f2; }
    .skipped { color: #8a6418; background: #fff4d6; }
    .reject-box {
      grid-column: 2 / 4;
      padding: 11px 14px;
      border-left: 3px solid #e46b78;
      border-radius: 0 12px 12px 0;
      background: #fff1f3;
      color: #9f3f4b;
      font-size: 12px;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .reject-title { display: block; margin-bottom: 3px; color: #b24654; font-weight: 500; letter-spacing: .08em; }
    .footer { display: flex; justify-content: space-between; gap: 16px; padding: 13px 30px 20px; color: #738198; font-size: 12px; }
    .brand { color: #4f7cff; font-weight: 500; }
  </style>
</head>
<body>
  <section class="card">
    <header class="hero">
      <p class="eyebrow">ASTRBOT · REVIEW HISTORY</p>
      <h1>本群审核记录</h1>
      <p class="subtitle">第 {{ page }} / {{ total_pages }} 页 · 共 {{ total_count }} 条记录</p>
      <img class="group-avatar" src="{{ group_avatar_data }}" alt="群头像">
    </header>
    <div class="records">
      {% for record in records %}
      <article class="record">
        {% if record.avatar_data %}
        <img class="applicant-avatar" src="{{ record.avatar_data }}" alt="申请者头像">
        {% else %}
        <div class="applicant-avatar">{{ record.initial }}</div>
        {% endif %}
        <div class="identity">
          <div class="name-line"><span class="name">{{ record.nickname }}</span><span class="qq">QQ：{{ record.user_id }}</span></div>
          <p class="reason">申请理由：{{ record.reason }}</p>
          <div class="time">{{ record.time }}</div>
        </div>
        <span class="status {{ record.status_class }}">{{ record.status }}</span>
        {% if record.reject_reason %}<div class="reject-box"><span class="reject-title">拒绝理由</span>{{ record.reject_reason }}</div>{% endif %}
      </article>
      {% endfor %}
    </div>
    <footer class="footer"><span>{{ navigation }}</span><span class="brand">QQ群自动审核</span></footer>
  </section>
</body>
</html>
"""


def _escape(value) -> str:
    return html.escape(str(value or ""), quote=True)


async def build_review_records_message(
    records,
    group_avatar_path,
    page,
    total_pages,
):
    """Render a page of review records as an image.

    Args:
        records: Review records to render, newest first.
        group_avatar_path: Temporary local path to the group avatar.
        page: Current one-based page number.
        total_pages: Total number of available pages.

    Returns:
        A message component chain containing the rendered image or text fallback.
    """
    pipeline_started_at = time.perf_counter()
    logger.info(
        f"[图片节点] 审核记录图片流程开始，第{page}页，记录数={len(records)}"
    )
    group_avatar_data = ""
    if group_avatar_path:
        try:
            avatar_file = Path(group_avatar_path)
            mime_type = mimetypes.guess_type(avatar_file.name)[0] or "image/png"
            encoded_avatar = base64.b64encode(avatar_file.read_bytes()).decode("ascii")
            group_avatar_data = f"data:{mime_type};base64,{encoded_avatar}"
            logger.info(
                f"[图片节点] 审核记录图片群头像读取完成，"
                f"大小={avatar_file.stat().st_size / 1024:.1f}KB"
            )
        except (OSError, ValueError) as error:
            logger.warning(f"读取群头像失败，将使用文字消息回退: {error}")

    try:
        if not group_avatar_data:
            raise RuntimeError("group avatar is unavailable")

        status_class = {"通过": "passed", "未通过": "rejected", "跳过": "skipped"}
        template_records = []
        for record in records:
            avatar_data = ""
            avatar_path = get_record_avatar_path(record.get("avatar_file"))
            if avatar_path and avatar_path.is_file():
                try:
                    mime_type = mimetypes.guess_type(avatar_path.name)[0] or "image/png"
                    encoded_avatar = base64.b64encode(
                        avatar_path.read_bytes()
                    ).decode("ascii")
                    avatar_data = f"data:{mime_type};base64,{encoded_avatar}"
                except (OSError, ValueError) as error:
                    logger.warning(
                        f"读取审核记录申请者头像失败，将使用首字占位: {error}"
                    )
            template_records.append(
                {
                    "initial": _escape(record.get("nickname", "未知用户")[:1]),
                    "avatar_data": avatar_data,
                    "nickname": _escape(record.get("nickname", "未知用户")),
                    "user_id": _escape(record.get("user_id", "未知")),
                    "reason": _escape(record.get("reason", "")),
                    "time": _escape(record.get("time", "获取失败")),
                    "status": _escape(record.get("status", "未知")),
                    "status_class": status_class.get(record.get("status"), "skipped"),
                    "reject_reason": _escape(record.get("reject_reason", "")),
                }
            )

        navigation = (
            f"使用 /验证 记录 {page + 1} 查看下一页"
            if page < total_pages
            else "已经是最后一页"
        )
        render_started_at = time.perf_counter()
        logger.info("[图片节点] 开始渲染审核记录图片")
        image_path = await html_renderer.render_custom_template(
            RECORDS_TEMPLATE,
            {
                "group_avatar_data": group_avatar_data,
                "records": template_records,
                "page": page,
                "total_pages": total_pages,
                "total_count": len(records),
                "navigation": navigation,
            },
            return_url=False,
            options={
                "full_page": True,
                "omit_background": True,
                "viewport_width": 784,
                "type": "png",
                "quality": 90,
            },
        )
        logger.info(
            f"[图片节点] 审核记录图片渲染完成，耗时={time.perf_counter() - render_started_at:.3f}s，"
            f"path={image_path}"
        )
        rendered_bytes = Path(image_path).read_bytes()
        original_size = len(rendered_bytes)
        with PILImage.open(io.BytesIO(rendered_bytes)) as rendered_image:
            rendered_image = rendered_image.convert("RGBA")
            original_dimensions = rendered_image.size
            alpha_box = rendered_image.getchannel("A").getbbox()
            if alpha_box:
                rendered_image = rendered_image.crop(alpha_box)
            logger.info(
                f"[图片节点] 审核记录图片裁剪完成，原尺寸={original_dimensions}，"
                f"新尺寸={rendered_image.size}，裁剪框={alpha_box}"
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
            f"[图片节点] 审核记录图片压缩完成，原始大小={original_size / 1024:.1f}KB，"
            f"压缩后大小={len(rendered_bytes) / 1024:.1f}KB"
        )
        logger.info(
            f"[图片节点] 审核记录图片消息链创建完成，"
            f"总耗时={time.perf_counter() - pipeline_started_at:.3f}s，准备交给AstrBot发送"
        )
        return [Image.fromBytes(rendered_bytes)]
    except Exception as error:
        logger.warning(
            f"渲染审核记录图片失败，将使用文字消息回退，"
            f"已耗时={time.perf_counter() - pipeline_started_at:.3f}s，错误={error}"
        )
        lines = [f"本群审核记录（第 {page}/{total_pages} 页）"]
        for record in records:
            lines.append(
                f"昵称：{record.get('nickname')}\n"
                f"QQ：{record.get('user_id')}\n"
                f"申请理由：{record.get('reason')}\n"
                f"审核状态：{record.get('status')}\n"
                f"拒绝理由：{record.get('reject_reason') or '无'}\n"
                f"时间：{record.get('time')}"
            )
        return [Plain("\n\n".join(lines))]
    finally:
        if group_avatar_path:
            try:
                Path(group_avatar_path).unlink(missing_ok=True)
            except OSError as error:
                logger.warning(f"删除临时群头像失败: {error}")
