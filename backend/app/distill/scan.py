# -*- coding: utf-8 -*-
"""Scan / image route (spec F-22): OCR every page with two engines, correct, vote, route.

A document is published only when every page is accepted automatically; otherwise it goes to
_pending/ with verdict REVIEW (the human review queue), page by page reasons in the report.
"""
from __future__ import annotations

import json
import os
import time

from . import ocr as O
from . import run as R
from .structure import UNIT_CLOSE, unit_open
from .triage import scan_instructions

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")


def _images(path):
    """Yield (page number, PIL image) for a scanned PDF or an image file (multi-page TIFF too)."""
    from PIL import Image, ImageSequence
    if path.lower().endswith(".pdf"):
        import pymupdf
        n = pymupdf.open(path).page_count
        for i in range(n):
            yield i + 1, O.render_page(path, i)
    else:
        with Image.open(path) as im:
            for i, frame in enumerate(ImageSequence.Iterator(im), 1):
                yield i, frame.convert("L").copy()


def distill_scan(path, rel_path, out_root, source_prefix, cache_dir, log=print, engines=None, max_pages=400):
    t0 = time.time()
    name = os.path.splitext(os.path.basename(rel_path))[0]
    rel_dir = os.path.dirname(rel_path)
    h = R.dropbox_content_hash(path)
    src_display = "/" + "/".join(x for x in [source_prefix.strip("/"), rel_path.replace(os.sep, "/")] if x)
    engines = engines if engines is not None else O.available_engines()
    pages = []
    for n, img in _images(path):
        if n > max_pages:
            break
        log(f"  OCR page {n}")
        pages.append(O.ocr_image(img, n, engines))
    review = [p for p in pages if p.status != "ok"]
    instr = [{"page": p.page, "text": s} for p in pages for s in scan_instructions(p.text)]
    rep = {
        "route": "ocr",
        "engines": [e.name for e in engines],
        "pages": [{"page": p.page, "status": p.status, "conf": p.conf, "agreement": p.agreement,
                   "reasons": p.reasons, "disagreements": p.disagreements[:10], "corrections": p.corrections}
                  for p in pages],
        "review_pages": [p.page for p in review],
        "instruction_like": {"count": len(instr), "examples": instr[:20]},
        "triage": {"class": "scan", "reason": "OCR route"},
        "source_unchanged": {"ok": R.dropbox_content_hash(path) == h, "content_hash": h},
        "seconds": round(time.time() - t0, 1),
    }
    ok = bool(pages) and not review and rep["source_unchanged"]["ok"]
    rep["status"] = "PASS" if ok else "REVIEW"

    parts = []
    for p in pages:
        flags = ["ocr"] + (["ocr_review"] if p.status != "ok" else []) + (["instruction_like"] if scan_instructions(p.text) else [])
        parts.append(unit_open(p.page, len(p.text), ",".join(flags)) + "\n\n"
                     + (p.text.strip() or "*(no text recognised on this page)*") + "\n\n" + UNIT_CLOSE)
    body = "\n\n".join(parts) + "\n"
    status = R.doc_status(name)
    std = R.parse_standard(name)
    fm = ["---", f"document: {R._yaml_str(name)}", f"format_version: {R.FORMAT_VERSION}",
          f"status: {R._yaml_str(status)}", f"edition_status: {R.edition_status(status)}",
          f"std_id: {R._yaml_str(std['std_id'])}", f"std_year: {R._yaml_str(std['std_year'])}",
          f"std_kind: {R._yaml_str(std['std_kind'])}", f"jurisdiction: {R._yaml_str(std['jurisdiction'])}",
          "languages: [en]", f"units: {len(pages)}",
          f"cite_as: {R._yaml_str(name + ', p.<N> from the nearest unit marker')}",
          f"source: {R._yaml_str(src_display + ' (content_hash ' + h[:12] + ')')}",
          f"source_filename: {R._yaml_str(os.path.basename(rel_path))}",
          f"source_relative_path: {R._yaml_str(rel_path.replace(os.sep, '/'))}", f"source_file_hash: {h}",
          f"parser: {R.PIPELINE_VERSION}/ocr:{'+'.join(e.name for e in engines) or 'none'}",
          f"audit_status: {'auto_verified' if ok else 'pending_review'}",
          f"flags: [ocr{', ocr_review' if review else ''}{', instruction_like' if instr else ''}]",
          f"verified: {R._yaml_str('PASS (two OCR engines agree on every page)' if ok else 'REVIEW - ' + str(len(review)) + ' page(s) need a human check')}",
          "---", ""]
    base = os.path.join(out_root, rel_dir) if ok else os.path.join(out_root, "_pending", rel_dir)
    os.makedirs(base, exist_ok=True)
    fn = os.path.basename(rel_path) + ".md"
    with open(R.longpath(os.path.join(base, fn)), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(fm) + body)
    with open(os.path.join(cache_dir, h + ".report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    return {"name": name, "rel_path": rel_path, "source": src_display, "status": status, "verdict": rep["status"],
            "pages": len(pages), "files": 1, "single_file": True, "max_file_chars": len(body),
            "total_chars": len(body), "content_hash": h,
            "out_dir": os.path.relpath(os.path.join(base, fn), out_root), "report": rep}
