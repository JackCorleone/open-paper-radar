"""推送适配层：Server酱 / PushPlus / WxPusher / 企业微信机器人 / 邮件。

所有渠道都通过环境变量配置，workflow 里用 GitHub Secrets 注入：
- PUSHPLUS_TOKEN            PushPlus（微信公众号推送，推荐）
- SERVERCHAN_SENDKEY        Server酱 Turbo
- WXPUSHER_APP_TOKEN        WxPusher 应用 token
- WXPUSHER_UIDS             可选，逗号分隔的接收者 uid，留空发给所有订阅者
- WECOM_WEBHOOK             企业微信群机器人 webhook
- SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / MAIL_TO / MAIL_FROM
- NOTIFY_PROVIDER           显式指定渠道；auto 表示按可用性自动选择
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from .http import HttpError, request_json
from .util import env, get_logger

log = get_logger(__name__)

PROVIDERS = ("pushplus", "serverchan", "wxpusher", "wecom", "email")


@dataclass
class NotifyResult:
    ok: bool
    provider: str
    detail: str = ""


def detect_provider(preferred: str = "auto") -> Optional[str]:
    """按配置与环境变量选择渠道。"""
    preferred = (preferred or "auto").strip().lower()
    if preferred in PROVIDERS and _provider_configured(preferred):
        return preferred
    order = ["pushplus", "serverchan", "wxpusher", "wecom", "email"]
    for name in order:
        if _provider_configured(name):
            return name
    return None


def _provider_configured(provider: str) -> bool:
    if provider == "pushplus":
        return bool(env("PUSHPLUS_TOKEN"))
    if provider == "serverchan":
        return bool(env("SERVERCHAN_SENDKEY"))
    if provider == "wxpusher":
        return bool(env("WXPUSHER_APP_TOKEN"))
    if provider == "wecom":
        return bool(env("WECOM_WEBHOOK"))
    if provider == "email":
        return bool(env("SMTP_HOST") and env("MAIL_TO"))
    return False


def send(
    title: str,
    content: str,
    provider: Optional[str] = None,
    summary: str = "",
    html: bool = False,
) -> NotifyResult:
    """发送一条消息。provider 为 None 时自动选择。"""
    name = provider or detect_provider()
    if not name:
        return NotifyResult(False, "none", "没有配置任何推送渠道")
    try:
        if name == "pushplus":
            return _send_pushplus(title, content, html=html)
        if name == "serverchan":
            return _send_serverchan(title, content)
        if name == "wxpusher":
            return _send_wxpusher(title, content, summary)
        if name == "wecom":
            return _send_wecom(title, content)
        if name == "email":
            return _send_email(title, content)
    except HttpError as exc:
        return NotifyResult(False, name, f"HTTP {exc.status}: {exc.body[:200]}")
    except Exception as exc:  # noqa: BLE001 - 推送失败不应中断流程
        return NotifyResult(False, name, f"{type(exc).__name__}: {exc}")
    return NotifyResult(False, name, f"未知渠道 {name}")


def _send_pushplus(title: str, content: str, html: bool = False) -> NotifyResult:
    token = env("PUSHPLUS_TOKEN")
    assert token
    template = "html" if html else "markdown"
    data = request_json(
        "https://www.pushplus.plus/send",
        method="POST",
        payload={"token": token, "title": title, "content": content, "template": template},
        timeout=30,
        retries=2,
    )
    code = data.get("code")
    ok = code == 200
    detail = f"code={code} msg={data.get('msg', '')}"
    log.info("PushPlus 推送%s：%s", "成功" if ok else "失败", detail)
    return NotifyResult(ok, "pushplus", detail)


def _send_serverchan(title: str, content: str) -> NotifyResult:
    sendkey = env("SERVERCHAN_SENDKEY")
    assert sendkey
    data = request_json(
        f"https://sctapi.ftqq.com/{sendkey}.send",
        method="POST",
        payload={"title": title, "desp": content},
        timeout=30,
        retries=2,
    )
    ok = data.get("code") == 0
    detail = f"code={data.get('code')} msg={data.get('message', '')}"
    log.info("Server酱 推送%s：%s", "成功" if ok else "失败", detail)
    return NotifyResult(ok, "serverchan", detail)


def _send_wxpusher(title: str, content: str, summary: str) -> NotifyResult:
    app_token = env("WXPUSHER_APP_TOKEN")
    assert app_token
    uids_raw = env("WXPUSHER_UIDS") or ""
    uids = [u.strip() for u in uids_raw.split(",") if u.strip()]
    payload = {
        "appToken": app_token,
        "content": content,
        "summary": summary or title[:100],
        "contentType": 3,  # 3 = markdown
        "uids": uids or [],
    }
    data = request_json(
        "https://wxpusher.zjiecode.com/api/send/message",
        method="POST",
        payload=payload,
        timeout=30,
        retries=2,
    )
    ok = data.get("code") == 1000
    detail = f"code={data.get('code')} msg={data.get('msg', '')}"
    log.info("WxPusher 推送%s：%s", "成功" if ok else "失败", detail)
    return NotifyResult(ok, "wxpusher", detail)


def _send_wecom(title: str, content: str) -> NotifyResult:
    webhook = env("WECOM_WEBHOOK")
    assert webhook
    text = f"**{title}**\n{content}"
    # 企业微信 markdown 消息上限 4096 字节
    encoded = text.encode("utf-8")
    if len(encoded) > 4000:
        text = encoded[:4000].decode("utf-8", errors="ignore") + "\n…"
    data = request_json(
        webhook,
        method="POST",
        payload={"msgtype": "markdown", "markdown": {"content": text}},
        timeout=30,
        retries=2,
    )
    ok = data.get("errcode") == 0
    detail = f"errcode={data.get('errcode')} errmsg={data.get('errmsg', '')}"
    log.info("企业微信 推送%s：%s", "成功" if ok else "失败", detail)
    return NotifyResult(ok, "wecom", detail)


def _send_email(title: str, content: str) -> NotifyResult:
    host = env("SMTP_HOST")
    assert host
    port = int(env("SMTP_PORT") or 465)
    user = env("SMTP_USER") or ""
    password = env("SMTP_PASSWORD") or ""
    mail_to = env("MAIL_TO") or ""
    mail_from = env("MAIL_FROM") or user

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = formataddr(("paper-radar", mail_from))
    msg["To"] = mail_to
    msg.set_content(content)

    use_ssl = env("SMTP_SSL", "true") not in ("false", "0", "no")
    if use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as server:
            if user:
                server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            if user:
                server.login(user, password)
            server.send_message(msg)
    log.info("邮件推送成功：%s", mail_to)
    return NotifyResult(True, "email", f"已发送到 {mail_to}")
