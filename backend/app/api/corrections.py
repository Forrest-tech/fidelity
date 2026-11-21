# -*- coding: utf-8 -*-
"""The correction library: confirm a fix once, and it is applied wherever the same reading appears.

Reading needs a login; saving, switching, undoing and confirming need a reviewer or administrator (main.py)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth.users import current_user
from ..jobs import corrections as C
from ..jobs import rooms as R

router = APIRouter()


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except C.CorrectionError as e:
        raise HTTPException(e.status, e.message)
    except R.RoomError as e:
        raise HTTPException(e.status, e.message)


def _who(user) -> str:
    return getattr(user, "email", "") or ""


class DraftIn(BaseModel):
    room_id: str
    rel: str
    find: str
    replace: str
    scope: str = "series"


class EnabledIn(BaseModel):
    enabled: bool


class PlaceIn(BaseModel):
    rel: str
    rule_id: str


@router.get("/corrections")
def library():
    return C.library()


@router.post("/corrections/preview")
def preview(body: DraftIn):
    """Where a fix would apply, before it is saved."""
    return _guard(C.preview, body.find, body.replace, body.scope, body.room_id, body.rel)


@router.post("/corrections")
def create(body: DraftIn, user=Depends(current_user)):
    return _guard(C.create, _who(user), body.find, body.replace, body.scope, body.room_id, body.rel)


@router.patch("/corrections/{rule_id}")
def set_enabled(rule_id: str, body: EnabledIn):
    return _guard(C.set_enabled, rule_id, body.enabled)


@router.get("/corrections/{rule_id}/affected")
def affected(rule_id: str):
    return {"documents": _guard(lambda: C.affected(C.get_rule(rule_id)))}


@router.post("/corrections/{rule_id}/apply")
def apply(rule_id: str):
    """Bring every document the rule touches up to date."""
    return _guard(C.apply_everywhere, rule_id)


@router.get("/rooms/{room_id}/result")
def result(room_id: str, rel: str):
    """One file's result as it is now, and the corrections applied to it."""
    _guard(R.get_room, room_id)
    return _guard(C.file_view, room_id, rel)


@router.post("/rooms/{room_id}/corrections/undo")
def undo(room_id: str, body: PlaceIn, user=Depends(current_user)):
    _guard(R.get_room, room_id)
    return _guard(C.undo, body.rule_id, room_id, body.rel, _who(user))


@router.post("/rooms/{room_id}/corrections/confirm")
def confirm(room_id: str, body: PlaceIn, user=Depends(current_user)):
    _guard(R.get_room, room_id)
    return _guard(C.confirm, body.rule_id, room_id, body.rel, _who(user))
