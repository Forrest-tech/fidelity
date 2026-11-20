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
    assert c.post("/api/v1/dropbox/sync", json={"source_link": "C:/Users/x", "dest_link": DST}).status_code == 422
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
    j = r.json()
    assert (j["reader"], j["writer"]) == (True, False) and "SECRET" not in r.text


def _fake_spawn(lines, code, seen=None):
    """Stands in for starting the sync process: the "process" has already written `lines` to the log and ended with `code`."""
    class P:
        pid = 4242

        def poll(self):
            return code

    def spawn(cmd, env, log):
        if seen is not None:
            seen.setdefault("cmd", cmd)
        log.write("".join(lines).encode("utf-8"))
        log.flush()
        return P()
    return spawn


def test_job_runs_the_command_line_sync_and_keeps_log_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", str(tmp_path))

    seen = {}
    monkeypatch.setattr(S, "_spawn", _fake_spawn(
        ["source /2025 (read-only)  ->  output /out\n", "files to check: 2\n", "\n", "[1] a.pdf\n",
         "  verification: PASS  files=1\n", "[2] b.pdf\n",
         "promoted 2 document(s); undo with: python -m app.distill.sync --rollback 20261119-101500\n",
         "{\n", ' "source": "/2025",\n', ' "documents": []\n', "}\n"], 0, seen))
    progress = []
    job = {"id": "j9", "rel": json.dumps({"source_link": SRC, "dest_link": DST, "dry_run": False})}
    out = S.handle_sync(job, lambda p, m="": progress.append((p, m)))
    assert seen["cmd"][1:4] == ["-m", "app.distill.sync", "--source-link"] and "--dry-run" not in seen["cmd"]
    assert out["published_run"] == "20261119-101500" and out["report"]["source"] == "/2025"
    assert max(p for p, _ in progress) >= 90 and (tmp_path / "j9.log").read_text(encoding="utf-8").count("\n") == 11


def test_job_reports_a_changed_source_as_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", str(tmp_path))

    monkeypatch.setattr(S, "_spawn", _fake_spawn(["SOURCE CHANGED during the run: a.pdf\n"], 2))
    with pytest.raises(RuntimeError, match="source folder changed"):
        S.handle_sync({"id": "j8", "rel": json.dumps({"source_link": SRC, "dest_link": DST})}, lambda *a: None)


def test_common_dropbox_errors_get_plain_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", str(tmp_path))

    monkeypatch.setattr(S, "_spawn", _fake_spawn(
        ["Traceback ...\n", "dropbox.exceptions.ApiError: ApiError('x', SharedLinkMetadataError('shared_link_not_found', None))\n"], 1))
    with pytest.raises(RuntimeError, match="Dropbox cannot find one of the shared links"):
        S.handle_sync({"id": "j7", "rel": json.dumps({"source_link": SRC, "dest_link": DST})}, lambda *a: None)
    assert S.explain("random failure") is None


def test_folder_paths_are_accepted_too(login):
    c = login("reviewer")
    r = c.post("/api/v1/dropbox/sync", json={"source_link": "/2025", "dest_link": "/Transfer_Md"})
    assert r.status_code == 200, r.text
    assert c.post("/api/v1/dropbox/sync", json={"source_link": "/2025", "dest_link": "/2025/"}).status_code == 422
    assert c.post("/api/v1/dropbox/sync", json={"source_link": "/a/../b", "dest_link": "/out"}).status_code == 422
    assert c.post("/api/v1/dropbox/sync", json={"source_link": "2025", "dest_link": "/out"}).status_code == 422


def test_dropbox_inputs_people_paste_are_understood():
    from app.distill import dropbox_io as D
    assert D.parse_link("/AS 3500/") == ("path", "/AS 3500")
    assert D.parse_link("https://www.dropbox.com/home/AS%203500?di=left_nav_browse") == ("path", "/AS 3500")
    assert D.parse_link("https://www.dropbox.com/home/Work/Transfer_Md") == ("path", "/Work/Transfer_Md")
    kind, base, sub = D.parse_link("https://www.dropbox.com/scl/fo/abc123/KEY456/AS%203500?dl=0&rlkey=r1&subfolder_nav_tracking=1")
    assert (kind, base, sub) == ("link", "https://www.dropbox.com/scl/fo/abc123/KEY456?rlkey=r1", "/AS 3500")
    assert D.parse_link("https://www.dropbox.com/scl/fo/abc123/KEY456?rlkey=r1&dl=0")[1:] == ("https://www.dropbox.com/scl/fo/abc123/KEY456?rlkey=r1", "")


def test_sub_folder_of_an_own_shared_folder_becomes_its_path():
    from app.distill import dropbox_io as D

    class Dbx:
        def sharing_get_shared_link_metadata(self, url):
            return type("M", (), {"path_lower": "/library"})()
    assert D.canonical(Dbx(), "https://www.dropbox.com/scl/fo/a/b/AS%203500?rlkey=r") == "/library/AS 3500"
    assert D.canonical(Dbx(), "https://www.dropbox.com/home/Transfer_Md") == "/Transfer_Md"

    class Foreign:
        def sharing_get_shared_link_metadata(self, url):
            return type("M", (), {"path_lower": None})()
    with pytest.raises(SystemExit, match="Copy link"):
        D.canonical(Foreign(), "https://www.dropbox.com/scl/fo/a/b/Sub?rlkey=r")


def test_live_status_follows_files_stages_and_ocr_pages():
    t = [100.0]
    live = S.Live("j1", now=lambda: t[0])
    for line in ["source dropbox:/as 3500 (read-only)  ->  output dropbox:/transfer_md", "files to check: 4",
                 "unchanged since last run, skipped: /a.pdf", "", "[1] /1990/Scan.pdf", "  download (0.5 MB)",
                 "  scanned document: OCR of 200 page(s) with 2 engine(s)", "  OCR page 50/200"]:
        t[0] += 1
        live.feed(line + "\n")
    st = live.state
    assert (st["total"], st["index"], st["file"], st["stage"], st["page"], st["pages"], st["scan"]) == \
        (4, 1, "/1990/Scan.pdf", "ocr", 50, 200, True)
    assert st["skipped"] == 1 and st["updated"] == 108.0
    assert 5 < live.percent() < 50                       # moves within a long scanned file, not stuck at file 1
    live.feed("  verification: REVIEW  files=1\n")
    live.feed("[2] /b.pdf\n")
    live.feed("  verification: PASS  files=3\n")
    assert live.state["counts"] == {"REVIEW": 1, "PASS": 1}


def test_cancel_stops_the_whole_process_tree_and_reports_cancelled(tmp_path, monkeypatch):
    import sys as _sys
    import time as _time
    import threading
    monkeypatch.setattr(S, "LOG_DIR", str(tmp_path))
    slow = [_sys.executable, "-c", "import time\nprint('files to check: 1', flush=True)\nprint('[1] /x.pdf', flush=True)\ntime.sleep(60)"]
    monkeypatch.setattr(S, "command", lambda p: slow)
    errors = []

    def run():
        try:
            S.handle_sync({"id": "jc", "rel": json.dumps({"source_link": SRC, "dest_link": DST})}, lambda *a: None)
        except RuntimeError as e:
            errors.append(str(e))
    th = threading.Thread(target=run)
    th.start()
    for _ in range(100):
        if "jc" in S._procs:
            break
        _time.sleep(0.05)
    _time.sleep(0.5)
    assert S.cancel("jc") is True
    th.join(timeout=20)
    assert not th.is_alive() and errors == ["cancelled by the user"]
    assert json.loads((tmp_path / "jc.live.json").read_text(encoding="utf-8"))["stage"] == "finished"
    assert S.cancel("jc") is False                       # nothing left to cancel


def test_failure_message_names_the_exception_not_the_last_progress_line():
    from app.jobs import sync_job as S
    text = "[1] a.pdf\n  OCR page 4\nTraceback (most recent call last):\n  File \"x.py\", line 1\n" \
           "PermissionError: [WinError 32] in use\n  OCR page 5\n"
    assert S.failure_message(text, 1) == "sync failed (exit 1): PermissionError: [WinError 32] in use"
    assert "Dropbox cannot find one of the shared links" in S.failure_message("ApiError('shared_link_not_found')", 1)
    assert S.failure_message("", 3) == "sync failed (exit 3): no output"


def test_live_status_writes_a_new_step_at_once_even_inside_the_throttle(tmp_path, monkeypatch):
    import json
    from app.jobs import sync_job as S
    monkeypatch.setattr(S, "LOG_DIR", str(tmp_path))
    clock = [100.0]
    live = S.Live("j1", now=lambda: clock[0])
    live.write(force=True)
    live.feed("files to check: 41")
    live.write()
    live.feed("[1] /a.pdf")                 # same second: still written, it is a new file
    live.write()
    assert json.load(open(S.live_path("j1")))["index"] == 1
    live.feed("  some chatty line")         # nothing changed and inside the second: not rewritten
    live.state["file"] = "marker"
    live.write()
    assert json.load(open(S.live_path("j1")))["file"] == "/a.pdf"
