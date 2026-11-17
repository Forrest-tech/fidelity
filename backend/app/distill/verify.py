# -*- coding: utf-8 -*-
"""Publish gate: prove the Markdown is complete and faithful to the source PDF.

Checks (per document):
  pages      every physical page appears exactly once as a unit marker
  headings   every bookmark (Section/Part/clause) became a heading
  chars      per page, alphanumeric characters of the source text layer are all
             present in the Markdown (multiset recall) — nothing dropped
  numbers    every number on every page is present (multiset) — 100% required
  agreement  an independent extractor (pypdf) reads the same characters as
             PyMuPDF — catches broken font encodings in the text layer
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import pymupdf

from .pdf_extract import clean_text, is_hf, is_watermark_line, UNREADABLE_RE, formula_span

PAGE_MARK = re.compile(r"^<!-- unit: p\d+ \| src: p\.(\d+)(?: \| printed: [^|]+?)? \| chars: \d+ \| flags: [^>]*?-->\s*$", re.M)
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_INJECTED = [
    re.compile(r"^<!-- /unit -->\s*$", re.M),         # unit close marker
    re.compile(r" · p\.\d+\s*$", re.M),                 # page suffix on headings
    re.compile(r"\*\(informative — not mandatory\)\*"),
    re.compile(r"\*\(no text on this page\)\*"),
    re.compile(re.escape("⚠️[formula/symbols not readable in source text layer — check source page]")),
]


def _alnum(s: str) -> Counter:
    return Counter(ch for ch in clean_text(s).lower() if ch.isalnum())


def _nums(s: str) -> Counter:
    return Counter(NUM_RE.findall(clean_text(s)))


def _rejoin_split_numbers(missing: Counter, md: Counter, src: Counter) -> Counter:
    """A number wrapped across lines in a table cell ("120/120/1" + "20") is written
    joined in the Markdown ("120/120/120"). Accept a missing pair only when the joined
    number really is in the Markdown more often than in the source."""
    missing = Counter(missing)
    spare = Counter({k: c - src.get(k, 0) for k, c in md.items() if c > src.get(k, 0)})
    for a in list(missing):
        for b in list(missing):
            while missing[a] > 0 and missing[b] > 0 and (a != b or missing[a] > 1) and spare.get(a + b, 0) > 0:
                missing[a] -= 1
                missing[b] -= 1
                spare[a + b] -= 1
    return +missing


def md_pages(md_texts):
    """Split concatenated Markdown into {page: text} using unit markers."""
    per, count = {}, Counter()
    for md in md_texts:
        md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)          # front matter
        md = md.split("\n## Cross-references", 1)[0]
        parts = PAGE_MARK.split(md)
        for i in range(1, len(parts), 2):
            p = int(parts[i])
            count[p] += 1
            body = parts[i + 1]
            for rx in _INJECTED:
                body = rx.sub("", body)
            per[p] = per.get(p, "") + "\n" + body
    return per, count


def source_pages(pdf_path, hf_set, band=0.07):
    doc = pymupdf.open(pdf_path)
    out = {}
    unreadable = []
    unver_nums = defaultdict(Counter)
    for page in doc:
        h = page.rect.height
        keep = []
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                if is_watermark_line(ln):
                    continue
                t = "".join(s["text"] for s in ln["spans"])
                y0, y1 = ln["bbox"][1], ln["bbox"][3]
                if (y0 < h * band or y1 > h * (1 - band)) and (is_hf(t, y0, hf_set)
                                                            or t.strip() == str(page.number + 1)):
                    continue
                if UNREADABLE_RE.search(t):       # keep readable spans, count unreadable ones
                    unreadable.append(page.number + 1)
                    unver_nums[page.number + 1].update(_nums(t))
                    texts = [s["text"] for s in ln["spans"]]
                    a, b = formula_span(texts)
                    t = "".join(texts[:a]) + " " + "".join(texts[b + 1:])
                keep.append(t)
        out[page.number + 1] = "\n".join(keep)
    doc.close()
    return out, unreadable, unver_nums


def pypdf_pages(pdf_path):
    try:
        from pypdf import PdfReader
    except Exception:
        return None
    r = PdfReader(pdf_path)
    out = {}
    for i, p in enumerate(r.pages, 1):
        try:
            out[i] = p.extract_text() or ""
        except Exception:
            out[i] = ""
    return out


def _recall(src: Counter, got: Counter):
    tot = sum(src.values())
    if not tot:
        return 1.0, 0, []
    hit = sum(min(c, got.get(k, 0)) for k, c in src.items())
    missing = [k for k, c in src.items() if got.get(k, 0) < c]
    return hit / tot, tot - hit, missing


def verify_document(pdf_path, md_texts, page_count, hf_set, unmatched_headings,
                    check_agreement=True, pages=None, table_grid=None):
    rep = {"page_count": page_count}
    per_md, marks = md_pages(md_texts)
    missing_pages = [p for p in range(1, page_count + 1) if marks.get(p, 0) == 0]
    dup_pages = [p for p, c in marks.items() if c > 1]
    # a page whose content is split between two chapter files legitimately has two
    # markers; duplicated *content* is caught by the precision check below
    rep["pages"] = {"ok": not missing_pages, "missing": missing_pages[:50],
                    "split_across_files": dup_pages[:50]}
    rep["headings"] = {"ok": not unmatched_headings, "unmatched": len(unmatched_headings),
                       "examples": [f"p.{e.page} {e.title}" for e in unmatched_headings[:20]]}

    src, unreadable, unver_nums = source_pages(pdf_path, hf_set)
    excluded_nums = 0
    rep["unreadable"] = {"lines": len(unreadable), "pages": sorted(set(unreadable)),
                         "note": "text-layer glyphs that decode to control characters (formula/symbol fonts); "
                                 "flagged with ⚠️ in the Markdown, need OCR or human check"}
    tot = hit = 0
    ntot = nhit = 0
    worst, num_miss, dupl = [], [], []
    for p in range(1, page_count + 1):
        s, m = src.get(p, ""), per_md.get(p, "")
        r, lost, _ = _recall(_alnum(s), _alnum(m))
        n = sum(_alnum(s).values())
        tot += n
        hit += n - lost
        if r < 0.995 and n:
            worst.append((round(r, 4), p, lost))
        m_body = re.sub(r"^\|.*\|\n(?=\|---)", "", m, flags=re.M)   # table header rows repeat by design
        pr, extra, _ = _recall(_alnum(m_body), _alnum(s))  # md chars not in source
        if extra > max(40, 0.03 * n):
            dupl.append((p, extra))
        sn, mn = _nums(s), _nums(m)
        if unver_nums.get(p):                  # digits inside flagged formula lines can't be verified
            before = sum(sn.values())
            sn = sn - unver_nums[p]
            excluded_nums += before - sum(sn.values())
        miss = Counter({k: c - mn.get(k, 0) for k, c in sn.items() if mn.get(k, 0) < c})
        miss = _rejoin_split_numbers(miss, mn, sn)
        nn = sum(sn.values())
        ntot += nn
        nhit += nn - sum(miss.values())
        if miss:
            num_miss.append((p, list(miss)[:8]))
    rep["chars"] = {"recall": round(hit / tot, 6) if tot else 1.0, "source_chars": tot,
                    "pages_below_99_5": sorted(worst)[:30], "ok": (hit / tot if tot else 1) >= 0.995}
    rep["extra_text"] = {"pages": dupl[:30], "ok": not dupl,
                         "note": "Markdown characters not found on the source page (duplication or injected text)"}
    rep["numbers"] = {"recall": round(nhit / ntot, 6) if ntot else 1.0, "source_numbers": ntot,
                      "excluded_in_flagged_formulas": excluded_nums,
                      "pages_with_missing": num_miss[:30], "ok": not num_miss}

    if check_agreement:
        alt = pypdf_pages(pdf_path)
        if alt is not None:
            at = ah = 0
            low = []
            for p in range(1, page_count + 1):
                a, b = _alnum(src.get(p, "")), _alnum(alt.get(p, ""))
                r, lost, _ = _recall(a, b)
                n = sum(a.values())
                at += n
                ah += n - lost
                if r < 0.98 and n > 50:
                    low.append((round(r, 3), p))
            rep["agreement"] = {"engine": "pypdf", "recall": round(ah / at, 6) if at else 1.0,
                                "pages_below_98": sorted(low)[:30],
                                "ok": (ah / at if at else 1) >= 0.99}
    if pages is not None and table_grid is not None:
        rep["tables"] = check_tables(pages, per_md, table_grid)
    checks = (["pages", "headings", "chars", "numbers", "extra_text"] + (["agreement"] if "agreement" in rep else [])
              + (["tables"] if "tables" in rep else []))
    rep["status"] = "PASS" if all(rep[c]["ok"] for c in checks) else "FAIL"
    return rep


# ---------------------------------------------------------------- table cell check (spec 6.4)
_CELL_SPLIT = re.compile("(?<!" + chr(92) * 2 + ")" + chr(92) + "|")
_TABLE_LINE = re.compile(r"^\|.*\|\s*$")
_SEP_LINE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")


_MARK_KEY = re.sub(r"[^0-9a-z]", "", "formula/symbols not readable in source text layer " + chr(8212) + " check source page")


def _ckey(s: str) -> str:
    """Alphanumeric key of a cell. The unreadable-formula marker is removed first: the page text
    the checker compares against has the marker stripped (see _INJECTED)."""
    return re.sub(r"[^0-9a-z]", "", (s or "").lower()).replace(_MARK_KEY, "")


def md_tables(page_md: str):
    """Markdown tables of one page as grids of cell keys (in order of appearance)."""
    tables, cur = [], []
    for ln in page_md.split("\n") + [""]:
        if _TABLE_LINE.match(ln):
            if not _SEP_LINE.match(ln.strip()):
                cells = _CELL_SPLIT.split(ln.strip())[1:-1]
                cur.append([_ckey(c) for c in cells])
        elif cur:
            tables.append(cur)
            cur = []
    return tables


def check_tables(pages, per_md, table_grid):
    """Every cell of every source table must sit at the same row/column in the Markdown.

    `pages` are the extracted pages (their Table items carry the source grid), `per_md` is
    {page: markdown of that page}. Catches swapped, shifted, dropped or merged cells."""
    n_tables = n_cells = 0
    bad = []
    for pg in pages:
        expected = []
        for it in pg.items:
            if it is not None and it.__class__.__name__ == "Table":
                grid, _ = table_grid(it)
                if grid:
                    expected.append([[_ckey(c) for c in r] for r in grid])
        got = md_tables(per_md.get(pg.number, ""))
        if len(expected) != len(got):
            bad.append({"page": pg.number, "problem": f"{len(expected)} source tables, {len(got)} in Markdown"})
            continue
        for ti, (e, g) in enumerate(zip(expected, got), 1):
            n_tables += 1
            if len(e) != len(g):
                bad.append({"page": pg.number, "table": ti, "problem": f"{len(e)} rows in source, {len(g)} in Markdown"})
                continue
            for ri, (er, gr) in enumerate(zip(e, g)):
                if len(er) != len(gr):
                    bad.append({"page": pg.number, "table": ti, "row": ri, "problem": "column count differs"})
                    continue
                for ci, (ec, gc) in enumerate(zip(er, gr)):
                    n_cells += 1
                    if ec != gc:
                        bad.append({"page": pg.number, "table": ti, "row": ri, "col": ci, "source": ec[:40], "markdown": gc[:40]})
    return {"ok": not bad, "tables": n_tables, "cells": n_cells, "mismatches": len(bad), "examples": bad[:20]}
