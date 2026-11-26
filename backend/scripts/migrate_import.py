"""Load a package made by migrate_export.py into this Fidelity (run inside the container, then restart it).

    python scripts/migrate_import.py /tmp/fidelity-migration.zip

Every file is checked against the package's own SHA-256 list before anything is written. What it replaces is first
saved to <data>/backups/pre-import-<time>.zip, so an import can be undone by importing that file. User accounts come
from the package: an administrator made on this machine before the import is replaced by the old server's accounts."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import zipfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
from app import config  # noqa: E402

ROOTS = {"appdata": config.DATA_DIR, "data": os.path.abspath(os.path.join(config.BASE_DIR, "..", "data"))}


def _target(name: str) -> str:
    area, _, rel = name.partition("/")
    if area not in ROOTS or not rel or ".." in rel.split("/") or rel.startswith("/"):
        raise SystemExit(f"refusing an entry outside the data folders: {name}")
    return os.path.join(ROOTS[area], *rel.split("/"))


def load(package: str) -> dict:
    with zipfile.ZipFile(package) as z:
        manifest = json.loads(z.read("manifest.json"))
        for f in manifest["files"]:                     # check everything first: nothing is written from a bad package
            if hashlib.sha256(z.read(f["name"])).hexdigest() != f["sha256"]:
                raise SystemExit(f"package damaged: {f['name']} does not match its checksum; nothing was changed")
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = os.path.join(ROOTS["data"], "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup = os.path.join(backup_dir, f"pre-import-{stamp}.zip")
        kept = []
        with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as b:
            for f in manifest["files"]:
                t = _target(f["name"])
                if os.path.isfile(t):
                    b.write(t, f["name"])
                    kept.append({"name": f["name"], "sha256": hashlib.sha256(open(t, "rb").read()).hexdigest(),
                                 "size": os.path.getsize(t)})
            b.writestr("manifest.json", json.dumps({"made": stamp, "from": "pre-import", "files": kept}))
        for f in manifest["files"]:
            t = _target(f["name"])
            os.makedirs(os.path.dirname(t), exist_ok=True)
            tmp = t + ".importing"
            with open(tmp, "wb") as out:
                out.write(z.read(f["name"]))
            os.replace(tmp, t)
            for side in ("-wal", "-shm"):               # a fresh SQLite file must not meet the old one's journal
                if t.endswith(".db") and os.path.exists(t + side):
                    os.remove(t + side)
    return {"files": len(manifest["files"]), "made": manifest.get("made"), "backup": backup}


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        raise SystemExit(__doc__)
    r = load(args[0])
    print(f"imported {r['files']} files from the package made {r['made']}; what they replaced is in {r['backup']}")
    print("Restart the service now (docker compose restart).")


if __name__ == "__main__":
    main()
