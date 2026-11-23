# -*- coding: utf-8 -*-
"""Notifications for the bell in the top bar.

They are worked out from the current state, not stored: a room's run finished or failed, files that cannot be
processed or wait for review, an AI skill near its monthly budget (administrators), a correction rule that people
often undo. Each has a stable key; reading one is remembered per person. Each says where it leads, and the page goes
there. Items older than 30 days are left out.
"""
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import db
from ..auth.users import current_user
from ..jobs import rooms as R

router = APIRouter()
KEEP_DAYS = 30
LIMIT = 30


class ReadIn(BaseModel):
    keys: list[str] = []
    all: bool = False


def _who(user) -> str:
    return getattr(user, "email", "") or ""


def _pending_signups() -> int:
    """People who asked for an account and wait for an administrator (run on a fresh loop: this route is sync)."""
    import asyncio
    try:
        from ..auth.signup import pending_count
        return asyncio.run(pending_count())
    except Exception:                                    # noqa: BLE001 - notifications never break the page
        return 0


def _items(user) -> list:
    since = time.time() - KEEP_DAYS * 86400
    out = []
    con = db.trust_rw()
    try:
        jobs = con.execute("SELECT id, room_id, status, message, rel, updated_at FROM job WHERE kind='dropbox_sync' AND room_id IS NOT NULL "
                           "AND updated_at>=? AND status IN ('done','error','interrupted') ORDER BY updated_at DESC LIMIT 50",
                           (since,)).fetchall()
    finally:
        con.close()
    rooms = {r["id"]: r for r in R.list_rooms(False) + R.list_rooms(True)}
    seen_rooms = set()
    for j in jobs:
        room = rooms.get(j["room_id"])
        if not room or j["room_id"] in seen_rooms:
            continue                                          # the latest run of each room only
        seen_rooms.add(j["room_id"])
        publish = '"publish_from"' in (j["rel"] or "")
        c = R.counts(room)
        base = {"room": room["id"], "room_name": room["name"], "at": j["updated_at"], "to": f"/distill?room={room['id']}"}
        if j["status"] == "done":
            out.append({**base, "key": f"done:{j['id']}", "type": "published" if publish else "done", "tone": "ok",
                        "finished": c["finished"], "total": c["total"], "ok": c["ok"]})
        else:
            out.append({**base, "key": f"fail:{j['id']}", "type": "interrupted" if j["status"] == "interrupted" else "failed",
                        "tone": "bad", "message": (j["message"] or "")[:160]})
    for room in rooms.values():
        if room["archived"]:
            continue
        c = R.counts(room)
        base = {"room": room["id"], "room_name": room["name"], "at": room["updated_at"]}
        if c["unprocessable"]:
            out.append({**base, "key": f"bad:{room['id']}:{c['unprocessable']}", "type": "unprocessable", "tone": "bad",
                        "n": c["unprocessable"], "to": f"/distill?room={room['id']}&state=unprocessable"})
        if c["below"]:
            out.append({**base, "key": f"review:{room['id']}:{c['below']}", "type": "review", "tone": "warn", "n": c["below"],
                        "to": f"/distill?room={room['id']}&state=below"})
    if getattr(user, "role", None) and getattr(user.role, "value", user.role) == "admin":
        try:
            from ..ai import config as CF
            from ..ai import gate as G
            s = CF.load()
            if s["enabled"]:
                st = G.stats()["skills"]
                month = time.strftime("%Y-%m")
                for name, sk in s["skills"].items():
                    spent = (st.get(name) or {}).get("spend", 0)
                    if sk.get("budget_usd") and spent >= 0.8 * sk["budget_usd"]:
                        out.append({"key": f"ai:{month}:{name}", "type": "ai_budget", "tone": "ai", "skill": name,
                                    "pct": round(100 * spent / sk["budget_usd"]), "at": time.time(), "to": "/settings/ai"})
        except Exception:                                     # noqa: BLE001 - notifications never break the page
            pass
    if getattr(user, "role", None) and getattr(user.role, "value", user.role) == "admin":
        n = _pending_signups()
        if n:
            out.append({"key": f"signup:{n}", "type": "signup", "tone": "warn", "n": n, "at": time.time(),
                        "to": "/settings/users"})
        try:
            from ..ops import health as H
            for a in H.alerts():                          # disk, memory, backups, failing runs (requirements v2, S-5)
                out.append({**{k: v for k, v in a.items() if k not in ("key", "level")}, "key": f"sys:{a['key']}",
                            "type": "system", "tone": a["level"], "at": time.time(), "to": "/settings/system"})
        except Exception:                                 # noqa: BLE001 - notifications never break the page
            pass
    try:
        from ..jobs import corrections as CO
        for r in CO.library()["rules"]:
            if r["often_undone"] and r["enabled"]:
                out.append({"key": f"rule:{r['id']}:{r['reverts']}", "type": "rule_undone", "tone": "warn", "num": r["num"],
                            "reverts": r["reverts"], "at": r["created_at"] or 0, "to": f"/settings/corrections?rule={r['id']}"})
    except Exception:                                         # noqa: BLE001
        pass
    out.sort(key=lambda x: -(x.get("at") or 0))
    return out[:LIMIT]


@router.get("/notifications")
def notifications(user=Depends(current_user)):
    items = _items(user)
    con = db.trust_rw()
    try:
        read = {r[0] for r in con.execute("SELECT nkey FROM notification_read WHERE user_email=?", (_who(user),)).fetchall()}
    finally:
        con.close()
    for it in items:
        it["read"] = it["key"] in read
    return {"items": items, "unread": sum(1 for it in items if not it["read"])}


@router.post("/notifications/read")
def mark_read(body: ReadIn, user=Depends(current_user)):
    """Reading is a person's own bookkeeping, so every signed-in person may do it (also read-only viewers)."""
    keys = [it["key"] for it in _items(user)] if body.all else body.keys[:200]
    con = db.trust_rw()
    try:
        for k in keys:
            if not con.execute("SELECT 1 FROM notification_read WHERE user_email=? AND nkey=?", (_who(user), k)).fetchone():
                con.execute("INSERT INTO notification_read(user_email, nkey, at) VALUES(?,?,?)", (_who(user), k, db.now()))
        con.commit()
    finally:
        con.close()
    return notifications(user)
