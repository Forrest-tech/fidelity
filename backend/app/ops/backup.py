"""Daily backups that are proven by restoring them (requirements v2, S-6).

What is kept (everything that cannot be rebuilt by running the rooms again in minutes):
  databases   backend/data/trust.db (rooms, files, jobs, audit), backend/data/fidelity.db (people and roles) —
              copied with SQLite's online backup, so a copy taken while the server writes is consistent;
  settings    backend/data/*.json, secret.key, licence/; data/dropbox_auth.json, data/glossary.json;
  results     backend/data/work/rooms/ (distilled results: hours of OCR to make again), data/work/ledger.json,
              data/work/publish/ (what each publish run changed: needed for --rollback), data/work/audit/.
Not kept: caches and downloaded sources (rebuilt on the next run), logs.

Each backup is one zip in data/backups, verified right after it is written: every database in it is restored to a
temporary file and must pass PRAGMA integrity_check with the same tables; every other file's SHA-256 is checked.
Fourteen are kept. FIDELITY_BACKUP_COPY_DIR (a synced folder on another disk or cloud) gets a copy of each.
The zip holds the Dropbox and AI keys: it stays on this machine or in a folder only administrators can open.
"""
from __future__ import annotations

import datetime as _dt
import glob
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile

from .. import config

BACKEND_DATA = config.DATA_DIR
ROOT_DATA = os.path.abspath(os.path.join(config.BASE_DIR, "..", "data"))
BACKUP_DIR = os.environ.get("FIDELITY_BACKUP_DIR") or os.path.join(ROOT_DATA, "backups")
KEEP = int(os.environ.get("FIDELITY_BACKUP_KEEP", "14"))
EVERY_S = 24 * 3600
STATUS = "latest.json"

DATABASES = ("trust.db", "fidelity.db")
FILES = ((BACKEND_DATA, ("*.json", "secret.key", "licence/**/*", "work/rooms/**/*")),
         (ROOT_DATA, ("dropbox_auth.json", "glossary.json", "work/ledger.json", "work/publish/**/*", "work/audit/**/*")))


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tables(path: str) -> list[str]:
    con = sqlite3.connect(path)
    try:
        return sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    finally:
        con.close()


def _copy_db(src: str, dst: str):
    s = sqlite3.connect(src)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)                                  # consistent even while the server writes
    finally:
        d.close()
        s.close()


def _files() -> list[tuple[str, str]]:
    """(absolute path, name inside the zip) for every file to keep."""
    out = []
    for base, patterns in FILES:
        tag = "backend-data" if base == BACKEND_DATA else "data"
        for pat in patterns:
            for p in glob.glob(os.path.join(base, pat), recursive=True):
                if os.path.isfile(p) and not p.endswith((".lock", ".tmp")):
                    out.append((p, f"{tag}/" + os.path.relpath(p, base).replace(os.sep, "/")))
    return sorted(set(out))


def make(dest_dir: str = BACKUP_DIR, now: float | None = None) -> dict:
    """Write one backup, verify it, prune old ones, copy it off this disk when configured. Returns its record."""
    os.makedirs(dest_dir, exist_ok=True)
    stamp = _dt.datetime.fromtimestamp(now or time.time()).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(dest_dir, f"fidelity-{stamp}.zip")
    manifest = {"created": stamp, "databases": {}, "files": {}}
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(path + ".part", "w", zipfile.ZIP_DEFLATED) as z:
        for name in DATABASES:
            src = os.path.join(BACKEND_DATA, name)
            if not os.path.exists(src):
                continue
            copy = os.path.join(tmp, name)
            _copy_db(src, copy)
            z.write(copy, f"databases/{name}")
            manifest["databases"][name] = {"sha256": _sha(copy), "tables": _tables(copy)}
        for p, arc in _files():
            try:
                z.write(p, arc)
                manifest["files"][arc] = _sha(p)
            except OSError:                          # a file that vanished meanwhile (a room deleted): skipped
                continue
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    os.replace(path + ".part", path)
    result = verify(path)
    record = {"path": path, "created": stamp, "at": now or time.time(), "size": os.path.getsize(path),
              "databases": list(manifest["databases"]), "files": len(manifest["files"]), **result}
    copied = os.environ.get("FIDELITY_BACKUP_COPY_DIR")
    if copied and result["ok"]:
        try:
            os.makedirs(copied, exist_ok=True)
            shutil.copy2(path, os.path.join(copied, os.path.basename(path)))
            record["copied_to"] = copied
        except OSError as e:
            record["copy_error"] = str(e)[:200]
    prune(dest_dir)
    with open(os.path.join(dest_dir, STATUS), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1)
    return record


def verify(path: str) -> dict:
    """Restore every database in the zip to a temporary file and check it; check every other file's hash."""
    problems = []
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
        manifest = json.loads(z.read("manifest.json"))
        for name, info in manifest["databases"].items():
            out = z.extract(f"databases/{name}", tmp)
            con = sqlite3.connect(out)
            try:
                ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                con.close()
            if ok != "ok":
                problems.append(f"{name}: integrity_check says {ok}")
            if _tables(out) != info["tables"]:
                problems.append(f"{name}: tables differ after restore")
            if _sha(out) != info["sha256"]:
                problems.append(f"{name}: content differs after restore")
        for arc, digest in manifest["files"].items():
            if hashlib.sha256(z.read(arc)).hexdigest() != digest:
                problems.append(f"{arc}: content differs")
    return {"ok": not problems, "problems": problems[:20], "verified_at": time.time()}


def prune(dest_dir: str = BACKUP_DIR, keep: int = KEEP):
    zips = sorted(glob.glob(os.path.join(dest_dir, "fidelity-*.zip")))
    for old in zips[:-keep] if keep > 0 else []:
        try:
            os.remove(old)
        except OSError:
            pass


def restore_to(path: str, target: str) -> list[str]:
    """Unpack a backup into `target` (an empty folder) for inspection or to put back by hand with the server
    stopped (docs/runbook). Returns the files written."""
    os.makedirs(target, exist_ok=True)
    if os.listdir(target):
        raise FileExistsError(f"{target} is not empty")
    with zipfile.ZipFile(path) as z:
        z.extractall(_long(target))       # room folders nest deep: past Windows' 260-character limit
        return z.namelist()


def _long(path: str) -> str:
    """Windows' extended-length form, which lifts the 260-character path limit; unchanged elsewhere."""
    path = os.path.abspath(path)
    if os.name != "nt" or path.startswith("\\\\?\\"):
        return path
    return "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path


def status(dest_dir: str = BACKUP_DIR) -> dict | None:
    try:
        with open(os.path.join(dest_dir, STATUS), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _loop(stop: threading.Event):
    while not stop.wait(60):
        st = status()
        if st is None or time.time() - st.get("at", 0) >= EVERY_S:
            try:
                rec = make()
                print(f"[backup] {os.path.basename(rec['path'])} {'verified' if rec['ok'] else 'FAILED: ' + '; '.join(rec['problems'])}",
                      flush=True)
            except Exception as e:                  # noqa: BLE001 - the health page and the bell report a missing backup
                print(f"[backup] failed: {type(e).__name__}: {e}", flush=True)
                with open(os.path.join(BACKUP_DIR, STATUS), "w", encoding="utf-8") as f:
                    json.dump({**(st or {}), "ok": False, "problems": [f"{type(e).__name__}: {e}"[:300]],
                               "failed_at": time.time()}, f)
        stop.wait(3600)


_STOP = threading.Event()


def start():
    """Run backups in the background: one when none was made in the last 24 hours, checked hourly."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    threading.Thread(target=_loop, args=(_STOP,), daemon=True, name="backup").start()
