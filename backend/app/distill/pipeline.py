# -*- coding: utf-8 -*-
"""Several files at once, each through its own steps.

A run used to take one file at a time: download it, distill it, check it, then start the next download. The network
sat idle while the processor worked and the other way round. Now the steps are separate, as in other document
pipelines (Unstructured's ingest, Docling's threaded pipeline): network steps (download, upload) run on threads, the
heavy reading (text extraction, OCR, verification) runs in worker processes, and bounded hand-overs between them keep
memory and disk in check. A few files are fetched ahead of the readers, never more than the readers can take.

Every file's step is kept in a small JSON file (the "live" status) that the page reads:

    {"v": 2, "stage": "running", "workers": 2, "total": 41, "done": 7, "skipped": 3,
     "active": {"/a.pdf": {"stage": "ocr", "page": 12, "pages": 40, "since": ...},
                "/b.pdf": {"stage": "downloading", "bytes": 3145728, "size": 9437184, "since": ...}},
     "queued": ["/c.pdf", ...], "counts": {"PASS": 5, "FAIL": 1}, ...}

Steps of one file: queued -> downloading -> ready (downloaded, waiting for a free reader) -> reading (or ocr, page by
page) -> checking -> [uploading] -> done.
"""
from __future__ import annotations

import json
import os
import queue as _queue
import re
import threading
import time

STAGES = ("queued", "downloading", "ready", "reading", "ocr", "checking", "uploading")
START = "__reader_started__"                    # a reader took the file (it may wait a while for a free reader before that)

_OCR = re.compile(r"OCR page (\d+)/(\d+|\?)")


def auto_workers(points_each: int = 1, free_points: int | None = None, cap: int = 4) -> int:
    """How many files may be read at once: as many as the free capacity holds, at least one, at most `cap`."""
    from ..jobs import capacity
    free = capacity.points() if free_points is None else free_points
    return max(1, min(cap, free // max(1, points_each)))


# ------------------------------------------------------------------ the live status
class LiveState:
    """The run's status for the page, written atomically at most twice a second (and at once when asked)."""

    def __init__(self, path: str | None, workers: int = 1, now=time.time):
        self.path, self.now = path, now
        self._lock = threading.Lock()
        self._dirty = True
        self._stop = threading.Event()
        self.s = {"v": 2, "started": now(), "updated": now(), "stage": "listing", "workers": workers, "total": 0,
                  "done": 0, "skipped": 0, "active": {}, "queued": [], "counts": {},
                  # the fields older pages read: the first file being worked on
                  "file": "", "index": 0, "page": 0, "pages": 0, "scan": False}
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            threading.Thread(target=self._loop, daemon=True, name="live-status").start()

    # -- changes
    def set(self, **kw):
        with self._lock:
            self.s.update(kw)
            self._touch()

    def file(self, rel: str, **kw):
        """Set what one file is doing now (stage, page, pages, bytes, size, scan)."""
        with self._lock:
            a = self.s["active"].get(rel)
            if a is None:
                a = self.s["active"][rel] = {"since": self.now()}
                if rel in self.s["queued"]:
                    self.s["queued"].remove(rel)
            if "stage" in kw and kw["stage"] != a.get("stage"):
                a["stage_since"] = self.now()
            a.update(kw)
            self._touch()

    def done(self, rel: str, verdict: str | None = None):
        with self._lock:
            self.s["active"].pop(rel, None)
            if rel in self.s["queued"]:
                self.s["queued"].remove(rel)
            self.s["done"] += 1
            if verdict:
                self.s["counts"][verdict] = self.s["counts"].get(verdict, 0) + 1
            self._touch()

    def skipped(self, n: int = 1):
        with self._lock:
            self.s["skipped"] += n
            self._touch()

    def message(self, rel: str, msg: str):
        """A line the reader printed for this file: work out its step from it."""
        m = msg.strip()
        if msg == START:
            self.file(rel, stage="reading")
        elif m.startswith("scanned document"):
            self.file(rel, stage="ocr", scan=True)
        elif mm := _OCR.match(m):
            self.file(rel, stage="ocr", scan=True, page=int(mm.group(1)),
                      pages=int(mm.group(2)) if mm.group(2).isdigit() else 0)
        elif m.startswith(("extracted", "visual check", "verification reused")):
            self.file(rel, stage="checking")

    def _touch(self):
        self.s["updated"] = self.now()
        act = self.s["active"]
        first = next(iter(act.items()), None)
        if first:                                          # older readers: the first active file
            rel, a = first
            self.s.update(file=rel[-200:], page=a.get("page", 0), pages=a.get("pages", 0), scan=bool(a.get("scan")))
        self.s["index"] = self.s["done"] + self.s["skipped"] + (1 if act else 0)
        self._dirty = True

    # -- writing
    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self.s))

    def flush(self):
        if not self.path:
            return
        data = self.snapshot()
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError:                                    # the page reading it at that moment (Windows): next time
            pass

    def _loop(self):
        while not self._stop.wait(0.5):
            if self._dirty:
                self.flush()

    def close(self, stage: str = "finished"):
        with self._lock:
            self.s["stage"] = stage
            self.s["active"] = {}
            self.s["queued"] = []
            self._touch()
        self._stop.set()
        self.flush()


def drain(q, live: LiveState, echo=print):
    """Hand the readers' messages (rel, text) to the live status and the log, until (None, None) arrives."""
    def _loop():
        while True:
            try:
                rel, msg = q.get()
            except (EOFError, OSError):
                return
            if rel is None:
                return
            live.message(rel, msg)
            if msg != START:
                echo(f"  {msg.strip()}  [{rel.rsplit('/', 1)[-1]}]")
    t = threading.Thread(target=_loop, daemon=True, name="reader-messages")
    t.start()
    return t


# ------------------------------------------------------------------ the readers
_Q = None


def _init_worker(q):
    global _Q
    _Q = q
    os.environ.setdefault("PYTHONUTF8", "1")


def read_file(lp, rel_local, out, cache, publish_protected, rel):
    """Distill and verify one downloaded file (runs in a reader process or thread)."""
    from .office import distill_any
    q = _Q

    def log(m):
        try:
            q.put((rel, str(m)))
        except Exception:                                  # noqa: BLE001 - progress must never fail a file
            pass
    log(START)
    return distill_any(lp, rel_local, out, "", cache, log=log, publish_protected=publish_protected)


class Readers:
    """A pool that reads files: worker processes when more than one file is read at once (the reading is
    processor-bound Python), a single thread otherwise (no extra process, no extra memory)."""

    def __init__(self, workers: int):
        self.workers = max(1, int(workers))
        self._make()

    def _make(self):
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
        if self.workers == 1 or os.environ.get("FIDELITY_READ_IN_THREADS") == "1":   # the latter: tests only
            if self.workers > 1:
                self.q = _queue.Queue()
                _init_worker(self.q)
                self.pool = ThreadPoolExecutor(self.workers, thread_name_prefix="reader")
                self.processes = False
                return
            self.q = _queue.Queue()
            _init_worker(self.q)
            self.pool = ThreadPoolExecutor(1, thread_name_prefix="reader")
            self.processes = False
        else:
            import multiprocessing as mp
            ctx = mp.get_context("spawn")
            self.q = ctx.Queue()
            kw = dict(max_workers=self.workers, mp_context=ctx, initializer=_init_worker, initargs=(self.q,))
            try:
                self.pool = ProcessPoolExecutor(max_tasks_per_child=20, **kw)   # bounds a slow leak in a long run
            except TypeError:                                                   # Python < 3.11
                self.pool = ProcessPoolExecutor(**kw)
            self.processes = True

    def submit(self, *args):
        return self.pool.submit(read_file, *args)

    def broken(self) -> bool:
        return bool(getattr(self.pool, "_broken", False))

    def renew(self):
        """After a reader process died (e.g. out of memory) the pool is broken: start a fresh one."""
        self.stop()
        self._make()

    def stop(self):
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except Exception:                                  # noqa: BLE001
            pass
        for p in list((getattr(self.pool, "_processes", None) or {}).values()):   # end a reader stuck on a file
            try:
                p.terminate()
            except Exception:                              # noqa: BLE001
                pass

    def close(self):
        try:
            self.q.put((None, None))
        except Exception:                                  # noqa: BLE001
            pass
        try:
            self.pool.shutdown(wait=True)
        except Exception:                                  # noqa: BLE001
            pass


# ------------------------------------------------------------------ download with progress
def watch_download(live: LiveState, rel: str, lp: str, size: int):
    """Report the bytes received so far by watching the partial file. Returns a stop() function."""
    stop = threading.Event()

    def _loop():
        while not stop.wait(0.5):
            for p in (lp + ".part", lp):
                try:
                    n = os.path.getsize(p)
                except OSError:
                    continue
                live.file(rel, bytes=min(n, size or n))
                break
    threading.Thread(target=_loop, daemon=True, name="download-progress").start()
    return stop.set
