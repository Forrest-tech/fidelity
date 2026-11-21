# -*- coding: utf-8 -*-
"""The uncertain places of one file in a room, with what the AI suggested for them.

A place comes from the file's review list (scoring.findings). For a place where the two OCR engines read differently,
the words around it are taken from the result, so a person (or the AI) sees it in context and a chosen reading can
be turned into a correction rule in one step.
"""
from __future__ import annotations

import json
import re

from .. import db
from ..jobs import corrections as CO
from ..jobs import rooms as R
from . import config as CF
from . import gate as G
from . import formulas as FX
from .skills import arbitrate, explain, transcribe

CONTEXT_WORDS = 8
AUTO_LIMIT = 10             # places asked by default each time a file is opened (level 2)


def _text(room_id: str, rel: str) -> str:
    try:
        v = CO.file_view(room_id, rel)
    except CO.CorrectionError:
        return ""
    from ..distill.rules import split_front
    return "\n".join(split_front(f["text"])[1] for f in v["files"])          # the body only, never the front matter


def _context(text: str, cands: list) -> tuple[str | None, str, str]:
    """Which candidate the result contains, and the words before and after it."""
    for c in cands:
        if not c:
            continue
        m = re.search(r"(?<!\w)" + re.escape(c) + r"(?!\w)", text) or (re.search(re.escape(c), text) if len(c) > 3 else None)
        if m:
            before = " ".join(text[:m.start()].split()[-CONTEXT_WORDS:])
            after = " ".join(text[m.end():].split()[:CONTEXT_WORDS])
            return c, before, after
    return None, "", ""


def _row(room: dict, rel: str):
    r = next((x for x in R._files(room["id"]) if x["rel"] == rel), None)
    if r is None:
        raise CF.ConfigError(404, "no such file in this room")
    return r


def items(room: dict, rel: str) -> dict:
    r = _row(room, rel)
    findings = json.loads(r["findings"]) if r["findings"] else []
    text = _text(room["id"], rel)
    fx = FX.summary(r) if any(f.get("kind") == "formula" for f in findings) else {"available": False, "pages": {}}
    out = []
    for i, f in enumerate(findings):
        it = {"i": i, "kind": f.get("kind"), "page": f.get("page"), "detail": f.get("detail")}
        if f.get("kind") == "reading":
            cands = [f.get("a") or "", f.get("b") or ""]
            in_text, before, after = _context(text, cands)
            it.update(candidates=cands, in_text=in_text, before=before, after=after)
        elif f.get("kind") == "formula":
            it["formulas"] = fx["pages"].get(f.get("page"), []) if fx["available"] else None
        out.append(it)
    # the latest suggestion for each place
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT id, skill, input, result, status, message, decision FROM ai_call WHERE room_id=? AND rel=? "
                           "AND status IN ('ok','cached','invalid','error','blocked') ORDER BY created_at",
                           (room["id"], rel)).fetchall()
    finally:
        con.close()
    latest, formula_latest = {}, {}
    for c in rows:
        try:
            inp = json.loads(c[2])
        except (TypeError, ValueError):
            continue
        sug = {"call": c[0], "skill": c[1], "status": c[4], "message": c[5], "decision": c[6],
               "result": json.loads(c[3]) if c[3] else None}
        if c[1] == "transcribe":
            formula_latest[(inp.get("page"), inp.get("k"))] = sug
            continue
        if c[1] not in ("arbitrate", "explain"):
            continue
        k = (c[1], json.dumps(arbitrate.key(inp) if c[1] == "arbitrate" else explain.key(inp), sort_keys=True))
        latest[k] = sug
    for it in out:
        p = _payload(it)
        sk = "arbitrate" if it["kind"] == "reading" else "explain"
        mod = arbitrate if sk == "arbitrate" else explain
        it["suggestion"] = latest.get((sk, json.dumps(mod.key(p), sort_keys=True)))
        for fm in it.get("formulas") or []:
            fm["suggestion"] = formula_latest.get((it["page"], fm["k"]))
    s = CF.load()
    return {"rel": rel, "items": out, "ai": status(s)}


def _payload(it: dict) -> dict:
    if it["kind"] == "reading":
        return arbitrate.payload(it.get("before") or "", it.get("candidates") or [], it.get("after") or "", it.get("page"))
    return explain.payload(it.get("kind") or "", it.get("page"), it.get("detail") or "")


def ask(room: dict, rel: str, index: int, user: str, auto: bool = False, k: int | None = None) -> dict:
    data = items(room, rel)
    it = next((x for x in data["items"] if x["i"] == index), None)
    if it is None:
        raise CF.ConfigError(404, "no such place in this file")
    if it["kind"] == "formula" and k is not None:
        return transcribe_one(room, rel, it["page"], k, user)
    skill = "arbitrate" if it["kind"] == "reading" else "explain"
    return G.ask(skill, _payload(it), user=user, source_link=(room["source"] or {}).get("link"),
                 doc_text=_text(room["id"], rel), room_id=room["id"], rel=rel, auto=auto)


def ask_default(room: dict, rel: str, user: str) -> dict:
    """Level 2: ask about the places of this file that have no suggestion yet (a few at a time)."""
    data = items(room, rel)
    s = CF.load()
    if not s["enabled"] or s["skills"]["arbitrate"]["level"] < 2:
        return {"asked": 0}
    n = 0
    for it in data["items"]:
        if n >= AUTO_LIMIT:
            break
        if it["kind"] != "reading" or it.get("suggestion"):
            continue
        out = ask(room, rel, it["i"], user, auto=True)
        n += 1
        if out["status"] == "blocked":
            break                                           # the reason holds for the rest too
    return {"asked": n}


def status(s: dict | None = None) -> dict:
    """What the review page needs to know: may it offer to ask the AI, and is it asked by default."""
    s = s or CF.load()
    out = {"enabled": s["enabled"], "skills": {}}
    for name, sk in s["skills"].items():
        out["skills"][name] = {"level": sk["level"] if s["enabled"] and sk["provider"] and sk["model"] else 0}
    return out


def transcribe_one(room: dict, rel: str, page: int, k: int, user: str) -> dict:
    """Ask for a transcription of one formula: only its image crop is sent; the local OCR checks its numbers."""
    r = _row(room, rel)
    png = FX.image(r, page, k)
    before, after = _around_marker(room["id"], rel, page, k)
    p = transcribe.payload(page, k, FX.image_sha(png), FX.ocr_text(png), before, after)
    return G.ask("transcribe", p, user=user, source_link=(room["source"] or {}).get("link"),
                 doc_text=_text(room["id"], rel), room_id=room["id"], rel=rel, image=png)


def _around_marker(room_id: str, rel: str, page: int, k: int) -> tuple[str, str]:
    """The readable words just before and after the k-th unreadable-formula marker on a page of the result."""
    import re as _re
    from ..distill.structure import UNREADABLE_MARK
    for m in _re.finditer(r"<!-- unit: p\d+ \| src: p\.(\d+) .*?-->(.*?)<!-- /unit -->", _text(room_id, rel), _re.S):
        if int(m.group(1)) != page:
            continue
        parts = m.group(2).split(UNREADABLE_MARK)
        if k < len(parts):
            return " ".join(parts[k - 1].split()[-CONTEXT_WORDS:]), " ".join(parts[k].split()[:CONTEXT_WORDS])
    return "", ""
