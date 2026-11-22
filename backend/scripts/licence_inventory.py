# -*- coding: utf-8 -*-
"""Licence inventory of a room's source files (requirement IR-5, Phase A).

Reads the vendor's licence stamp from each file's distilled text (see app/distill/licence.py) and writes:
  - a full CSV, licensee names included, to data/licence/<room>.csv (stays on this machine: data/ is not in git);
  - a summary on stdout with personal names withheld, fit for docs/licence/INVENTORY.md.

Usage (from backend/):  python scripts/licence_inventory.py [room_id]
"""
from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.distill import licence as L  # noqa: E402
from app.distill import run as RN  # noqa: E402
from app.jobs import rooms as R  # noqa: E402
from app.jobs import sync_job as SJ  # noqa: E402


def _text(base: str, out_dir: str) -> str:
    p = RN.longpath(os.path.join(base, out_dir))
    if os.path.isfile(p):
        files = [p]
    else:
        files = [os.path.join(a, f) for a, _, ff in os.walk(p) for f in ff]
    parts = []
    for f in files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            parts.append(fh.read())
    return "\n".join(parts)


def inventory(room_id: str) -> list[dict]:
    room = R.get_room(room_id)
    base = os.path.join(SJ.room_dir(room_id), "out")
    rows = []
    for r in R._files(room_id):
        h = L.holder(_text(base, r["out_dir"])) if r["out_dir"] else None
        rows.append({"source": r["rel"], "state": R.derive_state(r, room), "reason": r["reason"] or "",
                     "stamp": h["type"] if h else "", "licensee": h["who"] if h else "", "date": h["date"] if h else "",
                     "terms": h["terms"] if h else "", "kind": h["kind"] if h else "none found",
                     "network_prohibited": bool(h and h["network_prohibited"]),
                     "unlocked_copy": "已解锁" in r["rel"] or "unlocked" in r["rel"].lower()})
    return rows


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    rooms = [argv[0]] if argv else [r["id"] for r in R.list_rooms(False)]
    os.makedirs(os.path.join("data", "licence"), exist_ok=True)
    for rid in rooms:
        rows = inventory(rid)
        path = os.path.join("data", "licence", f"{rid}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["source"])
            w.writeheader()
            w.writerows(rows)
        print(f"# room {rid}: {len(rows)} file(s)  (full list: {path})")
        for x in rows:
            who = x["licensee"] if x["kind"] in (L.KIND_ORGANISATION,) else ("an individual" if x["licensee"] else "-")
            print(f"{x['kind']:<13}| {who:<38}| {x['date']:<13}| {x['state']:<13}| {x['source']}")


if __name__ == "__main__":
    main()
