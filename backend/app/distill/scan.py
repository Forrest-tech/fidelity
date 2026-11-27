# -*- coding: utf-8 -*-
"""Scan / image route (spec F-22): OCR every page with two engines, correct, vote, route.

A document is published only when every page is accepted automatically; otherwise it goes to
_pending/ with verdict REVIEW (the human review queue), page by page reasons in the report.
"""
from __future__ import annotations

import json
import os
import threading
import time

from . import ocr as O
from . import run as R
from .structure import UNIT_CLOSE, unit_open
from .triage import scan_instructions

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")


def page_count(path) -> int:
    """Pages to OCR (for progress); 0 when unknown."""
    try:
        if path.lower().endswith(".pdf"):
            import pymupdf
            with pymupdf.open(path) as d:
                return d.page_count
        from PIL import Image
        with Image.open(path) as im:
            return getattr(im, "n_frames", 1)
    except Exception:
        return 0


def _images(path):
    """Yield (page number, function that makes the page's image) for a scanned PDF or an image file (multi-page
    TIFF too). The image is made only when called, so a page read before is not rendered again."""
    from PIL import Image, ImageSequence
    if path.lower().endswith(".pdf"):
        import pymupdf
        with pymupdf.open(path) as d:
            n = d.page_count
        for i in range(n):
            yield i + 1, (lambda i=i: O.render_page(path, i))
    else:
        with Image.open(path) as im:
            for i, frame in enumerate(ImageSequence.Iterator(im), 1):
                f = frame.convert("L").copy()
                yield i, (lambda f=f: f)


class PageStore:
    """The raw readings of every page already OCR'd, kept on disk as they are made: one JSON line per page and
    engine in <cache>/ocr-pages/<content hash>.jsonl. A run that stops (network, a restart, the Mac sleeping, a
    cancel) and is started again reads only the pages still missing; before 2026-11-27 it began again at page 1
    (the owner's 330-page scan had reached page 192, about two and a half hours lost)."""

    def __init__(self, cache_dir, content_hash: str):
        self.path = os.path.join(cache_dir, "ocr-pages", content_hash + ".jsonl") if cache_dir else None
        self.pages: dict = {}
        self._lock = threading.Lock()
        if self.path and os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        self.pages.setdefault(int(d["page"]), {})[d["engine"]] = [d["text"], float(d["conf"])]
                    except (ValueError, KeyError, TypeError):
                        continue                          # a line cut off when the run stopped: that page is read again

    def get(self, page: int) -> dict:
        return self.pages.get(page, {})

    def put(self, page: int, key: str, text: str, conf: float):
        if not self.path:
            return
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"page": page, "engine": key, "text": text, "conf": conf}, ensure_ascii=False) + "\n")
            self.pages.setdefault(page, {})[key] = [text, conf]


def distill_scan(path, rel_path, out_root, source_prefix, cache_dir, log=print, engines=None, max_pages=400,
                 via="scan"):
    t0 = time.time()
    name = os.path.splitext(os.path.basename(rel_path))[0]
    rel_dir = os.path.dirname(rel_path)
    h = R.dropbox_content_hash(path)
    src_display = "/" + "/".join(x for x in [source_prefix.strip("/"), rel_path.replace(os.sep, "/")] if x)
    engines = engines if engines is not None else O.available_engines()
    pages = []
    total = page_count(path)
    log(f"  scanned document: OCR of {min(total, max_pages) if total else '?'} page(s) with {len(engines)} engine(s)")
    store = PageStore(cache_dir, h)
    keys = [O.engine_key(e) for e in engines]
    done = sum(1 for p in store.pages.values() if all(k in p for k in keys))
    if done:
        log(f"  {done} page(s) already read in an earlier run: carrying on from there")
    for n, img in _images(path):
        if n > max_pages:
            break
        have = store.get(n)
        if not all(k in have for k in keys):
            log(f"  OCR page {n}/{min(total, max_pages) if total else '?'}")
        pages.append(O.ocr_image(img, n, engines, cached=have, on_read=lambda k, t, c, n=n: store.put(n, k, t, c)))
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
        "triage": ({"class": "protected", "reason": "copying text not allowed: read from images of its pages"}
                   if via == "page_images" else {"class": "scan", "reason": "OCR route"}),
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
          f"flags: [ocr{', from_page_images' if via == 'page_images' else ''}{', ocr_review' if review else ''}{', instruction_like' if instr else ''}]",
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
