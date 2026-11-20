# -*- coding: utf-8 -*-
"""Distillation rooms: each room has its own input, output, rules and per-file results.

A room is a saved configuration plus everything learned from running it. "Run" queues a job for the room;
the job's per-file events (see distill/events.py) are kept as one row per source file, so the page can show
every file's own state without reading logs.

File state seen by people (derived, never stored, so changing a room's threshold needs no re-run):

    pending         not distilled yet
    processing      being processed now
    ok              has a result and meets the room's threshold
    below           has a result but is below the threshold, or has a number difference while the guard is on
    unprocessable   no result could be produced (reason says why); there is no percentage
    published       a person accepted it (it goes to the output folder)
"""
from __future__ import annotations

import json
import os
import re
import uuid

from .. import db
from ..distill import gdrive_io as G
from ..distill import scoring as SC
from . import capacity, sync_job as S

MODES = ("distill", "upload")
STATES = ("pending", "processing", "ok", "below", "unprocessable", "published")


class RoomError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ------------------------------------------------------------------ locations
def clean_location(v: str, what: str) -> dict:
    v = (v or "").strip()
    if not v:
        raise RoomError(422, f"the {what} is empty")
    if not (S.LINK_RE.match(v) or S.PATH_RE.match(v) or G.is_gdrive(v)) or ".." in v.split("/"):
        raise RoomError(422, f"the {what} must be a Dropbox folder path (/Folder/Sub), a Dropbox shared link or a "
                             "Google Drive folder link")
    return {"kind": "gdrive" if G.is_gdrive(v) else "dropbox", "link": v}


def _loc(raw):
    if not raw:
        return None
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    return v if isinstance(v, dict) and v.get("link") else None


def dest_key(loc: dict | None) -> str | None:
    """Identifies an output folder, so two runs never write the same one at once."""
    if not loc:
        return None
    return f"{loc['kind']}:{loc['link'].strip().rstrip('/').lower()}"


# ------------------------------------------------------------------ rooms
def _row(r) -> dict:
    d = dict(r)
    d["source"], d["dest"] = _loc(d.get("source")), _loc(d.get("dest"))
    d["number_guard"] = bool(d.get("number_guard"))
    d["archived"] = bool(d.get("archived"))
    return d


def get_room(room_id: str) -> dict:
    con = db.trust_rw()
    try:
        r = con.execute("SELECT * FROM room WHERE id=?", (room_id,)).fetchone()
    finally:
        con.close()
    if not r:
        raise RoomError(404, "no such distillation room")
    return _row(r)


def list_rooms(archived: bool = False) -> list:
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT * FROM room WHERE COALESCE(archived,0)=? ORDER BY position, created_at",
                           (1 if archived else 0,)).fetchall()
    finally:
        con.close()
    return [_row(r) for r in rows]


def create_room(name: str | None, user: str) -> dict:
    rid = uuid.uuid4().hex[:10]
    now = db.now()
    con = db.trust_rw()
    try:
        n = con.execute("SELECT COUNT(*) FROM room").fetchone()[0]
        used = {r[0] for r in con.execute("SELECT name FROM room").fetchall()}
        name = (name or "").strip()[:80]
        if not name:
            k = n + 1
            while f"蒸馏室 {k}" in used:
                k += 1
            name = f"蒸馏室 {k}"
        pos = con.execute("SELECT COALESCE(MAX(position),0)+1 FROM room").fetchone()[0]
        con.execute("INSERT INTO room(id,name,position,mode,threshold,number_guard,priority,points,archived,"
                    "created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, name, pos, "distill", 99.0, 1, 1, 1, 0, user, now, now))
        con.commit()
    finally:
        con.close()
    return get_room(rid)


_EDITABLE = ("name", "source", "dest", "mode", "threshold", "number_guard", "priority")


def update_room(room_id: str, fields: dict) -> dict:
    room = get_room(room_id)
    sets, vals = [], []
    for k, v in fields.items():
        if k not in _EDITABLE or v is None and k not in ("dest",):
            continue
        if k == "name":
            v = str(v).strip()[:80]
            if not v:
                raise RoomError(422, "the name cannot be empty")
        elif k in ("source", "dest"):
            new = clean_location(v if isinstance(v, str) else (v or {}).get("link", ""), k) if v else None
            if new != room.get(k) and active_job(room_id):
                raise RoomError(409, "stop the current run before changing the input or output")
            v = json.dumps(new, ensure_ascii=False) if new else None
        elif k == "mode":
            if v not in MODES:
                raise RoomError(422, "mode must be distill or upload")
        elif k == "threshold":
            v = float(v)
            if not 50.0 <= v <= 100.0:
                raise RoomError(422, "the threshold must be between 50 and 100")
        elif k == "number_guard":
            v = 1 if v else 0
        elif k == "priority":
            v = int(v)
            if v not in (0, 1, 2):
                raise RoomError(422, "priority must be 0 (low), 1 (normal) or 2 (high)")
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return room
    sets.append("updated_at=?")
    vals.append(db.now())
    con = db.trust_rw()
    try:
        con.execute(f"UPDATE room SET {','.join(sets)} WHERE id=?", (*vals, room_id))
        # a queued run follows the room's priority
        if "priority" in fields:
            con.execute("UPDATE job SET priority=? WHERE room_id=? AND status='queued'", (int(fields["priority"]), room_id))
        con.commit()
    finally:
        con.close()
    return get_room(room_id)


def active_job(room_id: str) -> dict | None:
    con = db.trust_rw()
    try:
        r = con.execute("SELECT * FROM job WHERE room_id=? AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
                        (room_id,)).fetchone()
    finally:
        con.close()
    return dict(r) if r else None


def delete_room(room_id: str):
    get_room(room_id)
    if active_job(room_id):
        raise RoomError(409, "stop the current run first")
    con = db.trust_rw()
    try:
        if con.execute("SELECT COUNT(*) FROM room_file WHERE room_id=? AND outcome IS NOT NULL", (room_id,)).fetchone()[0]:
            raise RoomError(409, "this room has results; archive it instead of deleting it")
        con.execute("DELETE FROM room_file WHERE room_id=?", (room_id,))
        con.execute("DELETE FROM room WHERE id=?", (room_id,))
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------------ file state
def derive_state(row, room: dict) -> str:
    """The state a person sees for one file (see the module docstring)."""
    if row["activity"] == "processing":
        return "processing"
    outcome = row["outcome"]
    if not outcome:
        return "pending"
    if outcome in ("unprocessable", "skipped"):
        return "unprocessable"
    if row["confirmed"]:
        return "published"
    return SC.decide(row["accuracy"], row["number_diffs"] or 0, room["threshold"], room["number_guard"])


def _files(room_id: str) -> list:
    con = db.trust_rw()
    try:
        return con.execute("SELECT rel, kind, size, activity, outcome, reason, detail, accuracy, parts, diffs, number_diffs, "
                           "confirmed, pages, run_id, updated_at FROM room_file WHERE room_id=?", (room_id,)).fetchall()
    finally:
        con.close()


def _zero() -> dict:
    return {"total": 0, **{s: 0 for s in STATES}}


def _add(c: dict, state: str):
    c["total"] += 1
    c[state] += 1


def _finish(c: dict) -> dict:
    c["finished"] = c["total"] - c["pending"] - c["processing"]
    c["rate"] = round(100 * c["finished"] / c["total"], 1) if c["total"] else 0.0
    return c


def counts(room: dict, rows=None) -> dict:
    rows = _files(room["id"]) if rows is None else rows
    c = _zero()
    for r in rows:
        _add(c, derive_state(r, room))
    return _finish(c)


def _file_out(r, room) -> dict:
    return {"rel": r["rel"], "name": r["rel"].rsplit("/", 1)[-1], "kind": r["kind"], "size": r["size"],
            "state": derive_state(r, room), "accuracy": r["accuracy"], "diffs": r["diffs"] or 0,
            "number_diffs": r["number_diffs"] or 0, "reason": r["reason"], "detail": r["detail"], "pages": r["pages"],
            "parts": json.loads(r["parts"]) if r["parts"] else None}


def children(room: dict, path: str = "", state: str | None = None, q: str | None = None) -> dict:
    """The next level of the folder tree under `path`: sub-folders with their roll-ups, and the files directly in it.
    Roll-ups cover everything below a folder, so a collapsed folder already shows its numbers."""
    path = "/" + path.strip("/") if path.strip("/") else ""
    prefix = path + "/"
    rows = _files(room["id"])
    folders: dict = {}
    files = []
    ql = (q or "").lower()
    for r in rows:
        rel = r["rel"]
        if not rel.startswith(prefix):
            continue
        st = derive_state(r, room)
        if state and st != state:
            continue
        if ql and ql not in rel.lower():
            continue
        rest = rel[len(prefix):]
        if "/" in rest:
            name = rest.split("/", 1)[0]
            f = folders.setdefault(name, {"name": name, "path": prefix + name, "counts": _zero()})
            _add(f["counts"], st)
        else:
            files.append(_file_out(r, room))
    out = sorted(folders.values(), key=lambda f: f["name"].lower())
    for f in out:
        _finish(f["counts"])
    files.sort(key=lambda f: f["name"].lower())
    return {"path": path or "/", "folders": out, "files": files}


def find_files(room: dict, state: str | None = None, q: str | None = None, offset: int = 0, limit: int = 200) -> dict:
    """A flat list (for search and for filtering by state), paged."""
    ql = (q or "").lower()
    out = []
    for r in _files(room["id"]):
        st = derive_state(r, room)
        if state and st != state:
            continue
        if ql and ql not in r["rel"].lower():
            continue
        out.append(_file_out(r, room))
    out.sort(key=lambda f: f["rel"].lower())
    return {"total": len(out), "files": out[offset:offset + limit]}


# ------------------------------------------------------------------ running
def queue_view() -> dict:
    """What runs now and what waits, in the order the scheduler will take them."""
    con = db.trust_rw()
    try:
        running = con.execute("SELECT id, room_id, points, progress, message, created_at FROM job "
                              "WHERE kind='dropbox_sync' AND status='running' ORDER BY created_at").fetchall()
        queued = con.execute("SELECT id, room_id, points, priority, created_at FROM job WHERE kind='dropbox_sync' "
                             "AND status='queued' ORDER BY COALESCE(priority,1) DESC, created_at").fetchall()
        names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM room").fetchall()}
    finally:
        con.close()
    cap = capacity.points()
    used = sum((r["points"] or 0) for r in running)
    return {"capacity": cap, "used": used,
            "running": [{"job": r["id"], "room": r["room_id"], "name": names.get(r["room_id"], ""), "points": r["points"] or 0,
                         "progress": r["progress"], "message": r["message"]} for r in running],
            "queued": [{"job": r["id"], "room": r["room_id"], "name": names.get(r["room_id"], ""), "position": i + 1,
                        "points": r["points"] or 0, "priority": r["priority"] if r["priority"] is not None else 1}
                       for i, r in enumerate(queued)]}


def submit_run(room_id: str, force: bool = False) -> str:
    from .queue import queue
    room = get_room(room_id)
    if room["archived"]:
        raise RoomError(409, "this room is archived; restore it first")
    if not room["source"]:
        raise RoomError(422, "choose the input folder first")
    if room["mode"] == "upload" and not room["dest"]:
        raise RoomError(422, "choose the output folder, or switch to \"distill only\"")
    if active_job(room_id):
        raise RoomError(409, "this room is already queued or running")
    upload = room["mode"] == "upload"
    p = {"source_link": room["source"]["link"], "dry_run": not upload, "force": bool(force), "room_id": room_id}
    if room["dest"]:
        p["dest_link"] = room["dest"]["link"]
    jid = queue.submit("dropbox_sync", json.dumps(p), "queued", room_id=room_id, priority=room["priority"],
                       points=room["points"] or 1, dest_key=dest_key(room["dest"]) if upload else None)
    con = db.trust_rw()
    try:
        con.execute("UPDATE room SET last_job_id=?, updated_at=? WHERE id=?", (jid, db.now(), room_id))
        con.commit()
    finally:
        con.close()
    return jid


def move_to_front(room_id: str):
    """Make the room's queued run the next one to start."""
    job = active_job(room_id)
    if not job or job["status"] != "queued":
        raise RoomError(409, "this room is not waiting in the queue")
    con = db.trust_rw()
    try:
        first = con.execute("SELECT MIN(created_at) FROM job WHERE status='queued'").fetchone()[0] or db.now()
        con.execute("UPDATE job SET priority=2, created_at=? WHERE id=?", (first - 1, job["id"]))
        con.execute("UPDATE room SET priority=2 WHERE id=?", (room_id,))
        con.commit()
    finally:
        con.close()


def archive_blockers(room: dict) -> list:
    """Why a room cannot be archived yet. Empty means it can."""
    out = []
    if active_job(room["id"]):
        out.append("a run is queued or running")
    c = counts(room)
    if not c["total"]:
        out.append("nothing has been distilled yet")
    for key, label in (("pending", "not distilled yet"), ("processing", "being processed"),
                       ("below", "below the threshold, waiting for review"), ("unprocessable", "could not be processed")):
        if c[key]:
            out.append(f"{c[key]} file(s) {label}")
    return out


def set_archived(room_id: str, archived: bool, user: str) -> dict:
    room = get_room(room_id)
    if archived:
        blockers = archive_blockers(room)
        if blockers:
            raise RoomError(409, "cannot archive yet: " + "; ".join(blockers))
    con = db.trust_rw()
    try:
        con.execute("UPDATE room SET archived=?, archived_at=?, archived_by=?, updated_at=? WHERE id=?",
                    (1 if archived else 0, db.now() if archived else None, user if archived else None, db.now(), room_id))
        con.commit()
    finally:
        con.close()
    return get_room(room_id)


def summary(room: dict) -> dict:
    """What the collapsed header of a room shows."""
    job = None
    con = db.trust_rw()
    try:
        r = con.execute("SELECT id, status, progress, message FROM job WHERE room_id=? ORDER BY created_at DESC LIMIT 1",
                        (room["id"],)).fetchone()
        if r:
            job = dict(r)
            if job["status"] == "queued":
                ahead = con.execute("SELECT COUNT(*) FROM job WHERE status='queued' AND (COALESCE(priority,1) > ? "
                                    "OR (COALESCE(priority,1) = ? AND created_at < (SELECT created_at FROM job WHERE id=?)))",
                                    (room["priority"], room["priority"], job["id"])).fetchone()[0]
                job["position"] = ahead + 1
    finally:
        con.close()
    return {**room, "counts": counts(room), "job": job}


# ------------------------------------------------------------------ events -> rows
_UPSERT_FILE = ("INSERT INTO room_file(room_id, rel, kind, size, activity, outcome, reason, detail, accuracy, parts, diffs, "
                "number_diffs, findings, pages, run_id, confirmed, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?) "
                "ON CONFLICT(room_id, rel) DO UPDATE SET kind=excluded.kind, size=COALESCE(excluded.size, room_file.size), "
                "activity=excluded.activity, outcome=excluded.outcome, reason=excluded.reason, detail=excluded.detail, "
                "accuracy=excluded.accuracy, parts=excluded.parts, diffs=excluded.diffs, number_diffs=excluded.number_diffs, "
                "findings=excluded.findings, pages=excluded.pages, run_id=excluded.run_id, confirmed=0, "
                "updated_at=excluded.updated_at")


def apply_event(con, room_id: str, job_id: str, ev: dict):
    t, now = ev.get("type"), ev.get("t") or db.now()
    if t == "listing":
        files = ev.get("files") or []
        for f in files:
            con.execute("INSERT INTO room_file(room_id, rel, kind, size, updated_at) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(room_id, rel) DO UPDATE SET kind=excluded.kind, size=excluded.size",
                        (room_id, f["rel"], f.get("kind"), f.get("size"), now))
        have = {f["rel"] for f in files}
        for (rel,) in con.execute("SELECT rel FROM room_file WHERE room_id=? AND outcome IS NULL", (room_id,)).fetchall():
            if rel not in have:                      # removed from the source before it was ever distilled
                con.execute("DELETE FROM room_file WHERE room_id=? AND rel=?", (room_id, rel))
    elif t == "start":
        con.execute("UPDATE room_file SET activity='processing', updated_at=? WHERE room_id=? AND rel=?",
                    (now, room_id, ev["rel"]))
    elif t == "unchanged":
        con.execute("UPDATE room_file SET activity=NULL WHERE room_id=? AND rel=?", (room_id, ev["rel"]))
    elif t == "file":
        findings = json.dumps((ev.get("findings") or [])[:200], ensure_ascii=False)
        con.execute(_UPSERT_FILE, (room_id, ev["rel"], ev.get("kind"), None, None, ev.get("outcome"), ev.get("reason") or "",
                                   ev.get("detail") or "", ev.get("accuracy"),
                                   json.dumps(ev.get("parts") or {}), ev.get("diffs") or 0, ev.get("number_diffs") or 0,
                                   findings, ev.get("pages"), job_id, now))
        if ev.get("scan"):                           # a scanned file needed OCR: later runs of this room take 2 points
            con.execute("UPDATE room SET points=2 WHERE id=? AND COALESCE(points,1) < 2", (room_id,))


class EventReader:
    """Reads a run's event file as it grows and keeps the room's file rows up to date."""

    def __init__(self, room_id: str, job_id: str, path: str):
        self.room_id, self.job_id, self.path, self.offset = room_id, job_id, path, 0

    def poll(self) -> int:
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read()
        except OSError:
            return 0
        end = data.rfind(b"\n")
        if end < 0:
            return 0                                 # a line is still being written
        chunk, self.offset = data[:end + 1], self.offset + end + 1
        n = 0

        def _do():
            con = db.trust_rw()
            try:
                for line in chunk.decode("utf-8", "replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        apply_event(con, self.room_id, self.job_id, json.loads(line))
                    except (ValueError, KeyError):
                        continue
                con.commit()
            finally:
                con.close()

        db.trust_write(_do)
        n = chunk.count(b"\n")
        return n
