# -*- coding: utf-8 -*-
"""Distillation as a background job (spec F-17, Phase 2 'job integration').

kind = "distill:<source id>", rel = path of a PDF inside that source's folder (read-only).
Output goes to <data>/distilled/<source id>/ (local sink); a result file per job is written to
<data>/distilled_reports/<source id>/<job id>.json so the API can show the verdict.
"""
import json
import os

from .. import config
from ..distill.office import SUPPORTED, distill_any



def out_root(sid):
    return os.path.join(config.DATA_DIR, "distilled", sid)


def report_path(sid, jid):
    return os.path.join(config.DATA_DIR, "distilled_reports", sid, jid + ".json")


def summarize(r):
    rep = r.get("report", {})
    s = {"verdict": r["verdict"], "files": r.get("files", 0), "pages": r.get("pages", 0),
         "single_file": r.get("single_file", False), "out": r.get("out_dir", "")}
    if r["verdict"] == "SKIP":
        s["triage"] = r.get("triage")
    else:
        s["checks"] = {k: rep[k].get("ok") for k in ("pages", "headings", "chars", "numbers", "extra_text",
                                                      "agreement", "tables") if k in rep}
        s["instruction_like"] = rep.get("instruction_like", {}).get("count", 0)
    return s


def handle_distill(job, report):
    sid = job["kind"].split(":", 1)[1] if ":" in job["kind"] else "n2"
    src = config.get_source(sid)
    if not src:
        raise RuntimeError("source %s not configured" % sid)
    rel = job["rel"]
    path = os.path.normpath(os.path.join(src["src_root"], rel))
    root = os.path.abspath(src["src_root"])
    if os.path.commonpath([root, os.path.abspath(path)]) != root:
        raise RuntimeError("path escapes the source folder")
    if not os.path.isfile(path):
        raise RuntimeError("source file not found: %s" % rel)
    if not rel.lower().endswith(SUPPORTED):
        raise RuntimeError("format not handled yet: %s" % os.path.splitext(rel)[1])
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    report(5, "distilling")
    r = distill_any(path, rel, out_root(sid), "", config.CACHE_DIR,
                      log=lambda m: report(30, str(m).strip()[:120]))
    summary = summarize(r)
    rp = report_path(sid, job["id"])
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"rel": rel, "sid": sid, **summary}, f, ensure_ascii=False, indent=1)
    report(95, "%s" % summary["verdict"])
    return summary


def list_source_files(sid, folder="", limit=500):
    src = config.get_source(sid)
    if not src:
        return None
    root = os.path.abspath(src["src_root"])
    base = os.path.abspath(os.path.join(root, folder))
    if os.path.commonpath([root, base]) != root:
        return None
    out = []
    for d, _, fns in os.walk(base):
        for fn in sorted(fns):
            if fn.lower().endswith(SUPPORTED):
                out.append(os.path.relpath(os.path.join(d, fn), root).replace(os.sep, "/"))
                if len(out) >= limit:
                    return out
    return out
