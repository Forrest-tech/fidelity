# -*- coding: utf-8 -*-
"""Distillation rooms: create, configure, run, queue, browse per-file results, archive.

Reading needs a login; changing needs a reviewer or administrator (enforced for the whole API in main.py)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import db
from ..auth.models import Role
from ..auth.users import current_user, require_role
from ..distill import live as L
from ..jobs import rooms as R
from ..jobs import sync_job as S
from ..jobs.queue import queue

router = APIRouter()


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except R.RoomError as e:
        raise HTTPException(e.status, e.message)


class RoomNew(BaseModel):
    name: str | None = None
    prefix: str | None = None          # the word a room without a name is called, in the person's language
    source: str | None = None          # a room is made with its folders in one step (the page keeps a draft until Save)
    dest: str | None = None
    mode: str | None = None


class RoomPatch(BaseModel):
    name: str | None = None
    source: str | None = None
    dest: str | None = None
    mode: str | None = None
    threshold: float | None = None
    number_guard: bool | None = None
    priority: int | None = None


class RunIn(BaseModel):
    force: bool = False


class AcceptIn(BaseModel):
    all_ok: bool = False
    rels: list[str] = []
    force: bool = False


@router.get("/rooms")
def rooms(archived: bool = False):
    return {"rooms": [R.summary(r) for r in R.list_rooms(archived)]}


@router.post("/rooms")
def create(body: RoomNew, user=Depends(current_user)):
    room = R.create_room(body.name, getattr(user, "email", "") or "", body.prefix)
    extra = {k: v for k, v in body.model_dump(include={"source", "dest", "mode"}).items() if v not in (None, "")}
    if extra:
        try:
            room = _guard(R.update_room, room["id"], extra)
        except Exception:
            R.delete_room(room["id"])          # all or nothing: a refused folder leaves no half-made room behind
            raise
    return R.summary(room)


@router.get("/queue")
def queue_state():
    return R.queue_view()


@router.get("/rooms/{room_id}")
def room(room_id: str):
    return R.summary(_guard(R.get_room, room_id))


@router.patch("/rooms/{room_id}")
def patch(room_id: str, body: RoomPatch):
    sent = body.model_dump(exclude_unset=True)
    return R.summary(_guard(R.update_room, room_id, sent))


@router.delete("/rooms/{room_id}")
def delete(room_id: str):
    _guard(R.delete_room, room_id)
    return {"deleted": True}


@router.post("/rooms/{room_id}/run")
def run(room_id: str, body: RunIn | None = None):
    jid = _guard(R.submit_run, room_id, bool(body and body.force))
    return {"job": jid, "queue": R.queue_view()}


@router.post("/rooms/{room_id}/cancel")
def cancel(room_id: str):
    _guard(R.get_room, room_id)
    job = R.active_job(room_id)
    if not job:
        raise HTTPException(409, "this room has no queued or running run")
    if job["status"] == "queued":
        con = db.trust_rw()
        try:
            con.execute("UPDATE job SET status='error', message='cancelled by the user' WHERE id=? AND status='queued'", (job["id"],))
            con.commit()
        finally:
            con.close()
    elif not S.cancel(job["id"]):
        raise HTTPException(409, "this run is not running")
    return {"cancelled": True}


@router.post("/rooms/{room_id}/front")
def front(room_id: str):
    _guard(R.move_to_front, room_id)
    return R.queue_view()


@router.post("/rooms/{room_id}/archive")
def archive(room_id: str, user=Depends(current_user)):
    return R.summary(_guard(R.set_archived, room_id, True, getattr(user, "email", "") or ""))


@router.post("/rooms/{room_id}/unarchive")
def unarchive(room_id: str, user=Depends(current_user)):
    return R.summary(_guard(R.set_archived, room_id, False, getattr(user, "email", "") or ""))


@router.get("/rooms/{room_id}/archive-check")
def archive_check(room_id: str):
    """What still stands in the way of archiving this room (empty list = it can be archived)."""
    r = _guard(R.get_room, room_id)
    return {"blockers": R.archive_blockers(r)}


@router.get("/rooms/{room_id}/accept-preview")
def accept_preview(room_id: str):
    return R.accept_preview(_guard(R.get_room, room_id))


@router.post("/rooms/{room_id}/accept")
def accept(room_id: str, body: AcceptIn, user=Depends(current_user)):
    """Accept results into the knowledge base: all that meet the threshold, or the files named (force = even below it)."""
    return _guard(R.accept, room_id, getattr(user, "email", "") or "", body.rels, body.all_ok, body.force)


@router.post("/rooms/{room_id}/restamp")
def restamp(room_id: str, user=Depends(current_user)):
    """Send the published files again with their edition lines up to date (which edition, superseded by which)."""
    return _guard(R.restamp, room_id)


@router.get("/rooms/{room_id}/editions")
def editions(room_id: str):
    """The room's standards by edition: which copy represents each edition and whether it is current here."""
    return _guard(R.editions_view, _guard(R.get_room, room_id))


@router.get("/rooms/{room_id}/accept-impact")
def accept_impact(room_id: str):
    """How many of the files that qualify are new to the output folder, and how many replace a live copy."""
    return _guard(R.accept_impact, _guard(R.get_room, room_id))


@router.get("/rooms/{room_id}/compare")
def compare(room_id: str, rel: str):
    """One file's new result against the copy in the output folder, line by line."""
    return _guard(R.compare_file, _guard(R.get_room, room_id), rel)


@router.get("/folders", dependencies=[Depends(require_role(Role.reviewer))])
def folders(path: str = ""):
    """The folders directly inside a folder of the connected Dropbox account, for picking an input or output."""
    try:
        return L.subfolders(path)
    except L.LiveError as e:
        raise HTTPException(e.status, e.message)


@router.get("/rooms/{room_id}/tree")
def tree(room_id: str, path: str = "", state: str | None = Query(None), q: str | None = Query(None)):
    """One level of the folder tree; folders carry roll-ups so a collapsed folder already shows its numbers."""
    if state and state not in R.STATES:
        raise HTTPException(422, "unknown state")
    return R.children(_guard(R.get_room, room_id), path, state, q)


@router.get("/rooms/{room_id}/files")
def files(room_id: str, state: str | None = Query(None), q: str | None = Query(None),
          offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000)):
    if state and state not in R.STATES:
        raise HTTPException(422, "unknown state")
    return R.find_files(_guard(R.get_room, room_id), state, q, offset, limit)


@router.get("/cloud/ready")
def storage_ready():
    """Which cloud storage can be read from (any signed-in user; no account details): a room needs one,
    so the page can say so before someone fills in a room it cannot open."""
    from ..distill import dropbox_io as D
    from ..distill import gdrive_io as G

    def has(data, role):
        a = data.get(role) if isinstance(data, dict) else None
        return bool(isinstance(a, dict) and a.get("refresh_token"))
    d, g = D.load_auth(), G.load_auth()
    return {"dropbox": has(d, "reader"), "google": has(g, "reader"),
            "dropbox_write": has(d, "writer"), "google_write": has(g, "writer")}
