# -*- coding: utf-8 -*-
"""AI: settings (administrators only), and suggestions on a file's uncertain places (reviewers ask, everyone reads).

Keys never leave the server: the page sees only their last four characters."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth.models import Role
from ..auth.users import current_user, require_role
from ..ai import config as CF
from ..ai import gate as G
from ..ai import providers as P
from ..ai import review as RV
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
    return _guard(RV.ask, room, body.rel, body.item, _who(user))


@router.post("/rooms/{room_id}/ask-default", dependencies=[Depends(require_role(Role.reviewer))])
def ask_default(room_id: str, body: FileIn, user=Depends(current_user)):
    room = _guard(R.get_room, room_id)
    return _guard(RV.ask_default, room, body.rel, _who(user))


@router.post("/ai/calls/{call_id}/decision", dependencies=[Depends(require_role(Role.reviewer))])
def decision(call_id: str, body: DecisionIn, user=Depends(current_user)):
    return _guard(G.decide, call_id, body.decision, _who(user), body.final)
