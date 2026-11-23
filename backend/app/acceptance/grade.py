"""Fixed grading rules (docs/acceptance/plan.md section 3), no model involved, so anyone re-running them gets the same
marks. A citation counts only when its quote is really on the cited page of the ORIGINAL PDF (±1 page)."""
from __future__ import annotations

import math
import re

from .text import contains_value, numbers, page_has, pdf_pages

_NOT_FOUND = re.compile(r"not found|not in the (?:knowledge base|library)|no (?:such|clause)|does not (?:exist|contain)"
                        r"|isn'?t in|not held|not available", re.I)


def _doc_matches(cited: str, designation: str) -> bool:
    num = re.search(r"3500\.\d", designation)
    year = re.search(r"(?:19|20)\d{2}", designation)
    c = cited.replace(" ", "")
    return bool(num and num.group(0) in c and (not year or year.group(0) in c))


def _quote_on_page(src: str, page: int, quote: str, cat: str) -> bool:
    if page_has(src, page, quote, spread=1):
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
    if a.get("error"):
        return {**r, "pass": False, "why": "no answer: " + a["error"]}
    trap = q.get("trap")
    if trap in ("not_found", "not_held"):
        refused = a.get("status") in ("not_found", "not_held") or bool(_NOT_FOUND.search(a.get("answer") or ""))
        invented = a.get("status") == "answered" and bool(numbers(" ".join(a.get("values") or [])))
        ok = refused and not invented
        return {**r, "pass": ok, "honesty_ok": ok, "why": "" if ok else "gave an answer to a question the library cannot answer"}
    src = sources.get(g.get("doc", ""))
    values_ok = all(contains_value(said, v) for v in g.get("values", []))
    hit = any(x.get("source") == g.get("doc") and abs(x.get("page", 0) - g.get("page", 0)) <= 1 for x in a.get("retrieved", []))
    good_cites = [c for c in a.get("citations") or []
                  if _doc_matches(c.get("document", ""), g["designation"]) and abs(int(c.get("page") or 0) - g["page"]) <= 1
                  and src and _quote_on_page(src, int(c.get("page") or 0), c.get("quote", ""), q["cat"])]
    citation_ok = bool(good_cites)
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
    return {**r, "pass": ok, "answer_ok": values_ok, "citation_ok": citation_ok, "status_ok": status_ok,
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
    n, k = len(rows), sum(r["pass"] for r in rows)
    lo, hi = wilson(k, n)
    cats: dict = {}
    for r in rows:
        c = cats.setdefault(r["cat"], [0, 0])
        c[0] += r["pass"]
        c[1] += 1
    traps = [r for r in rows if r["cat"].startswith("F")]
    return {"questions": n, "passed": k, "rate": round(k / n, 4) if n else 0, "ci95": [round(lo, 4), round(hi, 4)],
            "traps": [sum(r["pass"] for r in traps), len(traps)],
            "by_category": {c: {"passed": a, "of": b} for c, (a, b) in sorted(cats.items())},
            "blame": {b: sum(1 for r in rows if r.get("blame") == b) for b in {r.get("blame") for r in rows} if b}}
