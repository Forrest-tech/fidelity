# -*- coding: utf-8 -*-
"""Publishing: staging -> validate -> promote as a whole, previous version kept for rollback (spec F-18).

The knowledge-base ("live") folder is only ever changed by `promote` and `rollback`, which
use server-side moves of whole documents. Documents are first uploaded to a separate
staging folder, checked against what was sent, and only then moved into place; whatever
they replace goes to an archive folder keyed by run id, so a run can be undone.

`store` is any object with: upload(path, data), move(src, dst), list(path) -> {path: size},
delete(path). Dropbox implementation: DropboxStore in dropbox_io.py; tests use a fake.
"""
from __future__ import annotations

import json
import os
import threading


class PublishError(RuntimeError):
    pass


_STAGE_LOCK = threading.Lock()


class Publisher:
    def __init__(self, store, live: str, staging: str, archive: str, run_id: str, manifest_dir: str):
        for a, b in ((live, staging), (live, archive), (staging, archive)):
            la, lb = a.rstrip("/").lower() + "/", b.rstrip("/").lower() + "/"
            if la.startswith(lb) or lb.startswith(la):
                raise PublishError(f"live, staging and archive folders must not overlap: {a} / {b}")
        self.s, self.live, self.staging, self.archive, self.run = store, live.rstrip("/"), staging.rstrip("/"), archive.rstrip("/"), run_id
        self.manifest_path = os.path.join(manifest_dir, f"publish-{run_id}.json")
        self.docs = {}      # key -> {"files": {relpath: size}, "state": "staged|promoted|rolled_back", "archived": [..]}

    # --- paths ------------------------------------------------------------------------
    def _staged(self, key):
        return f"{self.staging}/{self.run}/{key}"

    def _live(self, key):
        return f"{self.live}/{key}"

    def _arch(self, key):
        return f"{self.archive}/{self.run}/{key}"

    def _save(self):
        os.makedirs(os.path.dirname(self.manifest_path), exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump({"run": self.run, "live": self.live, "staging": self.staging, "archive": self.archive,
                       "docs": self.docs}, f, ensure_ascii=False, indent=1)

    # --- stage ------------------------------------------------------------------------
    def stage(self, key: str, files: dict):
        """files: {relative path inside the document (or '' for a single-file document): bytes}"""
        sizes = {}
        for rel, data in files.items():
            dest = self._staged(key) + (f"/{rel}" if rel else "")
            self.s.upload(dest, data)
            sizes[rel] = len(data)
        with _STAGE_LOCK:                      # documents are staged from several upload threads at once
            self.docs[key] = {"files": sizes, "state": "staged", "archived": []}
            self._save()

    # --- validate ---------------------------------------------------------------------
    def validate(self, key: str) -> list:
        """Problems found (empty list = staged copy matches what was sent)."""
        d = self.docs[key]
        got = self.s.list(self._staged(key))
        base = self._staged(key)
        have = {(p[len(base):].lstrip("/") if p != base else ""): n for p, n in got.items()}
        problems = []
        for rel, n in d["files"].items():
            if rel not in have:
                problems.append(f"missing in staging: {rel or key}")
            elif have[rel] != n:
                problems.append(f"size differs in staging: {rel or key} ({have[rel]} != {n})")
        extra = set(have) - set(d["files"])
        problems += [f"unexpected file in staging: {x}" for x in sorted(extra)]
        return problems

    # --- promote ----------------------------------------------------------------------
    def promote(self, replaces: dict | None = None):
        """Move every staged document into the live folder. `replaces` maps a key to the other
        live paths (relative to live) it supersedes, e.g. a document that switched between
        single file and chapter folder. All documents are validated first; nothing moves if any fails."""
        bad = {k: p for k in self.docs if self.docs[k]["state"] == "staged" for p in [self.validate(k)] if p}
        if bad:
            raise PublishError(f"validation failed, nothing promoted: {bad}")
        for key, d in self.docs.items():
            if d["state"] != "staged":
                continue
            for old in [key] + list((replaces or {}).get(key, [])):
                if old in d["archived"]:
                    continue                                         # moved before a dropped connection
                if self.s.list(self._live(old)):
                    self._move(self._live(old), self._arch(old))     # previous version kept
                    d["archived"].append(old)
                    self._save()
            self._move(self._staged(key), self._live(key))
            d["state"] = "promoted"
            self._save()

    BACKOFF = (2, 5, 15, 30, 60)

    def _move(self, src: str, dst: str):
        """A server-side move that survives a dropped connection (requirements v2 S-2): retried on network errors,
        and a move the server finished although its answer was lost counts as done instead of failing on retry."""
        import time
        from .sync import _transient
        for n in range(len(self.BACKOFF) + 1):
            try:
                return self.s.move(src, dst)
            except Exception as e:                 # noqa: BLE001
                if self.s.list(dst) and not self.s.list(src):
                    return None                    # it went through; only the answer was lost
                if n == len(self.BACKOFF) or not _transient(e):
                    raise
                time.sleep(self.BACKOFF[n])

    def withdraw(self, key: str, also: list | None = None):
        """Take a document out of the live folder: it moves to the archive (nothing is deleted) and the same
        rollback brings it back. Used for a second copy of an edition that is already published."""
        d = self.docs.setdefault(key, {"state": "withdrawn", "archived": [], "files": {}})
        d["state"] = "withdrawn"
        for old in [key] + list(also or []):
            if self.s.list(self._live(old)):
                self._move(self._live(old), self._arch(old))
                d["archived"].append(old)
        self._save()
        return d["archived"]

    # --- rollback ---------------------------------------------------------------------
    def rollback(self):
        """Undo this run: new versions are moved back to staging, previous versions restored."""
        for key, d in self.docs.items():
            if d["state"] == "withdrawn":
                for old in d["archived"]:
                    self._move(self._arch(old), self._live(old))
                d["state"] = "rolled_back"
                self._save()
                continue
            if d["state"] != "promoted":
                continue
            if self.s.list(self._live(key)):
                self._move(self._live(key), f"{self.staging}/{self.run}-rolled-back/{key}")
            for old in d["archived"]:
                self._move(self._arch(old), self._live(old))
            d["state"] = "rolled_back"
            self._save()

    @staticmethod
    def load(store, manifest_path: str, manifest_dir: str):
        with open(manifest_path, encoding="utf-8") as f:
            m = json.load(f)
        p = Publisher(store, m["live"], m["staging"], m["archive"], m["run"], manifest_dir)
        p.docs = m["docs"]
        return p
