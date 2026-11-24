"""Fixed grading rules (docs/acceptance/plan.md section 3), no model involved, so anyone re-running them gets the same
marks. A citation counts only when its quote is really on the cited page of the ORIGINAL PDF (±1 page)."""
from __future__ import annotations

import math
import re

from .text import contains_value, norm, numbers, page_has, pdf_pages

_NOT_FOUND = re.compile(r"not found|not in the (?:knowledge base|library)|no (?:such|clause)|does not (?:exist|contain)"
                        r"|isn'?t in|not held|not available", re.I)


def _doc_matches(cited: str, designation: str) -> bool:
    num = re.search(r"3500\.\d", designation)
    year = re.search(r"(?:19|20)\d{2}", designation)
    c = cited.replace(" ", "")
    return bool(num and num.group(0) in c and (not year or year.group(0) in c))


def _pieces(quote: str) -> list[str]:
    """A quote as people write it: fragments joined by "…" and sentences that skip a heading in between. Every piece
    must still be on the page word for word; a piece too short to mean anything on its own is not counted."""
    quote = re.sub(r"(?m)^#+\s*|\s*·\s*p\.\d+\b", "", quote)       # the library's heading marks and page tags
    parts = re.split(r"\s*(?:\.\.\.|…)\s*|(?<=[.;:])\s+(?=[A-Z(\[])|\n+", quote)
    return [p.strip(" -—–") for p in parts if len(p.strip(" -—–")) >= 15]


def _piece_on_page(src: str, page: int, piece: str) -> bool:
    if page_has(src, page, piece, spread=1):
        return True
    # a table row ("80 100 125 150 | 1.65 1.65 …") or a drawing's labels ("Floor waste gully riser — Untrapped
    # waste DN 25 …") come out of the PDF cell by cell, in another order: then every cell must be on that page
    if "|" not in piece and "—" not in piece and not piece.startswith("["):
        return False
    cells = [c for c in re.split(r"\s*(?:\||—|\*\*)\s*", re.sub(r"^\[[^\]]*\]", "", piece)) if re.search(r"\w", c)]
    pages = pdf_pages(src)
    near = " ".join(norm(pages[p - 1]) for p in (page - 1, page, page + 1) if 1 <= p <= len(pages))
    return bool(cells) and all(norm(c) in near or all(n in numbers(near) for n in numbers(c)) and not re.search(r"[a-z]{3}", norm(c))
                               for c in cells)


_WORD = re.compile(r"[a-z]{3,}")


def _words_on_page(src: str, page: int, quote: str) -> bool:
    """Every number and at least 95 % of the content words of the quote are on that page (± 1). A table quoted as one
    line ("Kerb channels: without concrete gutter with concrete gutter …") or with stray punctuation ("Table 6.6.1. .")
    has its words in another order than the PDF's text layer; a figure that is not on the page still fails."""
    q = norm(quote)
    words, nums = _WORD.findall(q), numbers(quote)
    if len(words) < 6:
        return False
    pages = pdf_pages(src)
    for p in (page - 1, page, page + 1):
        if 1 <= p <= len(pages):
            h = norm(pages[p - 1])
            hw, hn = set(_WORD.findall(h)), set(numbers(h))
            if all(n in hn for n in nums) and sum(w in hw for w in words) >= 0.95 * len(words):
                return True
    return False


def _quote_on_page(src: str, page: int, quote: str, cat: str) -> bool:
    if page_has(src, page, quote, spread=1):
        return True
    if _words_on_page(src, page, quote):
        return True
    pieces = _pieces(quote)
    if pieces and sum(len(p) for p in pieces) >= 30 and all(_piece_on_page(src, page, p) for p in pieces):
        return True
    if not cat.startswith("E"):
        return False
    # a table row comes out of the PDF cell by cell: every figure of the quoted row must be on that page
    want = numbers(quote)
    pages = pdf_pages(src)
    return len(want) >= 2 and any(1 <= p <= len(pages) and set(want) <= set(numbers(pages[p - 1]))
                                  for p in (page - 1, page, page + 1))


def _said(a: dict) -> str:
    return " ".join([a.get("answer") or "", " ".join(a.get("values") or [])])


def grade_one(q: dict, a: dict, sources: dict[str, str]) -> dict:
    g = q.get("ground", {})
    said = _said(a)
    r = {"id": q["id"], "cat": q["cat"], "model": a.get("model"), "error": a.get("error")}
    if a.get("error"):        # the call failed (out of credit, network): not an answer, so not graded
        return {**r, "pass": None, "why": "not answered: " + a["error"]}
    trap = q.get("trap")
    if trap in ("not_found", "not_held"):
        refused = a.get("status") in ("not_found", "not_held") or bool(_NOT_FOUND.search(a.get("answer") or ""))
        invented = a.get("status") == "answered" and bool(numbers(" ".join(a.get("values") or [])))
        ok = refused and not invented
        return {**r, "pass": ok, "honesty_ok": ok, "why": "" if ok else "gave an answer to a question the library cannot answer"}
    src = sources.get(g.get("doc", ""))
    # a figure the question itself gives ("DN 25", "600 mm") is not something the answer has to supply (2026-11-24:
    # the Grok sample was marked wrong for not repeating the question's own figures in its final line)
    asked = q.get("q") or q.get("question") or ""
    needed = [v for v in g.get("values", []) if not contains_value(asked, v)] or g.get("values", [])
    values_ok = all(contains_value(said, v) for v in needed)
    hit = any(x.get("source") == g.get("doc") and abs(x.get("page", 0) - g.get("page", 0)) <= 1 for x in a.get("retrieved", []))
    good_cites = [c for c in a.get("citations") or []
                  if _doc_matches(c.get("document", ""), g["designation"]) and abs(int(c.get("page") or 0) - g["page"]) <= 1
                  and src and _quote_on_page(src, int(c.get("page") or 0), c.get("quote", ""), q["cat"])]
    citation_ok = bool(good_cites)
    # requirements v3 V-2: the strict measure, the cited page is exactly the page the answer comes from
    page_exact = any(int(c.get("page") or 0) == g["page"] for c in good_cites)
    status_ok = a.get("status") == "answered"
    if q["cat"].startswith("D"):                       # a superseded edition must be named as superseded
        status_ok = status_ok and bool(re.search(r"supersed|replaced|no longer current|not (?:the )?current",
                                                 said + " " + (a.get("edition_used") or ""), re.I))
    premise_ok = True
    if trap == "false_premise":                        # must not go along with the wrong figure
        premise_ok = not contains_value(said, g["wrong"]) or contains_value(said, g["values"][0])
    ok = values_ok and citation_ok and status_ok and premise_ok
    why = [w for w, bad in (("figure wrong or missing", not values_ok), ("citation not on the cited source page", not citation_ok),
                            ("edition status not stated" if q["cat"].startswith("D") else "did not answer", not status_ok),
                            ("accepted the false premise", not premise_ok)) if bad]
    return {**r, "pass": ok, "answer_ok": values_ok, "citation_ok": citation_ok, "page_exact": page_exact, "status_ok": status_ok,
            "found_by_search": hit, "why": "; ".join(why),
            "blame": "" if ok else ("library search: the page was not among the excerpts" if not hit else "answer")}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def summary(rows: list[dict]) -> dict:
    skipped = sum(1 for r in rows if r["pass"] is None)
    rows = [r for r in rows if r["pass"] is not None]
    n, k = len(rows), sum(r["pass"] for r in rows)
    lo, hi = wilson(k, n)
    cats: dict = {}
    for r in rows:
        c = cats.setdefault(r["cat"], [0, 0])
        c[0] += r["pass"]
        c[1] += 1
    traps = [r for r in rows if r["cat"].startswith("F")]
    cited = [r for r in rows if "page_exact" in r and r.get("answer_ok")]
    pk = sum(r["page_exact"] for r in cited)
    plo, phi = wilson(pk, len(cited))
    return {"questions": n, "not_answered": skipped, "passed": k, "rate": round(k / n, 4) if n else 0, "ci95": [round(lo, 4), round(hi, 4)],
            "traps": [sum(r["pass"] for r in traps), len(traps)],
            # v3 V-2: of the answers with the right figure, how many cite exactly the page it is on
            "page_exact": {"of": len(cited), "exact": pk, "rate": round(pk / len(cited), 4) if cited else 0,
                           "ci95": [round(plo, 4), round(phi, 4)],
                           "value_right_page_wrong": sum(1 for r in cited if not r["citation_ok"])},
            "by_category": {c: {"passed": a, "of": b} for c, (a, b) in sorted(cats.items())},
            "blame": {b: sum(1 for r in rows if r.get("blame") == b) for b in {r.get("blame") for r in rows} if b}}
