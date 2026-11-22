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
    skipped         not distilled on purpose, nothing is missing: a duplicate of another file, or a copy-protected file
                    whose unlocked copy ("...-已解锁", "...unlocked") in the same folder has a result
    publishing      accepted, being sent to the output folder
    published       accepted and in the output folder
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
STATES = ("pending", "processing", "ok", "below", "unprocessable", "skipped", "publishing", "published")


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


DEFAULT_PREFIX = "蒸馏室"


def create_room(name: str | None, user: str, prefix: str | None = None) -> dict:
    """A new room. Without a name it is called "<prefix> N" (the page sends the word in the person's language)."""
    rid = uuid.uuid4().hex[:10]
    now = db.now()
    con = db.trust_rw()
    try:
        n = con.execute("SELECT COUNT(*) FROM room").fetchone()[0]
        used = {r[0] for r in con.execute("SELECT name FROM room").fetchall()}
        name = (name or "").strip()[:80]
        if not name:
            base = re.sub(r"\s+", " ", (prefix or "").strip())[:40] or DEFAULT_PREFIX
            k = n + 1
            while f"{base} {k}" in used:
                k += 1
            name = f"{base} {k}"
        pos = con.execute("SELECT COALESCE(MAX(position),0)+1 FROM room").fetchone()[0]
        from ..api.appsettings import defaults as _defaults
        d = _defaults()
        con.execute("INSERT INTO room(id,name,position,mode,threshold,number_guard,priority,points,archived,"
                    "created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, name, pos, d["mode"], float(d["threshold"]), 1 if d["number_guard"] else 0, 1, 1, 0, user, now, now))
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
    _check_overlap(fields, room)
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


def _check_overlap(fields: dict, room: dict):
    """The output folder must lie outside the input folder and the other way round (the iron rule; the run checks
    it again, but saying so when the room is set up is kinder)."""
    from ..distill import dropbox_io as D
    src = fields["source"] if "source" in fields else (room["source"] or {}).get("link")
    dst = fields["dest"] if "dest" in fields else (room["dest"] or {}).get("link")
    src = src if isinstance(src, str) else (src or {}).get("link")
    dst = dst if isinstance(dst, str) else (dst or {}).get("link")
    if src and dst and src.strip().startswith("/") and dst.strip().startswith("/"):
        if D.is_under(dst, src) or D.is_under(src, dst):
            raise RoomError(422, "the output folder must be outside the input folder")


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
    if row["activity"] == "publishing":
        return "publishing"
    outcome = row["outcome"]
    if not outcome:
        return "pending"
    if outcome == "skipped" and row["reason"] == "duplicate":
        return "skipped"
    if outcome == "unprocessable" and row["reason"] == "protected" and _get(row, "covered_by"):
        return "skipped"
    if _get(row, "covered_by") and not row["confirmed"] and outcome in ("result", "unprocessable"):
        return "skipped"                     # another copy of the same edition is the one that is published
    if outcome in ("unprocessable", "skipped"):
        return "unprocessable"
    if row["confirmed"]:
        return "published"
    # a number fixed by a correction rule and picked for checking counts as a number difference until checked
    nd = (row["number_diffs"] or 0) + (_get(row, "rule_checks") or 0)
    return SC.decide(row["accuracy"], nd, room["threshold"], room["number_guard"])


def _get(row, key):
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _identity(room_id: str, r) -> dict:
    """The file's standard and edition (see distill/editions.py), read from the start of its result when it has one."""
    from ..distill import editions as ED
    from ..distill import run as RN
    text = ""
    if r["out_dir"]:
        base = RN.longpath(os.path.join(S.room_dir(room_id), "out", r["out_dir"]))
        try:
            files = [base] if os.path.isfile(base) else sorted(
                os.path.join(a, f) for a, _, ff in os.walk(base) for f in ff if f.lower().endswith(".md"))
            for f in files[:2]:
                with open(f, encoding="utf-8", errors="ignore") as fh:
                    text += fh.read(12000).split("---", 2)[-1][:6000]
        except OSError:
            pass
    return {**ED.identify(r["rel"], text), "out_dir": r["out_dir"] or ""}


def _editions(room_id: str, rows: list) -> list:
    """Rows with their edition worked out: identity is stored once per result (it reads the result's first pages),
    best copy and current/superseded are recomputed from the whole room every time."""
    from ..distill import editions as ED
    out, todo = [], []
    for r in rows:
        d = dict(r)
        e = json.loads(d["edition"]) if _get(r, "edition") else None
        if not e or e.get("out_dir", "") != (d["out_dir"] or ""):
            e = _identity(room_id, d)
            todo.append((json.dumps(e, ensure_ascii=False), room_id, d["rel"]))
        d["edition"] = e
        out.append(d)
    if todo:
        def _save():
            con = db.trust_rw()
            try:
                con.executemany("UPDATE room_file SET edition=? WHERE room_id=? AND rel=?", todo)
                con.commit()
            finally:
                con.close()
        try:
            db.trust_write(_save)
        except Exception:                                    # noqa: BLE001 - worked out again next time
            pass
    out = ED.registry(out)
    for d in out:
        d["covered_by"] = d["edition"].get("copy_of")
    return out


def editions_view(room: dict) -> dict:
    """Standards by edition: for each edition, the copy that represents it, the other copies, and its status here."""
    groups: dict = {}
    for r in _files(room["id"]):
        e = r["edition"]
        if not e.get("key"):
            continue
        g = groups.setdefault(e["key"], {"designation": e["designation"], "number": e["number"], "year": e["year"],
                                         "amendment": e.get("amendment"), "consolidated": e.get("consolidated"),
                                         "status": e["status"], "superseded_by": e["superseded_by"],
                                         "best": None, "copies": []})
        item = {"rel": r["rel"], "state": derive_state(r, room), "accuracy": r["accuracy"]}
        if e.get("copy_of"):
            g["copies"].append(item)
        else:
            g["best"] = item
    out = sorted(groups.values(), key=lambda g: (g["number"], g["year"], g["amendment"] or 0, bool(g["consolidated"])))
    editions = [g for g in out if g["amendment"] is None]
    return {"editions": out, "standards": len({g["number"] for g in out}),
            "current": sum(1 for g in editions if g["status"] == "current"),
            "superseded": sum(1 for g in editions if g["status"] == "superseded"),
            "amendments": sum(1 for g in out if g["amendment"] is not None),
            "extra_copies": sum(1 for g in out for c in g["copies"] if c["state"] != "published"),
            # the same edition published more than once: the AI library holds it twice
            "published_twice": sum(1 for g in out if any(c["state"] == "published" for c in g["copies"])
                                   and g["best"] and g["best"]["state"] == "published")}


def _files(room_id: str) -> list:
    return _editions(room_id, _rows(room_id))


def _rows(room_id: str) -> list:
    con = db.trust_rw()
    try:
        return con.execute("SELECT rel, kind, size, activity, outcome, reason, detail, accuracy, parts, diffs, number_diffs, "
                           "confirmed, confirmed_by, confirmed_at, pages, run_id, out_dir, content_hash, single_file, n_files, "
                           "verdict, corrections, rule_checks, findings, known, edition, updated_at FROM room_file WHERE room_id=?", (room_id,)).fetchall()
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
            "parts": json.loads(r["parts"]) if r["parts"] else None,
            "corrected": sum(i.get("count", 0) for i in json.loads(r["corrections"])) if r["corrections"] else 0,
            "checks": r["rule_checks"] or 0, "covered_by": _get(r, "covered_by"), "edition": _edition_out(_get(r, "edition"))}


def _edition_out(e) -> dict | None:
    if not e or not e.get("designation"):
        return None
    return {k: e.get(k) for k in ("designation", "amendment", "amendment_year", "consolidated", "status", "superseded_by",
                                  "copy_of", "copies", "basis")}


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
    # A room's run only distills (results stay on this machine). Sending results to the output folder is a separate
    # step, accept(), so a result is never published without having been judged, and nothing is distilled twice.
    # "parallel": the queue may give the run several slots (files read at once); "unit_points" is one file's share
    p = {"source_link": room["source"]["link"], "dry_run": True, "force": bool(force), "room_id": room_id,
         "parallel": True, "unit_points": room["points"] or 1}
    jid = queue.submit("dropbox_sync", json.dumps(p), "queued", room_id=room_id, priority=room["priority"],
                       points=room["points"] or 1, dest_key=None)
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
    if job and job["status"] == "running":
        try:                                                  # where the run is: file, stage, OCR page
            with open(S.live_path(job["id"]), encoding="utf-8") as f:
                live = json.load(f)
            job["live"] = {k: live.get(k) for k in ("file", "stage", "page", "pages", "index", "total", "started", "updated",
                                                     "scan", "v", "workers", "done", "skipped", "active", "queued", "counts")}
        except (OSError, ValueError):
            pass
    rows = _files(room["id"])
    accs = [r["accuracy"] for r in rows if r["outcome"] == "result" and r["accuracy"] is not None]
    return {**room, "counts": counts(room, rows), "job": job,
            "accuracy_avg": round(sum(accs) / len(accs), 1) if accs else None}


# ------------------------------------------------------------------ events -> rows
_UPSERT_FILE = ("INSERT INTO room_file(room_id, rel, kind, size, activity, outcome, reason, detail, accuracy, parts, diffs, "
                "number_diffs, findings, pages, run_id, out_dir, content_hash, single_file, n_files, verdict, confirmed, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?) "
                "ON CONFLICT(room_id, rel) DO UPDATE SET kind=excluded.kind, size=COALESCE(excluded.size, room_file.size), "
                "activity=excluded.activity, outcome=excluded.outcome, reason=excluded.reason, detail=excluded.detail, "
                "accuracy=excluded.accuracy, parts=excluded.parts, diffs=excluded.diffs, number_diffs=excluded.number_diffs, "
                "findings=excluded.findings, pages=excluded.pages, run_id=excluded.run_id, "
                "out_dir=excluded.out_dir, content_hash=excluded.content_hash, single_file=excluded.single_file, "
                "n_files=excluded.n_files, verdict=excluded.verdict, confirmed=0, confirmed_by=NULL, confirmed_at=NULL, "
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
        # A file removed from the source goes from the list unless it has a result: one never distilled, a skipped
        # duplicate or a file that could not be read leaves nothing behind (a deleted duplicate used to stay listed).
        for (rel,) in con.execute("SELECT rel FROM room_file WHERE room_id=? AND (outcome IS NULL OR outcome<>'result')",
                                  (room_id,)).fetchall():
            if rel not in have:
                con.execute("DELETE FROM room_file WHERE room_id=? AND rel=?", (room_id, rel))
    elif t == "start":
        con.execute("UPDATE room_file SET activity='processing', updated_at=? WHERE room_id=? AND rel=?",
                    (now, room_id, ev["rel"]))
    elif t == "unchanged":
        con.execute("UPDATE room_file SET activity=NULL WHERE room_id=? AND rel=?", (room_id, ev["rel"]))
    elif t == "published":
        con.execute("UPDATE room_file SET activity=NULL, confirmed=1, confirmed_at=COALESCE(confirmed_at, ?), updated_at=? "
                    "WHERE room_id=? AND rel=?", (now, now, room_id, ev["rel"]))
    elif t == "publish_failed":
        con.execute("UPDATE room_file SET activity=NULL, detail=?, updated_at=? WHERE room_id=? AND rel=?",
                    ("could not be sent to the output folder: " + str(ev.get("error") or "")[:300], now, room_id, ev["rel"]))
    elif t == "file":
        findings = json.dumps((ev.get("findings") or [])[:200], ensure_ascii=False)
        con.execute(_UPSERT_FILE, (room_id, ev["rel"], ev.get("kind"), None, None, ev.get("outcome"), ev.get("reason") or "",
                                   ev.get("detail") or "", ev.get("accuracy"),
                                   json.dumps(ev.get("parts") or {}), ev.get("diffs") or 0, ev.get("number_diffs") or 0,
                                   findings, ev.get("pages"), job_id, ev.get("out_dir"), ev.get("content_hash"),
                                   1 if ev.get("single_file") else 0, ev.get("n_files"), ev.get("verdict"), now))
        if ev.get("scan"):                           # a scanned file needed OCR: later runs of this room take 2 points
            con.execute("UPDATE room SET points=2 WHERE id=? AND COALESCE(points,1) < 2", (room_id,))


def end_activity(room_id: str):
    """The room's run has ended (finished, failed, cancelled or killed): files it had in hand and never finished go
    back to "not distilled yet" instead of showing as busy for ever. A room runs one job at a time, so every file
    still marked as being processed belonged to that run."""
    def _do():
        con = db.trust_rw()
        try:
            con.execute("UPDATE room_file SET activity=NULL WHERE room_id=? AND activity='processing'", (room_id,))
            con.commit()
        finally:
            con.close()
    db.trust_write(_do)


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

        fresh = []

        def _do():
            fresh.clear()
            con = db.trust_rw()
            try:
                for line in chunk.decode("utf-8", "replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                        apply_event(con, self.room_id, self.job_id, ev)
                    except (ValueError, KeyError):
                        continue
                    if ev.get("type") == "file" and ev.get("outcome") == "result" and ev.get("out_dir"):
                        fresh.append(ev["rel"])
                con.commit()
            finally:
                con.close()

        db.trust_write(_do)
        # a new result: keep the distiller's own copy and apply the correction rules to it
        from . import corrections as C
        for rel in fresh:
            try:
                C.on_new_result(self.room_id, rel)
            except Exception:                        # noqa: BLE001 - a rule problem must never stop the run
                import traceback
                traceback.print_exc()
        n = chunk.count(b"\n")
        return n


# ------------------------------------------------------------------ accepting into the knowledge base
def accept_preview(room: dict) -> dict:
    """What "accept all that qualify" would do now."""
    rows = _files(room["id"])
    c = {"ok": 0, "below": 0, "published": 0, "publishing": 0}
    for r in rows:
        st = derive_state(r, room)
        if st in c:
            c[st] += 1
    return {**c, "has_dest": bool(room["dest"]), "dest": (room["dest"] or {}).get("link"), "threshold": room["threshold"],
            "number_guard": room["number_guard"]}


def accept(room_id: str, user: str, rels=None, all_ok: bool = False, force: bool = False) -> dict:
    """Send accepted results to the output folder.

    all_ok: every file that meets the threshold. rels: these files; one below the threshold needs force=True (a person
    decides it is good enough, and the published copy says so). Returns {job, count}."""
    room = get_room(room_id)
    if not room["dest"]:
        raise RoomError(422, "choose the output folder first")
    if active_job(room_id):
        raise RoomError(409, "this room is queued or running; wait for it to finish")
    rows = {r["rel"]: r for r in _files(room_id)}
    chosen = []
    if all_ok:
        chosen = [r for r in rows.values() if derive_state(r, room) == "ok"]
    for rel in rels or []:
        r = rows.get(rel)
        if r is None:
            raise RoomError(404, f"no such file in this room: {rel}")
        st = derive_state(r, room)
        if st == "ok" or (st == "below" and force):
            chosen.append(r)
        elif st == "below":
            raise RoomError(409, f"{rel} is below the threshold; confirm it to accept it anyway")
        elif st in ("published", "publishing"):
            continue
        else:
            raise RoomError(409, f"{rel} has no result to accept ({st})")
    seen, items = set(), []
    for r in chosen:
        if r["rel"] in seen:
            continue
        seen.add(r["rel"])
        if not r["out_dir"]:
            raise RoomError(409, f"{r['rel']}: its result is missing; run the room again")
        items.append({"rel": r["rel"], "out_dir": r["out_dir"], "content_hash": r["content_hash"], "accuracy": r["accuracy"],
                      "forced": derive_state(r, room) == "below", "by": user, "edition": _edition_out(r.get("edition"))})
    if not items:
        raise RoomError(409, "nothing to accept")
    return _queue_publish(room, items, user)


def restamp(room_id: str) -> dict:
    """Send the published files again with their edition lines brought up to date (a newer edition arrived, so an
    older one is now superseded), keeping who accepted each and when. Nothing is distilled again."""
    import datetime as _dt
    room = get_room(room_id)
    if not room["dest"]:
        raise RoomError(422, "choose the output folder first")
    if active_job(room_id):
        raise RoomError(409, "this room is queued or running; wait for it to finish")
    items = []
    for r in _files(room_id):
        if not r["confirmed"] or not r["out_dir"]:
            continue
        nd = (r["number_diffs"] or 0) + (_get(r, "rule_checks") or 0)
        at = _dt.datetime.fromtimestamp(r["confirmed_at"]).astimezone().isoformat(timespec="seconds") if r["confirmed_at"] else None
        items.append({"rel": r["rel"], "out_dir": r["out_dir"], "content_hash": r["content_hash"], "accuracy": r["accuracy"],
                      "forced": SC.decide(r["accuracy"], nd, room["threshold"], room["number_guard"]) == "below",
                      "by": r["confirmed_by"] or "", "at": at, "edition": _edition_out(r.get("edition"))})
    if not items:
        raise RoomError(409, "nothing is published yet")
    return _queue_publish(room, items, None)


def _queue_publish(room: dict, items: list, user: str | None) -> dict:
    from .queue import queue
    room_id = room["id"]
    plan = os.path.join(S.room_dir(room_id), f"publish-{uuid.uuid4().hex[:8]}.json")
    os.makedirs(os.path.dirname(plan), exist_ok=True)
    with open(plan, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False)
    p = {"source_link": room["source"]["link"], "dest_link": room["dest"]["link"], "publish_from": plan, "room_id": room_id}
    jid = queue.submit("dropbox_sync", json.dumps(p), "queued", room_id=room_id, priority=room["priority"], points=1,
                       dest_key=dest_key(room["dest"]))
    now = db.now()
    con = db.trust_rw()
    try:
        for it in items:
            if user is None:                                 # a re-stamp keeps who accepted it and when
                con.execute("UPDATE room_file SET activity='publishing', updated_at=? WHERE room_id=? AND rel=?",
                            (now, room_id, it["rel"]))
            else:
                con.execute("UPDATE room_file SET activity='publishing', confirmed_by=?, confirmed_at=?, updated_at=? "
                            "WHERE room_id=? AND rel=?", (user, now, now, room_id, it["rel"]))
        con.execute("UPDATE room SET last_job_id=?, updated_at=? WHERE id=?", (jid, now, room_id))
        con.commit()
    finally:
        con.close()
    return {"job": jid, "count": len(items)}


def after_run(job: dict | None):
    """A room that is set to "upload" accepts what qualifies by itself once its distilling run has finished well."""
    if not job or not job.get("room_id"):
        return
    try:
        p = json.loads(job.get("rel") or "{}")
    except ValueError:
        return
    if p.get("publish_from"):
        return                                              # that was a publishing job
    room = get_room(job["room_id"])
    if room["mode"] == "upload" and room["dest"] and not room["archived"]:
        try:
            accept(room["id"], "automatic (room is set to upload)", all_ok=True)
        except RoomError:
            pass                                            # nothing qualified, or something is already queued


def install_hooks():
    from .queue import queue
    if after_run not in queue.after_done:
        queue.after_done.append(after_run)


# ------------------------------------------------------------------ comparing with the live copy
def _result_row(room: dict, rel: str):
    r = next((x for x in _files(room["id"]) if x["rel"] == rel), None)
    if r is None:
        raise RoomError(404, f"no such file in this room: {rel}")
    if derive_state(r, room) not in ("ok", "below", "published", "publishing") or not r["out_dir"]:
        raise RoomError(409, "this file has no result to compare")
    return r


def compare_file(room: dict, rel: str) -> dict:
    """The new result of one file against the copy now in the output folder."""
    from ..distill import accept as AC
    from ..distill import live as L
    if not room["dest"]:
        raise RoomError(422, "choose the output folder first")
    r = _result_row(room, rel)
    try:
        live = L.open_live(room["dest"]["link"])
        out = L.compare(os.path.join(S.room_dir(room["id"]), "out", r["out_dir"]), AC.live_key(r["out_dir"]), live)
    except L.LiveError as e:
        raise RoomError(e.status, e.message)
    return {"rel": rel, "dest": room["dest"]["link"], "accuracy": r["accuracy"], "state": derive_state(r, room), **out}


def accept_impact(room: dict) -> dict:
    """Of the files that would be accepted now, how many are new to the output folder and how many replace one."""
    from ..distill import accept as AC
    from ..distill import live as L
    if not room["dest"]:
        raise RoomError(422, "choose the output folder first")
    keys = [AC.live_key(r["out_dir"]) for r in _files(room["id"]) if derive_state(r, room) == "ok" and r["out_dir"]]
    try:
        return L.impact(keys, L.open_live(room["dest"]["link"]))
    except L.LiveError as e:
        raise RoomError(e.status, e.message)
