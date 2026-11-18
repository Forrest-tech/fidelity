# -*- coding: utf-8 -*-
"""Distil a non-PDF document (Office, web snapshot, e-mail) into one verified Markdown file.

Same output conventions as the PDF route: front matter, library unit markers, verification
by an independent reader, instruction-text flags, untrusted output under _pending/.
"""
from __future__ import annotations

import json
import os
import time

from . import formats as F
from . import run as R
from .structure import unit_open, UNIT_CLOSE
from .triage import scan_instructions


def _marker(i: int, u: F.Unit) -> str:
    flags = list(u.flags) + (["instruction_like"] if scan_instructions(u.text) else [])
    head = unit_open(i, len(u.text), ",".join(flags) if flags else "-")
    # unit_open writes 'src: p.N' for paged sources; non-paged units name their own location
    head = head.replace(f"src: p.{i} ", f"src: {u.src} ", 1).replace(f"unit: p{i:04d}", f"unit: u{i:04d}", 1)
    return head


def distill_document(path, rel_path, out_root, source_prefix, cache_dir, log=print):
    t0 = time.time()
    name = os.path.splitext(os.path.basename(rel_path))[0]
    rel_dir = os.path.dirname(rel_path)
    h = R.dropbox_content_hash(path)
    src_display = "/" + "/".join(x for x in [source_prefix.strip("/"), rel_path.replace(os.sep, "/")] if x)
    try:
        units = F.extract_any(path)
    except Exception as e:  # encrypted / corrupt Office files raise here
        reason = str(e)[:160]
        cls = "protected" if "encrypt" in reason.lower() or "password" in reason.lower() else "unsupported"
        tri = {"class": cls, "reason": f"cannot read: {reason}"}
        log(f"  triage: {cls} - {reason}")
        return {"name": name, "rel_path": rel_path, "source": src_display, "status": "", "verdict": "SKIP",
                "triage": tri, "pages": 0, "files": 0, "single_file": False, "max_file_chars": 0,
                "total_chars": 0, "content_hash": h, "out_dir": "", "report": {"status": "SKIP", "triage": tri}}
    rep = F.verify_units(units or [], F.raw_any(path))
    h_after = R.dropbox_content_hash(path)
    rep["source_unchanged"] = {"ok": h == h_after, "content_hash": h}
    if not rep["source_unchanged"]["ok"]:
        rep["status"] = "FAIL"
    instr = [{"unit": u.src, "text": s} for u in units for s in scan_instructions(u.text)]
    rep["instruction_like"] = {"count": len(instr), "examples": instr[:20]}
    rep["triage"] = {"class": "text", "reason": os.path.splitext(path)[1].lower() + " extractor"}
    rep["seconds"] = round(time.time() - t0, 1)
    trusted = rep["status"] == "PASS"

    body_parts = []
    for i, u in enumerate(units, 1):
        body_parts.append(_marker(i, u) + "\n\n" + u.text.strip() + "\n\n" + UNIT_CLOSE)
    body = "\n\n".join(body_parts) + "\n"
    status = R.doc_status(name)
    std = R.parse_standard(name)
    flags = sorted({f for u in units for f in u.flags} | ({"instruction_like"} if instr else set()))
    fm = ["---",
          f"document: {R._yaml_str(name)}",
          f"format_version: {R.FORMAT_VERSION}",
          f"status: {R._yaml_str(status)}",
          f"edition_status: {R.edition_status(status)}",
          f"std_id: {R._yaml_str(std['std_id'])}",
          f"std_year: {R._yaml_str(std['std_year'])}",
          f"std_kind: {R._yaml_str(std['std_kind'])}",
          f"jurisdiction: {R._yaml_str(std['jurisdiction'])}",
          "languages: [en]",
          f"units: {len(units)}",
          f"cite_as: {R._yaml_str(name + ', <location in the nearest unit marker (src: ...)>')}",
          f"source: {R._yaml_str(src_display + ' (content_hash ' + h[:12] + ')')}",
          f"source_filename: {R._yaml_str(os.path.basename(rel_path))}",
          f"source_relative_path: {R._yaml_str(rel_path.replace(os.sep, '/'))}",
          f"source_file_hash: {h}",
          f"parser: {R.PIPELINE_VERSION}/{os.path.splitext(path)[1].lower().lstrip('.')}",
          f"audit_status: {'auto_verified' if trusted else 'pending_review'}",
          f"flags: [{', '.join(flags)}]",
          f"verified: {R._yaml_str('PASS' if trusted else 'FAIL - not trusted')}",
          "---", ""]
    banner = f"> **{status.upper()}.** Not in force.\n\n" if status.startswith("DRAFT") else ""
    base = os.path.join(out_root, rel_dir) if trusted else os.path.join(out_root, "_pending", rel_dir)
    os.makedirs(base, exist_ok=True)
    fn = os.path.basename(rel_path) + ".md"
    with open(R.longpath(os.path.join(base, fn)), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(fm) + banner + body)
    with open(os.path.join(cache_dir, h + ".report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    return {"name": name, "rel_path": rel_path, "source": src_display, "status": status,
            "verdict": rep["status"], "pages": 0, "files": 1, "single_file": True, "verdict_trusted": trusted,
            "max_file_chars": len(body), "total_chars": len(body), "content_hash": h,
            "out_dir": os.path.relpath(os.path.join(base, fn), out_root), "report": rep}


def distill_any(path, rel_path, out_root, source_prefix, cache_dir, log=print, publish_protected=False):
    """Entry point for every supported format."""
    if path.lower().endswith(".pdf"):
        return R.distill_pdf(path, rel_path, out_root, source_prefix, cache_dir, log=log,
                             publish_protected=publish_protected)
    return distill_document(path, rel_path, out_root, source_prefix, cache_dir, log=log)


SUPPORTED = (".pdf",) + tuple(F.EXTRACTORS)
