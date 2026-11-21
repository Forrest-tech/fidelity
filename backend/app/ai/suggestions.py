# -*- coding: utf-8 -*-
"""Suggestions for the correction library, found from the fixes people have already confirmed.

    widen     the same fix was saved as separate rules for different documents or series: one rule for all of them
              (found by code; no AI needed).
    pattern   three or more text fixes of the same kind of misread ("fittcd" -> "fitted", "connectcd" -> "connected"):
              the AI proposes one pattern; code checks it (skills/suggest.py). Never for numbers: a number is only
              ever fixed with its exact context.

Each suggestion comes with a preview over every document. Nothing changes until a person approves it, and even then the
documents change only when the person applies the rule.
"""
from __future__ import annotations

import difflib
import json
import uuid

from .. import db
from ..distill import rules as RU
from ..jobs import corrections as CO
from . import config as CF
from . import gate as G
from .skills import suggest as SK

MIN_PATTERN_FIXES = 3
SAMPLES = 8


def signature(find: str, replace: str) -> str:
    """The kind of misread: the character changes between the wrong and the right text ("cd>ed")."""
    ops = difflib.SequenceMatcher(None, find, replace, autojunk=False).get_opcodes()
    return " ".join(f"{find[i1:i2]}>{replace[j1:j2]}" for op, i1, i2, j1, j2 in ops if op != "equal")


def _room_source(room_id: str | None) -> str | None:
    if not room_id:
        return None
    con = db.trust_rw()
    try:
        r = con.execute("SELECT source FROM room WHERE id=?", (room_id,)).fetchone()
    finally:
        con.close()
    try:
        return (json.loads(r[0]) or {}).get("link") if r and r[0] else None
    except ValueError:
        return None


def _existing() -> set:
    con = db.trust_rw()
    try:
        return {(r[0], r[1]) for r in con.execute("SELECT kind, rule_ids FROM rule_suggestion").fetchall()}
    finally:
        con.close()


def _current(r: dict) -> list:
    """A result's Markdown as it is now (with the rules already applied): what a new rule would still change."""
    import os
    _, out = CO._paths(r["room_id"], r["out_dir"])
    if not os.path.exists(out):
        return []
    return [CO._read(out, inner) for inner in CO._md_files(out)]


def _samples(rule: dict, limit: int = SAMPLES) -> list:
    """A few places where the rule would change something, in context."""
    import re
    out = []
    for r in CO._results():
        if not RU.applies_to(rule, r["rel"]):
            continue
        for text in _current(r):
            _, body = RU.split_front(text)
            rx = re.compile(rule["find"]) if rule["kind"] == "pattern" else RU._pattern(rule)
            for m in rx.finditer(body):
                old = m.group(0)
                new = m.expand(rule["replace"]) if rule["kind"] == "pattern" else old.replace(m.group(1), rule["replace"], 1)
                if old == new or (rule["kind"] == "pattern" and any(c.isdigit() for c in old + new)):
                    continue
                out.append({"rel": r["rel"], "room": r["room_name"], "before": " ".join(body[:m.start()].split()[-5:]),
                            "old": old, "new": new, "after": " ".join(body[m.end():].split()[:5])})
                if len(out) >= limit:
                    return out
    return out


def _preview(rule: dict) -> dict:
    """Where the rule would still change something, on top of the rules already in use."""
    docs = places = 0
    for r in CO._results():
        if not RU.applies_to(rule, r["rel"]):
            continue
        n = sum(RU.count(rule, t) for t in _current(r))
        if n:
            docs, places = docs + 1, places + n
    return {"documents": docs, "places": places, "samples": _samples(rule)}


def _save(kind: str, rule_ids: list, data: dict, preview: dict, call_id: str | None = None) -> str:
    sid = uuid.uuid4().hex[:10]
    con = db.trust_rw()
    try:
        con.execute("INSERT INTO rule_suggestion(id, kind, rule_ids, data, preview, status, call_id, created_at) "
                    "VALUES(?,?,?,?,?,'open',?,?)", (sid, kind, json.dumps(sorted(rule_ids)), json.dumps(data, ensure_ascii=False),
                                                     json.dumps(preview, ensure_ascii=False), call_id, db.now()))
        con.commit()
    finally:
        con.close()
    return sid


def scan(user: str) -> dict:
    """Look through the confirmed rules for suggestions not made before. Returns what was found."""
    rules = [r for r in CO.all_rules(enabled_only=True) if r["reverts"] < 3]
    seen = _existing()
    made = {"widen": 0, "pattern": 0, "pattern_needs_ai": 0, "pattern_rejected": 0}

    # 1. the same fix saved more than once, each for a narrower set of documents
    same: dict = {}
    for r in rules:
        if r["kind"] in ("text", "number"):
            same.setdefault((r["kind"], r["find"], r["replace"], r["before"], r["after"]), []).append(r)
    for (kind, find, rep, before, after), group in same.items():
        if len(group) < 2 or any(g["scope"] == "all" for g in group):
            continue
        ids = [g["id"] for g in group]
        if ("widen", json.dumps(sorted(ids))) in seen:
            continue
        series = {g["series"] for g in group if g["scope"] == "series"} | {RU.series_of(g["doc"] or "") for g in group if g["scope"] == "document"}
        scope = "series" if len(series) == 1 and None not in series else "all"
        data = {"find": find, "replace": rep, "before": before, "after": after, "kind": kind, "scope": scope,
                "series": next(iter(series)) if scope == "series" else None, "nums": [g["num"] for g in group]}
        _save("widen", ids, data, _preview({**data, "id": "preview", "doc": None}))
        made["widen"] += 1

    # 2. three or more text fixes of the same kind: a pattern (needs the AI)
    kinds: dict = {}
    for r in rules:
        if r["kind"] == "text" and not RU.is_number(r["find"], r["replace"]):
            kinds.setdefault(signature(r["find"], r["replace"]), []).append(r)
    patterns = [r for r in CO.all_rules(enabled_only=True) if r["kind"] == "pattern"]
    s = CF.load()
    for sig, group in kinds.items():
        if len({g["find"] for g in group}) < MIN_PATTERN_FIXES:
            continue
        ids = [g["id"] for g in group]
        if ("pattern", json.dumps(sorted(ids))) in seen:
            continue
        if any(all(RU.apply_pattern(g["find"], p)[0] == g["replace"] for g in group) for p in patterns):
            continue                                        # an existing pattern already covers them
        if not s["enabled"] or s["skills"]["suggest"]["level"] < 1:
            made["pattern_needs_ai"] += 1
            continue
        # every fix sent must come from a room whose input folder may be sent to AI
        links = [_room_source(g["source_room"]) for g in group]
        if any(G.allowed(s, link, None) for link in links):
            made["pattern_not_allowed"] = made.get("pattern_not_allowed", 0) + 1
            continue
        fixes = [{"find": g["find"], "replace": g["replace"]} for g in group]
        out = G.ask("suggest", SK.payload(fixes, sig), user=user, source_link=links[0], doc_text=None, settings=s)
        if out["status"] not in ("ok", "cached") or not out["result"]:
            made["pattern_rejected"] += 1
            continue
        res = out["result"]
        series = {g["series"] for g in group}
        scope = "series" if res["scope"] == "series" and len(series) == 1 and None not in series else "all"
        data = {"find": res["pattern"], "replace": res["replace"], "kind": "pattern", "scope": scope,
                "series": next(iter(series)) if scope == "series" else None, "counterexamples": res["counterexamples"],
                "reason": res["reason"], "accuracy": res["accuracy"], "signature": sig, "nums": [g["num"] for g in group]}
        _save("pattern", ids, data, _preview({**data, "id": "preview", "doc": None}), out["call"])
        made["pattern"] += 1
    return made


def listing(status: str = "open") -> list:
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT id, kind, rule_ids, data, preview, status, call_id, created_at FROM rule_suggestion "
                           "WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    finally:
        con.close()
    return [{"id": r[0], "kind": r[1], "rule_ids": json.loads(r[2]), "data": json.loads(r[3]), "preview": json.loads(r[4]),
             "status": r[5], "call": r[6], "created_at": r[7]} for r in rows]


def _get(sid: str) -> dict:
    s = next((x for x in listing("open") if x["id"] == sid), None)
    if not s:
        raise CF.ConfigError(404, "no such open suggestion")
    return s


def _close(sid: str, status: str, user: str):
    con = db.trust_rw()
    try:
        con.execute("UPDATE rule_suggestion SET status=?, decided_by=?, decided_at=? WHERE id=?", (status, user, db.now(), sid))
        con.commit()
    finally:
        con.close()


def approve(sid: str, user: str) -> dict:
    """Save the suggested rule. The documents change when the person applies it (as for any rule)."""
    sg = _get(sid)
    d = sg["data"]
    con = db.trust_rw()
    try:
        now = db.now()
        if sg["kind"] == "widen":
            keep, *rest = sg["rule_ids"]
            con.execute("UPDATE correction_rule SET scope=?, series=?, doc=NULL, updated_at=? WHERE id=?",
                        (d["scope"], d["series"], now, keep))
            for rid in rest:
                con.execute("UPDATE correction_rule SET enabled=0, updated_at=? WHERE id=?", (now, rid))
            rule_id = keep
        else:
            try:
                RU.check_pattern(d["find"], d["replace"])
            except RU.RuleError as e:
                raise CF.ConfigError(422, str(e))
            num = con.execute("SELECT COALESCE(MAX(num),0)+1 FROM correction_rule").fetchone()[0]
            rule_id = uuid.uuid4().hex[:12]
            con.execute("INSERT INTO correction_rule(id,num,find,replace_with,before_ctx,after_ctx,kind,scope,series,doc,enabled,"
                        "reverts,source_room,source_rel,created_by,created_at,updated_at) VALUES(?,?,?,?,'','','pattern',?,?,NULL,1,0,"
                        "NULL,NULL,?,?,?)", (rule_id, num, d["find"], d["replace"], d["scope"], d["series"], user, now, now))
        con.commit()
    finally:
        con.close()
    _close(sid, "approved", user)
    if sg["call"]:
        G.decide(sg["call"], "adopted", user, final=json.dumps({"pattern": d["find"], "replace": d["replace"]}))
    rule = CO.get_rule(rule_id)
    return {"rule": rule, "affected": CO.affected(rule)}


def dismiss(sid: str, user: str) -> dict:
    sg = _get(sid)
    _close(sid, "dismissed", user)
    if sg["call"]:
        G.decide(sg["call"], "rejected", user)
    return {"dismissed": True}
