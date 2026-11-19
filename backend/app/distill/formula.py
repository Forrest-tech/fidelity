# -*- coding: utf-8 -*-
"""Formulas and figures (spec Phase 6).

Formulas: a formula whose glyphs are unreadable in the text layer is published as the ⚠️ marker
("check the source page"). On a machine with a formula-OCR engine (pix2tex / LaTeX-OCR on the Mac
mini) each one is cropped from the page image and read; the LaTeX is NEVER published on its own —
it is a candidate for a reviewer (`scripts/formulas.py`). An approved formula replaces its marker on
the next distillation, labelled as transcribed and reviewed. Only verified content is published.

Figures: pages with a large image get a one-line notice that a figure is there but not reproduced,
so an AI answering from the text points to the page instead of assuming nothing is there.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

from .pdf_extract import UNREADABLE_RE
from .structure import UNREADABLE_MARK

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
APPROVALS = os.environ.get("FIDELITY_FORMULA_APPROVALS") or os.path.join(_REPO, "data", "formula_approvals.json")
FIGURE_NOTICE = "> *(Figure on this page — not reproduced in the text; see the source page.)*"
FIGURE_MIN_AREA = 0.12          # share of the page an image must cover to count as a figure
DONE_RE = re.compile(r"\$\$.*?\$\$ \*\(formula transcribed from the source image; reviewed [^)]*\)\*", re.S)
_UNIT = re.compile(r"(<!-- unit: p\d+ \| src: p\.(\d+) .*?-->)(.*?)(<!-- /unit -->)", re.S)


# ------------------------------------------------------------------ formula OCR engines (plug-ins)
class Pix2TexEngine:
    name = "pix2tex"
    _m = None

    @classmethod
    def available(cls) -> bool:
        try:
            import pix2tex  # noqa: F401
            return True
        except Exception:
            return False

    def read(self, img) -> str:
        if Pix2TexEngine._m is None:
            from pix2tex.cli import LatexOCR
            Pix2TexEngine._m = LatexOCR()
        return str(Pix2TexEngine._m(img.convert("RGB")))


ENGINES = [Pix2TexEngine]


def available_engines():
    return [e() for e in ENGINES if e.available()]


def norm_latex(s: str) -> str:
    return re.sub(r"\s+|\\[,;:! ]", "", s or "")


# ------------------------------------------------------------------ locating and reading formulas
def locate(pdf_path: str):
    """Unreadable formula lines per page, in reading order: [{page, k, bbox}] (k = 1-based order on the page)."""
    import pymupdf
    out = []
    with pymupdf.open(pdf_path) as doc:
        for pg in doc:
            k = 0
            lines = []
            for b in pg.get_text("dict")["blocks"]:
                for ln in b.get("lines", []):
                    t = "".join(s["text"] for s in ln["spans"])
                    if UNREADABLE_RE.search(t):
                        lines.append(tuple(ln["bbox"]))
            for bbox in sorted(lines, key=lambda r: (round(r[1] / 6), r[0])):
                k += 1
                out.append({"page": pg.number + 1, "k": k, "bbox": [round(v, 1) for v in bbox]})
    return out


def recover(pdf_path: str, engines=None, dpi: int = 300, log=print):
    """Read every unreadable formula with the formula engines. Returns candidates for review."""
    engines = engines if engines is not None else available_engines()
    if not engines:
        return {"skipped": "no formula OCR engine installed", "items": []}
    import pymupdf
    from PIL import Image
    items = locate(pdf_path)
    with pymupdf.open(pdf_path) as doc:
        for it in items:
            x0, y0, x1, y1 = it["bbox"]
            clip = pymupdf.Rect(x0 - 4, y0 - 6, x1 + 4, y1 + 6)
            pix = doc[it["page"] - 1].get_pixmap(dpi=dpi, clip=clip)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            cands = {}
            for e in engines:
                try:
                    cands[e.name] = e.read(img)
                except Exception as ex:                  # a failing engine leaves the formula for review
                    cands[e.name] = "ERROR " + str(ex)[:80]
            vals = {norm_latex(v) for v in cands.values() if not v.startswith("ERROR")}
            it["candidates"] = cands
            it["agreed"] = next(iter(cands.values())) if len(cands) >= 2 and len(vals) == 1 else None
            log(f"  formula p.{it['page']}#{it['k']}: {len(cands)} reading(s)")
    return {"engines": [e.name for e in engines], "items": items}


# ------------------------------------------------------------------ review decisions
def load_approvals(path: str = None) -> dict:
    try:
        with open(path or APPROVALS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def approve(content_hash: str, page: int, k: int, latex: str, reviewer: str, path: str = None, today=None):
    data = load_approvals(path)
    data.setdefault(content_hash, {})[f"p.{page}#{k}"] = {
        "latex": latex.strip(), "reviewer": reviewer, "date": (today or dt.date.today()).isoformat()}
    os.makedirs(os.path.dirname(os.path.abspath(path or APPROVALS)), exist_ok=True)
    with open(path or APPROVALS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data[content_hash][f"p.{page}#{k}"]


def apply_approved(body: str, content_hash: str, approvals: dict = None) -> tuple:
    """Replace the k-th marker on page N with its approved LaTeX. Returns (body, number replaced)."""
    approved = (approvals if approvals is not None else load_approvals()).get(content_hash) or {}
    if not approved:
        return body, 0
    count = 0

    def unit(m):
        nonlocal count
        page, text = int(m.group(2)), m.group(3)
        parts = text.split(UNREADABLE_MARK)
        out = parts[0]
        for k, rest in enumerate(parts[1:], 1):
            a = approved.get(f"p.{page}#{k}")
            if a:
                count += 1
                out += (f"$${a['latex']}$$ *(formula transcribed from the source image; reviewed "
                        f"{a['date']} by {a['reviewer']})*") + rest
            else:
                out += UNREADABLE_MARK + rest
        return m.group(1) + out + m.group(4)
    return _UNIT.sub(unit, body), count


# ------------------------------------------------------------------ figures
def figure_pages(pdf_path: str) -> set:
    import pymupdf
    pages = set()
    with pymupdf.open(pdf_path) as doc:
        for pg in doc:
            area = pg.rect.width * pg.rect.height or 1
            for info in pg.get_image_info():
                x0, y0, x1, y1 = info["bbox"]
                if (x1 - x0) * (y1 - y0) / area >= FIGURE_MIN_AREA:
                    pages.add(pg.number + 1)
                    break
    return pages


def add_figure_notices(body: str, pages: set) -> str:
    if not pages:
        return body

    def unit(m):
        if int(m.group(2)) in pages and FIGURE_NOTICE not in m.group(3):
            return m.group(1) + m.group(3).rstrip() + "\n\n" + FIGURE_NOTICE + "\n\n" + m.group(4)
        return m.group(0)
    return _UNIT.sub(unit, body)
