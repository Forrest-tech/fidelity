# -*- coding: utf-8 -*-
"""Dropbox sync from the web interface: runs exactly the command-line sync (`app.distill.sync`) as a
background job, streams its output to a log, and keeps the run summary. One code path for both."""
import json
import os
import re
import subprocess
import time
import sys

from .. import config, db
from .queue import Interrupted

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(config.DATA_DIR, "work", "sync-logs")
LINK_RE = re.compile(r"^https://(www\.)?dropbox\.com/\S+$")
PATH_RE = re.compile(r"^/[^\x00-\x1f]{0,500}$")      # a folder path in the connected Dropbox, e.g. /2025
_STEP = re.compile(r"^\[(\d+)\] ")
_TOTAL = re.compile(r"^files to check: (\d+)")
_RUN = re.compile(r"--rollback (\d{8}-\d{6})")


def log_path(jid):
    return os.path.join(LOG_DIR, f"{jid}.log")


def summary_path(jid):
    return os.path.join(LOG_DIR, f"{jid}.json")


def events_path(jid):
    return os.path.join(LOG_DIR, f"{jid}.events.jsonl")


def exit_path(jid):
    return os.path.join(LOG_DIR, f"{jid}.exit")


def room_dir(room_id):
    return os.path.join(config.DATA_DIR, "work", "rooms", room_id)


def command(p: dict, events: str | None = None) -> list:
    """The exact command line this job runs (also shown to the user)."""
    cmd = [sys.executable, "-m", "app.distill.sync", "--source-link", p["source_link"]]
    if p.get("dest_link"):                      # a "distill only" room has no output folder
        cmd += ["--dest-link", p["dest_link"]]
    if events:
        cmd += ["--events", events]
    if p.get("room_id"):
        cmd += ["--room-dir", room_dir(p["room_id"])]
    if p.get("live"):                           # the run keeps every file's step there itself
        cmd += ["--live", p["live"]]
    if (p.get("workers") or 1) > 1:
        cmd += ["--workers", str(int(p["workers"]))]
    if p.get("publish_from"):
        return cmd + ["--publish-from", p["publish_from"]]
    if p.get("rollback"):
        return cmd + ["--rollback", p["rollback"]]
    if p.get("dry_run"):
        cmd.append("--dry-run")
    if p.get("force"):
        cmd.append("--force")
    if p.get("only"):
        cmd += ["--only", p["only"]]
    return cmd


# Plain-language messages for the errors people actually hit; the full log stays available.
_EXPLAIN = [
    ("shared_link_not_found", "Dropbox cannot find one of the shared links (it may have been removed or replaced). "
                              "Easier: for a folder in your own Dropbox, paste the address from the Dropbox website "
                              "(https://www.dropbox.com/home/...) or type its path, e.g. /AS 3500."),
    ("not_found", "Dropbox cannot find that folder. Check the path (e.g. /AS 3500) or paste the address from the "
                  "Dropbox website (https://www.dropbox.com/home/...)."),
    ("missing_scope", "This machine's Dropbox access lacks a permission. Re-authorise it (runbook: Dropbox access)."),
    ("No Dropbox credentials", "Dropbox access is not set up on this machine (runbook: Dropbox access)."),
    ("must be a folder in your own Dropbox", "The output link must point to a folder in your own Dropbox."),
    ("not enough free disk space", "This machine ran out of disk space for the work files. Free some space "
                                   "(or move the work folder to a bigger disk) and run it again; files already "
                                   "checked are skipped."),
    ("No space left on device", "This machine ran out of disk space. Free some space and run it again."),
    ("overlap", "The source and output folders overlap. Choose an output folder outside the source folder."),
    ("expired_access_token", "The Dropbox authorisation has expired. Re-authorise it (runbook: Dropbox access)."),
    ("invalid_access_token", "The Dropbox authorisation is no longer valid. Re-authorise it (runbook: Dropbox access)."),
]


def explain(text: str):
    for key, msg in _EXPLAIN:
        if key in text:
            return msg
    return None


_ERRLINE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Exit)\b.*")


def failure_message(text: str, code) -> str:
    """One readable line for a failed run: a plain explanation when we have one, else the actual
    exception line (not just the last line printed, which is often progress such as "OCR page 5")."""
    if msg := explain(text):
        return msg
    rows = [l.strip() for l in text.splitlines() if l.strip()]
    errs = [l for l in rows if _ERRLINE.match(l)]
    line = (errs or rows or ["no output"])[-1]
    return f"sync failed (exit {code}): {line[:300]}"


def live_path(jid):
    return os.path.join(LOG_DIR, f"{jid}.live.json")


_DOC = re.compile(r"^\[(\d+)\] (.+)$")
_OCR = re.compile(r"^OCR page (\d+)/(\d+|\?)")
_VERDICT = re.compile(r"^verification: (\w+)")


class Live:
    """Turns the sync's output into a status the page can show: where it is, how far, results so far."""

    def __init__(self, jid, now=time.time):
        self.jid, self.now = jid, now
        self.state = {"started": now(), "updated": now(), "total": 0, "index": 0, "file": "", "stage": "starting",
                      "page": 0, "pages": 0, "scan": False, "counts": {}, "skipped": 0}
        self._written = 0.0

    def feed(self, line: str):
        st, s = self.state, line.strip()
        if not s:
            return
        st["updated"] = self.now()
        if m := _TOTAL.match(s):
            st["total"], st["stage"] = int(m.group(1)), "listing"
        elif m := _DOC.match(s):
            st.update(index=int(m.group(1)), file=m.group(2)[-200:], stage="preparing", page=0, pages=0, scan=False)
        elif s.startswith("download"):
            st["stage"] = "downloading"
        elif s.startswith("scanned document"):
            st["scan"], st["stage"] = True, "ocr"
        elif m := _OCR.match(s):
            st.update(stage="ocr", page=int(m.group(1)), pages=int(m.group(2)) if m.group(2).isdigit() else 0, scan=True)
        elif s.startswith("extracted"):
            st["stage"] = "verifying"
        elif m := _VERDICT.match(s):
            v = m.group(1)
            st["counts"][v] = st["counts"].get(v, 0) + 1
            st["stage"] = "uploading" if v in ("PASS", "METADATA") else "next"
        elif s.startswith(("unchanged since last run", "skip duplicate", "skip (format")):
            st["skipped"] += 1
        elif s.startswith("promoted"):
            st["stage"] = "publishing"

    def percent(self) -> float:
        st = self.state
        if not st["total"]:
            return 3.0
        within = st["page"] / st["pages"] if st["pages"] else 0.0
        done = max(st["index"] - 1, 0) + within
        return round(min(5 + 90 * (done + st["skipped"]) / st["total"], 98), 1)

    def _key(self):
        st = self.state
        return (st["stage"], st["index"], st["page"], st["total"], st["skipped"], sum(st["counts"].values()))

    def write(self, force=False):
        # Throttled for chatty output, but a change of stage/file/page is always written at once —
        # otherwise the page can show an old step for as long as the next step stays quiet.
        key = self._key()
        if force or key != getattr(self, "_last_key", None) or self.now() - self._written >= 1.0:
            self._written, self._last_key = self.now(), key
            tmp = live_path(self.jid) + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.state, f)
                os.replace(tmp, live_path(self.jid))
            except OSError:
                # Windows refuses to replace a file another process has open (the page reading it): that crashed the
                # supervisor and left the run going unseen. The status is written again on the next change.
                self._last_key = None


# ------------------------------------------------------------------ running, supervising, cancelling
# The sync runs as its own process, detached from the web server: it writes its log to a file and its exit code to
# another, so restarting the web server does not stop a run that may take hours. The server notes the process id and
# a heartbeat in the job row; after a restart it takes a still-running process back (adopt) or, when the process is
# gone, marks the run "interrupted" so the person can simply start it again and it carries on.
_procs: dict = {}
_cancelled: set = set()


def pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return bool(ok) and code.value == 259               # STILL_ACTIVE
        try:                                                    # our own child that has ended stays a zombie until reaped
            done, _ = os.waitpid(int(pid), os.WNOHANG)
            if done:
                return False
        except OSError:                                         # not our child: the normal case after a server restart
            pass
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _read_exit(jid):
    try:
        with open(exit_path(jid), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


class _Adopted:
    """A run started by an earlier web-server process that is still going (or has just ended)."""

    def __init__(self, pid, jid):
        self.pid, self.jid = pid, jid

    def poll(self):
        if pid_alive(self.pid):
            return None
        code = _read_exit(self.jid)
        return code if code is not None else -1                 # -1: it ended without saying how


def _kill_tree(proc):
    """Stop the sync and everything it started (a venv python.exe on Windows is a launcher + child)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass


def cancel(jid) -> bool:
    proc = _procs.get(jid)
    if not proc or proc.poll() is not None:
        return False
    _cancelled.add(jid)
    _kill_tree(proc)
    return True


def _spawn(cmd, env, log_fh):
    kw = dict(cwd=BACKEND, env=env, stdin=subprocess.DEVNULL, stdout=log_fh, stderr=subprocess.STDOUT)
    if os.name == "nt":
        # A console without a window, not DETACHED_PROCESS: a venv's python.exe is a launcher that starts the real
        # interpreter as a child, and a console program started from a process without a console gets a console WINDOW
        # of its own. Closing that window (or logging off) ended runs with 0xC000013A. With CREATE_NO_WINDOW the run and
        # its children share one hidden console that nobody can close, and the new process group keeps the server's
        # Ctrl+C away from it.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:                                                   # also leave a job object that would end it with the server
            return subprocess.Popen(cmd, creationflags=flags | 0x01000000, **kw)     # CREATE_BREAKAWAY_FROM_JOB
        except OSError:
            return subprocess.Popen(cmd, creationflags=flags, **kw)
    return subprocess.Popen(cmd, start_new_session=True, **kw)


def _db_note(sql, args):
    """Heartbeat and process id are bookkeeping: failing to write them must never stop a run."""
    def _do():
        con = db.trust_rw()
        try:
            con.execute(sql, args)
            con.commit()
        finally:
            con.close()
    try:
        db.trust_write(_do, retries=2)
    except Exception:                                          # noqa: BLE001
        pass


def _supervise(job, proc, p, report):
    """Follow the run until its process ends: feed the log to the live status, keep the room's file rows up to
    date from the event file, write a heartbeat. Returns (exit code, log text)."""
    jid = job["id"]
    reader = None
    if p.get("room_id"):
        from . import rooms
        reader = rooms.EventReader(p["room_id"], jid, events_path(jid))
    live = Live(jid)
    own = not p.get("room_id")                 # a room's run writes its own live status, file by file
    if own:
        live.write(force=True)
    lines, pos, last_poll, last_beat = [], 0, 0.0, 0.0

    def percent():
        if own:
            return live.percent()
        return run_percent(jid)

    def feed(final=False):
        nonlocal pos
        try:
            with open(log_path(jid), "rb") as f:
                f.seek(pos)
                data = f.read()
        except OSError:
            return
        end = len(data) if final else data.rfind(b"\n") + 1
        if end <= 0:
            return
        pos += end
        for line in data[:end].decode("utf-8", "replace").splitlines(keepends=True):
            lines.append(line)
            live.feed(line)
            if own:
                live.write()
            if line.strip():
                report(percent(), line.strip()[:160])

    def guarded(fn, what):
        """Bookkeeping (log, live status, file rows) must never end the supervision of a run that is still going:
        an error here used to mark the job failed while its process went on, unseen, beside the next run."""
        try:
            fn()
        except Exception as e:                                 # noqa: BLE001
            print(f"[supervise {jid}] {what} failed, carrying on: {type(e).__name__}: {e}", flush=True)

    try:
        while True:
            guarded(feed, "reading the log")
            now = time.time()
            if reader and now - last_poll >= 1.0:
                guarded(reader.poll, "reading the events")
                last_poll = now
            if now - last_beat >= 5.0:
                _db_note("UPDATE job SET heartbeat_at=? WHERE id=?", (now, jid))
                last_beat = now
            code = proc.poll()
            if code is not None:
                break
            time.sleep(0.4)
        feed(final=True)
    finally:
        _procs.pop(jid, None)
        if reader:
            reader.poll()                                      # the last events, also when the run ended early
            try:
                rooms.end_activity(p["room_id"])
            except Exception:                                  # noqa: BLE001 - bookkeeping must never fail the job
                pass
    if own:
        live.state["stage"] = "finished"
        live.write(force=True)
    else:
        end_live(jid)                          # also when the run was stopped mid-file: nothing shows as busy
    return code, "".join(lines)


def write_known(room_id):
    """Tell the run which files of the room already have a result on the web side (see sync._known)."""
    def _rows():
        con = db.trust_rw()
        try:
            # a file that failed on a dropped connection or a download has no result: the next run must read it again
            # (it was skipped as "unchanged" and stayed failed for good)
            return [r[0] for r in con.execute(
                "SELECT rel FROM room_file WHERE room_id=? AND outcome IS NOT NULL "
                "AND NOT (outcome='unprocessable' AND COALESCE(reason,'') IN ('download','network'))", (room_id,))]
        finally:
            con.close()
    try:
        d = room_dir(room_id)
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, "known.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_rows(), f, ensure_ascii=False)
        os.replace(tmp, os.path.join(d, "known.json"))
    except Exception:                                          # noqa: BLE001 - without it the run skips as before
        pass


def _read_live(jid):
    try:
        with open(live_path(jid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def run_percent(jid) -> float:
    """How far a room's run is, from its own live status: files done, plus the part of each file being read."""
    st = _read_live(jid)
    if not st or not st.get("total"):
        return 3.0
    part = 0.0
    for a in (st.get("active") or {}).values():
        if a.get("pages"):
            part += min(1.0, (a.get("page") or 0) / a["pages"]) * 0.9
        elif a.get("stage") == "checking":
            part += 0.9
    done = (st.get("done") or 0) + (st.get("skipped") or 0) + part
    return round(min(5 + 90 * done / st["total"], 98), 1)


def end_live(jid):
    st = _read_live(jid)
    if not st or st.get("stage") == "finished":
        return
    st.update(stage="finished", active={}, queued=[], updated=time.time())
    tmp = live_path(jid) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, live_path(jid))
    except OSError:
        pass


def _finish(job, p, code, text, report):
    """Turn the end of a run into the job's result (or its error)."""
    jid = job["id"]
    if jid in _cancelled:
        _cancelled.discard(jid)
        raise RuntimeError("cancelled by the user")
    if code == -1 and _read_exit(jid) is None and not text.rstrip().endswith("}"):
        raise Interrupted("the run was stopped before it finished (the server or machine restarted); "
                          "start it again and it carries on with the files not done yet")
    if code in (0xC000013A, -1073741510, -2, 130):           # Ctrl+C / its window closed / logged off (Windows); SIGINT
        raise Interrupted("the run was stopped from outside before it finished (Ctrl+C, a closed window or a log-off); "
                          "start it again and it carries on with the files not done yet")
    summary = {"params": {k: v for k, v in p.items()}, "exit_code": code}
    start = text.rfind("\n{")
    if start >= 0:
        try:
            summary["report"] = json.loads(text[start + 1:])
        except ValueError:
            pass
    if m := _RUN.search(text):
        summary["published_run"] = m.group(1)
    with open(summary_path(jid), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    if code == 2:
        raise RuntimeError("source folder changed during the run — stopped (see log)")
    if code != 0:
        raise RuntimeError(failure_message(text, code))
    report(99, "rolled back" if p.get("rollback") else ("dry run complete" if p.get("dry_run") else "published"))
    return summary


def handle_sync(job, report):
    p = json.loads(job["rel"])
    os.makedirs(LOG_DIR, exist_ok=True)
    jid = job["id"]
    # backslashreplace: PyMuPDF prints warnings that can hold stray surrogate characters from a
    # damaged PDF; with strict UTF-8 that print raised inside MuPDF and failed the whole file.
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8:backslashreplace", FIDELITY_EXIT_FILE=exit_path(jid))
    report(1, "starting")
    try:
        os.remove(exit_path(jid))
    except OSError:
        pass
    if p.get("room_id"):
        p = dict(p, live=live_path(jid))
        if not p.get("publish_from"):
            write_known(p["room_id"])
        if p.get("parallel"):                   # the capacity points the queue gave this run (text file 1, scan 2)
            p["workers"] = max(1, int(job.get("points") or 1))
    cmd = command(p, events_path(jid)) if p.get("room_id") else command(p)
    with open(log_path(jid), "wb") as log:
        proc = _spawn(cmd, env, log)
    _procs[jid] = proc
    _db_note("UPDATE job SET pid=?, heartbeat_at=? WHERE id=?", (proc.pid, time.time(), jid))
    try:
        code, text = _supervise(job, proc, p, report)
    except BaseException:
        # never leave a run going that nobody follows: the next run of the room would work beside it
        _kill_tree(proc)
        raise
    return _finish(job, p, code, text, report)


def adopt(job, update) -> bool:
    """After a web-server restart: take back a run whose process is still going, or finish the job from what the
    process left behind. False means nothing can be recovered (the caller marks the job interrupted)."""
    jid, pid = job["id"], job.get("pid")
    try:
        p = json.loads(job.get("rel") or "{}")
    except ValueError:
        return False
    if not p.get("source_link"):
        return False
    proc = _Adopted(pid, jid)
    if not pid or (proc.poll() is not None and _read_exit(jid) is None):
        return False

    def run():
        _procs[jid] = proc
        report = lambda pr, m="": update(jid, progress=pr, message=m)       # noqa: E731
        try:
            code, text = _supervise(job, proc, p, report)
            _finish(job, p, code, text, report)
            update(jid, status="done", progress=100.0, message="完成")
        except Interrupted as e:
            update(jid, status="interrupted", message=str(e)[:500])
        except Exception as e:                                              # noqa: BLE001
            update(jid, status="error", message=str(e)[:500])
    import threading
    threading.Thread(target=run, daemon=True, name=f"adopt-{jid}").start()
    return True
