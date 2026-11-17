# -*- coding: utf-8 -*-
"""TOC-driven structure: match bookmarks to heading rows, cut chapter chunks,
render Markdown with page markers. Content is never paraphrased: every output
character comes from the PDF text layer (only whitespace/markup is added)."""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

from .triage import scan_instructions
from .pdf_extract import Row, Table, clean_text, UNREADABLE_RE, formula_span

UNREADABLE_MARK = "⚠️[formula/symbols not readable in source text layer — check source page]"

CLAUSE_ID = r"(?:[A-J]\d{1,2}[GPDVOF]\d{1,2}|S\d{1,2}C\d{1,2}[a-z]?|H\d{1,2}[GPDVOF]\d{1,2})"
CLAUSE_ID_RE = re.compile(r"\b(" + CLAUSE_ID + r")\b")
STATE_RE = r"(?:ACT|NSW|NT|QLD|SA|TAS|VIC|WA)"


def key(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", clean_text(s).lower())


def display_title(raw: str) -> str:
    parts = [p.strip() for p in clean_text(raw).replace("\t", "\u0001").split("\u0001")]
    parts = [re.sub(r"\s+", " ", p) for p in parts if p.strip()]
    return " ".join(parts)


@dataclass
class TocEntry:
    level: int
    title: str
    page: int
    seq: int
    row: Row | None = None

    @property
    def clause_id(self):
        m = re.match(r"^(?:" + STATE_RE + r" )?(" + CLAUSE_ID + r")\b", self.title)
        return m.group(1) if m else None


def normalize_toc(toc):
    entries = [TocEntry(lv, display_title(t), p, i) for i, (lv, t, p) in enumerate(toc) if display_title(t)]
    # drop wrapper levels that hold a single entry (e.g. a document-title bookmark)
    while entries:
        top = min(e.level for e in entries)
        tops = [e for e in entries if e.level == top]
        if len(tops) == 1 and len(entries) > 1:
            entries = [e for e in entries if e is not tops[0]]
            continue
        break
    if entries:
        top = min(e.level for e in entries)
        for e in entries:
            e.level = e.level - top + 1
    return entries


def toc_is_usable(entries, page_count):
    if len(entries) < max(5, page_count / 40):
        return False
    back = sum(1 for a, b in zip(entries, entries[1:]) if b.page < a.page)
    return back <= len(entries) * 0.02


_FALLBACK_HEAD = re.compile(
    r"^(Section [A-Z]\b|Part [A-Z]\d+\b|Specification \d+\b|Schedule \d+\b|" + CLAUSE_ID + r"\b)")


def fallback_toc(pages):
    """No usable bookmarks: take bold rows that look like NCC headings."""
    out = []
    cur_code = None
    for pg in pages:
        for it in pg.items:
            if isinstance(it, Row) and it.all_bold and len(it.text) < 160:
                m = _FALLBACK_HEAD.match(it.text)
                if not m:
                    continue
                t = m.group(1)
                if len(it.text.strip()) < len(t) + 3:
                    continue          # bare ID (running header), not a titled heading
                lv = 1 if t.startswith("Section") else 2 if t.split()[0] in ("Part", "Specification", "Schedule") else 3
                e = TocEntry(lv, it.text, pg.number, len(out), row=it)
                it.kind, it.toc = "heading", e
                out.append(e)
                # excerpts may omit Part title pages: when the clause prefix changes
                # without a Part heading, start a new part there (named from the ID only)
                pm = re.match(r"^Part ([A-Z]\d+)", t) or re.match(r"^Specification (\d+)", t)
                if lv == 2 and pm:
                    cur_code = pm.group(1) if t.startswith("Part") else "S" + pm.group(1)
                elif lv == 3:
                    cm = re.match(r"^([A-J]\d{1,2})[GPDVOF]\d", t) or re.match(r"^(S\d{1,2})C\d", t)
                    code = cm.group(1) if cm else None
                    if code and code != cur_code:
                        label = f"Specification {code[1:]}" if code.startswith("S") else f"Part {code}"
                        it.part_break = TocEntry(2, label, pg.number, len(out))
                        cur_code = code
    return out


def match_headings(pages, entries):
    """Attach each TOC entry to the row that prints it. Returns unmatched entries."""
    rows = [it for pg in pages for it in pg.items if isinstance(it, Row)]
    first_row_of_page = {}
    for i, r in enumerate(rows):
        first_row_of_page.setdefault(r.page, i)
    pos = 0
    unmatched = []
    for e in entries:
        if e.row is not None:
            continue
        tk = key(e.title)
        if not tk:
            unmatched.append(e)
            continue
        start = max(pos, first_row_of_page.get(max(1, e.page - 1), pos))
        found = None
        for i in range(start, len(rows)):
            r = rows[i]
            if r.page > e.page + 1:
                break
            if r.kind == "heading" or (r.box is not None and not r.all_bold):
                continue
            rk = key(r.text)
            if not rk or not (rk.startswith(tk) or (len(rk) >= 4 and tk.startswith(rk))):
                continue
            # merge wrapped heading rows
            acc, j = rk, i
            while len(acc) < len(tk) and j + 1 < len(rows) and tk.startswith(acc) and j - i < 3:
                j += 1
                acc += key(rows[j].text)
            if acc == tk or (acc.startswith(tk) and len(tk) >= 0.8 * len(acc)) or (tk.startswith(acc) and len(acc) >= (0.8 if r.all_bold and len(acc) >= 30 else 0.9) * len(tk)):
                found = (i, j)
                break
        order = None
        if not found:
            # two-column headings: "Specification 44" left, title wrapped on the right,
            # so the rows interleave by height — try the orders of 2-3 adjacent bold rows
            for i in range(start, len(rows)):
                if rows[i].page > e.page + 1:
                    break
                for w in (2, 3):
                    win = rows[i:i + w]
                    if len(win) < w or any(x.page != win[0].page or not x.all_bold or x.kind != "row" for x in win):
                        continue
                    for perm in itertools.permutations(range(w)):
                        if "".join(key(win[p].text) for p in perm) == tk:
                            found, order = (i, i + w - 1), [i + p for p in perm]
                            break
                    if found:
                        break
                if found:
                    break
        if not found:
            unmatched.append(e)
            continue
        i, j = found
        order = order or list(range(i, j + 1))
        head = rows[order[0]]
        for k in order[1:]:                       # fold continuation rows into the heading
            head.spans = head.spans + [type(head.spans[0])(" ", False, False, 0)] + rows[k].spans
            rows[k].kind = "consumed"
        head.kind = "heading"
        e.row = head
        head.toc = e
        pos = j + 1
    return unmatched


# ---------------------------------------------------------------- chunks

@dataclass
class Chunk:
    l1: TocEntry | None
    l2: TocEntry | None
    items: list = field(default_factory=list)   # (page, label, item)
    seq: int = 0

    @property
    def title(self):
        if self.l2 is not None and self.l1 is not None:
            return f"{self.l1.title} — {self.l2.title}"
        if self.l1 is not None:
            return self.l1.title + (" (introduction)" if self.intro else "")
        if self.l2 is not None:
            return self.l2.title
        return "Front matter"

    intro: bool = False

    @property
    def pages(self):
        ps = [p for p, _, _ in self.items]
        return (min(ps), max(ps)) if ps else (None, None)


def build_chunks(pages, max_chars=120_000):
    chunks: list[Chunk] = []
    cur = Chunk(None, None)
    l1 = None
    for pg in pages:
        if not pg.items:
            cur.items.append((pg.number, pg.label, None))     # keep empty pages accounted for
            continue
        for it in pg.items:
            if isinstance(it, Row) and it.kind == "consumed":
                continue
            if isinstance(it, Row) and it.kind == "heading" and it.toc.level <= 2:
                if cur.items:
                    chunks.append(cur)
                if it.toc.level == 1:
                    l1 = it.toc
                    cur = Chunk(l1, None, intro=True)
                else:
                    cur = Chunk(l1, it.toc)
            elif isinstance(it, Row) and getattr(it, "part_break", None) is not None:
                if cur.items:
                    chunks.append(cur)
                cur = Chunk(l1, it.part_break)
            cur.items.append((pg.number, pg.label, it))
    if cur.items:
        chunks.append(cur)
    # drop "introduction" flag where the L1 node has no children at all
    for i, c in enumerate(chunks):
        if c.intro and not (i + 1 < len(chunks) and chunks[i + 1].l1 is c.l1 and chunks[i + 1].l2 is not None):
            c.intro = False
    # split oversized chunks at clause headings
    out = []
    for c in chunks:
        out.extend(_split(c, max_chars))
    for i, c in enumerate(out, 1):
        c.seq = i
    return out


def _item_len(it):
    if it is None:
        return 0
    if isinstance(it, Table):
        return sum(len(x or "") for r in it.rows for x in r)
    return len(it.text)


def _split(c, max_chars):
    total = sum(_item_len(it) for _, _, it in c.items)
    has_clauses = any(isinstance(it, Row) and it.kind == "heading" and it.toc.level >= 3 for _, _, it in c.items)
    if not has_clauses:
        max_chars = max_chars // 3        # glossaries / long lists: smaller files, named by letter range
    if total <= max_chars:
        return [c]
    def cut(items, is_boundary):
        parts, cur, size = [], [], 0
        prev_page = None
        for rec in items:
            if cur and size > max_chars * 0.6 and is_boundary(rec, prev_page):
                parts.append(cur)
                cur, size = [], 0
            cur.append(rec)
            size += _item_len(rec[2])
            prev_page = rec[0]
        if cur:
            parts.append(cur)
        return parts

    clause = lambda rec, _p: isinstance(rec[2], Row) and rec[2].kind == "heading" and rec[2].toc.level >= 3
    new_page = lambda rec, p: p is not None and rec[0] != p      # no clause headings (e.g. glossary)
    parts = []
    for part in cut(c.items, clause):
        big = sum(_item_len(r[2]) for r in part) > max_chars
        parts.extend(cut(part, new_page) if big else [part])
    out = []
    for n, items in enumerate(parts, 1):
        k = Chunk(c.l1, c.l2, items, intro=c.intro)
        k.part = (n, len(parts))
        out.append(k)
    return out


# ---------------------------------------------------------------- markdown

_MARKER = re.compile(r"^(\((?:\d{1,3}|[a-z]{1,2}|[ivxl]{1,6}|[A-Z]{1,2})\)|•|▪|◦)\s*")
_MD_ESC = re.compile(r"([*_`\\])")


def _esc(s: str) -> str:
    return _MD_ESC.sub(r"\\\1", s)


def row_md(r: Row) -> str:
    out, buf, cur_it = [], [], None

    def flush():
        if not buf:
            return
        t = "".join(buf)
        if cur_it and t.strip():
            lead = t[: len(t) - len(t.lstrip())]
            trail = t[len(t.rstrip()):]
            out.append(f"{lead}*{_esc(t.strip())}*{trail}")
        else:
            out.append(_esc(t))
        buf.clear()

    fs = formula_span([s.text for s in r.spans])
    for idx, s in enumerate(r.spans):
        if fs and fs[0] <= idx <= fs[1]:           # formula with lost operators: one marker, no junk
            if idx == fs[0]:
                flush()
                out.append(" " + UNREADABLE_MARK + " ")
            continue
        it = s.italic and bool(s.text.strip())
        if s.text.strip() and it != cur_it:
            flush()
            cur_it = it
        buf.append(s.text)
    flush()
    txt = re.sub(r"[ ]{2,}", " ", "".join(out)).strip()
    txt = re.sub(r"\*\s*\*", " ", txt) if txt.count("*") % 2 else txt
    return txt


def _page_tag(page, label):
    """Internal page tag (rewritten into library unit markers by `_to_units`)."""
    if label and label != str(page):
        return f"[p.{page} · printed {label}]"
    return f"[p.{page}]"


_TAG_RE = re.compile(r"^\[p\.(\d+)(?: · printed ([^\]]+))?\]$", re.M)
UNREADABLE_MARK = "⚠️[formula/symbols not readable"


def unit_open(page, chars, flags, printed=None):
    """Library unit marker: <!-- unit: p0002 | src: p.2 | chars: 1460 | flags: - -->"""
    pr = f" | printed: {printed}" if printed else ""
    return f"<!-- unit: p{page:04d} | src: p.{page}{pr} | chars: {chars} | flags: {flags or '-'} -->"


UNIT_CLOSE = "<!-- /unit -->"


def _to_units(md: str) -> str:
    """Wrap each page section (started by an internal [p.N] tag) in a unit marker pair."""
    tags = list(_TAG_RE.finditer(md))
    if not tags:
        return md
    out = [md[:tags[0].start()]]
    for i, m in enumerate(tags):
        end = tags[i + 1].start() if i + 1 < len(tags) else len(md)
        body = md[m.end():end].strip("\n")
        fl = (["unreadable_formula"] if UNREADABLE_MARK in body else []) + (["instruction_like"] if scan_instructions(body) else [])
        flags = ",".join(fl) if fl else "-"
        head = unit_open(int(m.group(1)), len(body), flags, m.group(2))
        out.append(head + "\n\n" + body + "\n\n" + UNIT_CLOSE + "\n\n")
    return "".join(out)


def table_grid(t: Table):
    def _cell(c):
        if UNREADABLE_RE.search(c):               # keep readable text around the formula
            fixed = []
            for ln in c.split("\n"):
                bad = [m.start() for m in UNREADABLE_RE.finditer(ln)]
                fixed.append(ln if not bad else ln[:bad[0]] + " " + UNREADABLE_MARK + " " + ln[bad[-1] + 1:])
            c = "\n".join(fixed)
        c = re.sub(r"(?<=[\d/])\n(?=\d)", "", c)          # "120/120/1\n20" -> "120/120/120"
        return c.replace("\n", " ").strip()
    rows = [[_cell(c) if c is not None else None for c in r] for r in t.rows]
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return [], []
    ncol = max(len(r) for r in rows)
    rows = [r + [None] * (ncol - len(r)) for r in rows]
    notes = []
    # full-width note rows (one text cell, rest merged) become notes below the table
    body = []
    for r in rows:
        filled = [c for c in r if c]
        if len(filled) == 1 and r[0] and all(c is None for c in r[1:]) and len(r[0]) > 60:
            notes.append(r[0])
        else:
            body.append(r)
    if not body:
        return [], notes
    hdr_n = 1
    if len(body) > 2 and any(c is None for c in body[0][1:]):
        hdr_n = 2
    hdr = [list(r) for r in body[:hdr_n]]
    for r in hdr:                                   # horizontal spans in header
        for j in range(1, ncol):
            if r[j] is None:
                r[j] = r[j - 1]
    if hdr_n == 2:
        for j in range(ncol):
            if not hdr[1][j]:
                hdr[1][j] = None
    head = []
    for j in range(ncol):
        vals = []
        for r in hdr:
            v = r[j]
            if v and v not in vals:
                vals.append(v)
        head.append(" — ".join(vals))
    grid = [head] + [[c or "" for c in r] for r in body[hdr_n:]]
    return grid, notes


def table_md(t: Table):
    grid, notes = table_grid(t)
    if not grid:
        return "", notes
    ncol = len(grid[0])
    cell = lambda c: (c or "").replace("|", "\\|")
    lines = ["| " + " | ".join(cell(h) for h in grid[0]) + " |", "|" + "---|" * ncol]
    for r in grid[1:]:
        lines.append("| " + " | ".join(cell(c) for c in r) + " |")
    return "\n".join(lines), notes


def render_chunk(c: Chunk) -> str:
    out: list[str] = []
    para: list[str] = []
    para_box = None
    prev_row: Row | None = None
    last_page = None

    def flush():
        nonlocal para, para_box
        if para:
            text = " ".join(para)
            # one italic term broken by a line wrap: "*Performance* *Requirements*" -> "*Performance Requirements*"
            text = re.sub(r"(?<=\w)\* \*(?=\w)", " ", text)
            if para_box is not None:
                out.append("> " + text)
                out.append(">")
            else:
                out.append(text)
                out.append("")
        para, para_box = [], None

    def end_quote():
        if out and out[-1] == ">":
            out[-1] = ""

    for page, label, it in c.items:
        if page != last_page:
            flush()
            end_quote()
            out.append(_page_tag(page, label))
            out.append("")
            last_page = page
            prev_row = None
            if it is None:
                out.append("*(no text on this page)*")
                out.append("")
        if it is None:
            continue
        if isinstance(it, Table):
            flush()
            end_quote()
            md, notes = table_md(it)
            if md:
                out.append(md)
                out.append("")
            for n in notes:
                out.append(_esc(n))
                out.append("")
            prev_row = None
            continue
        r: Row = it
        if r.kind == "heading":
            flush()
            end_quote()
            lv = min(r.toc.level, 4)
            out.append("#" * lv + " " + _esc(r.text) + f" · p.{page}")
            out.append("")
            prev_row = None
            continue
        text = row_md(r)
        if not text:
            continue
        if r.box != para_box and para:
            flush()
        if para_box is None and r.box is None and out and out[-1] == ">":
            end_quote()
        m = _MARKER.match(r.text)
        gap = (r.bbox[1] - prev_row.bbox[3]) if prev_row is not None else 99
        short_bold = r.all_bold and len(r.text) < 90
        new_para = (not para or m is not None or gap > 4.5 or short_bold
                    or (prev_row is not None and prev_row.all_bold and not r.all_bold))
        if new_para:
            flush()
            if r.box is None and out and out[-1] == ">":
                end_quote()
            if m and m.group(1) in "•▪◦":
                text = "- " + text[len(m.group(0)):].lstrip() if text.startswith(m.group(1)) else text
            if short_bold:
                text = f"**{text.replace('**', '')}**" if "*" not in text else text
                if r.box is not None and r.text.lower().startswith("explanatory information"):
                    text += " *(informative — not mandatory)*"
            para_box = r.box
            para.append(text)
        else:
            if para and para[-1].endswith("-") and not para[-1].endswith(" -"):
                para[-1] = para[-1] + text
            else:
                para.append(text)
        prev_row = r
    flush()
    end_quote()
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return _to_units(md).strip() + "\n"
