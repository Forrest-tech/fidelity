"""Sending e-mail (requirements v2, U-1 and U-4): sign-up confirmation and password reset links.

Plain SMTP through Python's standard library — any company mail server or mail service works (Microsoft 365,
Google Workspace, Tencent Exmail, an office relay). An administrator enters the server in Settings → Email; the
password is kept encrypted with the same key as the AI keys and is never shown again. Until a server is set, nothing
is sent and the sign-up and password pages fall back to an administrator.

FIDELITY_MAIL_OUTBOX=<folder> writes each message there as an .eml file instead of sending it (tests, trials).
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .. import config

PATH = os.path.join(config.DATA_DIR, "email_settings.json")
SECRET_ID = "__smtp__"
SECURITY = ("starttls", "ssl", "none")
APPROVAL = ("domains", "all", "none")      # who still needs an administrator after confirming their address
DEFAULTS = {"host": "", "port": 587, "security": "starttls", "username": "", "from_address": "", "from_name": "Fidelity",
            "site_url": "", "approval": "domains"}
_lock = threading.Lock()


class MailError(Exception):
    pass


def load() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        stored = {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def password() -> str | None:
    from ..ai import config as CF
    return CF.key_for(SECRET_ID)


def configured(s: dict | None = None) -> bool:
    s = s or load()
    return bool(s["host"] and s["from_address"]) or bool(os.environ.get("FIDELITY_MAIL_OUTBOX"))


def missing(s: dict | None = None) -> list:
    """Fields still needed before mail can be sent (the settings page names them)."""
    s = s or load()
    return [k for k in ("host", "from_address") if not s[k]]


def public() -> dict:
    s = load()
    return {**s, "password_set": bool(password()), "configured": configured(s), "missing": missing(s)}


def save(changes: dict) -> dict:
    s = load()
    for k in DEFAULTS:
        if k in changes and changes[k] is not None:
            s[k] = changes[k]
    s["host"] = str(s["host"]).strip()
    s["port"] = int(s["port"])
    if not 1 <= s["port"] <= 65535:
        raise MailError("the port must be between 1 and 65535")
    if s["security"] not in SECURITY:
        raise MailError("security must be starttls, ssl or none")
    if s["approval"] not in APPROVAL:
        raise MailError("approval must be domains, all or none")
    s["site_url"] = str(s["site_url"]).strip().rstrip("/")
    s["username"] = str(s["username"]).strip()
    s["from_address"] = str(s["from_address"]).strip()
    if not s["from_address"] and "@" in s["username"]:
        s["from_address"] = s["username"]        # Gmail, Microsoft 365 and most services send only as the signed-in address
    if "password" in changes and changes["password"] is not None:
        from ..ai import config as CF
        CF._store_key(SECRET_ID, changes["password"] or None)     # "" clears it
    with _lock:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
        os.replace(tmp, PATH)
    return public()


def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Send one message; raises MailError with a plain reason when it cannot be sent."""
    s = load()
    msg = EmailMessage()
    msg["From"] = formataddr((s["from_name"] or "Fidelity", s["from_address"] or "fidelity@localhost"))
    msg["To"] = to
    msg["Subject"] = subject
    # an explicit domain: without one make_msgid() asks DNS for this machine's full name, which takes seconds on some
    # networks (macOS CI) and made every message slow
    msg["Message-ID"] = make_msgid(domain=(s["from_address"].split("@")[-1] if "@" in s["from_address"] else "fidelity.local"))
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    outbox = os.environ.get("FIDELITY_MAIL_OUTBOX")
    if outbox:
        os.makedirs(outbox, exist_ok=True)
        import uuid
        name = f"{time.time():.6f}-{uuid.uuid4().hex[:8]}-{to.replace('@', '_at_')}.eml"   # the clock alone repeats
        with open(os.path.join(outbox, name), "wb") as f:
            f.write(bytes(msg))
        return
    if not configured(s):
        raise MailError("no mail server is set up (Settings → Email)")
    try:
        ctx = ssl.create_default_context()
        if s["security"] == "ssl":
            server = smtplib.SMTP_SSL(s["host"], s["port"], timeout=20, context=ctx)
        else:
            server = smtplib.SMTP(s["host"], s["port"], timeout=20)
        with server:
            if s["security"] == "starttls":
                server.starttls(context=ctx)
            if s["username"]:
                server.login(s["username"], password() or "")
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise MailError("the mail server refused the username or password")
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"the mail could not be sent: {type(e).__name__}: {str(e)[:160]}")


def site_url(request=None) -> str:
    """The address people open Fidelity at, for links in e-mails: the setting, else the address this request came to."""
    s = load()
    if s["site_url"]:
        return s["site_url"]
    if request is not None:
        return str(request.base_url).rstrip("/")
    return "http://localhost:8000"


def _wrap(title: str, lines: list[str], button: str, link: str, foot: str) -> tuple[str, str]:
    from html import escape
    text = "\n\n".join([title, *lines, f"{button}: {link}", foot])
    paras = "".join(f'<p style="margin:0 0 12px">{escape(x)}</p>' for x in lines)
    html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:520px;margin:0 auto;color:#111">'
            f'<h2 style="font-size:18px">{escape(title)}</h2>{paras}'
            f'<p style="margin:20px 0"><a href="{escape(link)}" style="background:#1d4ed8;color:#fff;padding:10px 18px;'
            f'border-radius:6px;text-decoration:none;display:inline-block">{escape(button)}</a></p>'
            f'<p style="font-size:12px;color:#666">{escape(foot)}</p></div>')
    return text, html


def confirm_message(link: str, hours: int) -> tuple[str, str, str]:
    subject = "Confirm your email for Fidelity / 确认你的 Fidelity 邮箱"
    text, html = _wrap("Confirm your email address / 确认邮箱地址",
                       ["Someone (we hope you) asked for a Fidelity account with this address.",
                        "有人（希望是你）用这个邮箱申请了 Fidelity 账号。"],
                       "Confirm email / 确认邮箱", link,
                       f"The link works for {hours} hours. If you did not ask for an account, ignore this message. "
                       f"链接 {hours} 小时内有效；如果不是你申请的，请忽略此邮件。")
    return subject, text, html


def reset_message(link: str, minutes: int) -> tuple[str, str, str]:
    subject = "Reset your Fidelity password / 重置 Fidelity 密码"
    text, html = _wrap("Reset your password / 重置密码",
                       ["We received a request to reset the password of the Fidelity account for this address.",
                        "我们收到了重置这个邮箱对应的 Fidelity 账号密码的请求。"],
                       "Choose a new password / 设置新密码", link,
                       f"The link works for {minutes} minutes and only once. If you did not ask, ignore this message: "
                       f"your password stays as it is. 链接 {minutes} 分钟内有效且只能用一次；如果不是你申请的，请忽略，密码不会改变。")
    return subject, text, html
