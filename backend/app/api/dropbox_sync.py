# -*- coding: utf-8 -*-
"""Dropbox sync in the web interface: start a run (reviewer/admin), follow it, roll back (admin)."""
import json
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..auth.users import require_role
from ..distill import dropbox_io as D
from ..distill import gdrive_io as G
from ..jobs import sync_job as S
from ..jobs.queue import queue

router = APIRouter()


class SyncIn(BaseModel):
    source_link: str
    dest_link: str
    dry_run: bool = True
    force: bool = False
    only: str = ""


class RollbackIn(BaseModel):
    source_link: str
    dest_link: str
    run: str


def _check_links(src, dest):
    for name, v in (("source", src), ("destination", dest)):
        v = v.strip()
        if not (S.LINK_RE.match(v) or S.PATH_RE.match(v) or G.is_gdrive(v)) or ".." in v.split("/"):
            raise HTTPException(422, f"the {name} must be a Dropbox folder path (/Folder/Sub), a Dropbox shared "
                                     "link (https://www.dropbox.com/...) or a Google Drive folder link "
                                     "(https://drive.google.com/drive/folders/...)")
    if src.strip().rstrip("/").lower() == dest.strip().rstrip("/").lower():
        raise HTTPException(422, "source and destination must be different folders")


@router.get("/dropbox/status")
def status():
    """Which Dropbox roles are authorised on this machine (never returns secrets)."""
    roles = []
    if os.path.exists(D.AUTH_PATH):
        try:
            with open(D.AUTH_PATH, encoding="utf-8") as f:
                roles = sorted(k for k, v in json.load(f).items() if isinstance(v, dict) and v.get("refresh_token"))
        except (OSError, ValueError):
            roles = []
    g = G.load_auth()
    google = {r: bool((g.get(r) or {}).get("refresh_token")) and bool((g.get("client") or {}).get("client_id"))
              for r in ("reader", "writer")}
    return {"reader": "reader" in roles, "writer": "writer" in roles, "google": google}


@router.post("/dropbox/sync")
def start(body: SyncIn):
    _check_links(body.source_link, body.dest_link)
    if _busy():
        raise HTTPException(409, "a Dropbox sync is already running; wait for it to finish")
    p = {"source_link": body.source_link.strip(), "dest_link": body.dest_link.strip(),
         "dry_run": body.dry_run, "force": body.force, "only": body.only.strip()[:120]}
    jid = queue.submit("dropbox_sync", json.dumps(p), "queued")
    return {"job": jid, "command": " ".join(S.command(p)[1:])}


@router.post("/dropbox/rollback", dependencies=[Depends(require_role())])     # administrators only
def rollback(body: RollbackIn):
    _check_links(body.source_link, body.dest_link)
    if not (len(body.run) == 15 and body.run.replace("-", "").isdigit()):
        raise HTTPException(422, "run id looks like 20261118-153000")
    if _busy():
        raise HTTPException(409, "a Dropbox sync is already running; wait for it to finish")
    p = {"source_link": body.source_link.strip(), "dest_link": body.dest_link.strip(), "rollback": body.run}
    return {"job": queue.submit("dropbox_sync", json.dumps(p), "queued")}


def _busy() -> bool:
    con = db.trust_rw()
    try:
        return con.execute("SELECT 1 FROM job WHERE kind='dropbox_sync' AND status IN ('queued','running') "
                           "LIMIT 1").fetchone() is not None
    finally:
        con.close()


def _row(r):
    d = dict(r)
    try:
        d["params"] = json.loads(d.pop("rel") or "{}")
    except ValueError:
        d["params"] = {}
    return d


@router.get("/dropbox/sync")
def runs(limit: int = 20):
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT id, rel, status, progress, message, created_at, updated_at FROM job "
                           "WHERE kind='dropbox_sync' ORDER BY created_at DESC LIMIT ?", (min(max(limit, 1), 100),)).fetchall()
    finally:
        con.close()
    return {"runs": [_row(r) for r in rows]}


@router.get("/dropbox/sync/{jid}")
def run(jid: str, lines: int = 200):
    if not jid.replace("-", "").isalnum():
        raise HTTPException(400, "bad id")
    job = queue.get(jid)
    if not job or job.get("kind") != "dropbox_sync":
        raise HTTPException(404, "no such sync run")
    out = _row(job)
    try:
        with open(S.log_path(jid), encoding="utf-8", errors="replace") as f:
            out["log"] = f.read().splitlines()[-min(max(lines, 1), 2000):]
    except OSError:
        out["log"] = []
    try:
        with open(S.summary_path(jid), encoding="utf-8") as f:
            out["summary"] = json.load(f)
    except (OSError, ValueError):
        out["summary"] = None
    try:
        with open(S.live_path(jid), encoding="utf-8") as f:
            out["live"] = json.load(f)
    except (OSError, ValueError):
        out["live"] = None
    return out


@router.post("/dropbox/sync/{jid}/cancel")
def cancel_run(jid: str):
    """Stop a running sync (reviewer/admin). Nothing is promoted to the output folder after a cancel."""
    if not jid.replace("-", "").isalnum():
        raise HTTPException(400, "bad id")
    job = queue.get(jid)
    if not job or job.get("kind") != "dropbox_sync":
        raise HTTPException(404, "no such sync run")
    if job["status"] == "queued":
        con = db.trust_rw()
        try:
            con.execute("UPDATE job SET status='error', message='cancelled by the user' WHERE id=? AND status='queued'", (jid,))
            con.commit()
        finally:
            con.close()
        return {"cancelled": True}
    if job["status"] != "running" or not S.cancel(jid):
        raise HTTPException(409, "this run is not running")
    return {"cancelled": True}
