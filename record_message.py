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
    html, body { margin: 0; padding: 0; background: transparent; height: fit-content; min-height: 0; }
    body {
      width: fit-content;
      padding: 72px;
      color: #1B1A2E;
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    }
    .card {
      width: 760px;
      border-radius: 30px;
      overflow: hidden;
      background: #ffffff;
      border: 1px solid #EFEBFA;
      box-shadow: 0 28px 56px rgba(58, 42, 122, 0.16), 0 5px 14px rgba(58, 42, 122, 0.06);
    }

    /* ── Hero ── */
    .hero {
      position: relative;
      min-height: 208px;
      padding: 32px 34px 62px;
      color: #ffffff;
      background-color: #6C5CE7;
      background-image:
        radial-gradient(88% 118% at 90% 6%, rgba(255, 172, 112, 0.58) 0%, rgba(255, 172, 112, 0) 56%),
        radial-gradient(86% 104% at 8% 104%, rgba(126, 96, 255, 0.6) 0%, rgba(126, 96, 255, 0) 62%),
        linear-gradient(128deg, #5B4BE0 0%, #7C5CF0 46%, #9B6DFF 100%);
    }
    .hero-art { position: absolute; top: 18px; right: 28px; width: 150px; height: 150px; }
    .art-ring {
      position: absolute; inset: 0; margin: auto;
      width: 132px; height: 132px;
      border-radius: 50%;
      border: 1.5px solid rgba(255, 255, 255, 0.26);
    }
    .art-glow {
      position: absolute; inset: 0; margin: auto;
      width: 146px; height: 146px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255, 255, 255, 0.18) 0%, rgba(255, 255, 255, 0.06) 44%, rgba(255, 255, 255, 0) 70%);
    }
    .art-spark { position: absolute; left: 0; top: 24px; width: 22px; height: 22px; }
    .group-wrap { position: absolute; inset: 0; margin: auto; width: 88px; height: 88px; }
    .group-av {
      display: block;
      width: 88px; height: 88px;
      border-radius: 20px;
      border: 4px solid rgba(255, 255, 255, 0.88);
      object-fit: cover;
      background: #EFEAFF;
      box-shadow: 0 14px 30px rgba(36, 16, 88, 0.34);
    }
    .count-badge {
      position: absolute;
      right: -11px; bottom: -11px;
      display: grid; place-items: center;
      width: 34px; height: 34px;
      border-radius: 50%;
      background: #FF9A6B;
      border: 3.5px solid #ffffff;
      box-shadow: 0 7px 16px rgba(120, 52, 16, 0.32);
    }
    .count-badge svg { width: 17px; height: 17px; }

    .chip {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 6px 14px 6px 10px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.16);
      border: 1px solid rgba(255, 255, 255, 0.3);
      font-size: 10.5px; font-weight: 700; letter-spacing: 0.14em;
    }
    .chip .dot {
      width: 6px; height: 6px;
      border-radius: 50%;
      background: #8CF2C6;
      box-shadow: 0 0 0 3px rgba(140, 242, 198, 0.26);
    }
    h1 {
      margin: 17px 0 0;
      font-size: 31px; font-weight: 700; letter-spacing: 0.01em;
      text-shadow: 0 2px 12px rgba(40, 18, 92, 0.28);
    }
    .sub { margin: 10px 0 0; font-size: 13.5px; color: rgba(255, 255, 255, 0.82); }

    /* ── Records list, floated up over the hero edge ── */
    .sheet {
      position: relative; z-index: 2;
      margin: -46px 28px 0;
      padding: 6px 24px 18px;
      border-radius: 24px;
      background: #ffffff;
      border: 1px solid #F1EEFB;
      box-shadow: 0 18px 40px rgba(86, 70, 160, 0.15), 0 3px 10px rgba(86, 70, 160, 0.06);
    }
    .record {
      display: grid;
      grid-template-columns: 52px minmax(0, 1fr) auto;
      gap: 14px;
      align-items: start;
      padding: 16px 0;
    }
    .record + .record { border-top: 1px dashed #E2DDF4; }

    .applicant-avatar {
      display: grid; place-items: center;
      width: 52px; height: 52px;
      overflow: hidden;
      border-radius: 16px;
      background: linear-gradient(145deg, #B9A6FF, #8B6BFF);
      color: #ffffff;
      font-size: 19px; font-weight: 700;
    }
    img.applicant-avatar { object-fit: cover; }

    .identity { min-width: 0; }
    .name-line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
    .name { font-size: 16px; font-weight: 700; color: #1B1A2E; }
    .qq-tag {
      padding: 2px 7px;
      border-radius: 6px;
      background: #F2F0FA;
      color: #6C5CE7;
      font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em;
    }
    .qq { color: #4A4863; font-size: 12.5px; font-variant-numeric: tabular-nums; }
    .reason { margin: 8px 0 0; color: #4A4863; font-size: 13.5px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
    .time { display: flex; align-items: center; gap: 6px; margin-top: 8px; color: #6E6B88; font-size: 12px; font-variant-numeric: tabular-nums; }

    .status {
      display: inline-flex; align-items: center; gap: 7px;
      padding: 6px 13px 6px 11px;
      border-radius: 999px;
      border: 1px solid rgba(20, 30, 60, 0.07);
      font-size: 12.5px; font-weight: 700;
      white-space: nowrap;
    }
    .status::before {
      content: "";
      flex: 0 0 auto;
      width: 6px; height: 6px;
      border-radius: 50%;
      background: currentColor;
    }
    .passed { color: #0B8A66; background: #E4F7F0; }
    .rejected { color: #A83B4A; background: #FFF0F2; }
    .skipped { color: #8A6418; background: #FFF4D6; }

    .reject-box {
      grid-column: 2 / 4;
      margin-top: 2px;
      padding: 12px 16px;
      border: 1px solid #F7DADE;
      border-left: 3px solid #E46B78;
      border-radius: 0 14px 14px 0;
      background: #FFF5F6;
      color: #8E3742;
      font-size: 12.5px; line-height: 1.6;
      overflow-wrap: anywhere;
    }
    .reject-title {
      display: block;
      margin-bottom: 3px;
      color: #B24654;
      font-size: 11px; font-weight: 700; letter-spacing: 0.1em;
    }

    .sheet-footer {
      display: flex; align-items: center; justify-content: space-between; gap: 16px;
      margin-top: 4px; padding-top: 16px;
      border-top: 1px solid #F1EFFA;
      color: #6E6B88; font-size: 12.5px;
    }
    .brand {
      display: inline-flex; align-items: center; gap: 7px;
      padding: 6px 13px;
      border-radius: 999px;
      background: #F3F0FF;
      color: #5A48D6;
      font-size: 12.5px; font-weight: 700;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="hero">
      <!-- Group avatar with a history badge, so the card shows which group it is. -->
      <div class="hero-art">
        <span class="art-ring"></span>
        <span class="art-glow"></span>
        <svg class="art-spark" viewBox="0 0 24 24" fill="none">
          <path d="M12 2.6l2.4 6.6 6.6 2.4-6.6 2.4L12 20.6l-2.4-6.6L3 11.6l6.6-2.4z" fill="rgba(255,206,150,0.95)"/>
        </svg>
        <span class="group-wrap">
          <img class="group-av" src="{{ group_avatar_data }}" alt="群头像">
          <span class="count-badge">
            <svg viewBox="0 0 20 20" fill="none">
              <path d="M4.4 6.2h11.2M4.4 10h11.2M4.4 13.8h7" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round"/>
            </svg>
          </span>
        </span>
      </div>

      <span class="chip"><span class="dot"></span>ASTRBOT · REVIEW HISTORY</span>
      <h1>本群审核记录</h1>
      <p class="sub">第 {{ page }} / {{ total_pages }} 页 · 共 {{ total_count }} 条记录</p>
    </div>

    <div class="sheet">
      {% for record in records %}
      <article class="record">
        {% if record.avatar_data %}
        <img class="applicant-avatar" src="{{ record.avatar_data }}" alt="申请者头像">
        {% else %}
        <div class="applicant-avatar">{{ record.initial }}</div>
        {% endif %}
        <div class="identity">
          <div class="name-line">
            <span class="name">{{ record.nickname }}</span>
            <span class="qq"><span class="qq-tag">QQ</span> {{ record.user_id }}</span>
          </div>
          <p class="reason">申请理由：{{ record.reason }}</p>
          <div class="time">
            <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="#9A96B4" stroke-width="1.8">
              <circle cx="10" cy="10" r="7.6"/>
              <path d="M10 6.1V10l2.9 1.8" stroke-linecap="round"/>
            </svg>
            {{ record.time }}
          </div>
        </div>
        <span class="status {{ record.status_class }}">{{ record.status }}</span>
        {% if record.reject_reason %}
        <div class="reject-box"><span class="reject-title">拒绝理由</span>{{ record.reject_reason }}</div>
        {% endif %}
      </article>
      {% endfor %}

      <div class="sheet-footer">
        <span>{{ navigation }}</span>
        <span class="brand">
          <svg width="14" height="14" viewBox="0 0 20 20">
            <path d="M10 2.4l1.9 5.2 5.2 1.9-5.2 1.9L10 16.6 8.1 11.4 2.9 9.5l5.2-1.9z" fill="#6C5CE7"/>
          </svg>
          QQ群自动审核
        </span>
      </div>
    </div>
  </div>
</body>
</html>
"""


def _escape(value) -> str:
    return html.escape(str(value or ""), quote=True)


def build_review_records_text(records, page, total_pages):
    """Build the text format used when image sending is disabled.

    Args:
        records: Review records to render, newest first.
        page: Current one-based page number.
        total_pages: Total number of available pages.

    Returns:
        A message component chain containing the formatted records.
    """
    lines = [f"本群审核记录（第 {page}/{total_pages} 页）"]
    for record in records:
        lines.extend(
            [
                "-------------------------",
                f"申请时间: {record.get('time')}",
                f"昵称: {record.get('nickname')}",
                f"QQ: {record.get('user_id')}",
                f"申请理由: {record.get('reason')}",
                f"审核状态: {record.get('status')}",
            ]
        )
        if record.get("status") == "未通过":
            lines.append(f"拒绝理由: {record.get('reject_reason') or '无'}")
    lines.append("--------------------------")
    return [Plain("\n".join(lines))]


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
    group_avatar_data = ""
    if group_avatar_path:
        try:
            avatar_file = Path(group_avatar_path)
            mime_type = mimetypes.guess_type(avatar_file.name)[0] or "image/png"
            encoded_avatar = base64.b64encode(avatar_file.read_bytes()).decode("ascii")
            group_avatar_data = f"data:{mime_type};base64,{encoded_avatar}"
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
                "viewport_width": 920,
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
            original_dimensions = rendered_image.size
            alpha_box = rendered_image.getchannel("A").getbbox()
            if alpha_box:
                rendered_image = rendered_image.crop(alpha_box)
            background = PILImage.new("RGB", rendered_image.size, "#ffffff")
            background.paste(
                rendered_image,
                mask=rendered_image.getchannel("A"),
            )
            output = io.BytesIO()
            background.save(output, format="JPEG", quality=65, optimize=True)
            rendered_bytes = output.getvalue()
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
