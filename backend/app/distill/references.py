"""Which editions the building code itself calls up (requirements v2, D-1: checked against an official source).

The NCC lists every standard it relies on in Schedule 2 "Referenced documents": number, part, date, title and the
clauses that use it. That table is the authority on which edition is in force under that NCC; "the newest edition
this library holds" is not (on 2026-11-22 the AS 3500 room's newest were the 2021 editions while NCC 2025 calls up
AS/NZS 3500 Parts 1–4:2025). NCC 2022 onward is CC BY 4.0, so the extracted facts may be kept and shipped.

Adoption differs by state and date (NSW adopts NCC 2025 on 2027-05-01; NCC 2022 applies until then), so an edition
the newer code replaces is reported as "a newer edition is called up", never as withdrawn.
"""
from __future__ import annotations

import json
import os
import re

_ENTRY = re.compile(r"(?m)^(?P<prefix>AS/NZS|AS|NZS|SA TS|SA/SNZ TS|ISO|IEC|EN|BS)\s+(?P<num>\d{3,5})"
                    r"(?:\s+Part\s*\n?\s*(?P<part>[\d.]+))?[^\n]*\n\s*(?P<year>(?:19|20)\d{2})[A-Z]?\s*\n")
_CLAUSE = re.compile(r"\b(?:[A-J]\d[A-Z]\d{1,2}|Spec(?:ification)?\s*\d+|Schedule\s*\d+|\d+\.\d+\.\d+)\b")
_NOISE = re.compile(r"(?m)^(?:Referenced documents|NCC \d{4} Volume [A-Za-z]+ - .*|Page \d+\s*|No\.|Date|Title|"
                    r"Volume One|Volume Two|Housing Provisions|Volume Three)\s*$")
DATA = os.path.join(os.path.dirname(__file__), "data")


def parse_table(text: str) -> list[dict]:
    """Rows of a "Referenced documents" table read from the PDF's text (one row per edition)."""
    text = _NOISE.sub("", text)
    hits = list(_ENTRY.finditer(text))
    out = []
    for i, m in enumerate(hits):
        body = text[m.end(): hits[i + 1].start() if i + 1 < len(hits) else len(text)]
        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        title = []
        for ln in lines:
            if ln == "N/A" or _CLAUSE.match(ln):
                break
            title.append(ln)
        number = m.group("num") + (f".{m.group('part')}" if m.group("part") else "")
        clauses = sorted(set(_CLAUSE.findall(body)) - {""}, key=lambda c: (len(c), c))
        out.append({"prefix": m.group("prefix"), "number": number, "year": m.group("year"),
                    "designation": f"{m.group('prefix')} {number}:{m.group('year')}",
                    "title": re.sub(r"\s+", " ", " ".join(title)).strip(" —-"), "clauses": clauses})
    return out


def load(name: str = "ncc2025_references.json") -> dict:
    """{"code": "NCC 2025", "rows": [...]}; an empty set when the file is missing."""
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"code": "", "rows": []}


def by_number(refs: dict) -> dict:
    """{"3500.1": [{"year": "2025", "designation": …, "clauses": […]}, …]} for quick lookup."""
    out: dict = {}
    for r in refs.get("rows", []):
        out.setdefault(r["number"], []).append(r)
    return out
