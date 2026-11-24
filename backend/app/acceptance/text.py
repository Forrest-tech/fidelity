"""Text normalisation and source-page access shared by question generation and grading."""
from __future__ import annotations

import functools
import os
import re
import unicodedata

_FOLD = str.maketrans({"–": "-", "—": "-", "‑": "-", "−": "-", "’": "'", "‘": "'", "“": '"', "”": '"',
                       " ": " ", " ": " ", " ": " ", " ": " ", "×": "x"})
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def norm(s: str) -> str:
    """Lower case, one space, Markdown marks gone, "100 mm" == "100mm", "1 000" == "1000", dashes folded."""
    s = unicodedata.normalize("NFKC", s or "").translate(_FOLD)
    s = re.sub(r"<!--.*?-->|[*_|`#>\[\]]", " ", s, flags=re.S)
    s = re.sub(r"(?<=\d) (?=\d{3}\b)", "", s)                    # thousands written with a space
    s = re.sub(r"(?<=\d)\s+(?=(?:mm|m|kpa|kg|l|s|°c|%|m/s|l/s|dn|h|min)\b)", "", s.lower())
    s = re.sub(r"\s*([/:=])\s*", r"\1", s)
    s = re.sub(r"\b(dn|da|pn)\s+(?=\d)", r"\1", s)                 # "DN 65" == "DN65"
    return re.sub(r"\s+", " ", s).strip()


def numbers(s: str) -> list[str]:
    return [n.replace(",", "") for n in _NUM.findall(norm(s))]


def contains_value(hay: str, value: str) -> bool:
    """`value` (a figure from the standard, e.g. "600 mm" or "15 to 50 kPa") is stated in `hay`: either verbatim
    after normalising, or every number in it appears in `hay` and so does its unit word."""
    v, h = norm(value), norm(hay)
    if v and v in h:
        return True
    want = numbers(value)
    if not want:
        return False
    have = set(numbers(hay))
    if not all(n in have for n in want):
        return False
    units = re.findall(r"(?<=\d)(mm|m|kpa|kg|l/s|m/s|°c|%|dn|l|h|min)\b", v)
    return all(u in h for u in units)


def _lp(p: str) -> str:
    p = os.path.abspath(p)
    return "\\\\?\\" + p if os.name == "nt" and not p.startswith("\\\\") else p


@functools.lru_cache(maxsize=16)
def pdf_pages(path: str) -> tuple[str, ...]:
    """Text of each page of the ORIGINAL PDF (the publisher's text layer), 1-based index = position + 1."""
    import pymupdf
    with pymupdf.open(_lp(path)) as doc:
        return tuple(pg.get_text() for pg in doc)


def page_has(path: str, page: int, text: str, spread: int = 0, min_ratio: float = 92.0) -> bool:
    """`text` is on page `page` (± `spread`) of the source PDF; long quotes may differ in a few characters
    (line breaks, hyphenation)."""
    from rapidfuzz import fuzz
    pages = pdf_pages(path)
    t = norm(text)
    if not t:
        return False
    for p in range(page - spread, page + spread + 1):
        if 1 <= p <= len(pages):
            h = norm(pages[p - 1])
            if t in h:
                return True
            # a near match forgives line breaks and hyphenation, never a figure: every number of the quote must be on
            # the page (found 2026-11-24: "1:100" passed for a page that says "1:150")
            if len(t) >= 20 and fuzz.partial_ratio(t, h) >= min_ratio and set(numbers(t)) <= set(numbers(h)):
                return True
    return False
