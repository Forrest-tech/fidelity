"""Question bank from the publisher's own pages.

A model reads ONE page of an original PDF and proposes questions whose answers are figures printed on that page; every
proposed figure, quote and clause number is then looked up on the page by this code, and a question is kept only when
all of them are there. Trap questions are built by rules, not by a model:
  T1 a clause number the standard does not have          -> must say "not found"
  T2 an edition the library does not hold (NCC 2025 calls up AS/NZS 3500.x:2025) -> must say so, no figure
  T3 a false premise (a wrong figure stated as fact)      -> must correct it with the right figure
Category D asks about a superseded edition by name     -> the figure from that edition AND that it is superseded.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import random
import re

from ..distill.editions import identify
from .text import contains_value, norm, page_has, pdf_pages

HEAD = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,3}){1,4})\s+[A-Z][^\n]{2,}", re.M)
FIGURE = re.compile(r"\d+(?:\.\d+)?\s*(?:mm|m|kPa|L/s|m/s|°C|%|kg|L|DN|h|min)\b")

SYSTEM = """You write test questions for a plumbing compliance knowledge base, from ONE page of a standard.
Rules:
- Use only the page text given. Each question asks for a specific requirement whose answer is a figure (a number with
  its unit) or a short set of figures printed on this page.
- "values": each figure copied character for character from the page text (each must contain a digit).
- "quote": an exact fragment of 40-200 characters copied from the page that states the answer.
- "clause": the clause number printed above the answer on this page (e.g. 5.3.3.3), exactly as printed.
- Write up to two questions in plain trade English, as a plumber or hydraulic engineer would ask:
  kind "A": names the standard and the clause, e.g. "Under {desig}, Clause 5.3.3.3, what is the minimum ...?"
  kind "B": names the standard but NOT the clause number; describe the situation instead.
  Use kind "E" instead of "A" when the figure comes from a table.
- Every question must name the standard exactly as "{desig}".
- Each question must have ONE correct answer: include the conditions (pipe material, size, location) that make it so.
- If the page has no such requirement (contents, preface, figures only), return {{"questions": []}}."""

SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["A", "B", "E"]}, "question": {"type": "string"},
    "answer": {"type": "string"}, "values": {"type": "array", "items": {"type": "string"}},
    "quote": {"type": "string"}, "clause": {"type": "string"}},
    "required": ["kind", "question", "answer", "values", "quote", "clause"]}}}, "required": ["questions"]}


def designation(path: str) -> dict:
    ed = identify(os.path.basename(path))
    return {"designation": ed["designation"].replace("AS/NZS", "AS/NZS"), "number": ed["number"], "year": ed["year"]}


def candidate_pages(path: str) -> list[int]:
    out = []
    pages = pdf_pages(path)
    for i, t in enumerate(pages, 1):
        prev = pages[i - 2] if i > 1 else ""        # a clause may start on the page before its figures
        if (HEAD.search(t) or HEAD.search(prev)) and len(FIGURE.findall(t)) >= 2 and "contents" not in t[:300].lower():
            out.append(i)
    return out


def _check(q: dict, path: str, page: int, desig: str, number: str) -> str | None:
    """Why a proposed question is rejected, or None when every part of it is on the page."""
    text = pdf_pages(path)[page - 1]
    vals = [v for v in q.get("values") or [] if re.search(r"\d", v)]
    if not vals or len(vals) != len(q.get("values") or []):
        return "a value without a figure"
    if not all(norm(v) in norm(text) for v in vals):
        return "a value is not on the page"
    if q.get("kind") != "E":            # a table cell has no sentence to quote; its figures are checked above
        if len(q.get("quote", "")) < 30 or not page_has(path, page, q["quote"]):
            return "the quote is not on the page"
        if not all(contains_value(q["quote"], v) for v in vals[:1]):
            return "the quote does not state the answer"
    cl = re.sub(r"\s*\(.*$", "", q.get("clause", "").strip())      # "6.3.7(b)(ii)": its clause is 6.3.7
    q["clause"] = cl
    prev = pdf_pages(path)[page - 2] if page > 1 else ""
    if not re.fullmatch(r"\d{1,2}(?:\.\d{1,3}){1,4}", cl) or not re.search(rf"(?m)^\s*{re.escape(cl)}\s", text + "\n" + prev):
        return "the clause is not printed on the page"
    if number not in q["question"]:
        return "the question does not name the standard"
    if q["kind"] == "B" and re.search(rf"\b{re.escape(cl)}\b", q["question"]):
        return "a topic question names its clause"
    return None


def from_document(model, path: str, pages_wanted: int, kind_override: str | None = None, seed: int = 7,
                  workers: int = 6, log=print) -> tuple[list[dict], list[dict]]:
    d = designation(path)
    pages = candidate_pages(path)
    random.Random(seed).shuffle(pages)
    pages = sorted(pages[:pages_wanted])
    kept, rejected = [], []

    def one(page):
        text = pdf_pages(path)[page - 1][:7000]
        try:
            out = model.json(SYSTEM.format(desig=d["designation"]), f"Standard: {d['designation']}\nPage {page}:\n\n{text}",
                             SCHEMA)
        except RuntimeError as e:
            return page, [], [{"page": page, "why": str(e)}]
        ok, bad = [], []
        for q in (out.get("questions") or [])[:2]:
            why = _check(q, path, page, d["designation"], d["number"])
            if why:
                bad.append({"page": page, "why": why, "question": q.get("question", "")})
                continue
            ok.append({"cat": kind_override or q["kind"], "q": q["question"].strip(), "expected": q["answer"].strip(),
                       "ground": {"doc": os.path.basename(path), "designation": d["designation"], "page": page,
                                  "values": q["values"], "quote": q["quote"], "clause": q["clause"].strip()}})
        return page, ok, bad

    with cf.ThreadPoolExecutor(workers) as ex:
        for page, ok, bad in ex.map(one, pages):
            kept += ok
            rejected += bad
    log(f"  {d['designation']}: {len(pages)} pages read, {len(kept)} questions kept, {len(rejected)} rejected")
    return kept, rejected


def traps(bank: list[dict], sources: dict[str, str], not_held: list[str], seed: int = 11) -> list[dict]:
    """T1-T3 from the kept questions; `sources` = {doc file name: path}; `not_held` = designations the NCC calls up
    that the library does not hold."""
    rnd = random.Random(seed)
    out = []
    by_doc: dict = {}
    for q in bank:
        if q["cat"] in ("A", "E"):
            by_doc.setdefault(q["ground"]["doc"], []).append(q)
    for doc, qs in sorted(by_doc.items()):
        g0 = qs[0]["ground"]
        heads = [h for t in pdf_pages(sources[doc]) for h in HEAD.findall(t)]
        top = max(int(h.split(".")[0]) for h in heads) if heads else 20
        for n in range(4):                                                     # T1
            cl = f"{top + 3 + n}.{rnd.randint(2, 9)}.{rnd.randint(2, 9)}"
            out.append({"cat": "F trap: clause does not exist", "q": f"Under {g0['designation']}, Clause {cl}, what is "
                        f"the minimum clearance required?", "expected": "Not found in the knowledge base",
                        "trap": "not_found", "ground": {"doc": doc, "designation": g0["designation"], "absent_clause": cl}})
        for q in rnd.sample(qs, min(5, len(qs))):                             # T3
            g = q["ground"]
            v = g["values"][0]
            num = re.search(r"\d+(?:\.\d+)?", v).group(0)
            wrong = v.replace(num, str(int(float(num) * 3) if float(num) >= 1 else float(num) * 3), 1)
            out.append({"cat": "F trap: false premise", "q": f"{g['designation']} Clause {g['clause']} requires {wrong} "
                        f"here, doesn't it? ({q['q']})", "expected": q["expected"], "trap": "false_premise",
                        "ground": {**g, "wrong": wrong}})
    held_q = [q for q in bank if q["cat"] in ("A", "B", "E")]
    for desig in not_held:                                                     # T2
        num = re.search(r"3500\.\d", desig).group(0)
        for q in rnd.sample([q for q in held_q if num in q["q"]], 3) if any(num in q["q"] for q in held_q) else []:
            text = re.sub(r"AS/NZS 3500\.\d:\d{4}", desig, q["q"])
            out.append({"cat": "F trap: edition not held", "q": text, "expected": f"{desig} is not in the knowledge base",
                        "trap": "not_held", "ground": {"designation": desig, "held": q["ground"]["designation"]}})
    return out


def save(bank: list[dict], path: str, meta: dict):
    for i, q in enumerate(bank, 1):
        q["id"] = i
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**meta, "questions": bank}, f, ensure_ascii=False, indent=1)
