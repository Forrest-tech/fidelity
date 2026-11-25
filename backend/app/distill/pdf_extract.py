# -*- coding: utf-8 -*-
"""PDF -> ordered page items (text rows + tables) with page numbers and coordinates.

Only reads the PDF (never writes). Every item keeps its page and bbox so later
stages can cite pages exactly and the verifier can check coverage per page.
"""
from __future__ import annotations

import collections
import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

# MuPDF prints one line per damaged content-stream operator ("syntax error: unknown keyword 'Bn'"),
# hundreds per file, which buries real errors in the sync log. They are collected instead and
# summarised once per document (see reader_warnings).
pymupdf.TOOLS.mupdf_display_errors(False)


def reader_warnings(max_examples: int = 2):
    """One-line summary of what the PDF reader complained about since the last call, or ''."""
    raw = [ln.strip() for ln in (pymupdf.TOOLS.mupdf_warnings() or "").splitlines() if ln.strip()]
    if not raw:
        return ""
    kinds = Counter(raw)
    top = ", ".join(f"{k[:70]} x{n}" for k, n in kinds.most_common(max_examples))
    return f"PDF reader noted {len(raw)} damaged-content warning(s) ({top}); the text layer was still read"

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
    y: float = 0.0                # baseline (origin y); tells a raised or lowered small span from the line's own text


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


def is_watermark_line(ln) -> bool:
    """Big text, or text drawn diagonally (watermarks such as DRAFT / PREVIEW DRAFT). Horizontal and
    vertical text are real content; rotated table headings are vertical, never diagonal."""
    if max((s["size"] for s in ln["spans"]), default=0) >= WATERMARK_SIZE:
        return True
    dx, dy = ln.get("dir", (1, 0))
    return abs(dx) > 0.2 and abs(dy) > 0.2


EXTRACT_VERSION = "5"      # part of the extraction cache key: bump when extraction behaviour changes (5: 2026-11-25 reading order, scripts, lost table cells)


def to_view(page, bbox):
    """Coordinates of text and drawings are given on the UNROTATED page, but table detection and the
    page size (used for the header/footer bands) are given on the page as displayed. A landscape page
    stored rotated by 90 degrees therefore never matched its own tables (their text was printed twice)
    and had its header/footer bands in the wrong place. Everything is compared in displayed coordinates."""
    if not page.rotation:
        return tuple(bbox)
    r = pymupdf.Rect(bbox) * page.rotation_matrix
    r.normalize()
    return (r.x0, r.y0, r.x1, r.y1)


def _drawn_out_of_order(ln) -> bool:
    """Some PDFs draw a line's characters out of reading order (AS 3500.3:2003 p.59 draws "0.233)" right to left, so
    equation 5.4.6 read "m (.0013310 I − .0233)"). A span's origin is its first DRAWN character; when that is not its
    leftmost character, the order in the text layer is not the reading order."""
    if abs(ln.get("dir", (1, 0))[1]) > 0.01:            # rotated text (side-of-page licence lines) is not a reading line
        return False
    return any(abs(s["origin"][0] - s["bbox"][0]) > 1.5 for s in ln["spans"] if s["text"].strip())


def _reordered_spans(raw_line) -> list:
    """The line's characters in x order, regrouped into spans of the same size and style."""
    chars = sorted(((c["origin"][0], c["c"], c["origin"][1], s) for s in raw_line["spans"] for c in s["chars"]),
                   key=lambda t: t[0])
    out = []
    for _, ch, y, s in chars:
        key = (_is_italic(s), _is_bold(s), s["size"], round(y, 1))
        if out and (out[-1][0] == key):
            out[-1][1].append(ch)
        else:
            out.append((key, [ch]))
    return [Span(clean_text("".join(cs)), it, bo, size, y) for (it, bo, size, y), cs in out]


_EQUATION = re.compile(r"\.\s*\.\s*\.\s*[A-Z]?\d+(?:\.\d+)+\s*$")     # a numbered equation: "… . . . 5.4.6"


def _mark_scripts(spans: list) -> list:
    """In a numbered equation, small text above or below the line's baseline is a superscript or subscript. Flattened,
    "C_p = m (0.0133 ¹⁰I₆₀ − 0.233)" reads "Cp = m (0.013310 I60 − 0.233)" — a different number. Marked, it reads
    "C<sub>p</sub> = m (0.0133 <sup>10</sup>I<sub>60</sub> − 0.233)"."""
    body = [s for s in spans if s.text.strip() and s.size]
    if not body:
        return spans
    big = max(s.size for s in body)
    base = [s.y for s in body if s.size >= 0.9 * big]
    y0 = sorted(base)[len(base) // 2]
    out = []
    for s in spans:
        if s.text.strip() and s.size and s.size < 0.8 * big and abs(s.y - y0) > 0.08 * big:
            tag = "sup" if s.y < y0 else "sub"
            lead = " " if tag == "sup" and out and out[-1].text[-1:].isdigit() else ""
            out.append(Span(f"{lead}<{tag}>{s.text.strip()}</{tag}>", s.italic, s.bold, s.size, s.y))
        else:
            out.append(s)
    return out


def _script_of(spans, group, bbox, gb) -> bool:
    """A small raised or lowered piece (subscript "p", superscript "10") belongs to the line it overlaps, although its
    centre sits more than 3 pt off that line's centre; or the other way round, the line belongs to a group that so far
    holds only such small pieces."""
    size = lambda sp: max((x.size for x in sp if x.text.strip()), default=0)       # noqa: E731
    mine, theirs = size(spans), max(size(sp) for _, sp in group)
    if not mine or not theirs or 0.8 * max(mine, theirs) <= min(mine, theirs):
        return False
    small = spans if mine < theirs else [x for _, sp in group for x in sp]
    if len("".join(x.text for x in small).strip()) > 4:      # scripts are short; a small caption beside text is not one
        return False
    overlap = min(bbox[3], gb[3]) - max(bbox[1], gb[1])
    return overlap >= 0.5 * min(bbox[3] - bbox[1], gb[3] - gb[1])


def _page_lines(page):
    out = []
    d = page.get_text("dict")
    raw = None
    for bi, b in enumerate(d["blocks"]):
        if b.get("type") != 0:
            continue
        for li, ln in enumerate(b["lines"]):
            if is_watermark_line(ln):
                continue                                  # e.g. diagonal "DRAFT" watermark
            if _drawn_out_of_order(ln):
                raw = raw or page.get_text("rawdict")     # character positions, only for pages that need them
                spans = _reordered_spans(raw["blocks"][bi]["lines"][li])
            else:
                spans = [Span(clean_text(s["text"]), _is_italic(s), _is_bold(s), s["size"], s["origin"][1])
                         for s in ln["spans"]]
            if not "".join(s.text for s in spans).strip():
                continue
            out.append((to_view(page, ln["bbox"]), spans))
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
        r = pymupdf.Rect(*to_view(page, dr["rect"]))
        if not fill or r.width < 150 or r.height < 14:
            continue
        if min(fill) > 0.97:                              # white
            continue
        boxes.append((r.x0, r.y0, r.x1, r.y1))
    return boxes


def _inside(b, r, pad=2):
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return r[0] - pad <= cx <= r[2] + pad and r[1] - pad <= cy <= r[3] + pad


_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers_intact(page, bbox, rows) -> bool:
    """False when the detected grid cut a number in two ("250" became "2" | "50"). Every number in
    the cells must exist as a word of the page inside the table; otherwise the grid is not trusted
    and the text stays as ordinary lines, which keep every number exactly as printed."""
    got = Counter(n for r in rows for c in r if c for w in c.split() for n in _NUM.findall(w))
    if not got:
        return True
    have = Counter()
    for w in page.get_text("words"):
        if _inside(to_view(page, w[:4]), bbox, pad=2):
            have.update(_NUM.findall(clean_text(w[4])))
    return not (got - have)


_NUMERIC = re.compile(r"^[−-]?\d+(?:[.,]\d+)?\s*(?:%|mm|m|kPa|L|°C?)?$")


def _is_data_row(r) -> bool:
    vals = [c.strip() for c in r if c and c.strip()]
    return bool(vals) and sum(bool(_NUMERIC.match(v)) for v in vals) >= 0.5 * len(vals)


def _fill_missing(page, t, rows):
    """Cells the grid finder returns as None ("merged") although the page has text there. Found 2026-11-25 in
    AS/NZS 3500.4:2018 Table 6.5.1.2(A): the row labels ("1 or 2 bedrooms") and the whole ">75° to 90°" column came back
    empty, and the values 14 and 32 ended up as loose text under the table. Each run of None cells in a row gets the
    words lying in it, grouped into phrases (words closer than a space); a phrase goes into the cell where it starts,
    so a heading spanning three columns stays one heading and the cells after it stay None (continuation)."""
    if getattr(page, "rotation", 0):
        return rows                                       # word and cell coordinates disagree on a turned page
    try:
        trows = t.rows
    except Exception:                                     # noqa: BLE001 - older PyMuPDF: leave the table as found
        return rows
    ncol = max((len(r) for r in rows), default=0)
    cols = []
    for j in range(ncol):
        xs = [r.cells[j] for r in trows if j < len(r.cells) and r.cells[j]]
        cols.append((min(c[0] for c in xs), max(c[2] for c in xs)) if xs else None)
    if not any(c is None for r in rows for c in r) or any(c is None for c in cols):
        return rows
    words = page.get_text("words")
    # only a table that lost figures is filled: the page has more numbers inside the table's frame than its cells hold
    num = re.compile(r"\d+(?:\.\d+)?")
    x0, y0, x1, y1 = t.bbox
    on_page = collections.Counter(n for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1
                                  for n in num.findall(w[4]))
    in_cells = collections.Counter(n for r in rows for c in r if c for n in num.findall(c))
    if not (on_page - in_cells):
        return rows
    out = [list(r) for r in rows]
    for i, (r, tr) in enumerate(zip(out, trows)):
        y0, y1 = tr.bbox[1], tr.bbox[3]
        j = 0
        while j < len(r):
            if r[j] is not None:
                j += 1
                continue
            k = j
            while k < len(r) and r[k] is None:
                k += 1
            x0, x1 = cols[j][0], cols[k - 1][1]
            ws = sorted((w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1),
                        key=lambda w: (round((w[1] + w[3]) / 2 / 3), w[0]))
            phrases = []
            for w in ws:
                if phrases and w[0] - phrases[-1][2] < 0.6 * (w[3] - w[1]) and abs(w[1] - phrases[-1][1]) < 3:
                    phrases[-1] = (phrases[-1][0], phrases[-1][1], w[2], phrases[-1][3] + " " + w[4])
                elif phrases and any(cols[c][0] <= (w[0] + w[2]) / 2 <= cols[c][1] and
                                     cols[c][0] <= phrases[-1][0] + 1 <= cols[c][1] for c in range(j, k)):
                    phrases[-1] = (phrases[-1][0], phrases[-1][1], w[2], phrases[-1][3] + " " + w[4])    # same cell, next line
                else:
                    phrases.append((w[0], w[1], w[2], w[4]))
            data_row = _is_data_row(r)
            for px0, _, px1, text in phrases:
                left = r[j - 1] if j else None
                if not data_row and left and left.endswith(clean_text(text)) and len(left) > len(clean_text(text)):
                    continue                              # the tail of the heading to the left, spilling over
                span = [c for c in range(j, k) if cols[c][0] - 1 <= px0 <= cols[c][1] or px0 <= cols[c][0] <= px1]
                if not span:
                    continue
                one_col = len(span) == 1
                # a data row takes values that sit inside one column; a heading row only takes a lone missing cell, a
                # first-column label, or a heading that starts after the merged part ends (">45° … east from true north")
                ok = one_col if data_row else ((one_col and (k - j == 1 or j == 0)) or span[0] > j)
                if ok:
                    c = span[0]
                    r[c] = clean_text(text) if r[c] is None else r[c] + " " + clean_text(text)
            j = k
    return out


def _tables(page):
    out = []
    try:
        found = page.find_tables().tables
    except Exception:
        return out
    for t in found:
        if t.row_count < 2 or t.col_count < 2:
            continue
        rows = _fill_missing(page, t, t.extract())
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
        if not _numbers_intact(page, tuple(t.bbox), rows):
            continue
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
            apart = all(bbox[0] >= x[0][2] - 1 or bbox[2] <= x[0][0] + 1 for x in g)
            if apart and (abs(cy - (gb[1] + gb[3]) / 2) <= 3 or _script_of(spans, g, bbox, gb)):
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
        if _EQUATION.search("".join(x.text for x in spans)):
            spans = _mark_scripts(spans)
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
