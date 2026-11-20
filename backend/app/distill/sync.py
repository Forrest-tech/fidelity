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
from . import scoring as SC
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
_BACKOFF = (2, 5, 15)


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


def _check_space(work, size):
    """Stop cleanly before a download would fill the disk (a real run died mid-download with
    "No space left on device", and even the error could not be saved)."""
    free = shutil.disk_usage(work).free
    need = 3 * size + MIN_FREE      # the file, its rendered pages / extracted text, and headroom
    if free < need:
        raise SystemExit(f"not enough free disk space on this machine: {free / 1e9:.1f} GB free, "
                         f"about {need / 1e9:.1f} GB needed for the next file — stopped before downloading")


def _skip(a, ledger, rledger, rel, content_hash) -> bool:
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
    return a.dry_run or e["verdict"] not in ("PASS", "METADATA") or ledger.up_to_date(rel, content_hash, R.PIPELINE_VERSION)


def _err(e) -> str:
    return f"{type(e).__name__}: {e}"[:300]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-link", required=True)
    ap.add_argument("--dest-link", default=None, help="output folder; may be left out with --dry-run (results stay local)")
    ap.add_argument("--room-dir", default=None, help="a room's own folder: its results and its ledger of what was distilled "
                                                      "persist there, so a stopped run can carry on")
    ap.add_argument("--events", default=None, help="write one JSON line per file event to this path (used by the web interface)")
    ap.add_argument("--work", default=os.path.join(D.DATA_DIR, "work"))
    ap.add_argument("--dry-run", action="store_true", help="distill and verify, upload nothing")
    ap.add_argument("--force", action="store_true", help="re-distill even if the ledger says the file is up to date")
    ap.add_argument("--only", default=None, help="only files whose name contains this text")
    ap.add_argument("--publish-protected-metadata", action="store_true",
                    help="publish a metadata-only entry for protected files (they are always listed in the report)")
    ap.add_argument("--rollback", default=None, metavar="RUN", help="undo a published run: restore the previous versions from the archive")
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
    before = src.snapshot()
    print(f"files to check: {sum(1 for r in before if r.lower().endswith(SUPPORTED))}", flush=True)
    report = {"source": src.label, "source_provider": src.provider, "dest": dest_root,
              "dest_provider": dst.provider if dst else "", "run": stamp, "documents": []}
    ev.emit("listing", files=[{"rel": r_, "size": f_.get("size"), "kind": kind_of(r_)} for r_, f_ in sorted(before.items())])
    results = []
    seen_hash = {}
    pub = Publisher(dst.store, dest_root, stage_root, archive_root, stamp, os.path.join(a.work, "publish")) if dst else None
    pending = []       # (rel, content_hash, doc) staged this run, promoted together at the end
    ledger = Ledger(os.path.join(a.work, "ledger.json"), src.label)

    for rel, f in sorted(before.items()):
        name = rel.rsplit("/", 1)[-1]
        if not rel.lower().endswith(SUPPORTED):
            print(f"skip (format not handled yet): {rel}", flush=True)
            report.setdefault("unsupported", []).append({"source": rel, "reason": "format not handled yet"})
            ev.emit("file", rel=rel, kind=kind_of(rel), outcome="unprocessable", reason="unsupported",
                    detail=SC.REASONS["unsupported"])
            continue
        if a.only and a.only not in name:
            continue
        first = seen_hash.get(f["content_hash"])
        if first:                                   # F-26: duplicate sources are detected by content hash
            print(f"skip duplicate of {first}: {rel}", flush=True)
            report.setdefault("duplicates", []).append({"source": rel, "duplicate_of": first})
            ev.emit("file", rel=rel, kind=kind_of(rel), outcome="skipped", reason="duplicate", detail=f"same content as {first}")
            continue
        seen_hash[f["content_hash"]] = rel
        if _skip(a, ledger, rledger, rel, f["content_hash"]):
            print(f"unchanged since last run, skipped: {rel}", flush=True)
            report.setdefault("unchanged", []).append(rel)
            ev.emit("unchanged", rel=rel)
            continue
        rel_local = os.path.join(src_name, *rel.strip("/").split("/"))
        lp = os.path.join(a.work, "src", rel_local)
        print(f"\n[{len(results) + 1}] {rel}", flush=True)

        ev.emit("start", rel=rel)

        def failed(e, step):
            err = _err(e)
            print(f"  verification: FAIL  (error while {step}: {err})", flush=True)
            ev.emit("file", rel=rel, kind=kind_of(rel), **SC.classify(None, error=f"{step}: {err}"))
            results.append({"verdict": "FAIL"})
            report["documents"].append({"source": rel, "verdict": "FAIL", "files": 0, "uploaded": 0,
                                        "error": f"{step}: {err}"})

        try:
            if not src.local_matches(lp, f):
                os.makedirs(a.work, exist_ok=True)
                _check_space(a.work, f["size"])
                print(f"  download ({f['size'] / 1e6:.1f} MB)", flush=True)
                _retry(lambda: src.download(rel, f, lp), "download")
            if not src.verify_local(lp, f):
                raise SystemExit(f"local copy of {rel} does not match the source file's checksum")
            r = distill_any(lp, rel_local, out, "", cache, log=lambda m: print(m, flush=True),
                            publish_protected=a.publish_protected_metadata)
        except Exception as e:                      # SystemExit (safety stops) is not caught
            failed(e, "reading the file")
            continue
        results.append(r)
        if rledger is not None:                     # a result of any quality is remembered, so a resumed run skips it
            rledger.record(rel, f["content_hash"], R.PIPELINE_VERSION, r["verdict"])
        _c = SC.classify(r)
        ev.emit("file", rel=rel, kind=kind_of(rel), pages=r.get("pages"), scan=_c.get("basis") == "ocr_agreement", **_c)
        if r["verdict"] == "SKIP":                  # triaged out: listed with its class, never silently dropped
            report.setdefault("triaged_out", []).append({"source": rel, **r["triage"]})
            if not a.dry_run:
                ledger.record(rel, f["content_hash"], R.PIPELINE_VERSION, "SKIP")
            continue
        print(f"  verification: {r['verdict']}  files={r['files']}", flush=True)

        try:
            now = _retry(lambda: src.identity(rel, f), "re-check")
        except Exception as e:
            results.pop()
            failed(e, "re-checking the source")
            continue
        if (now["id"], now["rev"], now["size"]) != (f["id"], f["rev"], f["size"]):
            raise SystemExit(f"SOURCE CHANGED during the run: {rel} — stopping, nothing more uploaded")

        doc = {"source": rel, "verdict": r["verdict"], "files": r["files"], "uploaded": 0,
               "dest": f"{dest_root}/{r['out_dir'].replace(os.sep, '/')}"}
        if r["verdict"] not in ("PASS", "METADATA"):
            # a document that fails verification is never published; it stays local
            print(f"  NOT uploaded (failed verification) — local copy: {os.path.join(out, r['out_dir'])}", flush=True)
        elif not a.dry_run:
            key = r["out_dir"].replace(os.sep, "/")
            files = {}
            if r.get("single_file"):
                with open(R.longpath(os.path.join(out, r["out_dir"])), "rb") as fh:
                    files[""] = fh.read()
            else:
                base = os.path.join(out, r["out_dir"])
                for root_, _, fns_ in os.walk(R.longpath(base)):
                    for fn_ in sorted(fns_):
                        lp_ = os.path.join(root_, fn_)
                        with open(lp_, "rb") as fh:
                            files[os.path.relpath(lp_, R.longpath(base)).replace(os.sep, "/")] = fh.read()
            try:
                _retry(lambda: pub.stage(key, files), "upload")   # live folder is not touched until promote
            except Exception as e:
                results.pop()
                failed(e, "uploading")
                continue
            doc["uploaded"] = len(files)
            doc["key"] = key
            pending.append((rel, f["content_hash"], doc))
            print(f"  staged {len(files)} file(s) -> {stage_root}/{stamp}/{key}", flush=True)
        report["documents"].append(doc)

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
