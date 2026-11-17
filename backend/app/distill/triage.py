# -*- coding: utf-8 -*-
"""Triage before distilling (spec F-22) and instruction-text scan (F-23).

Every source file is classified first; each class has its own route:
  text        text-layer PDF                -> distilled by this pipeline
  scan        image-only / scanned PDF      -> OCR route (Phase 4); listed, not distilled here
  drawing     large-format vector drawing   -> drawing route (Phase 4); listed, not distilled here
  protected   password / copy-restricted    -> listed as "protected, not distilled" (F-13)
"""
from __future__ import annotations

import re

import pymupdf

SAMPLE_PAGES = 24
SCAN_TEXT_CHARS = 25          # average text characters per sampled page below this => no usable text layer
DRAWING_MIN_SIDE_PT = 1000    # about A1 and larger
DRAWING_MIN_VECTORS = 300


def triage_pdf(path: str) -> dict:
    """Classify a PDF without modifying it. Returns {"class", "reason", ...}."""
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # unreadable / corrupt
        return {"class": "unsupported", "reason": "cannot open: %s" % str(e)[:120]}
    try:
        if doc.needs_pass:
            return {"class": "protected", "reason": "password required"}
        if not (doc.permissions & pymupdf.PDF_PERM_COPY):   # unencrypted files report all permissions
            return {"class": "protected", "reason": "copying of text is not permitted by the file's permissions"}
        n = doc.page_count
        if n == 0:
            return {"class": "unsupported", "reason": "no pages"}
        step = max(1, n // SAMPLE_PAGES)
        sample = list(range(0, n, step))[:SAMPLE_PAGES]
        chars = vectors = images = big = 0
        for i in sample:
            pg = doc[i]
            chars += len(pg.get_text().strip())
            vectors += len(pg.get_drawings())
            images += len(pg.get_images())
            if max(pg.rect.width, pg.rect.height) >= DRAWING_MIN_SIDE_PT:
                big += 1
        k = len(sample)
        info = {"pages": n, "avg_text_chars": round(chars / k, 1), "avg_vectors": round(vectors / k, 1)}
        if big >= k / 2 and vectors / k >= DRAWING_MIN_VECTORS:
            return {"class": "drawing", "reason": "large-format page with many vector elements", **info}
        if chars / k < SCAN_TEXT_CHARS:
            return {"class": "scan", "reason": "no usable text layer (%s images on sampled pages)" % images, **info}
        return {"class": "text", "reason": "text layer present", **info}
    finally:
        doc.close()


# ------------------------------------------------------------------ instruction-like text (F-23)
_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules?|context)",
    r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules?)",
    r"(?:forget|override)\s+(?:all\s+|your\s+)?(?:previous|prior|earlier)?\s*(?:instructions?|rules?|guidelines)",
    r"you\s+are\s+now\s+(?:a|an|in)\b",
    r"new\s+instructions?\s*:",
    r"system\s+prompt",
    r"(?:reveal|print|show|output)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions)",
    r"do\s+not\s+(?:tell|inform|mention\s+to)\s+the\s+user",
    r"act\s+as\s+(?:if\s+you\s+(?:are|were)|an?\s+\w+\s+(?:assistant|model|AI))",
    r"as\s+an\s+AI\s+(?:language\s+)?(?:model|assistant)",
    r"<\s*/?\s*(?:system|assistant|instructions?)\s*>",
]
_RX = re.compile("|".join("(?:%s)" % p for p in _PATTERNS), re.I)


def scan_instructions(text: str) -> list:
    """Snippets of text that read like instructions aimed at an AI (not at a human reader)."""
    out = []
    for m in _RX.finditer(text or ""):
        a, b = max(0, m.start() - 30), min(len(text), m.end() + 30)
        out.append(" ".join(text[a:b].split()))
    return out
