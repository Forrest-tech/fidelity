# -*- coding: utf-8 -*-
"""Triage before distilling (spec F-22) and instruction-text scan (F-23).

Every source file is classified first; each class has its own route:
  text        text-layer PDF                -> distilled by this pipeline
  scan        image-only / scanned PDF      -> OCR route (Phase 4); listed, not distilled here
              also a scan someone else ran OCR on ("Converted to Searchable"): each page is one picture with an
              invisible text layer over it. That layer is another program's OCR, not the publisher's text, so it is
              read again and verified like any scan (measured: such layers lost ~8% of numbers on AS/NZS 3500 2021).
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
OCR_LAYER_IMAGE_SHARE = 0.85  # a page this much covered by one picture, with text on it, is a scan with an OCR layer


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
            return {"class": "protected", "reason": "copying of text is not permitted by the file's permissions",
                    "copy_only": True}         # it opens and shows its pages; only copying its text is refused
        n = doc.page_count
        if n == 0:
            return {"class": "unsupported", "reason": "no pages"}
        step = max(1, n // SAMPLE_PAGES)
        sample = list(range(0, n, step))[:SAMPLE_PAGES]
        chars = vectors = images = big = pictured = 0
        for i in sample:
            pg = doc[i]
            text = len(pg.get_text().strip())
            chars += text
            vectors += len(pg.get_drawings())
            images += len(pg.get_images())
            if max(pg.rect.width, pg.rect.height) >= DRAWING_MIN_SIDE_PT:
                big += 1
            if text >= SCAN_TEXT_CHARS and _picture_share(pg) >= OCR_LAYER_IMAGE_SHARE:
                pictured += 1
        k = len(sample)
        info = {"pages": n, "avg_text_chars": round(chars / k, 1), "avg_vectors": round(vectors / k, 1)}
        if big >= k / 2 and vectors / k >= DRAWING_MIN_VECTORS:
            return {"class": "drawing", "reason": "large-format page with many vector elements", **info}
        if chars / k < SCAN_TEXT_CHARS:
            return {"class": "scan", "reason": "no usable text layer (%s images on sampled pages)" % images, **info}
        if pictured >= k / 2:
            return {"class": "scan", "reason": "scanned pages with another program's OCR text layer (%s of %s sampled "
                                               "pages are one full-page picture): read again and verified" % (pictured, k),
                    "ocr_layer": True, **info}
        return {"class": "text", "reason": "text layer present", **info}
    finally:
        doc.close()


def ocr_protected_enabled() -> bool:
    """Settings → Defaults: read copy-restricted PDFs from images of their pages (the owner's decision of 2026-11-22;
    the company is licensed for this content). FIDELITY_OCR_PROTECTED=1/0 overrides the setting."""
    import json
    import os
    env = (os.environ.get("FIDELITY_OCR_PROTECTED") or "").strip()
    if env:                                               # an empty value means "not set", not "off"
        return env.lower() in ("1", "on", "true", "yes")
    from .. import config
    try:
        with open(os.path.join(config.DATA_DIR, "app_settings.json"), encoding="utf-8") as f:
            return bool((json.load(f).get("room_defaults") or {}).get("ocr_protected", True))
    except (OSError, ValueError):
        return True                                       # not set: the owner's decision (on), see appsettings.DEFAULTS


def reads_as_scan(tri: dict) -> bool:
    """Needs the OCR route (and its two capacity points)."""
    return tri.get("class") == "scan"


def reads_protected_text(tri: dict) -> bool:
    """A PDF whose only restriction is on copying, read through its own text layer when the owner switched that on.
    Measured 2026-11-22 on AS/NZS 3500.2:2018: OCR of its page images got 84% of the numbers right; the text layer is
    the publisher's exact text (as in the unlocked copy), and it is still checked against images of its pages."""
    return tri.get("class") == "protected" and bool(tri.get("copy_only")) and ocr_protected_enabled()


def _picture_share(page) -> float:
    """The largest share of the page one picture covers (0 when it has none)."""
    area = abs(page.rect) or 1.0
    best = 0.0
    try:
        for info in page.get_image_info():
            r = pymupdf.Rect(info["bbox"]) & page.rect
            best = max(best, abs(r) / area)
    except Exception:                                       # noqa: BLE001 - a page we cannot inspect counts as text
        return 0.0
    return best


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
