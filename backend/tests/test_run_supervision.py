# -*- coding: utf-8 -*-
"""A run is its own process: it outlives a restart of the web server, is taken back afterwards, and is marked
"interrupted" (not left showing "running", not "error") when it was killed."""
import json
import subprocess
import sys
import threading
import time

import pytest

from app import db
from app.jobs import sync_job as S
from app.jobs.queue import Interrupted

SRC = "/as 3500"


@pytest.fixture(autouse=True)
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", str(tmp_path))
    db.init_trust()
    con = db.trust_rw()
    con.execute("DELETE FROM job")
    con.commit()
    con.close()


def _script(tmp_path, body):
    p = tmp_path / "fake_sync.py"
    p.write_text(body, encoding="utf-8")
    return [sys.executable, str(p)]


def _start(jid, tmp_path, body, write_exit=True):
    """Start a fake sync the way a run is started, but without supervising it."""
    cmd = _script(tmp_path, "import os,sys,time\n" + body + ("\nopen(os.environ['FIDELITY_EXIT_FILE'],'w').write('0')\n" if write_exit else "\n"))
    env = dict(__import__("os").environ, FIDELITY_EXIT_FILE=S.exit_path(jid))
    with open(S.log_path(jid), "wb") as log:
        return S._spawn(cmd, env, log)


def _job(jid, pid):
    return {"id": jid, "kind": "dropbox_sync", "pid": pid, "rel": json.dumps({"source_link": SRC, "dry_run": True})}


def _wait(cond, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_a_run_is_supervised_to_its_end_and_leaves_a_heartbeat_and_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "command", lambda p, events=None: _script(
        tmp_path, "import time\nprint('files to check: 1', flush=True)\nprint('[1] /x.pdf', flush=True)\ntime.sleep(1)\nprint('{}')\n"))
    jid = "sup1"
    con = db.trust_rw()
    con.execute("INSERT INTO job(id,kind,rel,status,progress,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (jid, "dropbox_sync", "{}", "running", 0, 1.0, 1.0))
    con.commit()
    con.close()
    progress = []
    out = S.handle_sync({"id": jid, "rel": json.dumps({"source_link": SRC})}, lambda p, m="": progress.append(m))
    assert out["exit_code"] == 0 and any("[1] /x.pdf" in m for m in progress)
    con = db.trust_rw()
    row = con.execute("SELECT pid, heartbeat_at FROM job WHERE id=?", (jid,)).fetchone()
    con.close()
    assert row["pid"] and row["heartbeat_at"]


def test_a_still_running_process_is_taken_back_and_finishes_the_job(tmp_path):
    jid = "adopt1"
    proc = _start(jid, tmp_path, "print('files to check: 1', flush=True)\nprint('[1] /x.pdf', flush=True)\ntime.sleep(2)\nprint('{}', flush=True)")
    updates = []
    assert S.adopt(_job(jid, proc.pid), lambda j, **kw: updates.append(kw)) is True      # "the server restarted here"
    assert _wait(lambda: any(u.get("status") == "done" for u in updates))
    assert any("[1] /x.pdf" in (u.get("message") or "") for u in updates)


def test_a_process_that_ended_while_the_server_was_away_still_finishes_the_job(tmp_path):
    jid = "adopt2"
    proc = _start(jid, tmp_path, "print('files to check: 0', flush=True)\nprint('{}', flush=True)")
    proc.wait()
    updates = []
    assert S.adopt(_job(jid, proc.pid), lambda j, **kw: updates.append(kw)) is True
    assert _wait(lambda: any(u.get("status") == "done" for u in updates))


def test_a_process_that_is_gone_without_a_trace_cannot_be_taken_back(tmp_path):
    jid = "adopt3"
    proc = _start(jid, tmp_path, "print('hi', flush=True)", write_exit=False)
    proc.wait()
    assert S.adopt(_job(jid, proc.pid), lambda j, **kw: None) is False
    assert S.adopt(_job("none", None), lambda j, **kw: None) is False


def test_killing_a_taken_back_process_marks_the_job_interrupted(tmp_path):
    jid = "adopt4"
    proc = _start(jid, tmp_path, "print('[1] /x.pdf', flush=True)\ntime.sleep(60)", write_exit=False)
    updates = []
    assert S.adopt(_job(jid, proc.pid), lambda j, **kw: updates.append(kw)) is True
    time.sleep(1.0)
    S._kill_tree(proc)                                                 # killed from outside: no exit file is written
    assert _wait(lambda: any(u.get("status") == "interrupted" for u in updates))
    assert not any(u.get("status") == "error" for u in updates)


def test_a_run_started_by_this_server_survives_it_stopping_to_supervise(tmp_path):
    """The point of the whole thing: the process does not depend on its supervisor."""
    jid = "survive"
    proc = _start(jid, tmp_path, "time.sleep(3)\nprint('{}', flush=True)")
    assert proc.poll() is None and S.pid_alive(proc.pid)
    # no supervisor at all is watching it, and it still runs to its end and records its exit code
    assert _wait(lambda: S._read_exit(jid) == 0)


def test_startup_takes_back_running_syncs_and_marks_the_rest(tmp_path, monkeypatch):
    from app import main as M
    from app.jobs.queue import queue
    monkeypatch.setitem(M._OWNED, "ok", True)
    live = _start("up1", tmp_path, "time.sleep(2)\nprint('{}', flush=True)")
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    con = db.trust_rw()
    rows = [("up1", "dropbox_sync", json.dumps({"source_link": SRC}), "running", live.pid),
            ("up2", "dropbox_sync", json.dumps({"source_link": SRC}), "running", gone.pid),
            ("up3", "parse", "", "running", None),
            ("up4", "dropbox_sync", json.dumps({"source_link": SRC}), "queued", None)]
    for jid, kind, rel, status, pid in rows:
        con.execute("INSERT INTO job(id,kind,rel,status,progress,created_at,updated_at,pid) VALUES(?,?,?,?,?,?,?,?)",
                    (jid, kind, rel, status, 0, 1.0, 1.0, pid))
    con.commit()
    con.close()
    M._reap_stale_jobs()
    st = {j: (queue.get(j) or {}).get("status") for j in ("up1", "up2", "up3", "up4")}
    assert st["up1"] == "running"                 # taken back
    assert st["up2"] == "interrupted"             # its process is gone
    assert st["up3"] == "error"                   # not a sync: nothing to take back
    assert st["up4"] == "queued"                  # waiting jobs are safe in the table and stay waiting
    assert _wait(lambda: (queue.get("up1") or {}).get("status") == "done")


def test_a_sync_without_its_resume_state_is_an_interrupted_run_not_an_error(tmp_path):
    with pytest.raises(Interrupted):
        S._finish({"id": "x1"}, {"source_link": SRC}, -1, "[1] /x.pdf\n", lambda *a: None)


# ------------------------------------------------------------------ a run cannot be ended by closing a window
import sys as _sys  # noqa: E402

import pytest as _pytest  # noqa: E402


@_pytest.mark.skipif(_sys.platform != "win32", reason="console windows are a Windows matter")
def test_a_run_gets_no_console_window_that_someone_could_close(tmp_path):
    """Regression: a venv python.exe is a launcher; with DETACHED_PROCESS the real interpreter got a visible console
    window, and closing it ended the run with 0xC000013A in the middle of OCR."""
    import os
    from app.jobs import sync_job as S
    out = tmp_path / "w.txt"
    code = "import ctypes; open(r'%s', 'w').write(str(ctypes.windll.kernel32.GetConsoleWindow()))" % out
    with open(os.devnull, "w") as fh:
        S._spawn([_sys.executable, "-c", code], dict(os.environ), fh).wait(timeout=60)
    assert out.read_text() == "0"


@_pytest.mark.parametrize("code", [0xC000013A, -1073741510])
def test_a_run_stopped_from_outside_is_reported_as_interrupted(code, tmp_path, monkeypatch):
    from app.jobs import sync_job as S
    monkeypatch.setattr(S, "summary_path", lambda jid: str(tmp_path / f"{jid}.json"))
    with _pytest.raises(S.Interrupted, match="start it again"):
        S._finish({"id": "jx"}, {"source_link": "/x"}, code, "OCR page 5/80\n", {})


def test_the_live_status_survives_windows_refusing_to_replace_a_file_being_read(monkeypatch, tmp_path):
    """Windows will not replace a file another process has open (the page reading the status). That error used to
    end the supervision while the run went on unseen; now the status is simply written again on the next change."""
    from app.jobs import sync_job as SJ
    monkeypatch.setattr(SJ, "LOG_DIR", str(tmp_path))

    def refuse(a, b):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(SJ.os, "replace", refuse)
    live = SJ.Live("j-refused")
    live.feed("[1] /a.pdf")
    live.write(force=True)                     # no exception
    monkeypatch.undo()
    monkeypatch.setattr(SJ, "LOG_DIR", str(tmp_path))
    live.write()                               # the next write goes through
    assert (tmp_path / "j-refused.live.json").exists()
