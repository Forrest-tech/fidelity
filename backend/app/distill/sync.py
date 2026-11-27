# -*- coding: utf-8 -*-
"""End to end, one document at a time:
Dropbox source link -> download one file -> distill + verify -> upload its Markdown -> next.

    python -m app.distill.sync --source-link <shared folder link> --dest-link <shared folder link>
                               [--work ../data/work] [--dry-run] [--only NAME]

Per document (the source is only ever read):
  1. download the file (skipped if the local copy already has the same content_hash)
  2. distill + verify locally (a failed document goes to _pending/, never the trusted tree)
  3. re-check that this source file is unchanged in Dropbox (id/rev/size)
  4. upload its folder (guarded writer; no catalog/README files are published)
A full before/after snapshot of the source folder is compared at the end and
written to /<dest>/_sync/<source folder>.json as proof the source was not modified.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import sys
import time

from . import backends as B
from . import dropbox_io as D
from . import run as R
from . import accept as AC
from . import scoring as SC
from . import pipeline as P
from .events import Events, kind_of
from .ledger import Ledger
from .publish import Publisher

from .office import SUPPORTED, distill_any  # noqa: E402  (all registered formats)


def _state_path(work):
    return os.path.join(work, "catalog_state.json")


def load_state(work):
    try:
        with open(_state_path(work), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(work, state):
    with open(_state_path(work), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, default=str)


# ------------------------------------------------------------------ network hiccups
# A long run makes thousands of requests; one dropped connection (seen in testing: SSLEOFError
# while downloading from Dropbox) must not end a 41-file run. Transient errors are retried with
# backoff; a file that still fails is reported as FAIL with the reason and the run carries on.
# Seen on this machine for days in a row: the TLS connection to Dropbox drops now and then (SSLEOFError,
# "UNEXPECTED_EOF_WHILE_READING"), sometimes for a minute or two. Wait up to about 3.5 minutes before giving up.
_BACKOFF = (2, 5, 15, 30, 60, 90)
NET_PAUSE = 120                   # seconds to wait before files a dropped connection stopped are tried once more


def _transient(e) -> bool:
    import ssl
    try:
        import requests
        if isinstance(e, requests.exceptions.RequestException):
            return True
    except ImportError:                                   # pragma: no cover
        pass
    if isinstance(e, (ConnectionError, TimeoutError, ssl.SSLError)):
        return True
    # Windows "file in use by another process" (WinError 32): antivirus or the search indexer holding a file that was
    # just downloaded. It lets go within seconds; a run failed on it once (failure-mode table, docs/quality/FMEA.md).
    if isinstance(e, PermissionError) and getattr(e, "winerror", None) == 32:
        return True
    name = type(e).__name__
    if name in ("InternalServerError", "RateLimitError"):  # dropbox.exceptions
        return True
    status = getattr(getattr(e, "resp", None), "status", None)
    if name == "HttpError" and status is not None:         # googleapiclient
        return int(status) == 429 or int(status) >= 500
    return False


def _retry(fn, what):
    tries = len(_BACKOFF) + 1
    for n in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:
            if n == tries or not _transient(e):
                raise
            print(f"  network error, retrying ({n}/{tries - 1}) {what}: {type(e).__name__}: {str(e)[:160]}", flush=True)
            time.sleep(_BACKOFF[n - 1])


MIN_FREE = 2 * 1024 ** 3          # keep this much disk free besides the file and its work files


def _evict(work, need, keep=()):
    """Downloaded sources under <work>/src are a cache: every file has a result once read, and the formula helper
    copes with a missing copy. When the disk runs short, delete the oldest copies first (never one this run still
    needs) instead of stopping the run. Returns the bytes freed."""
    keep = {os.path.normcase(os.path.abspath(R.longpath(k))) for k in keep}
    files = []
    for root, _, names in os.walk(R.longpath(os.path.join(work, "src"))):
        for n in names:
            p = os.path.join(root, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if os.path.normcase(os.path.abspath(p)) not in keep:
                files.append((st.st_mtime, st.st_size, p))
    freed = 0
    for _, size, p in sorted(files):
        if shutil.disk_usage(work).free >= need:
            break
        try:
            os.remove(p)
            freed += size
        except OSError:
            pass
    if freed:
        print(f"freed {freed / 1e9:.1f} GB of older downloaded copies (they are downloaded again only if needed)", flush=True)
    return freed


def _check_space(work, size, keep=()):
    """Stop cleanly before a download would fill the disk (a real run died mid-download with
    "No space left on device", and even the error could not be saved). Older downloaded copies are
    removed first; the run stops only when that is not enough."""
    free = shutil.disk_usage(work).free
    need = 3 * size + MIN_FREE      # the file, its rendered pages / extracted text, and headroom
    if free < need:
        _evict(work, need, keep)
        free = shutil.disk_usage(work).free
    if free < need:
        raise SystemExit(f"not enough free disk space on this machine: {free / 1e9:.1f} GB free, "
                         f"about {need / 1e9:.1f} GB needed for the next file — stopped before downloading")


def _known(room_dir):
    """The files whose results the web side has (written by it before a run), or None when it did not say.
    A room's own ledger can hold a result the web side never received (a run whose events were lost); such a file
    is read again instead of being skipped while the page shows it as never distilled."""
    try:
        with open(os.path.join(room_dir, "known.json"), encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError, TypeError):
        return None


def _skip(a, ledger, rledger, rel, content_hash, known=None) -> bool:
    """Is this file already done for this content and pipeline version?
    With a room folder: a stored result of any quality counts; a file that was published (PASS) must also be in the
    publishing ledger when this run publishes. Without one: the publishing ledger decides, as before."""
    if a.force:
        return False
    if rledger is None:
        return ledger.up_to_date(rel, content_hash, R.PIPELINE_VERSION)
    e = rledger.docs.get(rel)
    if not (e and e["content_hash"] == content_hash and e["pipeline"] == R.PIPELINE_VERSION):
        return False
    if known is not None and rel not in known:
        return False
    return a.dry_run or e["verdict"] not in ("PASS", "METADATA") or ledger.up_to_date(rel, content_hash, R.PIPELINE_VERSION)


def _publish_accepted(a, src, dst, ev, dest_root, stage_root, archive_root, live=None) -> int:
    """Send results that a person accepted. They are staged, checked and promoted together, like a normal run, and
    the previous versions go to the storage's history (Dropbox deleted files), so the same --rollback undoes it."""
    if not dst or not a.room_dir:
        raise SystemExit("--publish-from needs --dest-link and --room-dir")
    with open(a.publish_from, encoding="utf-8") as f:
        plan = json.load(f)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(a.room_dir, "out")
    pub = Publisher(dst.store, dest_root, stage_root, archive_root, stamp, os.path.join(a.work, "publish"))
    ledger = Ledger(os.path.join(a.work, "ledger.json"), src.label)
    when = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    pending, failed = [], []
    withdraw = [it for it in plan["items"] if it.get("withdraw")]
    items = [it for it in plan["items"] if not it.get("withdraw")]
    errors = []
    print(f"publishing {len(items)} accepted document(s)  ->  output {dst.provider}:{dest_root}", flush=True)
    live = live or P.LiveState(None)
    live.set(stage="running", total=len(items), queued=[it["rel"] for it in items])

    def send(it):
        rel, key = it["rel"], AC.live_key(it["out_dir"], src.name)
        live.file(rel, stage="uploading")
        # The walk and the relative paths both use the long (\\?\) form: mixing it with the plain form failed every
        # multi-file document on Windows ("path is on mount '\\?\C:', start on mount 'C:'"), so nothing was sent.
        files = {}
        for relpath, data in _read_files(os.path.join(out, it["out_dir"])).items():
            if (relpath or it["out_dir"]).lower().endswith(".md"):
                data = AC.accept_markdown(data.decode("utf-8"), it.get("by") or "", it.get("at") or when,
                                          it.get("accuracy"), bool(it.get("forced")), it.get("edition")).encode("utf-8")
            files[relpath] = data
        if not files:
            raise FileNotFoundError("the distilled result is no longer on this machine; run the room again")
        _retry(lambda: pub.stage(key, files), "upload")
        return key, len(files)

    # a few documents go up at once (network-bound); the live folder is only changed by promote(), all together
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3, thread_name_prefix="upload") as ex:
        futs = [(it, ex.submit(send, it)) for it in items]
        for n, (it, fut) in enumerate(futs, 1):
            rel = it["rel"]
            print(f"[{n}] {rel}", flush=True)
            try:
                key, count = fut.result()
            except Exception as e:                 # noqa: BLE001 - one document failing must not stop the others
                print(f"  NOT published: {_err(e)}", flush=True)
                failed.append(rel)
                errors.append(_err(e))
                ev.emit("publish_failed", rel=rel, error=_err(e))
                live.done(rel, "FAIL")
                continue
            pending.append((rel, it, key, count))
            print(f"  staged {count} file(s)", flush=True)
            live.done(rel, "PASS")
    live.set(stage="publishing")
    report = {"source": src.label, "dest": dest_root, "run": stamp, "mode": "publish accepted results",
              "published": [p[0] for p in pending], "failed": failed}
    if pending:
        replaces = {k: [k[:-len(".pdf.md")]] if k.endswith(".pdf.md") else [k + ".pdf.md"] for _, _, k, _ in pending}
        pub.by = ", ".join(sorted({it.get("by") for _, it, _, _ in pending if it.get("by")}))   # for the release note
        pub.promote(replaces=replaces)
        for rel, it, key, n in pending:
            ledger.record(rel, it["content_hash"], R.PIPELINE_VERSION, "PASS", f"{dest_root}/{key}", n)
            ev.emit("published", rel=rel, files=n, run=stamp)
        report["published_run"] = stamp
        print(f"\npromoted {len(pending)} document(s); undo with: python -m app.distill.sync --rollback {stamp}", flush=True)
    for it in withdraw:                            # second copies of an edition: out of the live folder, archived
        key = AC.live_key(it["out_dir"], src.name)
        alt = [key[:-len(".pdf.md")]] if key.endswith(".pdf.md") else [key + ".pdf.md"]
        try:
            moved = _retry(lambda: pub.withdraw(key, alt), "withdraw")
        except Exception as e:                     # noqa: BLE001
            failed.append(it["rel"])
            errors.append(_err(e))
            ev.emit("publish_failed", rel=it["rel"], error=_err(e))
            continue
        print(f"withdrawn from the output folder (archived): {it['rel']} ({len(moved)} item(s))", flush=True)
        ev.emit("withdrawn", rel=it["rel"], run=stamp)
        report.setdefault("withdrawn", []).append(it["rel"])
        report["published_run"] = stamp
    print(json.dumps(report, indent=1), flush=True)
    if failed:
        # a publishing run where documents were not sent must not look done: the job fails and says why
        raise SystemExit(f"{len(failed)} of {len(items)} document(s) could not be sent to the output folder"
                         f"{' (the others were)' if pending else ''}: {errors[0]}")
    return 0


def _err(e) -> str:
    return f"{type(e).__name__}: {e}"[:300]


def _fetch(src, rel, f, lp, live):
    """Download one file (unless the local copy is already this content) and check it. Runs on a download thread."""
    # A copy downloaded by an earlier run is used again when it is this very content (checked once, by its hash):
    # it shows as downloaded at once, not as "0 MB" while its hash is worked out (2026-11-27, the owner thought the
    # file was being downloaded again).
    if os.path.exists(lp):
        live.file(rel, bytes=f.get("size") or 0)
        if src.local_matches(lp, f):
            print(f"  using the copy downloaded earlier  [{rel.rsplit('/', 1)[-1]}]", flush=True)
            return
        live.file(rel, bytes=0)
    print(f"  download ({f['size'] / 1e6:.1f} MB)  [{rel.rsplit('/', 1)[-1]}]", flush=True)
    stop = P.watch_download(live, rel, lp, f.get("size") or 0)
    try:
        _retry(lambda: src.download(rel, f, lp), "download")
    finally:
        stop()
    if not src.verify_local(lp, f):
        # a download carried on from a partial copy of another version (the file changed between the two): once
        # more from 0 before giving up
        D.restart(lp)
        print(f"  the downloaded copy does not match; downloading it again in full  [{rel.rsplit('/', 1)[-1]}]", flush=True)
        _retry(lambda: src.download(rel, f, lp), "download")
        if not src.verify_local(lp, f):
            raise SystemExit(f"local copy of {rel} does not match the source file's checksum")


def _cost(lp) -> int:
    """Capacity points reading this file takes: a scan (OCR) 2, everything else 1. OCR holds a lot of memory and
    every processor core on its own, so two scans side by side on a small machine are slower than one after the
    other. The check is the same quick triage the reader starts with."""
    low = lp.lower()
    if low.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")):
        return 2
    if low.endswith(".pdf"):
        try:
            from .triage import reads_as_scan, triage_pdf
            return 2 if reads_as_scan(triage_pdf(lp)) else 1
        except Exception:                                  # noqa: BLE001 - the reader will report a broken file
            return 1
    return 1


def _read_files(out_dir_base):
    """The bytes of one distilled document, as the publisher stages them."""
    files = {}
    if os.path.isfile(R.longpath(out_dir_base)):
        with open(R.longpath(out_dir_base), "rb") as fh:
            files[""] = fh.read()
        return files
    for root_, _, fns_ in os.walk(R.longpath(out_dir_base)):
        for fn_ in sorted(fns_):
            lp_ = os.path.join(root_, fn_)
            with open(lp_, "rb") as fh:
                files[os.path.relpath(lp_, R.longpath(out_dir_base)).replace(os.sep, "/")] = fh.read()
    return files


def _pipeline(a, plan, src, src_name, out, cache, rledger, ledger, ev, live, workers, downloads, results, report,
              pending, pub, dest_root, stage_root, stamp):
    """Read the planned files, several at once.

    Downloads run ahead of the readers on their own threads, but never more than `workers + 1` files are downloaded
    and not yet read (bounded, so a fast network cannot fill the disk while the readers are busy). The disk check
    counts every file that is downloading or waiting to be read. Everything that decides a file's fate — recording
    it, re-checking the source, staging its upload — happens here, on one thread, in the order the readers finish,
    so the ledgers and the report are written by one hand. A source that changed during the run still stops it all."""
    from collections import deque
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    from concurrent.futures.process import BrokenProcessPool

    todo = deque(plan)
    budget = workers                   # capacity points this run holds: a text file takes 1, a scan 2 (see _cost)
    used = 0                           # points taken by the files being read now
    ready = deque()                    # downloaded, waiting for points to be free: (rel, f, lp, cost)
    readers = P.Readers(workers)
    P.drain(readers.q, live)
    dl = ThreadPoolExecutor(downloads, thread_name_prefix="download")
    up = ThreadPoolExecutor(2, thread_name_prefix="upload")
    inflight = {}                      # future -> (step, rel, f, extra)
    reserved = 0                       # bytes of files downloading or waiting to be read
    window = workers + 1               # files downloaded ahead of the readers, at most
    retried = set()
    started = 0
    later = []                         # files a dropped connection stopped: tried once more at the end of the run
    second = set()

    def failed(rel, e, step):
        err = _err(e)
        print(f"  verification: FAIL  (error while {step}: {err})  [{rel}]", flush=True)
        ev.emit("file", rel=rel, kind=kind_of(rel), **SC.classify(None, error=f"{step}: {err}"))
        results.append({"verdict": "FAIL"})
        report["documents"].append({"source": rel, "verdict": "FAIL", "files": 0, "uploaded": 0, "error": f"{step}: {err}"})
        live.done(rel, "FAIL")

    def ahead():
        return len(ready) + sum(1 for s, *_ in inflight.values() if s in ("download", "read"))

    passed = {}                        # rel -> how often a later file was started ahead of it

    def dispatch():
        """Start reading the first waiting files whose points fit. A text file may pass a scan that has to wait for
        its two points, but only twice: after that nothing new starts until the scan has its points, so a long row
        of text files cannot keep a scan waiting until the end of the run."""
        nonlocal used
        while ready:
            fits = lambda x: used == 0 or used + x[3] <= budget          # noqa: E731
            head = ready[0]
            if fits(head):
                pick = head
            elif passed.get(head[0], 0) >= 2:
                return                                                    # hold the points free for the waiting file
            else:
                pick = next((x for x in ready if fits(x)), None)
                if pick is None:
                    return
                passed[head[0]] = passed.get(head[0], 0) + 1
            ready.remove(pick)
            used += pick[3]
            start_read(*pick)

    def start_download(rel, f):
        nonlocal reserved
        os.makedirs(a.work, exist_ok=True)
        in_use = [x[3] for x in inflight.values() if x[0] == "download"] +                  [x[3][0] for x in inflight.values() if x[0] == "read"] + [x[2] for x in ready]
        _check_space(a.work, (f.get("size") or 0) + reserved, in_use)   # SystemExit: stop cleanly before the disk fills
        reserved += f.get("size") or 0
        lp = os.path.join(a.work, "src", src_name, *rel.strip("/").split("/"))
        ev.emit("start", rel=rel)
        live.file(rel, stage="downloading", bytes=0, size=f.get("size") or 0)
        inflight[dl.submit(_fetch, src, rel, f, lp, live)] = ("download", rel, f, lp)

    def start_read(rel, f, lp, cost):
        nonlocal started
        started += 1
        print(f"\n[{started}] {rel}", flush=True)
        rel_local = os.path.join(src_name, *rel.strip("/").split("/"))
        inflight[readers.submit(lp, rel_local, out, cache, a.publish_protected_metadata, rel,
                                rel in getattr(a, "older_editions", ()))] = ("read", rel, f, (lp, cost))

    def after_read(rel, f, r):
        results.append(r)
        if rledger is not None:                     # a result of any quality is remembered, so a resumed run skips it
            rledger.record(rel, f["content_hash"], R.PIPELINE_VERSION, r["verdict"])
        _c = SC.classify(r)
        ev.emit("file", rel=rel, kind=kind_of(rel), pages=r.get("pages"), scan=_c.get("basis") == "ocr_agreement",
                out_dir=r.get("out_dir"), content_hash=r.get("content_hash"), single_file=bool(r.get("single_file")),
                n_files=r.get("files"), verdict=r.get("verdict"), **_c)
        if r["verdict"] == "SKIP":                  # triaged out: listed with its class, never silently dropped
            report.setdefault("triaged_out", []).append({"source": rel, **r["triage"]})
            if not a.dry_run:
                ledger.record(rel, f["content_hash"], R.PIPELINE_VERSION, "SKIP")
            live.done(rel, "SKIP")
            return
        print(f"  verification: {r['verdict']}  files={r['files']}  [{rel}]", flush=True)
        live.file(rel, stage="checking")
        try:
            now = _retry(lambda: src.identity(rel, f), "re-check")
        except Exception as e:                      # noqa: BLE001
            results.pop()
            if _transient(e) and rel not in second:    # the reading is done: only the re-check is repeated later
                second.add(rel)
                later.append(("recheck", rel, f, r))
                print(f"  connection lost while re-checking; will re-check again at the end of the run  [{rel}]", flush=True)
                return
            failed(rel, e, "re-checking the source")
            return
        if (now["id"], now["rev"], now["size"]) != (f["id"], f["rev"], f["size"]):
            raise SystemExit(f"SOURCE CHANGED during the run: {rel} — stopping, nothing more uploaded")
        doc = {"source": rel, "verdict": r["verdict"], "files": r["files"], "uploaded": 0,
               "dest": f"{dest_root}/{r['out_dir'].replace(os.sep, '/')}"}
        if r["verdict"] not in ("PASS", "METADATA"):
            # a document that fails verification is never published; it stays local
            print(f"  NOT uploaded (failed verification) — local copy: {os.path.join(out, r['out_dir'])}", flush=True)
        elif not a.dry_run:
            key = r["out_dir"].replace(os.sep, "/")
            files = _read_files(os.path.join(out, r["out_dir"]))
            live.file(rel, stage="uploading")
            # live folder is not touched until promote
            inflight[up.submit(_retry, lambda k=key, fs=files: pub.stage(k, fs), "upload")] = ("upload", rel, f, (doc, key, files, r))
            return
        report["documents"].append(doc)
        live.done(rel, r["verdict"])

    try:
        while todo or inflight or ready or later:
            if later and not (todo or inflight or ready):
                # 2026-11-26, the Mac in Docker: Dropbox could not be reached for a few minutes mid-run and two files
                # failed as "network dropped" although the rest of the run was fine. Give the connection time, then
                # try those files once more before the run ends.
                print(f"\n{len(later)} file(s) stopped by a dropped connection; waiting {NET_PAUSE} s, then trying "
                      "them once more", flush=True)
                time.sleep(NET_PAUSE)
                again, later[:] = list(later), []
                for item in again:
                    if item[0] == "download":
                        todo.append((item[1], item[2]))
                    else:
                        after_read(item[1], item[2], item[3])
                continue
            dispatch()
            while todo and ahead() < window:
                start_download(*todo.popleft())
            if not inflight:
                continue
            finished, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
            for fut in finished:
                step, rel, f, extra = inflight.pop(fut)
                if step == "download":
                    try:
                        fut.result()
                    except Exception as e:          # noqa: BLE001 - SystemExit (safety stops) is not caught
                        reserved -= f.get("size") or 0
                        if _transient(e) and rel not in second:
                            second.add(rel)
                            later.append(("download", rel, f))
                            print(f"  connection lost while downloading; will try again at the end of the run  [{rel}]",
                                  flush=True)
                            continue
                        failed(rel, e, "reading the file")
                        continue
                    cost = min(_cost(extra), budget)
                    live.file(rel, stage="ready", bytes=f.get("size") or 0, scan=cost > 1)   # "reading" once a reader takes it
                    ready.append((rel, f, extra, cost))
                elif step == "read":
                    lp, cost = extra
                    used -= cost
                    reserved -= f.get("size") or 0
                    try:
                        r = fut.result()
                    except BrokenProcessPool as e:
                        # a reader process died (most often: out of memory). Every file it held fails with it; try each
                        # once more in a fresh pool, and give up on a file that breaks it twice.
                        if not readers.processes or rel in retried:
                            failed(rel, e, "reading the file (the reader stopped, likely out of memory)")
                            continue
                        retried.add(rel)
                        if readers.broken():                # once per broken pool, not once per file it held
                            readers.renew()
                            P.drain(readers.q, live)
                        reserved += f.get("size") or 0
                        ready.appendleft((rel, f, lp, cost))
                        continue
                    except Exception as e:          # noqa: BLE001
                        failed(rel, e, "reading the file")
                        continue
                    after_read(rel, f, r)
                else:                               # upload
                    doc, key, files, r = extra
                    try:
                        fut.result()
                    except Exception as e:          # noqa: BLE001
                        if r in results:
                            results.remove(r)
                        failed(rel, e, "uploading")
                        continue
                    doc["uploaded"], doc["key"] = len(files), key
                    pending.append((rel, f["content_hash"], doc))
                    report["documents"].append(doc)
                    print(f"  staged {len(files)} file(s) -> {stage_root}/{stamp}/{key}", flush=True)
                    live.done(rel, r["verdict"])
    except BaseException:
        readers.stop()                              # a safety stop ends the readers at once, mid-file
        dl.shutdown(wait=False, cancel_futures=True)
        up.shutdown(wait=False, cancel_futures=True)
        raise
    readers.close()
    dl.shutdown()
    up.shutdown()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-link", required=True)
    ap.add_argument("--dest-link", default=None, help="output folder; may be left out with --dry-run (results stay local)")
    ap.add_argument("--room-dir", default=None, help="a room's own folder: its results and its ledger of what was distilled "
                                                      "persist there, so a stopped run can carry on")
    ap.add_argument("--publish-from", default=None, help="publish the accepted results listed in this JSON file "
                                                          "(from a room's results folder) instead of distilling")
    ap.add_argument("--events", default=None, help="write one JSON line per file event to this path (used by the web interface)")
    ap.add_argument("--work", default=os.path.join(D.DATA_DIR, "work"))
    ap.add_argument("--dry-run", action="store_true", help="distill and verify, upload nothing")
    ap.add_argument("--force", action="store_true", help="re-distill even if the ledger says the file is up to date")
    ap.add_argument("--only", default=None, help="only files whose name contains this text ('a|b': either)")
    ap.add_argument("--publish-protected-metadata", action="store_true",
                    help="publish a metadata-only entry for protected files (they are always listed in the report)")
    ap.add_argument("--rollback", default=None, metavar="RUN", help="undo a published run: restore the previous versions (from Dropbox deleted files, or the old archive folder)")
    ap.add_argument("--workers", type=int, default=1, help="capacity points for reading: a text file takes 1, a scanned "
                                                            "file (OCR) 2; files are read at once while their points fit")
    ap.add_argument("--live", default=None, help="keep every file's step in this JSON file while the run goes (web interface)")
    a = ap.parse_args(argv)
    if not a.dest_link and not a.dry_run:
        ap.error("--dest-link is required unless --dry-run")
    if not a.dest_link and a.rollback:
        ap.error("--rollback needs --dest-link")
    ev = Events(a.events)

    src = B.open_source(a.source_link)                     # Dropbox or Google Drive, read-only connection
    dst = B.open_dest(a.dest_link, src) if a.dest_link else None   # guarded writer; raises if the folders overlap
    dest_root, stage_root, archive_root = (dst.root, dst.stage_root, dst.archive_root) if dst else ("", "", "")
    src_name = src.name
    print(f"source {src.provider}:{src.label} (read-only)  ->  "
          + (f"output {dst.provider}:{dest_root}" if dst else "no output folder (results stay on this machine)"), flush=True)

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(a.room_dir, "out") if a.room_dir else os.path.join(a.work, "runs", stamp)
    rledger = None
    if a.room_dir:
        os.makedirs(a.room_dir, exist_ok=True)
        rledger = Ledger(os.path.join(a.room_dir, "ledger.json"), src.label)
    cache = os.path.join(a.work, "cache")
    os.makedirs(cache, exist_ok=True)
    if a.rollback:
        mp = os.path.join(a.work, "publish", f"publish-{a.rollback}.json")
        undo = Publisher.load(dst.store, mp, os.path.join(a.work, "publish"))
        undo.rollback()
        ledger = Ledger(os.path.join(a.work, "ledger.json"), src.label)
        keys = set(undo.docs)
        for rel_, e in list(ledger.docs.items()):
            if e.get("dest", "").replace(dest_root + "/", "", 1) in keys:
                del ledger.docs[rel_]            # next run will distill these again
        ledger.save()
        print(f"rolled back run {a.rollback}: {len(keys)} document(s) restored to their previous version", flush=True)
        return 0
    workers = max(1, a.workers)
    # Dropbox takes several downloads at once; the Google Drive client is not safe to share between threads
    downloads = min(3, workers + 1) if src.provider == "dropbox" else 1
    live = P.LiveState(a.live, workers)
    if a.publish_from:
        try:
            return _publish_accepted(a, src, dst, ev, dest_root, stage_root, archive_root, live)
        finally:
            live.close()
    try:
        return _distill_run(a, src, dst, ev, live, workers, downloads, src_name, stamp, out, rledger, cache,
                            dest_root, stage_root, archive_root)
    finally:
        live.close()


def _distill_run(a, src, dst, ev, live, workers, downloads, src_name, stamp, out, rledger, cache,
                 dest_root, stage_root, archive_root):
    before = _retry(src.snapshot, "listing the input folder")   # also the first call: signing in to Dropbox
    print(f"files to check: {sum(1 for r in before if r.lower().endswith(SUPPORTED))}", flush=True)
    report = {"source": src.label, "source_provider": src.provider, "dest": dest_root,
              "dest_provider": dst.provider if dst else "", "run": stamp, "documents": []}
    ev.emit("listing", files=[{"rel": r_, "size": f_.get("size"), "kind": kind_of(r_)} for r_, f_ in sorted(before.items())])
    results = []
    seen_hash = {}
    pub = Publisher(dst.store, dest_root, stage_root, archive_root, stamp, os.path.join(a.work, "publish")) if dst else None
    pending = []       # (rel, content_hash, doc) staged this run, promoted together at the end
    ledger = Ledger(os.path.join(a.work, "ledger.json"), src.label)

    # ---- editions a newer one in this input folder replaces: their files are joined into larger ones (plan C2)
    from . import editions as ED
    reg = ED.registry([{"rel": r_, "edition": ED.identify(r_)} for r_ in before])
    a.older_editions = {x["rel"] for x in reg if (x.get("edition") or {}).get("status") == "superseded"}
    if a.older_editions:
        print(f"older editions (larger files): {len(a.older_editions)}", flush=True)

    # ---- which files this run reads (cheap: decided from the listing alone)
    known = _known(a.room_dir) if a.room_dir else None
    plan = []
    for rel, f in sorted(before.items()):
        name = rel.rsplit("/", 1)[-1]
        if not rel.lower().endswith(SUPPORTED):
            print(f"skip (format not handled yet): {rel}", flush=True)
            report.setdefault("unsupported", []).append({"source": rel, "reason": "format not handled yet"})
            ev.emit("file", rel=rel, kind=kind_of(rel), outcome="unprocessable", reason="unsupported",
                    detail=SC.REASONS["unsupported"])
            continue
        if a.only and not any(o and o in name for o in a.only.split("|")):
            continue
        first = seen_hash.get(f["content_hash"])
        if first:                                   # F-26: duplicate sources are detected by content hash
            print(f"skip duplicate of {first}: {rel}", flush=True)
            report.setdefault("duplicates", []).append({"source": rel, "duplicate_of": first})
            ev.emit("file", rel=rel, kind=kind_of(rel), outcome="skipped", reason="duplicate", detail=f"same content as {first}")
            live.skipped()
            continue
        seen_hash[f["content_hash"]] = rel
        if _skip(a, ledger, rledger, rel, f["content_hash"], known):
            print(f"unchanged since last run, skipped: {rel}", flush=True)
            report.setdefault("unchanged", []).append(rel)
            ev.emit("unchanged", rel=rel)
            live.skipped()
            continue
        plan.append((rel, f))
    live.set(stage="running", total=len(plan) + live.s["skipped"], queued=[r_ for r_, _ in plan])
    print(f"to read: {len(plan)} file(s), {workers} at a time, {downloads} download(s) at a time", flush=True)
    _pipeline(a, plan, src, src_name, out, cache, rledger, ledger, ev, live, workers, downloads, results, report,
              pending, pub, dest_root, stage_root, stamp)

    if pending:
        # promote the whole run at once; a document that changed layout (single file <-> folder)
        # also replaces its old variant. The previous versions are kept in the archive for rollback.
        replaces = {}
        for _, _, d in pending:
            k = d["key"]
            replaces[k] = [k[:-len(".pdf.md")]] if k.endswith(".pdf.md") else [k + ".pdf.md"]
        pub.promote(replaces=replaces)
        for rel_, h_, d in pending:
            ledger.record(rel_, h_, R.PIPELINE_VERSION, "PASS", d["dest"], d["uploaded"])
        report["published_run"] = stamp
        print(f"\npromoted {len(pending)} document(s); undo with: python -m app.distill.sync --rollback {stamp}", flush=True)

    gone = ledger.removed(before.keys())
    if gone:   # renames/deletions wait for administrator confirmation; published files stay untouched
        report["removed_sources"] = gone
        print(f"{len(gone)} previously distilled source(s) no longer present; published files left untouched: {gone[:5]}", flush=True)
    after = _retry(src.snapshot, "final source check")
    diffs = D.compare_snapshots(before, after)
    report["source_unchanged"] = not diffs
    report["diffs"] = diffs
    report["source_snapshot"] = {k: {x: v[x] for x in ("id", "rev", "content_hash")} for k, v in before.items()}
    # Audit trail stays on this machine (nothing but distilled chapters goes to Dropbox):
    # one file per run, per source folder, never overwritten.
    audit = os.path.join(a.work, "audit", src_name)
    os.makedirs(audit, exist_ok=True)
    with open(os.path.join(audit, f"{stamp}.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "source_snapshot"}, indent=1))
    return 0 if not diffs else 2


def _entry():
    """Run main(); when the web interface supervises this process it names a file (FIDELITY_EXIT_FILE) where the
    exit code is written, so a supervisor that was restarted meanwhile can still tell finished from killed."""
    code = 1
    try:
        code = main() or 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if isinstance(e.code, str):
            print(e.code, flush=True)
    except BaseException:                                  # noqa: BLE001 - the supervisor needs the exit code in every case
        import traceback
        traceback.print_exc()
        code = 1
    finally:
        path = os.environ.get("FIDELITY_EXIT_FILE")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(str(code))
            except OSError:
                pass
    return code


if __name__ == "__main__":
    sys.exit(_entry())
