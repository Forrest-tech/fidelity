"""Notification e-mails (requirements v2 U-4 and S-5): what the bell shows, sent by e-mail too.

One source of truth: the items are the bell's own (api/notifications.py), so the two never disagree. Every few
minutes each administrator and reviewer who has not switched it off gets ONE message listing the items that are new
for them; each item is mailed once. Reviewers get room items (finished, failed, needs review, cannot be processed);
administrators also get system alerts (disk, memory, backups, failing runs), sign-ups, AI budgets and rules people
keep undoing. The first pass for a person only remembers what is already there, so switching mail on never floods
anyone with old news. Nothing is sent while no mail server is set up (Settings → Email)."""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

from .. import db

EVERY_S = 300
ROOM_TYPES = {"done", "published", "failed", "interrupted", "unprocessable", "review"}
ADMIN_TYPES = ROOM_TYPES | {"system", "signup", "ai_budget", "rule_undone"}
BASELINE = "__baseline__"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notification_mail (user_email TEXT, nkey TEXT, at REAL, PRIMARY KEY (user_email, nkey));
CREATE TABLE IF NOT EXISTS notification_pref (user_email TEXT PRIMARY KEY, email INTEGER NOT NULL DEFAULT 1);
"""


def _con():
    con = db.trust_rw()
    con.executescript(_SCHEMA)
    return con


def wants_mail(email: str) -> bool:
    con = _con()
    try:
        r = con.execute("SELECT email FROM notification_pref WHERE user_email=?", (email,)).fetchone()
        return True if r is None else bool(r[0])
    finally:
        con.close()


def set_wants_mail(email: str, on: bool):
    con = _con()
    try:
        con.execute("INSERT INTO notification_pref(user_email, email) VALUES(?, ?) "
                    "ON CONFLICT(user_email) DO UPDATE SET email=excluded.email", (email, int(bool(on))))
        con.commit()
    finally:
        con.close()


async def _people_async() -> list[tuple[str, str]]:
    from sqlalchemy import select

    from ..auth.models import User
    from ..orm import SessionLocal
    async with SessionLocal() as s:
        rows = (await s.execute(select(User.email, User.role).where(User.is_active.is_(True)))).all()
    return [(e, getattr(r, "value", r)) for e, r in rows if getattr(r, "value", r) in ("admin", "reviewer")]


def people() -> list[tuple[str, str]]:
    return asyncio.run(_people_async())


def describe(it: dict) -> str:
    """One line per item, English then Chinese (the e-mail goes to everyone in the same words)."""
    room = it.get("room_name", "")
    t = it["type"]
    if t in ("done", "published"):
        what = "published" if t == "published" else f"finished: {it.get('ok', 0)} of {it.get('total', 0)} files qualify"
        return f"Room “{room}” {what}. / 蒸馏室“{room}”已完成。"
    if t in ("failed", "interrupted"):
        return f"Room “{room}”: the run {'was interrupted' if t == 'interrupted' else 'failed'} — {it.get('message', '')} / 蒸馏室“{room}”运行未完成。"
    if t == "review":
        return f"Room “{room}”: {it['n']} file(s) wait for review. / 蒸馏室“{room}”有 {it['n']} 个文件等待审核。"
    if t == "unprocessable":
        return f"Room “{room}”: {it['n']} file(s) cannot be processed. / 蒸馏室“{room}”有 {it['n']} 个文件无法处理。"
    if t == "signup":
        return f"{it['n']} sign-up(s) wait for approval. / 有 {it['n']} 个注册申请等待批准。"
    if t == "ai_budget":
        return f"AI skill “{it['skill']}” has used {it['pct']}% of its monthly budget. / AI 技能“{it['skill']}”本月预算已用 {it['pct']}%。"
    if t == "rule_undone":
        return f"Correction rule #{it['num']} was undone {it['reverts']} times. / 修正规则 #{it['num']} 被撤销了 {it['reverts']} 次。"
    if t == "system":
        k = it.get("kind", "")
        words = {"disk": "disk space is low", "memory": "memory is low", "backup_none": "no backup has been made yet",
                 "backup_failed": "the last backup failed", "backup_old": "the last backup is more than two days old",
                 "runs_failing": "many runs are failing", "ai_credit": "the AI provider account has no credit left"}
        return f"System: {words.get(k, k)}. / 系统提醒：{k}。"
    return t


def run_once() -> dict:
    from ..api import notifications as N
    from . import mail
    if not mail.configured():
        return {"sent": 0, "why": "no mail server"}
    sent, base = 0, mail.site_url()
    for email, role in people():
        if not wants_mail(email):
            continue
        allowed = ADMIN_TYPES if role == "admin" else ROOM_TYPES
        items = [i for i in N._items(SimpleNamespace(email=email, role=role)) if i["type"] in allowed]
        con = _con()
        try:
            done = {r[0] for r in con.execute("SELECT nkey FROM notification_mail WHERE user_email=?", (email,))}
            new = [i for i in items if i["key"] not in done]
            if BASELINE in done and new:
                lines = [f"• {describe(i)}\n  {base}{i.get('to', '/')}" for i in new]
                text = ("What is new in Fidelity / Fidelity 的新消息:\n\n" + "\n\n".join(lines) +
                        f"\n\nTurn these e-mails off: {base}/settings/notifications\n关闭这类邮件：{base}/settings/notifications")
                try:
                    mail.send(email, f"Fidelity: {len(new)} new / {len(new)} 条新消息", text)
                    sent += 1
                except mail.MailError as e:
                    print(f"[notify-mail] {email}: {e}", flush=True)
                    continue                      # not marked: tried again next time
            now = time.time()
            con.executemany("INSERT OR IGNORE INTO notification_mail(user_email, nkey, at) VALUES(?,?,?)",
                            [(email, k, now) for k in [BASELINE] + [i["key"] for i in new]])
            con.commit()
        finally:
            con.close()
    return {"sent": sent}


def _loop(stop: threading.Event):
    while not stop.wait(EVERY_S):
        try:
            run_once()
        except Exception as e:                    # noqa: BLE001 - the bell still shows everything
            print(f"[notify-mail] {type(e).__name__}: {e}", flush=True)


_STOP = threading.Event()


def start():
    threading.Thread(target=_loop, args=(_STOP,), daemon=True, name="notify-mail").start()
