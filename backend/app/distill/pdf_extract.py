# -*- coding: utf-8 -*-
"""PDF -> ordered page items (text rows + tables) with page numbers and coordinates.

Only reads the PDF (never writes). Every item keeps its page and bbox so later
stages can cite pages exactly and the verifier can check coverage per page.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

# Characters that are layout artefacts, not content.
_SPACE_LIKE = {" ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
               "​": "", "﻿": "", "\t": " "}
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}


WATERMARK_SIZE = 60
UNREADABLE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]")


def formula_span(texts):
    """(first, last) index of spans holding unreadable glyphs, or None. Everything
    between them is one formula whose operators are lost in the text layer."""
    bad = [i for i, t in enumerate(texts) if UNREADABLE_RE.search(t)]
    return (bad[0], bad[-1]) if bad else None


def clean_text(s: str) -> str:
    for k, v in _SPACE_LIKE.items():
        s = s.replace(k, v)
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    return s


@dataclass
class Span:
    text: str
    italic: bool
    bold: bool
    size: float


@dataclass
class Row:
    page: int                     # 1-based physical page
    bbox: tuple                   # x0, y0, x1, y1
    spans: list                   # list[Span] in x order
    box: int | None = None        # index of shaded box the row sits in
    kind: str = "row"

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(s.text for s in self.spans)).strip()

    @property
    def unreadable(self) -> bool:
        """Glyphs decoded to control characters: the text layer cannot be trusted here."""
        return bool(UNREADABLE_RE.search("".join(s.text for s in self.spans)))

    @property
    def max_size(self) -> float:
        return max((s.size for s in self.spans if s.text.strip()), default=0)

    @property
    def all_bold(self) -> bool:
        sp = [s for s in self.spans if s.text.strip()]
        return bool(sp) and all(s.bold for s in sp)


@dataclass
class Table:
    page: int
    bbox: tuple
    rows: list                    # list[list[str|None]]
    kind: str = "table"

    @property
    def key(self) -> str:
        if not hasattr(self, "_key"):
            self._key = _k("".join(c for r in self.rows for c in r if c))
        return self._key

    @property
    def cell_keys(self) -> list:
        if not hasattr(self, "_cells"):
            self._cells = [_k(c) for r in self.rows for c in r if c and _k(c)]
        return self._cells

    def contains_line(self, txt: str, spans) -> bool:
        """A text line belongs to the table if its whole text is in one cell, or — when
        one PDF text line runs across neighbouring cells ("BCA 2004" + "1 May") — every
        span of it is in some cell."""
        if self.contains_text(txt):
            return True
        pieces = [s.text for s in spans if _k(s.text)]
        return len(pieces) > 1 and all(self.contains_text(p) for p in pieces)

    def contains_text(self, txt: str) -> bool:
        """Line text is inside ONE cell (exact, or same characters when subscripts such
        as CO2 are ordered differently). Checked per cell: a short label like '410'
        must not be dropped just because those digits occur somewhere in the table."""
        k = _k(txt)
        if not k:
            return False
        for ck in self.cell_keys:
            if k in ck:
                return True
        if len(k) < 12:
            return False
        need = Counter(k)
        for ck in self.cell_keys:
            if k[:8] in ck:
                cc = Counter(ck)
                if all(cc.get(ch, 0) >= n for ch, n in need.items()):
                    return True
        return False


def _union(bbs):
    return (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs))


def _k(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", s.lower())


@dataclass
class Page:
    number: int
    label: str | None             # printed page number from footer, if any
    items: list = field(default_factory=list)   # Row | Table, reading order
    boxes: list = field(default_factory=list)   # shaded rects (x0,y0,x1,y1)
    raw_chars: int = 0


# digits OR roman numerals, never mixed: "C3D4" / "I3D14" are clause IDs, not page numbers
_PAGE_LABEL_RE = re.compile(r"^(?:page\s+)?((?:\d+|[ivxlcdm]+)(?:-\d+)?)$", re.I)


def _norm_hf(t: str) -> str:
    """Normalise header/footer text so 'Page 77' and 'Page 78' compare equal."""
    return re.sub(r"\d+", "#", t.strip().lower())


def _is_bold(span) -> bool:
    f = span["font"].lower()
    return bool(span["flags"] & 16) or "bold" in f or "semibold" in f or "black" in f


def _is_italic(span) -> bool:
    f = span["font"].lower()
    return bool(span["flags"] & 2) or "italic" in f or "oblique" in f


def _page_lines(page):
    out = []
    d = page.get_text("dict")
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            if max((s["size"] for s in ln["spans"]), default=0) >= WATERMARK_SIZE:
                continue                                  # e.g. diagonal "DRAFT" watermark
            spans = [Span(clean_text(s["text"]), _is_italic(s), _is_bold(s), s["size"])
                     for s in ln["spans"]]
            if not "".join(s.text for s in spans).strip():
                continue
            out.append((tuple(ln["bbox"]), spans))
    return out


def detect_header_footer(doc, band=0.07, min_pages=4, lines_cache=None):
    """Text repeated in the top/bottom band on several pages = running header/footer
    (section titles in the header change per section, so a small absolute count is used)."""
    cnt = Counter()
    for page in doc:
        h = page.rect.height
        seen = set()
        lines = lines_cache[page.number] if lines_cache else _page_lines(page)
        band_lines = [(b, sp) for b, sp in lines if b[1] < h * band or b[3] > h * (1 - band)]
        per_y = Counter(int(round(b[1])) for b, _ in band_lines)
        for bbox, spans in band_lines:
            y = int(round(bbox[1]))
            if sum(per_y.get(y + d, 0) for d in (-1, 0, 1)) >= 3:
                continue            # 3+ fragments on one line = a table header row, not a running header
            seen.add(hf_key("".join(s.text for s in spans), bbox[1]))
        cnt.update(seen)
    # A running header/footer is printed at the SAME height on many pages and contains
    # words. Repeated table headers or list markers near the top are content.
    return {k for k, c in cnt.items()
            if c >= min_pages and sum(ch.isalpha() for ch in k.rsplit("@", 1)[0]) >= 3}


def _hf_text(text: str) -> str:
    return _norm_hf(re.sub(r"\s+", " ", clean_text(text)))


def hf_key(text: str, y0: float) -> str:
    return _hf_text(text) + "@" + str(int(round(y0)))


def is_hf(text: str, y0: float, hf_set) -> bool:
    n, y = _hf_text(text), int(round(y0))
    return any(n + "@" + str(y + d) in hf_set for d in (-1, 0, 1))


def _shaded_boxes(page):
    boxes = []
    for dr in page.get_drawings():
        fill = dr.get("fill")
        r = dr["rect"]
        if not fill or r.width < 150 or r.height < 14:
            continue
        if min(fill) > 0.97:                              # white
            continue
        boxes.append((r.x0, r.y0, r.x1, r.y1))
    return boxes


def _inside(b, r, pad=2):
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return r[0] - pad <= cx <= r[2] + pad and r[1] - pad <= cy <= r[3] + pad


def _tables(page):
    out = []
    try:
        found = page.find_tables().tables
    except Exception:
        return out
    for t in found:
        if t.row_count < 2 or t.col_count < 2:
            continue
        rows = t.extract()
        filled = sum(1 for r in rows for c in r if c and c.strip())
        if filled < 3:
            continue
        rows = [[clean_text(c) if c is not None else None for c in r] for r in rows]
        cells = [c for r in rows for c in r]
        if sum(1 for c in cells if c and c.strip()) < 0.3 * len(cells):
            continue                                      # mostly-empty grid = a drawing, not a table
        if any(c and re.search(r"(?m)^(?:[A-Z]{2,3} )?Figure\b", c) for c in cells):
            continue                                      # figure caption inside the "table" = a drawing
        toks = [w for r in rows for c in r if c for w in c.split()]
        if toks and sum(1 for w in toks if len(w) == 1 and w.isalpha()) / len(toks) > 0.25:
            continue                                      # letter-spaced map/figure labels, not a table
        out.append(Table(page.number + 1, tuple(t.bbox), rows))
    return out


def extract_page(page, hf_set, band=0.07, cached=None) -> Page:
    h = page.rect.height
    pg = Page(number=page.number + 1, label=None)
    pg.boxes = _shaded_boxes(page)
    tables = _tables(page)
    lines = []
    for bbox, spans in (cached if cached is not None else _page_lines(page)):
        txt = re.sub(r"\s+", " ", "".join(s.text for s in spans)).strip()
        in_band = bbox[1] < h * band or bbox[3] > h * (1 - band)
        if in_band and is_hf(txt, bbox[1], hf_set):
            m = _PAGE_LABEL_RE.match(txt)
            if m and bbox[3] > h * (1 - band):
                pg.label = m.group(1)
            continue
        if in_band and bbox[3] > h * (1 - band):
            if txt.strip() == str(pg.number):             # bare page number in footer
                pg.label = txt.strip()
                continue
        lines.append((bbox, spans, txt))
        pg.raw_chars += len(txt)

    # a grid directly under a "Figure ..." caption is a drawing (map, diagram), not a table
    def caption_above(t, reach):
        """Text of the nearest line above the table (same-baseline fragments joined)."""
        cand = [(t.bbox[1] - b[3], b, txt) for b, _, txt in lines
                if -2 <= t.bbox[1] - b[3] <= reach and b[0] < page.rect.width and b[2] > 0]
        if not cand:
            return ""
        dmin = min(c[0] for c in cand)
        same = sorted((c for c in cand if c[0] - dmin <= 3), key=lambda c: c[1][0])
        return " ".join(c[2] for c in same)

    def any_figure_caption_above(t, reach=350):
        return any(txt.lower().startswith("figure") and 0 <= t.bbox[1] - b[3] <= reach
                   for b, _, txt in lines)

    fig_re = re.compile(r"^(?:[A-Z]{2,3} )?figure\b", re.I)

    def is_figure(t):
        if caption_above(t, 40).lower().startswith("figure"):
            return True
        overlaps = lambda b: b[0] < t.bbox[2] and b[2] > t.bbox[0] and b[1] < t.bbox[3] and b[3] > t.bbox[1]
        if any(fig_re.match(txt.strip()) and overlaps(b) for b, _, txt in lines):
            return True                       # a figure caption inside the grid = a drawing
        narrow = (t.bbox[2] - t.bbox[0]) < 0.35 * page.rect.width
        return narrow and any_figure_caption_above(t)
    tables = [t for t in tables if not is_figure(t)]
    # drop a text line only if its text really is inside a table cell (never lose text)
    lines = [(b, s) for b, s, txt in lines
             if not any(_inside(b, t.bbox, pad=1) and t.contains_line(txt, s) for t in tables)]

    # group lines that share a baseline into rows (e.g. "(a)" marker + its text)
    lines.sort(key=lambda l: ((l[0][1] + l[0][3]) / 2, l[0][0]))
    groups: list[list] = []
    for bbox, spans in lines:
        cy = (bbox[1] + bbox[3]) / 2
        if groups:
            g = groups[-1]
            gb = _union([x[0] for x in g])
            if abs(cy - (gb[1] + gb[3]) / 2) <= 3 and all(bbox[0] >= x[0][2] - 1 or bbox[2] <= x[0][0] + 1 for x in g):
                g.append((bbox, spans))
                continue
        groups.append([(bbox, spans)])
    rows: list[Row] = []
    for g in groups:
        g.sort(key=lambda x: x[0][0])
        gaps = [b[0][0] - a[0][2] for a, b in zip(g, g[1:])]
        size = max((x.size for _, sp in g for x in sp if x.text.strip()), default=10)
        thr = size * 0.18
        frags = ["".join(s.text for s in sp).strip() for _, sp in g]
        if len(gaps) >= 4 and sum(1 for f in frags if len(f) <= 2 and f.isalpha()) >= 0.7 * len(frags):
            # letter-spaced labels (one glyph per fragment): word gap > letter gap
            med = sorted(gaps)[len(gaps) // 2]
            thr = max(thr, med * 1.8)
        spans = list(g[0][1])
        for gap, (_, sp) in zip(gaps, g[1:]):
            if gap > thr and not spans[-1].text.endswith(" ") and not sp[0].text.startswith(" "):
                spans.append(Span(" ", False, False, 0))
            spans.extend(sp)
        rows.append(Row(pg.number, _union([x[0] for x in g]), spans))
    for r in rows:
        for i, b in enumerate(pg.boxes):
            if _inside(r.bbox, b):
                r.box = i
                break
    items = rows + tables
    items.sort(key=lambda it: (it.bbox[1], it.bbox[0]))
    pg.items = items
    return pg


def extract_pdf(path: str):
    doc = pymupdf.open(path)
    cache = [_page_lines(p) for p in doc]
    hf = detect_header_footer(doc, lines_cache=cache)
    pages = [extract_page(p, hf, cached=cache[p.number]) for p in doc]
    meta = {
        "page_count": len(doc),
        "title": (doc.metadata or {}).get("title") or "",
        "producer": (doc.metadata or {}).get("producer") or "",
        "toc": doc.get_toc(simple=True),
        "header_footer": sorted(hf),
    }
    doc.close()
    return pages, meta
