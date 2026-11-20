# -*- coding: utf-8 -*-
"""Dropbox sync from the web interface: runs exactly the command-line sync (`app.distill.sync`) as a
background job, streams its output to a log, and keeps the run summary. One code path for both."""
import json
import os
import re
import subprocess
import time
import sys

from .. import config

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


def command(p: dict) -> list:
    """The exact command line this job runs (also shown to the user)."""
    cmd = [sys.executable, "-m", "app.distill.sync", "--source-link", p["source_link"], "--dest-link", p["dest_link"]]
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
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f)
            os.replace(tmp, live_path(self.jid))


# ------------------------------------------------------------------ cancelling
_procs: dict = {}
_cancelled: set = set()


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


def handle_sync(job, report):
    p = json.loads(job["rel"])
    os.makedirs(LOG_DIR, exist_ok=True)
    # backslashreplace: PyMuPDF prints warnings that can hold stray surrogate characters from a
    # damaged PDF; with strict UTF-8 that print raised inside MuPDF and failed the whole file.
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8:backslashreplace")
    report(1, "starting")
    lines = []
    live = Live(job["id"])
    live.write(force=True)
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with open(log_path(job["id"]), "w", encoding="utf-8") as log:
        proc = subprocess.Popen(command(p), cwd=BACKEND, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **group)
        _procs[job["id"]] = proc
        try:
            for line in proc.stdout:
                log.write(line)
                log.flush()
                lines.append(line)
                live.feed(line)
                live.write()
                if line.strip():
                    report(live.percent(), line.strip()[:160])
            code = proc.wait()
        finally:
            _procs.pop(job["id"], None)
    live.state["stage"] = "finished"
    live.write(force=True)
    if job["id"] in _cancelled:
        _cancelled.discard(job["id"])
        raise RuntimeError("cancelled by the user")
    text = "".join(lines)
    summary = {"params": {k: v for k, v in p.items()}, "exit_code": code}
    start = text.rfind("\n{")
    if start >= 0:
        try:
            summary["report"] = json.loads(text[start + 1:])
        except ValueError:
            pass
    if m := _RUN.search(text):
        summary["published_run"] = m.group(1)
    with open(summary_path(job["id"]), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    if code == 2:
        raise RuntimeError("source folder changed during the run — stopped (see log)")
    if code != 0:
        raise RuntimeError(failure_message(text, code))
    report(99, "rolled back" if p.get("rollback") else ("dry run complete" if p.get("dry_run") else "published"))
    return summary
