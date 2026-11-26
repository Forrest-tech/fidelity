"""Pack this server's state so another Fidelity (e.g. the Mac in Docker) continues where this one is.

    python scripts/migrate_export.py [--out FILE.zip]

What goes in: the sign-in secret and user accounts, the job/room database (rooms, which files were distilled, spot
checks, notifications), the rooms' results, the Dropbox / Google connections, AI and e-mail settings, the human-check
settings, the glossary, and the publish records with release notes (so `--rollback <run>` still works there).
What stays out: caches, downloaded source PDFs, logs, old work folders and the OCR models (the container fetches them).

The package holds secrets (Dropbox tokens, the AI key file, the SMTP password, the sign-in secret): copy it by USB,
AirDrop or a local network share, never by e-mail, and delete it once imported. The SQLite files are copied with
SQLite's own backup call, so a running server is safe to export from."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import zipfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
from app import config  # noqa: E402

APPDATA = config.DATA_DIR                                          # backend/data  -> /app/backend/data
DATA = os.path.abspath(os.path.join(config.BASE_DIR, "..", "data"))  # data          -> /app/data

# (area, path relative to that area) — a missing file is simply not packed
FILES = [
    ("appdata", "secret.key"), ("appdata", "fidelity.db"), ("appdata", "trust.db"),
    ("appdata", "ai_keys.json"), ("appdata", "ai_secret.key"), ("appdata", "ai_settings.json"),
    ("appdata", "app_settings.json"), ("appdata", "email_settings.json"), ("appdata", "captcha_settings.json"),
    ("appdata", "config.json"),
    ("data", "dropbox_auth.json"), ("data", "google_auth.json"), ("data", "glossary.json"),
    ("data", "ocr_selection.json"), ("data", "formula_approvals.json"),
    ("data", "work/ledger.json"),
]
TREES = [("appdata", "licence"), ("appdata", "work/rooms"), ("data", "work/releases"), ("data", "work/publish")]


LONG = "\\\\?\\"


def _long(p: str) -> str:
    """Windows refuses paths over 260 characters unless they carry the long-path prefix (room results are deep)."""
    p = os.path.abspath(p)
    return LONG + p if os.name == "nt" and not p.startswith(LONG) else p


def _root(area: str) -> str:
    return APPDATA if area == "appdata" else DATA


def _sqlite_copy(src: str) -> str:
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    a, b = sqlite3.connect(src), sqlite3.connect(tmp)
    with b:
        a.backup(b)
    a.close()
    b.close()
    return tmp


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def entries():
    for area, rel in FILES:
        p = os.path.join(_root(area), *rel.split("/"))
        if os.path.isfile(p):
            yield area, rel, p
    for area, rel in TREES:
        base = os.path.join(_root(area), *rel.split("/"))
        for d, _, fs in os.walk(_long(base)):
            for f in fs:
                p = os.path.join(d, f)
                plain = p[len(LONG):] if p.startswith(LONG) else p
                yield area, os.path.relpath(plain, _root(area)).replace(os.sep, "/"), p


def export(out: str) -> dict:
    manifest = {"made": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "from": "fidelity",
                "files": []}
    tmps = []
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for area, rel, path in entries():
                src = _sqlite_copy(path) if rel.endswith(".db") else path
                if src != path:
                    tmps.append(src)
                name = f"{area}/{rel}"
                z.write(src, name)
                manifest["files"].append({"name": name, "sha256": _sha(src), "size": os.path.getsize(src)})
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    finally:
        for t in tmps:
            os.remove(t)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    ap.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "Desktop", f"fidelity-migration-{stamp}.zip"))
    a = ap.parse_args(argv)
    m = export(a.out)
    total = sum(f["size"] for f in m["files"])
    print(f"{len(m['files'])} files, {total / 1e6:.1f} MB -> {a.out}")
    print("It holds secrets: copy it by USB / AirDrop / local share, never by e-mail; delete it after importing.")


if __name__ == "__main__":
    main()
