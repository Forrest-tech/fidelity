"""Dropbox sync from the web interface: who may start it, link checks, one at a time, the job itself."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.auth.models import Role, User
from app.auth.schemas import UserCreate
from app.auth.users import UserManager
from app.jobs import sync_job as S
from app.jobs.queue import queue
from app.main import app
from app.migrate import upgrade
from app.orm import SessionLocal
from fastapi_users.db import SQLAlchemyUserDatabase

PW = "correct-horse-battery"
SRC = "https://www.dropbox.com/scl/fo/abc/src?rlkey=1&dl=0"
DST = "https://www.dropbox.com/scl/fo/def/out?rlkey=2&dl=0"


async def _mk(email, role):
    async with SessionLocal() as s:
        try:
            await UserManager(SQLAlchemyUserDatabase(s, User)).create(UserCreate(email=email, password=PW, role=role, is_verified=True))
        except Exception:
            pass


@pytest.fixture()
def login(monkeypatch):
    upgrade()
    db.init_trust()
    for r in Role:
        asyncio.run(_mk("dbx-%s@example.com" % r.value, r))
    con = db.trust_rw()
    con.execute("DELETE FROM job WHERE kind='dropbox_sync'")
    con.commit()
    con.close()
    submitted = []
    monkeypatch.setattr(queue, "submit", lambda kind, rel="", message="": submitted.append((kind, rel)) or "job1")

    def do(role):
        c = TestClient(app)
        assert c.post("/api/v1/auth/login", data={"username": "dbx-%s@example.com" % role, "password": PW}).status_code in (200, 204)
        c.submitted = submitted
        return c
    return do


def test_viewer_cannot_start_a_sync(login):
    c = login("viewer")
    assert c.post("/api/v1/dropbox/sync", json={"source_link": SRC, "dest_link": DST}).status_code == 403


def test_reviewer_starts_a_dry_run_by_default(login):
    c = login("reviewer")
    r = c.post("/api/v1/dropbox/sync", json={"source_link": SRC, "dest_link": DST, "only": "Volume One"})
    assert r.status_code == 200, r.text
    kind, rel = c.submitted[-1]
    p = json.loads(rel)
    assert kind == "dropbox_sync" and p["dry_run"] is True and p["only"] == "Volume One"
    assert "--dry-run" in r.json()["command"] and "--only" in r.json()["command"]


def test_links_are_checked(login):
    c = login("reviewer")
    assert c.post("/api/v1/dropbox/sync", json={"source_link": "/2025", "dest_link": DST}).status_code == 422
    assert c.post("/api/v1/dropbox/sync", json={"source_link": SRC, "dest_link": SRC}).status_code == 422
    assert c.post("/api/v1/dropbox/sync", json={"source_link": "https://evil.example/x", "dest_link": DST}).status_code == 422


def test_only_one_sync_at_a_time(login):
    con = db.trust_rw()
    con.execute("INSERT INTO job(id,kind,rel,status,progress,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                ("busy1", "dropbox_sync", "{}", "running", 10.0, "", db.now(), db.now()))
    con.commit()
    con.close()
    c = login("admin")
    assert c.post("/api/v1/dropbox/sync", json={"source_link": SRC, "dest_link": DST}).status_code == 409
    runs = c.get("/api/v1/dropbox/sync").json()["runs"]
    assert runs[0]["id"] == "busy1" and runs[0]["status"] == "running"


def test_rollback_is_admin_only(login):
    body = {"source_link": SRC, "dest_link": DST, "run": "20261118-153000"}
    assert login("reviewer").post("/api/v1/dropbox/rollback", json=body).status_code == 403
    c = login("admin")
    assert c.post("/api/v1/dropbox/rollback", json=body).status_code == 200
    assert json.loads(c.submitted[-1][1])["rollback"] == "20261118-153000"
    assert c.post("/api/v1/dropbox/rollback", json={**body, "run": "x; rm -rf /"}).status_code == 422


def test_status_never_returns_secrets(login, tmp_path, monkeypatch):
    from app.distill import dropbox_io as D
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"reader": {"refresh_token": "SECRET", "app_key": "k"}}), encoding="utf-8")
    monkeypatch.setattr(D, "AUTH_PATH", str(p))
    r = login("viewer").get("/api/v1/dropbox/status")
    assert r.json() == {"reader": True, "writer": False} and "SECRET" not in r.text


def test_job_runs_the_command_line_sync_and_keeps_log_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", str(tmp_path))

    class P:
        stdout = iter(["source /2025 (read-only)  ->  output /out\n", "files to check: 2\n", "\n", "[1] a.pdf\n",
                       "  verification: PASS  files=1\n", "[2] b.pdf\n",
                       "promoted 2 document(s); undo with: python -m app.distill.sync --rollback 20261119-101500\n",
                       "{\n", ' "source": "/2025",\n', ' "documents": []\n', "}\n"])

        def wait(self):
            return 0
    seen = {}
    monkeypatch.setattr(S.subprocess, "Popen", lambda cmd, **kw: seen.setdefault("cmd", cmd) and P())
    progress = []
    job = {"id": "j9", "rel": json.dumps({"source_link": SRC, "dest_link": DST, "dry_run": False})}
    out = S.handle_sync(job, lambda p, m="": progress.append((p, m)))
    assert seen["cmd"][1:4] == ["-m", "app.distill.sync", "--source-link"] and "--dry-run" not in seen["cmd"]
    assert out["published_run"] == "20261119-101500" and out["report"]["source"] == "/2025"
    assert max(p for p, _ in progress) >= 90 and (tmp_path / "j9.log").read_text(encoding="utf-8").count("\n") == 11


def test_job_reports_a_changed_source_as_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", str(tmp_path))

    class P:
        stdout = iter(["SOURCE CHANGED during the run: a.pdf\n"])

        def wait(self):
            return 2
    monkeypatch.setattr(S.subprocess, "Popen", lambda cmd, **kw: P())
    with pytest.raises(RuntimeError, match="source folder changed"):
        S.handle_sync({"id": "j8", "rel": json.dumps({"source_link": SRC, "dest_link": DST})}, lambda *a: None)


def test_common_dropbox_errors_get_plain_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", str(tmp_path))

    class P:
        stdout = iter(["Traceback ...\n", "dropbox.exceptions.ApiError: ApiError('x', SharedLinkMetadataError('shared_link_not_found', None))\n"])

        def wait(self):
            return 1
    monkeypatch.setattr(S.subprocess, "Popen", lambda cmd, **kw: P())
    with pytest.raises(RuntimeError, match="Dropbox cannot find one of the shared links"):
        S.handle_sync({"id": "j7", "rel": json.dumps({"source_link": SRC, "dest_link": DST})}, lambda *a: None)
    assert S.explain("random failure") is None
