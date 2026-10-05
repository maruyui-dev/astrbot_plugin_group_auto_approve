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
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: transparent; height: fit-content; min-height: 0; }
  body {
    width: fit-content;
    padding: 0;
    color: #1B1A2E;
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
  }

  .card {
    width: 720px;
    border-radius: 30px;
    overflow: hidden;
    background: #ffffff;
    border: 1px solid #EFEBFA;
    box-shadow: 0 28px 56px rgba(58, 42, 122, 0.16), 0 5px 14px rgba(58, 42, 122, 0.06);
  }

  /* ── Hero: violet dusk gradient + warm apricot glow + illustration ── */
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
  /* ── Hero art: the group avatar, with an "add member" badge ── */
  .hero-art { position: absolute; top: 18px; right: 28px; width: 150px; height: 150px; }
  .art-ring { position: absolute; inset: 0; margin: auto; border-radius: 50%; }
  .art-ring.r1 { width: 132px; height: 132px; border: 1.5px solid rgba(255, 255, 255, 0.26); }
  .art-glow {
    position: absolute;
    inset: 0; margin: auto;
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
  .plus-badge {
    position: absolute;
    right: -11px; bottom: -11px;
    display: grid;
    place-items: center;
    width: 34px; height: 34px;
    border-radius: 50%;
    background: #2FBF8F;
    border: 3.5px solid #ffffff;
    box-shadow: 0 7px 16px rgba(16, 92, 70, 0.34);
  }
  .plus-badge svg { width: 17px; height: 17px; }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px 6px 10px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.16);
    border: 1px solid rgba(255, 255, 255, 0.3);
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.14em;
  }
  .chip .dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #8CF2C6;
    box-shadow: 0 0 0 3px rgba(140, 242, 198, 0.26);
  }
  h1 {
    margin: 17px 0 0;
    font-size: 31px;
    font-weight: 700;
    letter-spacing: 0.01em;
    text-shadow: 0 2px 12px rgba(40, 18, 92, 0.28);
  }
  .sub { margin: 10px 0 0; font-size: 13.5px; color: rgba(255, 255, 255, 0.82); }

  /* ── Applicant panel, floated up over the hero edge ── */
  .pass {
    position: relative;
    z-index: 2;
    display: flex;
    align-items: center;
    gap: 16px;
    margin: -46px 28px 0;
    padding: 18px 22px;
    border-radius: 24px;
    background: #ffffff;
    border: 1px solid #F1EEFB;
    box-shadow: 0 18px 40px rgba(86, 70, 160, 0.15), 0 3px 10px rgba(86, 70, 160, 0.06);
  }
  .ring {
    flex: 0 0 auto;
    width: 72px; height: 72px;
    padding: 3px;
    border-radius: 23px;
    background: linear-gradient(140deg, #8B6BFF 0%, #FF9A6B 58%, #FFC98F 100%);
    box-shadow: 0 8px 20px rgba(108, 92, 231, 0.24);
  }
  .ring img { display: block; width: 100%; height: 100%; border-radius: 20px; object-fit: cover; background: #EFEAFF; }

  .who { min-width: 0; }
  .name { margin: 0; font-size: 20px; font-weight: 700; letter-spacing: 0.01em; }
  .qq { display: flex; align-items: center; gap: 7px; margin-top: 7px; }
  .qq-tag {
    padding: 2px 7px;
    border-radius: 6px;
    background: #F2F0FA;
    color: #6C5CE7;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.06em;
  }
  .qq-id { color: #4A4863; font-size: 13px; font-variant-numeric: tabular-nums; }

  .status {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-left: auto;
    padding: 9px 16px 9px 13px;
    border-radius: 999px;
    border: 1px solid rgba(20, 30, 60, 0.07);
    color: {{ status_color }};
    background: {{ status_background }};
    font-size: 13.5px;
    font-weight: 700;
    white-space: nowrap;
  }
  .status::before {
    content: "";
    flex: 0 0 auto;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: currentColor;
  }

  /* ── Body ── */
  .body { padding: 24px 34px 26px; }
  .sec-head { display: flex; align-items: center; gap: 13px; margin-bottom: 15px; }
  .sec-title { font-size: 12.5px; font-weight: 700; letter-spacing: 0.13em; color: #726F8C; }
  .sec-line { flex: 1; height: 1px; background: linear-gradient(90deg, #E6E2F5 0%, rgba(245, 243, 252, 0) 100%); }

  /* The reason arrives as one pre-wrapped block. ::first-line lets the question
     line carry the highlight without splitting the string in Python. */
  .qa-text {
    margin: 0;
    padding: 15px 22px;
    border-radius: 20px;
    background: #F8F7FD;
    border: 1px solid #EDEAF8;
    color: #4A4863;
    font-size: 15px;
    line-height: 1.8;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .qa-text::first-line {
    color: #5A48D6;
    font-weight: 700;
    background-color: #ECE7FF;
  }

  .reject-box {
    margin-top: 12px;
    padding: 14px 18px;
    border: 1px solid #F7DADE;
    border-left: 3px solid #E46B78;
    border-radius: 0 16px 16px 0;
    background: #FFF5F6;
    color: #8E3742;
    font-size: 13.5px;
    line-height: 1.65;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .reject-title {
    display: block;
    margin-bottom: 4px;
    color: #B24654;
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 0.1em;
  }

  .meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 18px;
    padding-top: 18px;
    border-top: 1px solid #F1EFFA;
  }
  .time { display: inline-flex; align-items: center; gap: 8px; color: #6E6B88; font-size: 13px; font-variant-numeric: tabular-nums; }
  .brand {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 6px 13px;
    border-radius: 999px;
    background: #F3F0FF;
    color: #5A48D6;
    font-size: 12.5px;
    font-weight: 700;
  }
</style>
</head>
<body>
  <div class="card">
    <div class="hero">
      <!-- Group avatar with an "add member" badge, so the card always shows which group it is. -->
      <div class="hero-art">
        <span class="art-ring r1"></span>
        <span class="art-glow"></span>
        <svg class="art-spark" viewBox="0 0 24 24" fill="none">
          <path d="M12 2.6l2.4 6.6 6.6 2.4-6.6 2.4L12 20.6l-2.4-6.6L3 11.6l6.6-2.4z" fill="rgba(255,206,150,0.95)"/>
        </svg>
        <span class="group-wrap">
          <img class="group-av" src="{{ group_avatar_data }}" alt="群头像">
          <span class="plus-badge">
            <svg viewBox="0 0 20 20" fill="none">
              <path d="M10 4.2v11.6M4.2 10h11.6" stroke="#ffffff" stroke-width="3" stroke-linecap="round"/>
            </svg>
          </span>
        </span>
      </div>

      <span class="chip"><span class="dot"></span>ASTRBOT · 自动审核</span>
      <h1>新的入群申请</h1>
      <p class="sub">有人申请加入你的群聊，等待你的确认</p>
    </div>

    <div class="pass">
      <span class="ring"><img src="{{ avatar_data }}" alt="申请者头像"></span>
      <div class="who">
        <p class="name">{{ nickname }}</p>
        <div class="qq"><span class="qq-tag">QQ</span><span class="qq-id">{{ user_id }}</span></div>
      </div>
      <span class="status">{{ status }}</span>
    </div>

    <div class="body">
      <div class="sec-head">
        <span class="sec-title">申请理由</span>
        <span class="sec-line"></span>
      </div>

      <p class="qa-text">{{ reason }}</p>

      {% if reject_reason %}
      <div class="reject-box"><span class="reject-title">拒绝理由</span>{{ reject_reason }}</div>
      {% endif %}

      <div class="meta">
        <span class="time">
          <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="#9A96B4" stroke-width="1.7">
            <circle cx="10" cy="10" r="7.6"/>
            <path d="M10 6.1V10l2.9 1.8" stroke-linecap="round"/>
          </svg>
          {{ request_time }}
        </span>
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

LEAVE_TEMPLATE = """
<html>
<head>
  <meta charset="UTF-8">
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: transparent; height: fit-content; min-height: 0; }
    body {
      width: fit-content;
      padding: 0;
      color: #1B1A2E;
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    }
    .card {
      width: 680px;
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
    .art-tile {
      position: absolute; inset: 0; margin: auto;
      display: grid; place-items: center;
      width: 88px; height: 88px;
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.16);
      border: 3px solid rgba(255, 255, 255, 0.55);
      box-shadow: 0 14px 30px rgba(36, 16, 88, 0.28);
    }
    .art-tile svg { width: 46px; height: 46px; }
    .art-spark { position: absolute; left: 0; top: 24px; width: 22px; height: 22px; }

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

    /* ── Member panel, floated up over the hero edge ── */
    .member {
      position: relative; z-index: 2;
      display: flex; align-items: center; gap: 16px;
      margin: -46px 28px 0;
      padding: 18px 22px;
      border-radius: 24px;
      background: #ffffff;
      border: 1px solid #F1EEFB;
      box-shadow: 0 18px 40px rgba(86, 70, 160, 0.15), 0 3px 10px rgba(86, 70, 160, 0.06);
    }
    .ring {
      flex: 0 0 auto;
      width: 72px; height: 72px;
      padding: 3px;
      border-radius: 23px;
      background: linear-gradient(140deg, #8B6BFF 0%, #FF9A6B 58%, #FFC98F 100%);
      box-shadow: 0 8px 20px rgba(108, 92, 231, 0.24);
    }
    .ring img { display: block; width: 100%; height: 100%; border-radius: 20px; object-fit: cover; background: #EFEAFF; }
    .batch-icon {
      display: grid; place-items: center;
      flex: 0 0 auto;
      width: 72px; height: 72px;
      border-radius: 23px;
      background: linear-gradient(140deg, #8B6BFF 0%, #FF9A6B 100%);
      box-shadow: 0 8px 20px rgba(108, 92, 231, 0.24);
    }
    .batch-icon svg { width: 38px; height: 38px; }
    .who { min-width: 0; }
    .name { margin: 0; font-size: 20px; font-weight: 700; letter-spacing: 0.01em; }
    .qq { display: flex; align-items: center; gap: 7px; margin-top: 7px; }
    .qq-tag {
      padding: 2px 7px;
      border-radius: 6px;
      background: #F2F0FA;
      color: #6C5CE7;
      font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em;
    }
    .qq-id { color: #4A4863; font-size: 13px; font-variant-numeric: tabular-nums; }
    .status {
      display: inline-flex; align-items: center; gap: 8px;
      margin-left: auto;
      padding: 9px 16px 9px 13px;
      border-radius: 999px;
      border: 1px solid rgba(20, 30, 60, 0.07);
      color: {{ status_color }};
      background: {{ status_background }};
      font-size: 13.5px; font-weight: 700;
      white-space: nowrap;
    }
    .status::before {
      content: "";
      flex: 0 0 auto;
      width: 7px; height: 7px;
      border-radius: 50%;
      background: currentColor;
    }

    /* ── Body ── */
    .body { padding: 24px 34px 26px; }
    .sec-head { display: flex; align-items: center; gap: 13px; margin-bottom: 15px; }
    .sec-title { font-size: 12.5px; font-weight: 700; letter-spacing: 0.13em; color: #726F8C; }
    .sec-line { flex: 1; height: 1px; background: linear-gradient(90deg, #E6E2F5 0%, rgba(245, 243, 252, 0) 100%); }

    .time-panel {
      display: flex; align-items: center; gap: 14px;
      padding: 18px 22px;
      border-radius: 20px;
      background: #F8F7FD;
      border: 1px solid #EDEAF8;
    }
    .time-panel svg { width: 22px; height: 22px; flex: 0 0 auto; }
    .time-value {
      font-size: 17px; font-weight: 700; color: #23213A;
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.01em;
    }

    .operator {
      margin-top: 12px;
      padding: 15px 20px;
      border: 1px solid #F7DADE;
      border-left: 3px solid #E46B78;
      border-radius: 0 18px 18px 0;
      background: #FFF5F6;
      color: #8E3742;
      font-size: 13.5px; line-height: 1.65;
    }
    .operator-title {
      display: block;
      margin-bottom: 5px;
      color: #B24654;
      font-size: 11.5px; font-weight: 700; letter-spacing: 0.1em;
    }
    .operator .who-line { color: #23213A; font-weight: 700; }

    .meta {
      display: flex; align-items: center; justify-content: space-between;
      margin-top: 18px; padding-top: 18px;
      border-top: 1px solid #F1EFFA;
    }
    .group {
      display: inline-flex; align-items: center; gap: 8px;
      color: #6E6B88; font-size: 13px;
      font-variant-numeric: tabular-nums;
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
      <!-- Illustration: a member stepping out through the door. -->
      <div class="hero-art">
        <span class="art-ring"></span>
        <span class="art-glow"></span>
        <svg class="art-spark" viewBox="0 0 24 24" fill="none">
          <path d="M12 2.6l2.4 6.6 6.6 2.4-6.6 2.4L12 20.6l-2.4-6.6L3 11.6l6.6-2.4z" fill="rgba(255,206,150,0.95)"/>
        </svg>
        <span class="art-tile">
          <svg viewBox="0 0 48 48" fill="none">
            <rect x="6" y="10" width="16" height="28" rx="5.5" fill="rgba(255,255,255,0.5)"/>
            <path d="M17 24h21" stroke="#ffffff" stroke-width="3.4" stroke-linecap="round"/>
            <path d="M31.5 17.5L38 24l-6.5 6.5" stroke="#ffffff" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
      </div>

      <span class="chip"><span class="dot"></span>ASTRBOT · 自动管理</span>
      <h1>群成员离开了群聊</h1>
      <p class="sub">群组成员变动通知</p>
    </div>

    <div class="member">
      {% if is_batch %}
      <span class="batch-icon">
        <svg viewBox="0 0 48 48" fill="none">
          <circle cx="18" cy="17" r="6" fill="rgba(255,255,255,0.9)"/>
          <circle cx="32" cy="19" r="5" fill="rgba(255,255,255,0.65)"/>
          <path d="M7 35c1.8-6.2 5.5-9.2 11-9.2S27.2 28.8 29 35" stroke="#ffffff" stroke-width="3" stroke-linecap="round"/>
          <path d="M28 29.5h12M34 23.5v12" stroke="#ffffff" stroke-width="3" stroke-linecap="round"/>
        </svg>
      </span>
      <div class="who">
        <p class="name">批量移出群成员</p>
        <div class="qq"><span class="qq-tag">数量</span><span class="qq-id">{{ count }} 人</span></div>
      </div>
      <span class="status">{{ event_label }}</span>
      {% else %}
      <span class="ring"><img src="{{ avatar_data }}" alt="退群者头像"></span>
      <div class="who">
        <p class="name">{{ nickname }}</p>
        <div class="qq"><span class="qq-tag">QQ</span><span class="qq-id">{{ user_id }}</span></div>
      </div>
      <span class="status">{{ event_label }}</span>
      {% endif %}
    </div>

    <div class="body">
      <div class="sec-head">
        <span class="sec-title">退群时间</span>
        <span class="sec-line"></span>
      </div>

      <div class="time-panel">
        <svg viewBox="0 0 24 24" fill="none" stroke="#8B84C8" stroke-width="1.9">
          <circle cx="12" cy="12" r="9"/>
          <path d="M12 7.2V12l3.6 2.2" stroke-linecap="round"/>
        </svg>
        <span class="time-value">{{ leave_time }}</span>
      </div>

      {% if operator_id %}
      <div class="operator">
        <span class="operator-title">操作人</span>
        <span class="who-line">{{ operator_nickname }}</span>（QQ：{{ operator_id }}）<br>
        {% if is_batch %}本批成员已被管理员移出群聊{% else %}该成员被管理员移出群聊{% endif %}
      </div>
      {% endif %}

      <div class="meta">
        <span class="group">
          <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="#9A96B4" stroke-width="1.7">
            <circle cx="8" cy="7" r="3.2"/>
            <path d="M2.6 16.4a5.6 5.6 0 0 1 10.8 0" stroke-linecap="round"/>
            <path d="M14.2 5.2a2.8 2.8 0 0 1 0 5.4M15.6 16.4a5.2 5.2 0 0 0-2.4-4.2" stroke-linecap="round"/>
          </svg>
          群号 {{ group_id }}
        </span>
        <span class="brand">
          <svg width="14" height="14" viewBox="0 0 20 20">
            <path d="M10 2.4l1.9 5.2 5.2 1.9-5.2 1.9L10 16.6 8.1 11.4 2.9 9.5l5.2-1.9z" fill="#6C5CE7"/>
          </svg>
          QQ群自动管理
        </span>
      </div>
    </div>
  </div>
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
    if result.get("is_batch"):
        lines = [
            "-------------------------",
            "群成员批量变动",
            "",
            f"本次被管理员移出人数: {result['count']} 人",
        ]
    else:
        lines = [
            "-------------------------",
            "群成员离开了群聊",
            "",
            f"退群类型: {result['event_label']}",
            f"退群者昵称: {result['nickname']}",
            f"退群者QQ: {result['user_id']}",
        ]
    if result.get("operator_id"):
        lines.append(
            f"操作人昵称: {result.get('operator_nickname', '未知用户')}\n"
            f"操作人QQ: {result['operator_id']}"
        )
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
    if not avatar_data and not result.get("is_batch"):
        return build_leave_text(result)
    try:
        viewport_height = 500 if result.get("operator_id") else 420
        image_path = await html_renderer.render_custom_template(
            LEAVE_TEMPLATE,
            {
                "avatar_data": avatar_data,
                "is_batch": result.get("is_batch", False),
                "count": result.get("count", 1),
                "nickname": _escape(result.get("nickname", "群成员")),
                "user_id": _escape(result.get("user_id", "")),
                "group_id": _escape(result.get("group_id", "")),
                "leave_time": _escape(result.get("leave_time", "获取失败")),
                "event_label": _escape(result.get("event_label", "群成员变动")),
                "operator_id": _escape(result.get("operator_id", "")),
                "operator_nickname": _escape(
                    result.get("operator_nickname", "未知用户")
                ),
                "status_color": result["status_color"],
                "status_background": result["status_background"],
            },
            return_url=False,
            options={
                "full_page": True,
                "omit_background": True,
                "viewport_width": 680,
                "viewport_height": viewport_height,
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
            viewport_height = 500 if reject_reason else 420
            image_path = await html_renderer.render_custom_template(
                CARD_TEMPLATE,
                template_data,
                return_url=False,
                options={
                    "full_page": True,
                    "omit_background": True,
                    "viewport_width": 720,
                    "viewport_height": viewport_height,
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
