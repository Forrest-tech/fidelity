# -*- coding: utf-8 -*-
"""Incremental processing ledger (spec F-17).

Records, per source file, what was distilled from which content hash with which
pipeline version. A re-run skips files whose hash and versions are unchanged; a changed
file is re-distilled; a file that disappeared from the source is only *reported* -
published files are never touched without administrator confirmation.
The ledger lives in Fidelity's own work folder, never in the knowledge base.
"""
from __future__ import annotations

import datetime as _dt
import json
import os


class Ledger:
    def __init__(self, path: str, source_key: str):
        self.path = path
        self.key = source_key
        self.data = {}
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        except FileNotFoundError:
            pass
        self.docs = self.data.setdefault(source_key, {})

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)       # atomic: an interrupted run never leaves a half-written ledger

    def record(self, rel: str, content_hash: str, pipeline: str, verdict: str, dest: str = "", files: int = 0):
        self.docs[rel] = {"content_hash": content_hash, "pipeline": pipeline, "verdict": verdict,
                          "dest": dest, "files": files,
                          "at": _dt.datetime.now().astimezone().isoformat(timespec="seconds")}
        self.save()

    def up_to_date(self, rel: str, content_hash: str, pipeline: str) -> bool:
        e = self.docs.get(rel)
        return bool(e and e["content_hash"] == content_hash and e["pipeline"] == pipeline
                    and e["verdict"] in ("PASS", "SKIP"))

    def removed(self, current_rels) -> list:
        """Documents recorded earlier that are no longer in the source (renamed or deleted)."""
        cur = set(current_rels)
        return sorted(r for r in self.docs if r not in cur)
