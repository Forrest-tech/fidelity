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
import sys

from . import dropbox_io as D
from . import run as R
from .ledger import Ledger
from .publish import Publisher

SUPPORTED = (".pdf",)


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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-link", required=True)
    ap.add_argument("--dest-link", required=True)
    ap.add_argument("--work", default=os.path.join(D.DATA_DIR, "work"))
    ap.add_argument("--dry-run", action="store_true", help="distill and verify, upload nothing")
    ap.add_argument("--force", action="store_true", help="re-distill even if the ledger says the file is up to date")
    ap.add_argument("--only", default=None, help="only files whose name contains this text")
    ap.add_argument("--rollback", default=None, metavar="RUN", help="undo a published run: restore the previous versions from the archive")
    a = ap.parse_args(argv)

    reader, writer = D.client("reader"), D.client("writer")
    src_root = D.link_root(reader, a.source_link)          # e.g. /2025
    dest_root = D.link_root(writer, a.dest_link)           # e.g. /transfer_md
    if not dest_root:
        raise SystemExit("The output link must be a folder in your own Dropbox")
    src_name = src_root.rstrip("/").split("/")[-1] if src_root else "source"
    stage_root, archive_root = dest_root.rstrip("/") + "_staging", dest_root.rstrip("/") + "_archive"
    guard = D.SafeWriter(writer, dest_root, [src_root], extra_roots=[stage_root, archive_root])  # raises on overlap
    print(f"source {src_root or a.source_link} (read-only)  ->  output {dest_root}", flush=True)

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(a.work, "runs", stamp)
    cache = os.path.join(a.work, "cache")
    os.makedirs(cache, exist_ok=True)
    if a.rollback:
        mp = os.path.join(a.work, "publish", f"publish-{a.rollback}.json")
        undo = Publisher.load(D.DropboxStore(guard), mp, os.path.join(a.work, "publish"))
        undo.rollback()
        ledger = Ledger(os.path.join(a.work, "ledger.json"), src_root or a.source_link)
        keys = set(undo.docs)
        for rel_, e in list(ledger.docs.items()):
            if e.get("dest", "").replace(dest_root + "/", "", 1) in keys:
                del ledger.docs[rel_]            # next run will distill these again
        ledger.save()
        print(f"rolled back run {a.rollback}: {len(keys)} document(s) restored to their previous version", flush=True)
        return 0
    before = D.snapshot(reader, a.source_link)
    report = {"source": src_root, "dest": dest_root, "run": stamp, "documents": []}
    results = []
    seen_hash = {}
    pub = Publisher(D.DropboxStore(guard), dest_root, stage_root, archive_root, stamp, os.path.join(a.work, "publish"))
    pending = []       # (rel, content_hash, doc) staged this run, promoted together at the end
    ledger = Ledger(os.path.join(a.work, "ledger.json"), src_root or a.source_link)

    for rel, f in sorted(before.items()):
        name = rel.rsplit("/", 1)[-1]
        if not rel.lower().endswith(SUPPORTED):
            print(f"skip (format not handled yet): {rel}", flush=True)
            report.setdefault("unsupported", []).append({"source": rel, "reason": "format not handled yet"})
            continue
        if a.only and a.only not in name:
            continue
        first = seen_hash.get(f["content_hash"])
        if first:                                   # F-26: duplicate sources are detected by content hash
            print(f"skip duplicate of {first}: {rel}", flush=True)
            report.setdefault("duplicates", []).append({"source": rel, "duplicate_of": first})
            continue
        seen_hash[f["content_hash"]] = rel
        if not a.force and ledger.up_to_date(rel, f["content_hash"], R.PIPELINE_VERSION):
            print(f"unchanged since last run, skipped: {rel}", flush=True)
            report.setdefault("unchanged", []).append(rel)
            continue
        rel_local = os.path.join(src_name, *rel.strip("/").split("/"))
        lp = os.path.join(a.work, "src", rel_local)
        print(f"\n[{len(results) + 1}] {rel}", flush=True)
        if not (os.path.exists(lp) and R.dropbox_content_hash(lp) == f["content_hash"]):
            print(f"  download ({f['size'] / 1e6:.1f} MB)", flush=True)
            D.download(reader, a.source_link, rel, lp)
        if R.dropbox_content_hash(lp) != f["content_hash"]:
            raise SystemExit(f"local copy of {rel} does not match Dropbox content_hash")

        r = R.distill_pdf(lp, rel_local, out, "", cache, log=lambda m: print(m, flush=True))
        results.append(r)
        if r["verdict"] == "SKIP":                  # triaged out: listed with its class, never silently dropped
            report.setdefault("triaged_out", []).append({"source": rel, **r["triage"]})
            if not a.dry_run:
                ledger.record(rel, f["content_hash"], R.PIPELINE_VERSION, "SKIP")
            continue
        print(f"  verification: {r['verdict']}  files={r['files']}", flush=True)

        now = D.file_identity(reader, a.source_link, rel)
        if (now["id"], now["rev"], now["size"]) != (f["id"], f["rev"], f["size"]):
            raise SystemExit(f"SOURCE CHANGED during the run: {rel} — stopping, nothing more uploaded")

        doc = {"source": rel, "verdict": r["verdict"], "files": r["files"], "uploaded": 0,
               "dest": f"{dest_root}/{r['out_dir'].replace(os.sep, '/')}"}
        if r["verdict"] != "PASS":
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
            pub.stage(key, files)                    # live folder is not touched until promote
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
    after = D.snapshot(reader, a.source_link)
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


if __name__ == "__main__":
    sys.exit(main())
