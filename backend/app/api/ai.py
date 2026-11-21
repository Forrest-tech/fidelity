# -*- coding: utf-8 -*-
"""AI: settings (administrators only), and suggestions on a file's uncertain places (reviewers ask, everyone reads).

Keys never leave the server: the page sees only their last four characters."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth.models import Role
from ..auth.users import current_user, require_role
from ..ai import config as CF
from ..ai import gate as G
from ..ai import providers as P
from ..ai import formulas as FX
from ..ai import review as RV
from ..ai import suggestions as SG
from ..jobs import rooms as R

router = APIRouter()
admin = [Depends(require_role())]                         # administrators only


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except CF.ConfigError as e:
        raise HTTPException(e.status, e.message)
    except R.RoomError as e:
        raise HTTPException(e.status, e.message)


def _who(user) -> str:
    return getattr(user, "email", "") or ""


class ProviderIn(BaseModel):
    kind: str
    key: str
    base_url: str | None = None
    label: str | None = None


class ProviderPatch(BaseModel):
    models: list[str] | None = None
    prices: dict[str, list[float]] | None = None
    key: str | None = None


class TestIn(BaseModel):
    model: str


class EvalIn(BaseModel):
    provider: str
    model: str


class AskIn(BaseModel):
    rel: str
    item: int
    k: int | None = None              # which formula on the page (formula places only)


class FormulaIn(BaseModel):
    rel: str
    page: int
    k: int
    latex: str
    call: str | None = None


class FileIn(BaseModel):
    rel: str


class DecisionIn(BaseModel):
    decision: str
    final: str | None = None


# ------------------------------------------------------------------ settings (administrators)
def _settings():
    return {**CF.public(), "stats": G.stats(), "examples": {s: G.example_count(s) for s in CF.SKILLS}}


@router.get("/ai/settings", dependencies=admin)
def get_settings():
    return _settings()


@router.put("/ai/settings", dependencies=admin)
def put_settings(body: dict):
    examples = max(G.example_count(s) for s in CF.SKILLS)
    _guard(CF.update, body, examples)
    return _settings()


@router.post("/ai/providers", dependencies=admin)
def add_provider(body: ProviderIn):
    _guard(CF.add_provider, body.kind, body.key, body.base_url, body.label)
    return _settings()


@router.patch("/ai/providers/{pid}", dependencies=admin)
def patch_provider(pid: str, body: ProviderPatch):
    _guard(CF.update_provider, pid, body.models, body.prices, body.key)
    return _settings()


@router.delete("/ai/providers/{pid}", dependencies=admin)
def delete_provider(pid: str):
    _guard(CF.remove_provider, pid)
    return _settings()


@router.post("/ai/providers/{pid}/test", dependencies=admin)
def test_provider(pid: str, body: TestIn):
    s = CF.load()
    p = CF.provider(s, pid)
    if not p:
        raise HTTPException(404, "no such provider")
    key = CF.key_for(pid)
    if not key:
        raise HTTPException(409, "the key cannot be read; enter it again")
    try:
        return P.test(p, key, body.model.strip())
    except P.ProviderError as e:
        return {"ok": False, "message": e.message}


@router.delete("/ai/keys", dependencies=admin)
def delete_all_keys():
    CF.remove_all_keys()
    return _settings()


@router.post("/ai/skills/{skill}/evaluate", dependencies=admin)
def evaluate(skill: str, body: EvalIn):
    if skill not in CF.SKILLS:
        raise HTTPException(404, "no such skill")
    out = _guard(G.evaluate, skill, body.provider, body.model)
    return {**out, "settings": _settings()}


@router.get("/ai/examples", dependencies=admin)
def list_examples():
    return {"examples": G.examples()}


@router.delete("/ai/examples/{eid}", dependencies=admin)
def delete_example(eid: str):
    G.delete_example(eid)
    return {"deleted": True}


# ------------------------------------------------------------------ suggestions (signed in; asking needs a reviewer)
@router.get("/ai/status")
def ai_status():
    return RV.status()


@router.get("/rooms/{room_id}/review")
def review(room_id: str, rel: str):
    room = _guard(R.get_room, room_id)
    return _guard(RV.items, room, rel)


@router.post("/rooms/{room_id}/ask", dependencies=[Depends(require_role(Role.reviewer))])
def ask(room_id: str, body: AskIn, user=Depends(current_user)):
    room = _guard(R.get_room, room_id)
    return _guard(RV.ask, room, body.rel, body.item, _who(user), False, body.k)


@router.post("/rooms/{room_id}/ask-default", dependencies=[Depends(require_role(Role.reviewer))])
def ask_default(room_id: str, body: FileIn, user=Depends(current_user)):
    room = _guard(R.get_room, room_id)
    return _guard(RV.ask_default, room, body.rel, _who(user))


@router.post("/ai/calls/{call_id}/decision", dependencies=[Depends(require_role(Role.reviewer))])
def decision(call_id: str, body: DecisionIn, user=Depends(current_user)):
    return _guard(G.decide, call_id, body.decision, _who(user), body.final)


# ------------------------------------------------------------------ formulas
def _file_row(room_id: str, rel: str):
    room = _guard(R.get_room, room_id)
    row = next((x for x in R._files(room["id"]) if x["rel"] == rel), None)
    if row is None:
        raise HTTPException(404, "no such file in this room")
    return room, row


@router.get("/rooms/{room_id}/formula.png")
def formula_image(room_id: str, rel: str, page: int, k: int):
    """The crop of the source page that holds one formula (what a person checks a transcription against)."""
    _, row = _file_row(room_id, rel)
    return Response(content=_guard(FX.image, row, page, k), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/rooms/{room_id}/formula/approve", dependencies=[Depends(require_role(Role.reviewer))])
def formula_approve(room_id: str, body: FormulaIn, user=Depends(current_user)):
    """A person approves a transcription (typed, or taken from a suggestion and perhaps changed)."""
    room, row = _file_row(room_id, body.rel)
    out = _guard(FX.approve, room["id"], row, body.page, body.k, body.latex, _who(user))
    if body.call:                                     # it came from a suggestion: record whether it was changed
        final = body.latex.strip().strip("$").strip()
        _guard(G.decide, body.call, "adopted" if final == _suggested_latex(body.call) else "modified", _who(user), final)
    return out


def _suggested_latex(call_id: str) -> str:
    import json as _json
    from .. import db
    con = db.trust_rw()
    try:
        r = con.execute("SELECT result FROM ai_call WHERE id=?", (call_id,)).fetchone()
    finally:
        con.close()
    try:
        return (_json.loads(r[0]) or {}).get("latex", "") if r and r[0] else ""
    except ValueError:
        return ""


# ------------------------------------------------------------------ suggestions for the correction library
@router.get("/corrections/suggestions")
def suggestions():
    return {"suggestions": SG.listing()}


@router.post("/corrections/suggestions/scan", dependencies=[Depends(require_role(Role.reviewer))])
def scan_suggestions(user=Depends(current_user)):
    found = _guard(SG.scan, _who(user))
    return {"found": found, "suggestions": SG.listing()}


@router.post("/corrections/suggestions/{sid}/approve", dependencies=[Depends(require_role(Role.reviewer))])
def approve_suggestion(sid: str, user=Depends(current_user)):
    return _guard(SG.approve, sid, _who(user))


@router.post("/corrections/suggestions/{sid}/dismiss", dependencies=[Depends(require_role(Role.reviewer))])
def dismiss_suggestion(sid: str, user=Depends(current_user)):
    return _guard(SG.dismiss, sid, _who(user))
