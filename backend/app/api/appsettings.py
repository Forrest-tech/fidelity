# -*- coding: utf-8 -*-
"""Settings that are not about one room: defaults for new rooms, the audit log, and a person's own password."""
import json
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, db
from ..auth.models import Role
from ..auth.users import current_user, get_user_manager, require_role
from ..distill import scoring as SC

router = APIRouter()
PATH = os.path.join(config.DATA_DIR, "app_settings.json")
# ocr_protected on by default: the owner decided on 2026-11-22 that copy-restricted PDFs are read (the company is
# licensed for this content). A new installation (the Mac, 2026-11-26) had it off and refused all such files.
DEFAULTS = {"threshold": 99.0, "number_guard": True, "mode": "distill", "ocr_protected": True}


def defaults() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            stored = json.load(f).get("room_defaults") or {}
    except (OSError, ValueError):
        stored = {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


class DefaultsIn(BaseModel):
    threshold: float | None = None
    number_guard: bool | None = None
    mode: str | None = None
    ocr_protected: bool | None = None


@router.get("/app-settings/defaults")
def get_defaults():
    return {**defaults(), "weights": SC.WEIGHTS}


@router.put("/app-settings/defaults", dependencies=[Depends(require_role())])
def put_defaults(body: DefaultsIn):
    d = defaults()
    if body.threshold is not None:
        if not 50 <= body.threshold <= 100:
            raise HTTPException(422, "the threshold must be between 50 and 100")
        d["threshold"] = float(body.threshold)
    if body.number_guard is not None:
        d["number_guard"] = bool(body.number_guard)
    if body.mode is not None:
        if body.mode not in ("distill", "upload"):
            raise HTTPException(422, "mode must be distill or upload")
        d["mode"] = body.mode
    if body.ocr_protected is not None:
        d["ocr_protected"] = bool(body.ocr_protected)
    try:
        with open(PATH, encoding="utf-8") as f:
            all_ = json.load(f)
    except (OSError, ValueError):
        all_ = {}
    all_["room_defaults"] = d
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(all_, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)
    return {**d, "weights": SC.WEIGHTS}


# ------------------------------------------------------------------ audit log
@router.get("/audit", dependencies=[Depends(require_role())])
def audit(limit: int = 200):
    """Who decided what, from what the system already records: rules, undo and checks, AI decisions, acceptances,
    archiving. Newest first."""
    out = []
    con = db.trust_rw()
    try:
        for r in con.execute("SELECT num, find, replace_with, scope, created_by, created_at, kind FROM correction_rule "
                             "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall():
            out.append({"at": r[5], "who": r[4], "what": "rule_created", "detail": f"#{r[0]} {r[1]} → {r[2]} ({r[3]})"})
        for r in con.execute("SELECT e.by_user, e.at, e.rel, c.num FROM correction_exempt e LEFT JOIN correction_rule c ON c.id=e.rule_id "
                             "ORDER BY e.at DESC LIMIT ?", (limit,)).fetchall():
            out.append({"at": r[1], "who": r[0], "what": "rule_undone", "detail": f"#{r[3]} · {r[2]}"})
        for r in con.execute("SELECT decided_by, decided_at, skill, decision, rel FROM ai_call WHERE decision IS NOT NULL "
                             "ORDER BY decided_at DESC LIMIT ?", (limit,)).fetchall():
            out.append({"at": r[1], "who": r[0], "what": "ai_" + r[3], "detail": f"{r[2]} · {r[4] or ''}"})
        for r in con.execute("SELECT f.confirmed_by, f.confirmed_at, f.rel, m.name FROM room_file f LEFT JOIN room m ON m.id=f.room_id "
                             "WHERE f.confirmed_by IS NOT NULL ORDER BY f.confirmed_at DESC LIMIT ?", (limit,)).fetchall():
            out.append({"at": r[1], "who": r[0], "what": "accepted", "detail": f"{r[3]} · {r[2]}"})
        for r in con.execute("SELECT archived_by, archived_at, name FROM room WHERE archived_by IS NOT NULL ORDER BY archived_at DESC "
                             "LIMIT ?", (limit,)).fetchall():
            out.append({"at": r[1], "who": r[0], "what": "archived", "detail": r[2]})
    finally:
        con.close()
    out = [x for x in out if x["at"]]
    out.sort(key=lambda x: -x["at"])
    return {"events": out[:limit]}


# ------------------------------------------------------------------ one's own password
class PasswordIn(BaseModel):
    current: str
    new: str


@router.post("/account/password")
async def change_password(body: PasswordIn, user=Depends(current_user), manager=Depends(get_user_manager)):
    """Every signed-in person may change their own password; the current one is checked first."""
    from fastapi_users.exceptions import InvalidPasswordException
    from fastapi_users.schemas import BaseUserUpdate
    ok, _ = manager.password_helper.verify_and_update(body.current, user.hashed_password)
    if not ok:
        time.sleep(0.5)                                   # slows down guessing
        raise HTTPException(400, "the current password is not right")
    if body.new == body.current:
        raise HTTPException(422, "choose a password different from the current one")
    try:
        await manager.validate_password(body.new, user)
    except InvalidPasswordException as e:
        raise HTTPException(422, str(e.reason))
    await manager.user_db.update(user, {"hashed_password": manager.password_helper.hash(body.new)})
    return {"changed": True}


_ = (Role, BaseModel)  # keep imports used by type checkers
