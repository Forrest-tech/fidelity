# -*- coding: utf-8 -*-
"""Dropbox sync from the web interface: runs exactly the command-line sync (`app.distill.sync`) as a
background job, streams its output to a log, and keeps the run summary. One code path for both."""
import json
import os
import re
import subprocess
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
    ("overlap", "The source and output folders overlap. Choose an output folder outside the source folder."),
    ("expired_access_token", "The Dropbox authorisation has expired. Re-authorise it (runbook: Dropbox access)."),
    ("invalid_access_token", "The Dropbox authorisation is no longer valid. Re-authorise it (runbook: Dropbox access)."),
]


def explain(text: str):
    for key, msg in _EXPLAIN:
        if key in text:
            return msg
    return None


def handle_sync(job, report):
    p = json.loads(job["rel"])
    os.makedirs(LOG_DIR, exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    report(1, "starting")
    total, done, lines = 0, 0, []
    with open(log_path(job["id"]), "w", encoding="utf-8") as log:
        proc = subprocess.Popen(command(p), cwd=BACKEND, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            log.write(line)
            log.flush()
            lines.append(line)
            s = line.strip()
            if m := _TOTAL.match(s):
                total = int(m.group(1))
            elif m := _STEP.match(s):
                done = int(m.group(1))
            if s:
                pct = 5 + (85 * done / total if total else 0)
                report(round(min(pct, 95), 1), s[:160])
        code = proc.wait()
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
        tail = [l.strip() for l in lines if l.strip()][-1:] or ["no output"]
        raise RuntimeError(explain(text) or f"sync failed (exit {code}): {tail[0][:300]}")
    report(99, "rolled back" if p.get("rollback") else ("dry run complete" if p.get("dry_run") else "published"))
    return summary
