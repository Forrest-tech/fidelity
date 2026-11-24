"""How the system is doing, in one place (requirements v2, S-1 and S-5).

`report()` feeds the System page, `metrics()` a Prometheus scrape, `alerts()` the notification bell. Every figure is
measured, not assumed: free disk and memory now, the share of room runs that ended in failure over the last 7 days,
the age and verification of the last backup, what the queue holds, which version is running.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from .. import config, db
from . import backup as BK

STARTED = time.time()
DISK_WARN, DISK_BAD = 3 * 1024 ** 3, 1.5 * 1024 ** 3
MEM_WARN = 500 * 1024 ** 2
BACKUP_MAX_AGE = 36 * 3600
FAIL_RATE_WARN, FAIL_MIN = 0.05, 2   # requirements v3 S-2: <= 5 % of runs fail, four weeks rolling


def _version() -> str:
    try:
        root = os.path.dirname(config.BASE_DIR)
        return subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=5).stdout.strip() or "unknown"
    except Exception:                                    # noqa: BLE001
        return "unknown"


_VERSION = None


def version() -> str:
    global _VERSION
    if _VERSION is None:
        _VERSION = _version()
    return _VERSION


def _runs(days: int = 28) -> dict:
    since = time.time() - days * 86400
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT status, COUNT(*) n FROM job WHERE kind='dropbox_sync' AND updated_at>=? "
                           "AND status IN ('done','error','interrupted') GROUP BY status", (since,)).fetchall()
        q = con.execute("SELECT status, COUNT(*) n FROM job WHERE status IN ('queued','running') GROUP BY status").fetchall()
        last_fail = con.execute("SELECT id, room_id, message, updated_at FROM job WHERE kind='dropbox_sync' AND "
                                "status='error' ORDER BY updated_at DESC LIMIT 1").fetchone()
    finally:
        con.close()
    c = {r["status"]: r["n"] for r in rows}
    total = sum(c.values())
    failed = c.get("error", 0) + c.get("interrupted", 0)
    return {"days": days, "done": c.get("done", 0), "failed": c.get("error", 0), "interrupted": c.get("interrupted", 0),
            "total": total, "failure_rate": round(failed / total, 3) if total else 0.0,
            "queued": next((r["n"] for r in q if r["status"] == "queued"), 0),
            "running": next((r["n"] for r in q if r["status"] == "running"), 0),
            "last_failure": dict(last_fail) if last_fail else None}


def report() -> dict:
    from ..jobs import capacity
    du = shutil.disk_usage(config.DATA_DIR)
    mem = capacity.available_memory_bytes()
    bk = BK.status()
    out = {"version": version(), "uptime_s": int(time.time() - STARTED), "checked_at": time.time(),
           "disk": {"free": du.free, "total": du.total}, "memory": {"available": mem},
           "cpus": os.cpu_count() or 1, "runs": _runs(), "backup": bk}
    out["alerts"] = alerts(out)
    return out


def alerts(r: dict | None = None) -> list[dict]:
    """Problems an administrator must act on, worst first: {key, level, kind, …figures}."""
    r = r or report()
    out = []
    free = r["disk"]["free"]
    if free < DISK_WARN:
        out.append({"key": f"disk:{int(free // 1024 ** 3)}", "level": "bad" if free < DISK_BAD else "warn",
                    "kind": "disk", "free": free})
    mem = r["memory"]["available"]
    if mem is not None and 0 <= mem < MEM_WARN:
        out.append({"key": "memory", "level": "warn", "kind": "memory", "available": mem})
    bk = r["backup"]
    if not bk:
        out.append({"key": "backup:none", "level": "warn", "kind": "backup_none"})
    elif not bk.get("ok"):
        out.append({"key": f"backup:failed:{int(bk.get('failed_at') or bk.get('at') or 0)}", "level": "bad",
                    "kind": "backup_failed", "problem": (bk.get("problems") or [""])[0]})
    elif time.time() - bk.get("at", 0) > BACKUP_MAX_AGE:
        out.append({"key": f"backup:old:{bk.get('created')}", "level": "warn", "kind": "backup_old", "at": bk.get("at")})
    runs = r["runs"]
    failed = runs["failed"] + runs["interrupted"]
    if failed >= FAIL_MIN and runs["failure_rate"] >= FAIL_RATE_WARN:
        out.append({"key": f"runs:{failed}", "level": "warn", "kind": "runs_failing", "failed": failed,
                    "total": runs["total"], "rate": runs["failure_rate"]})
    credit = _ai_out_of_credit()
    if credit:
        out.append({"key": f"ai_credit:{credit}", "level": "bad", "kind": "ai_credit", "provider": credit})
    out.sort(key=lambda a: 0 if a["level"] == "bad" else 1)
    return out


def _ai_out_of_credit() -> str:
    """The provider of the latest AI call, when that call failed because the account has no credit (HTTP 402):
    every AI suggestion stops until someone tops it up, so say so instead of letting calls fail quietly."""
    try:
        con = db.trust_rw()
        try:
            r = con.execute("SELECT provider, status, message FROM ai_call WHERE status IN ('ok','error','invalid','cached') "
                            "ORDER BY created_at DESC LIMIT 1").fetchone()
        finally:
            con.close()
    except Exception:                                   # noqa: BLE001 - no AI table yet
        return ""
    return (r["provider"] or "AI") if r and r["status"] == "error" and "no credit" in (r["message"] or "") else ""


def metrics() -> str:
    """Prometheus text exposition (version 0.0.4); no client library needed for a handful of gauges."""
    r = report()
    bk = r["backup"] or {}
    g = [("fidelity_up", "1 while the server answers", 1),
         ("fidelity_uptime_seconds", "seconds since the server started", r["uptime_s"]),
         ("fidelity_disk_free_bytes", "free bytes on the data disk", r["disk"]["free"]),
         ("fidelity_memory_available_bytes", "available memory", r["memory"]["available"] if r["memory"]["available"] is not None else -1),
         ("fidelity_runs_total", "room runs that ended in the last 7 days", r["runs"]["total"]),
         ("fidelity_runs_failed", "room runs that failed or were interrupted in the last 28 days",
          r["runs"]["failed"] + r["runs"]["interrupted"]),
         ("fidelity_jobs_queued", "jobs waiting", r["runs"]["queued"]),
         ("fidelity_jobs_running", "jobs running", r["runs"]["running"]),
         ("fidelity_backup_age_seconds", "seconds since the last backup (-1: none)",
          int(time.time() - bk["at"]) if bk.get("at") else -1),
         ("fidelity_backup_verified", "1 when the last backup was restored and checked", 1 if bk.get("ok") else 0),
         ("fidelity_alerts", "open alerts", len(r["alerts"]))]
    lines = []
    for name, help_, value in g:
        lines += [f"# HELP {name} {help_}", f"# TYPE {name} gauge", f"{name} {value}"]
    return "\n".join(lines) + "\n"
