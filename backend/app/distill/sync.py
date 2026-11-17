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
    ap.add_argument("--only", default=None, help="only files whose name contains this text")
    ap.add_argument("--prune", action="store_true",
                    help="after uploading a document, delete older files left in ITS output folder")
    a = ap.parse_args(argv)

    reader, writer = D.client("reader"), D.client("writer")
    src_root = D.link_root(reader, a.source_link)          # e.g. /2025
    dest_root = D.link_root(writer, a.dest_link)           # e.g. /transfer_md
    if not dest_root:
        raise SystemExit("The output link must be a folder in your own Dropbox")
    src_name = src_root.rstrip("/").split("/")[-1] if src_root else "source"
    guard = D.SafeWriter(writer, dest_root, [src_root])     # raises if the roots overlap
    print(f"source {src_root or a.source_link} (read-only)  ->  output {dest_root}", flush=True)

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(a.work, "runs", stamp)
    cache = os.path.join(a.work, "cache")
    os.makedirs(cache, exist_ok=True)
    before = D.snapshot(reader, a.source_link)
    report = {"source": src_root, "dest": dest_root, "run": stamp, "documents": []}
    results = []

    for rel, f in sorted(before.items()):
        name = rel.rsplit("/", 1)[-1]
        if not rel.lower().endswith(SUPPORTED):
            print(f"skip (format not handled yet): {rel}", flush=True)
            continue
        if a.only and a.only not in name:
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
            n0 = len(guard.written)
            doc["uploaded"] = guard.upload_tree(os.path.join(out, r["out_dir"]), dest_prefix=doc["dest"])
            mine = {D._norm(p) for p in guard.written[n0:]}
            stale = sorted(p for p in D.list_tree(writer, doc["dest"]) if p not in mine)
            doc["stale_remote_files"] = len(stale)
            if stale and a.prune:
                for p in stale:
                    guard.delete(p)
                doc["pruned"] = len(stale)
            print(f"  uploaded {doc['uploaded']} files -> {doc['dest']}"
                  + (f"; {len(stale)} older files {'removed' if a.prune else 'left in place (use --prune)'}" if stale else ""),
                  flush=True)
        report["documents"].append(doc)

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
