"""Answer each question from the library, under the same rules the AI tools get in their instruction pack."""
from __future__ import annotations

import concurrent.futures as cf
import os
import time

from .library import Search

PACK = os.path.join(os.path.dirname(__file__), "..", "..", "..", "adapters", "dist", "grok", "au-compliance-kb.md")

HARNESS = """
--- Test harness ---
In this test you cannot browse Dropbox: the library search has already run and its best excerpts are given with the
question. Skip the set-up, access and logging steps; every other rule above applies — in particular: answer only from
the excerpts, never from memory; cite document, clause and the page from the excerpt header (p.N); quote the exact words
that state the answer; say which edition you used and whether it is superseded; if the excerpts do not contain the
answer or the edition asked for, set status "not_found" (or "not_held" when that edition is not in the library) and
do not give a figure. If the question states something the library contradicts, say so and give the library's figure.
Reply with JSON only."""

SCHEMA = {"type": "object", "properties": {
    "status": {"type": "string", "enum": ["answered", "not_found", "not_held"]},
    "answer": {"type": "string"},
    "values": {"type": "array", "items": {"type": "string"}},
    "edition_used": {"type": "string"},
    "citations": {"type": "array", "items": {"type": "object", "properties": {
        "document": {"type": "string"}, "clause": {"type": "string"}, "page": {"type": "integer"},
        "quote": {"type": "string"}}, "required": ["document", "clause", "page", "quote"]}}},
    "required": ["status", "answer", "values", "edition_used", "citations"]}


def system_prompt(pack: str | None = None) -> str:
    with open(pack or PACK, encoding="utf-8") as f:
        return f.read() + "\n" + HARNESS


def run(model, questions: list[dict], search: Search, k: int = 8, workers: int = 6, log=print,
        pack: str | None = None) -> list[dict]:
    system = system_prompt(pack)

    def one(q):
        hits = search.top(q["q"], k)
        ctx = "\n\n".join(f"[{i}] {u.header()}\n{u.text[:2800]}" for i, u in enumerate(hits, 1))
        t = time.time()
        try:
            out = model.json(system, f"Question: {q['q']}\n\nLibrary excerpts:\n\n{ctx}", SCHEMA)
            err = None
        except RuntimeError as e:
            out, err = {}, str(e)
        return {"id": q["id"], "model": model.name, "seconds": round(time.time() - t, 1), "error": err,
                "retrieved": [{"file": u.file, "source": u.source_filename, "page": u.page} for u in hits], **out}

    rows = []
    with cf.ThreadPoolExecutor(workers) as ex:
        for n, r in enumerate(ex.map(one, questions), 1):
            rows.append(r)
            if n % 25 == 0:
                log(f"  {model.name}: {n}/{len(questions)} answered")
    return rows
