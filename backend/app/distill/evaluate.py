"""Measured accuracy against a known-good text (requirements v2, Q-1 and §9 "who proves it").

Ground truth without a person: a library often holds the same edition twice — a native text PDF (exact text) and a
printed scan. Comparing what was distilled from the scan with what was distilled from the native copy, page by page,
measures OCR on real scans. The same metrics serve the synthetic gate in CI (tests/test_eval_gate.py).

Metrics per page (both sides normalised: Markdown marks, unit markers and whitespace removed, lower-case):
  cer           — character error rate, Levenshtein distance / truth length (order-sensitive; tables that come out in
                  a different order count as errors, so this is the strict figure);
  word_recall   — share of the truth's words found in the scan's words (order-free);
  number_recall — share of the truth's numbers found in the scan's numbers (a missing number is the costly error);
  number_extra  — numbers the scan has that the truth has not (an invented or misread number).
"""
from __future__ import annotations

import collections
import os
import re
import unicodedata

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

MIN_PAGE_CHARS = 300
UNIT = re.compile(r"<!-- unit: p\d+ \| src: p\.(\d+)[^>]*-->(.*?)(?=<!-- unit:|<!-- /unit -->|\Z)", re.S)
_MARKS = re.compile(r"<!--.*?-->|[#*_|`>\[\]]|⚠️", re.S)
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
_FOLD = str.maketrans({"–": "-", "—": "-", "‑": "-", "−": "-", "’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})


# Lines that are not the document's content and differ between copies by nature: the vendor's licence stamp (one
# copy carries it in its text layer, an OCR of another copy does not see it) and the running header with the
# designation (an OCR reads it, a text layer often leaves it out). Left in, they cost every page two or three numbers.
_STAMP = re.compile(r"licensed to\b.{0,220}?(?:prohibited(?:\s*\(\d+\))?\.?|use only\.?)"
                    r"|accessed by\b.{0,120}?\b(?:19|20)\d{2}\b(?:\s*\(document currency[^)]*\))?", re.I)
_HEADER = re.compile(r"\b(?:as\s*/\s*nzs|as|nzs)\s+\d{3,5}(?:\.\d+)*\s*[:—–-]\s*(?:19|20)\d{2}\b", re.I)
_TIGHT = re.compile(r"(?<=\d)\s*([x×%:])\s*(?=[\d(])")
_DN = re.compile(r"\b(dn|da|pn)\s+(?=\d)", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_FOLD)
    s = _MARKS.sub(" ", s)
    s = _STAMP.sub(" ", s)
    s = _HEADER.sub(" ", s)
    s = _TIGHT.sub(r"\1", s)          # "80 x 100", "1% (1:100)": spacing is not content
    s = _DN.sub(r"\1", s)             # "DN 65" / "DN65"
    return re.sub(r"\s+", " ", s).strip().lower()


def pages_of(markdown_files: list[str]) -> dict[int, str]:
    """{source page: text} from a distilled document's files (a document folder has its pages spread over files)."""
    out: dict = collections.defaultdict(str)
    for f in markdown_files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            for m in UNIT.finditer(fh.read()):
                out[int(m.group(1))] += "\n" + m.group(2)
    return {p: norm(t) for p, t in out.items()}


def compare_page(truth: str, got: str) -> dict:
    tn, gn = _NUM.findall(truth), _NUM.findall(got)
    tw, gw = collections.Counter(_WORD.findall(truth)), collections.Counter(_WORD.findall(got))
    tc, gc = collections.Counter(tn), collections.Counter(gn)
    return {"chars": len(truth),
            "cer": Levenshtein.distance(truth, got) / len(truth) if truth else 0.0,
            "word_recall": sum((tw & gw).values()) / sum(tw.values()) if tw else 1.0,
            "numbers": len(tn),
            "number_recall": sum((tc & gc).values()) / len(tn) if tn else 1.0,
            "number_extra": sum((gc - tc).values())}


def align(truth: dict[int, str], test: dict[int, str], window: int = 8, min_match: float = 55.0) -> list[tuple]:
    """(test page, truth page, similarity) for each test page whose best match within ±window pages of the expected
    position is similar enough. A printed copy often has a few extra pages (cover, licence sheet), so pages shift."""
    pairs, shift = [], 0
    tkeys = sorted(truth)
    for p in sorted(test):
        if len(test[p]) < 40:
            continue
        best, best_score = None, 0.0
        for q in tkeys:
            if abs(q - (p + shift)) > window:
                continue
            s = fuzz.token_set_ratio(test[p][:3000], truth[q][:3000])
            if s > best_score:
                best, best_score = q, s
        if best is not None and best_score >= min_match:
            pairs.append((p, best, best_score))
            shift = best - p
    return pairs


def compare_documents(truth: dict[int, str], test: dict[int, str]) -> dict:
    """Summary over aligned pages, with the per-page rows for the worst pages."""
    rows = []
    for p, q, sim in align(truth, test):
        a, b = truth[q], test[p]
        if len(a) < MIN_PAGE_CHARS or not 0.5 <= len(b) / len(a) <= 2.0:
            continue                       # a cover, a blank or a page the other copy splits differently
        r = compare_page(a, b)
        rows.append({"page": p, "truth_page": q, "similarity": round(sim, 1), **r})
    if not rows:
        return {"pages": 0}
    chars = sum(r["chars"] for r in rows) or 1
    nums = sum(r["numbers"] for r in rows) or 1
    return {"pages": len(rows), "test_pages": len(test), "truth_pages": len(truth),
            "cer": round(sum(r["cer"] * r["chars"] for r in rows) / chars, 4),
            "word_recall": round(sum(r["word_recall"] * r["chars"] for r in rows) / chars, 4),
            "number_recall": round(sum(r["number_recall"] * r["numbers"] for r in rows) / nums, 4),
            "number_extra": sum(r["number_extra"] for r in rows),
            "pages_cer_le_1pct": sum(1 for r in rows if r["cer"] <= 0.01),
            "pages_all_numbers": sum(1 for r in rows if r["number_recall"] >= 1.0),
            "worst": sorted(rows, key=lambda r: -r["cer"])[:5]}


def markdown_files(path: str) -> list[str]:
    if os.path.isfile(path):
        return [path]
    return sorted(os.path.join(a, f) for a, _, ff in os.walk(path) for f in ff if f.lower().endswith(".md"))
