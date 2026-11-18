# -*- coding: utf-8 -*-
"""OCR framework for scans and images (spec F-14, F-22, Phase 4).

- Engines are plug-ins behind one interface: RapidOCR (PP-OCR on ONNX, pip) and Tesseract 5
  (system binary through pytesseract). Further engines (e.g. on the Mac) register the same way.
- Two engines read every page; their texts are aligned word by word. A page is accepted
  automatically only when the engines agree (>= AGREE) and both are confident (>= CONF).
  Anything else, or a page read by a single engine, goes to the human review queue.
- Rule-based corrections (correct.py) run before the vote and every change is logged.
"""
from __future__ import annotations

import difflib
import re
import shutil
from dataclasses import dataclass, field

AGREE = 0.995          # share of words both engines read identically
CONF = 0.90            # mean engine confidence
RENDER_DPI = 300
MAX_SIDE = 1400        # longest image side fed to an engine: measured best for RapidOCR, and fits a 4 GB machine


@dataclass
class PageOCR:
    page: int
    text: str                                 # text chosen for publication (primary engine, corrected)
    engines: dict = field(default_factory=dict)   # name -> {"text", "conf"}
    agreement: float | None = None
    conf: float | None = None
    status: str = "review"                    # "ok" | "review"
    reasons: list = field(default_factory=list)
    disagreements: list = field(default_factory=list)
    corrections: list = field(default_factory=list)


# ------------------------------------------------------------------ engines
class RapidOCREngine:
    name = "rapidocr"
    _eng = None

    @classmethod
    def available(cls) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except Exception:
            return False

    def read(self, img):
        import numpy as np
        if RapidOCREngine._eng is None:
            from rapidocr_onnxruntime import RapidOCR
            RapidOCREngine._eng = RapidOCR()
        res, _ = RapidOCREngine._eng(np.asarray(img.convert("RGB")))
        lines = []
        for item in res or []:
            box, txt, conf = item[0], item[1], float(item[2])
            if txt.strip():
                lines.append((min(p[1] for p in box), min(p[0] for p in box), txt.strip(), conf))
        return _join_lines(lines)


class TesseractEngine:
    name = "tesseract"

    @classmethod
    def available(cls) -> bool:
        try:
            import pytesseract  # noqa: F401
        except Exception:
            return False
        return shutil.which("tesseract") is not None

    def read(self, img):
        import pytesseract
        d = pytesseract.image_to_data(img, lang="eng", config="--psm 3", output_type=pytesseract.Output.DICT)
        words = {}
        for i, w in enumerate(d["text"]):
            if not w.strip() or float(d["conf"][i]) < 0:
                continue
            key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            y, x = d["top"][i], d["left"][i]
            words.setdefault(key, []).append((x, y, w.strip(), float(d["conf"][i]) / 100.0))
        lines = []
        for ws in words.values():
            ws.sort()
            lines.append((min(w[1] for w in ws), ws[0][0], " ".join(w[2] for w in ws), sum(w[3] for w in ws) / len(ws)))
        return _join_lines(lines)


ENGINES = [RapidOCREngine, TesseractEngine]


def available_engines():
    return [e() for e in ENGINES if e.available()]


def _join_lines(lines):
    """(top, left, text, conf) -> page text in reading order + mean confidence (weighted by length)."""
    lines.sort(key=lambda l: (round(l[0] / 12), l[1]))
    text = "\n".join(l[2] for l in lines)
    n = sum(len(l[2]) for l in lines)
    conf = sum(l[3] * len(l[2]) for l in lines) / n if n else 0.0
    return text, conf


# ------------------------------------------------------------------ voting
_WORD = re.compile(r"\S+")


def agreement(a: str, b: str):
    """Share of words read identically by both engines, and the spans where they differ."""
    wa, wb = _WORD.findall(a), _WORD.findall(b)
    if not wa and not wb:
        return 1.0, []
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    same = sum(bl.size for bl in sm.get_matching_blocks())
    diffs = [(" ".join(wa[i1:i2]), " ".join(wb[j1:j2])) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    return same / max(len(wa), len(wb)), diffs


def decide(page: int, readings: dict, corrected: str, corrections: list) -> PageOCR:
    r = PageOCR(page=page, text=corrected, engines=readings, corrections=corrections)
    confs = [v["conf"] for v in readings.values()]
    r.conf = round(min(confs), 4) if confs else 0.0
    if len(readings) < 2:
        r.reasons.append("only one OCR engine available: cannot cross-check")
    else:
        names = list(readings)
        r.agreement, diffs = agreement(readings[names[0]]["text_corrected"], readings[names[1]]["text_corrected"])
        r.agreement = round(r.agreement, 4)
        r.disagreements = diffs[:50]
        if r.agreement < AGREE:
            r.reasons.append(f"engines disagree on {len(diffs)} span(s) (agreement {r.agreement:.3f})")
    if r.conf < CONF:
        r.reasons.append(f"low confidence {r.conf:.2f}")
    if not corrected.strip():
        r.reasons.append("no text recognised")
    r.status = "ok" if not r.reasons else "review"
    return r


def ocr_image(img, page: int = 1, engines=None) -> PageOCR:
    from .correct import correct_text
    engines = engines if engines is not None else available_engines()
    readings, failures = {}, []
    if img is not None and max(img.size) > MAX_SIDE:
        from PIL import Image
        k = MAX_SIDE / max(img.size)
        img = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)
    for e in engines:
        try:
            text, conf = e.read(img)
        except Exception as x:          # an engine crash sends the page to review, never stops the run
            failures.append(f"{e.name} failed: {str(x)[:120]}")
            continue
        fixed, log = correct_text(text)
        readings[e.name] = {"text": text, "text_corrected": fixed, "conf": round(conf, 4), "corrections": log}
    if not readings:
        return PageOCR(page=page, text="", status="review", reasons=failures or ["no OCR engine installed"])
    primary = next(iter(readings.values()))
    r = decide(page, readings, primary["text_corrected"], primary["corrections"])
    if failures:
        r.reasons += failures
        r.status = "review"
    return r


def render_page(pdf_path: str, index: int, dpi: int = RENDER_DPI):
    import pymupdf
    from PIL import Image
    doc = pymupdf.open(pdf_path)
    try:
        pix = doc[index].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        return Image.frombytes("L", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
