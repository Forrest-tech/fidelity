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
import re
import threading
import time


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
        self.by = ""        # who accepted what this run publishes (for the release note)

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
        sizes = {rel: len(data) for rel, data in files.items()}
        clauses = sum(len([c for c in m.group(1).split(b",") if c.strip()])
                      for data in files.values()
                      for m in [re.search(rb"^clauses: \[(.*)\]\s*$", data[:4000], re.M)] if m)
        paths = {self._staged(key) + (f"/{rel}" if rel else ""): data for rel, data in files.items()}
        if hasattr(self.s, "upload_many"):                 # Dropbox: parallel sessions, one commit
            self.s.upload_many(paths)
        else:
            for dest, data in paths.items():
                self.s.upload(dest, data)
        with _STAGE_LOCK:                      # documents are staged from several upload threads at once
            self.docs[key] = {"files": sizes, "state": "staged", "archived": [], "clauses": clauses}
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
        single file and chapter folder. All documents are validated first; nothing moves if any fails.

        What a document replaces is deleted into the storage's own history (Dropbox "deleted files", the Drive
        trash) after its restore handles are written to this run's record, so undo brings it back and no archive
        folder sits next to the library. A store without that history keeps the archive folder."""
        bad = {k: p for k in self.docs if self.docs[k]["state"] == "staged" for p in [self.validate(k)] if p}
        if bad:
            raise PublishError(f"validation failed, nothing promoted: {bad}")
        for key, d in self.docs.items():
            if d["state"] != "staged":
                continue
            for old in [key] + list((replaces or {}).get(key, [])):
                if old in d["archived"] or old in {t["key"] for t in d.get("trashed", [])}:
                    continue                                         # done before a dropped connection
                if self.s.list(self._live(old)):
                    self._put_away(d, old)
            self._move(self._staged(key), self._live(key))
            d["state"] = "promoted"
            self._save()
        self._tidy_staging()
        self.release_note()

    # --- release note (requirements v3 R-1) ------------------------------------------------
    def release_note(self) -> dict | None:
        """One numbered release of the knowledge base per publishing run: what was added, replaced or withdrawn, with
        files and clauses, who accepted it, and how to undo it. Written next to the publish records."""
        changed = [(k, d) for k, d in self.docs.items() if d.get("state") in ("promoted", "withdrawn")]
        if not changed:
            return None
        rel_dir = os.path.join(os.path.dirname(self.manifest_path.rstrip(os.sep)), "..", "releases")
        rel_dir = os.path.normpath(rel_dir)
        os.makedirs(rel_dir, exist_ok=True)
        existing = [f for f in os.listdir(rel_dir) if re.match(r"^\d{4}-.*\.json$", f)]
        if any(f.endswith(f"-{self.run}.json") for f in existing):
            return None                                              # this run already has its note
        n = len(existing) + 1
        docs = []
        for k, d in sorted(changed):
            before = sum(len(t.get("tokens") or []) for t in d.get("trashed", [])) + len(d.get("archived", []))
            change = "withdrawn" if d["state"] == "withdrawn" else ("replaced" if before else "added")
            docs.append({"key": k, "change": change, "files_before": before, "files": len(d.get("files") or {}),
                         "clauses": d.get("clauses", 0)})
        note = {"release": n, "run": self.run, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "library": self.live,
                "accepted_by": self.by, "documents": docs,
                "totals": {c: sum(1 for x in docs if x["change"] == c) for c in ("added", "replaced", "withdrawn")},
                "undo": f"python -m app.distill.sync --dest-link <library> --rollback {self.run}"}
        base = os.path.join(rel_dir, f"{n:04d}-{self.run}")
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(note, f, ensure_ascii=False, indent=1)
        lines = [f"# Library release {n} ({note['at'][:10]})", "",
                 f"Library: `{self.live}` · run `{self.run}` · accepted by {self.by or '—'}", "",
                 f"Added {note['totals']['added']} · replaced {note['totals']['replaced']} · withdrawn {note['totals']['withdrawn']}",
                 "", "| Document | Change | Files (before → now) | Clauses |", "|---|---|---|---|"]
        lines += [f"| {x['key']} | {x['change']} | {x['files_before']} → {x['files']} | {x['clauses']} |" for x in docs]
        lines += ["", f"Undo this release: `{note['undo']}`", ""]
        with open(base + ".md", "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))
        return note

    def _history(self) -> bool:
        return hasattr(self.s, "revisions") and hasattr(self.s, "restore")

    def _put_away(self, d: dict, old: str):
        """The previous version of `old` leaves the live folder, restorable by rollback."""
        if self._history():
            d.setdefault("trashed", []).append({"key": old, "tokens": self.s.revisions(self._live(old))})
            self._save()                                             # the way back is on disk before anything goes
            self._retry(lambda: self.s.delete(self._live(old)), done=lambda: not self.s.list(self._live(old)))
        else:
            self._move(self._live(old), self._arch(old))
            d["archived"].append(old)
        self._save()

    def _tidy_staging(self):
        """Staging holds a run only while it is published: the empty folders it leaves go too."""
        drop = getattr(self.s, "drop_empty", None)
        if drop is None:
            return
        try:
            drop(f"{self.staging}/{self.run}")
            drop(self.staging)
        except Exception as e:                     # noqa: BLE001 - tidying never fails a publish
            print(f"  staging folder left in place: {type(e).__name__}: {e}", flush=True)

    BACKOFF = (2, 5, 15, 30, 60)

    def _move(self, src: str, dst: str):
        """A server-side move that survives a dropped connection (requirements v2 S-2): retried on network errors,
        and a move the server finished although its answer was lost counts as done instead of failing on retry."""
        self._retry(lambda: self.s.move(src, dst), done=lambda: bool(self.s.list(dst)) and not self.s.list(src))

    def _retry(self, fn, done):
        import time
        from .sync import _transient
        for n in range(len(self.BACKOFF) + 1):
            try:
                return fn()
            except Exception as e:                 # noqa: BLE001
                if done():
                    return None                    # it went through; only the answer was lost
                if n == len(self.BACKOFF) or not _transient(e):
                    raise
                time.sleep(self.BACKOFF[n])

    def withdraw(self, key: str, also: list | None = None):
        """Take a document out of the live folder (into the storage's history, or the archive folder) and the same
        rollback brings it back. Used for a second copy of an edition that is already published."""
        d = self.docs.setdefault(key, {"state": "withdrawn", "archived": [], "files": {}})
        d["state"] = "withdrawn"
        for old in [key] + list(also or []):
            if self.s.list(self._live(old)):
                self._put_away(d, old)
        self._save()
        return d["archived"] + [t["key"] for t in d.get("trashed", [])]

    # --- rollback ---------------------------------------------------------------------
    def rollback(self):
        """Undo this run: new versions leave the live folder, previous versions come back."""
        for key, d in self.docs.items():
            if d["state"] not in ("promoted", "withdrawn"):
                continue
            if d["state"] == "promoted" and self.s.list(self._live(key)):
                if self._history():
                    self._retry(lambda: self.s.delete(self._live(key)), done=lambda: not self.s.list(self._live(key)))
                else:
                    self._move(self._live(key), f"{self.staging}/{self.run}-rolled-back/{key}")
            for old in d["archived"]:                                # records written before 2026-11-23
                self._move(self._arch(old), self._live(old))
            for t in d.get("trashed", []):
                self.s.restore(t["tokens"])
            d["state"] = "rolled_back"
            self._save()

    @staticmethod
    def load(store, manifest_path: str, manifest_dir: str):
        with open(manifest_path, encoding="utf-8") as f:
            m = json.load(f)
        p = Publisher(store, m["live"], m["staging"], m["archive"], m["run"], manifest_dir)
        p.docs = m["docs"]
        return p
