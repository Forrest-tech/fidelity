# -*- coding: utf-8 -*-
"""Everything around one AI request. The iron rules, in the order they are applied:

    switched on     the master switch is on and the skill's level allows it (level 1: a person asked; level 2: also
                    asked by default). Level 0 never calls.
    allowed folder  only documents from folders an administrator allowed are sent; documents carrying a licence
                    watermark ("Licensed to ...") are held back by default.
    data, not instructions
                    text that reads like an instruction to an AI is not sent; a person looks at it instead.
    cheapest first  the same question asked before (same skill version and model) is answered from the cache.
    budget, breaker each skill has a monthly budget and a monthly cap on calls; after repeated errors it pauses.
    code checks     the skill's check() enforces its rules on the answer; an answer that breaks them is discarded.
    log everything  every request is logged with its input, output, cost and, later, what a person decided.

The result is always a suggestion. Nothing here writes to a document.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import time
import uuid

from .. import db
from . import config as CF
from . import providers as P
from .skills import SKILLS

BREAKER_ERRORS = 3          # this many failed calls in a row ...
BREAKER_WINDOW = 600        # ... within this many seconds pause the skill
BREAKER_PAUSE = 600         # for this long
EXAMPLES = 3                # confirmed examples sent with a request
LICENCE_MARKS = ("licensed to", "licenced to")


class Blocked(Exception):
    pass


def month_start(now: float | None = None) -> float:
    d = _dt.datetime.fromtimestamp(now or time.time())
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def _log(**f) -> str:
    cid = uuid.uuid4().hex[:12]
    cols = ["id", "skill", "version", "provider", "model", "room_id", "rel", "input", "output", "result", "status", "message",
            "tokens_in", "tokens_out", "cost", "seconds", "created_by", "created_at"]
    row = {"id": cid, "created_at": db.now(), "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "seconds": 0.0, **f}
    con = db.trust_rw()
    try:
        con.execute(f"INSERT INTO ai_call({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [row.get(c) for c in cols])
        con.commit()
    finally:
        con.close()
    return cid


def _month(skill: str) -> tuple[int, float]:
    con = db.trust_rw()
    try:
        r = con.execute("SELECT COUNT(*), COALESCE(SUM(cost),0) FROM ai_call WHERE skill=? AND status IN ('ok','invalid') "
                        "AND created_at>=?", (skill, month_start())).fetchone()
    finally:
        con.close()
    return int(r[0]), float(r[1])


def _paused(skill: str) -> float:
    """Seconds left of a pause after repeated errors (0 when not paused)."""
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT status, created_at FROM ai_call WHERE skill=? AND status IN ('ok','invalid','error') "
                           "ORDER BY created_at DESC LIMIT ?", (skill, BREAKER_ERRORS)).fetchall()
    finally:
        con.close()
    if len(rows) < BREAKER_ERRORS or any(r[0] != "error" for r in rows):
        return 0.0
    if rows[0][1] - rows[-1][1] > BREAKER_WINDOW:
        return 0.0
    return max(0.0, rows[0][1] + BREAKER_PAUSE - time.time())


def _examples(skill_mod, p: dict) -> list:
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT input, answer FROM ai_example WHERE skill=? ORDER BY at DESC LIMIT 300",
                           (skill_mod.VERSION.split("-")[0],)).fetchall()
    finally:
        con.close()
    scored = []
    for r in rows:
        inp = json.loads(r[0])
        if skill_mod.key(inp) == skill_mod.key(p):
            continue                                       # never hand the model the answer to this very question
        sim = skill_mod.similarity(p, inp)
        if sim >= 0.5:
            scored.append((sim, {"input": inp, "answer": r[1]}))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:EXAMPLES]]


def _cache_key(skill_mod, p: dict, prov: dict, model: str) -> str:
    raw = json.dumps({"v": skill_mod.VERSION, "kind": prov["kind"], "model": model, "q": skill_mod.key(p)}, sort_keys=True,
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def allowed(s: dict, source_link: str | None, doc_text: str | None) -> str | None:
    """Why this document may not be sent (None when it may)."""
    prefixes = [x.strip().rstrip("/").lower() for x in s["scope"]["allowed_prefixes"]]
    src = (source_link or "").strip().rstrip("/").lower()
    if not any(src == x or src.startswith(x + "/") for x in prefixes if x):
        return "this room's input folder is not on the list of folders allowed to be sent to AI"
    if s["scope"]["block_licensed"] and doc_text and any(m in doc_text.lower() for m in LICENCE_MARKS):
        return "this document carries a licence watermark, so it is not sent to AI"
    return None


def ask(skill: str, p: dict, *, user: str, source_link: str | None = None, doc_text: str | None = None,
        room_id: str | None = None, rel: str | None = None, auto: bool = False, settings: dict | None = None) -> dict:
    """Ask one skill one question. Returns {call, status, result, message, cached}. Never raises for a refusal of any
    kind: the status says what happened (blocked / error / invalid / ok / cached)."""
    from ..distill.run import scan_instructions
    mod = SKILLS[skill]
    s = settings or CF.load()
    sk = s["skills"][skill]
    prov = CF.provider(s, sk["provider"])
    base = {"skill": skill, "version": mod.VERSION, "provider": prov["kind"] if prov else None, "model": sk["model"],
            "room_id": room_id, "rel": rel, "input": json.dumps(p, ensure_ascii=False), "created_by": user}

    def blocked(msg):
        return {"call": _log(**base, status="blocked", message=msg), "status": "blocked", "result": None, "message": msg,
                "cached": False}

    if not s["enabled"]:
        return {"call": None, "status": "off", "result": None, "message": "AI is switched off", "cached": False}
    if sk["level"] == 0 or (auto and sk["level"] < 2):
        return {"call": None, "status": "off", "result": None, "message": "this skill is not switched on", "cached": False}
    if not prov or not sk["model"]:
        return {"call": None, "status": "off", "result": None, "message": "no model is chosen for this skill", "cached": False}
    why = allowed(s, source_link, doc_text)
    if why:
        return blocked(why)
    if scan_instructions(mod.text_of(p)):
        return blocked("the text reads like an instruction to an AI; a person should look at it")

    ck = _cache_key(mod, p, prov, sk["model"])
    con = db.trust_rw()
    try:
        hit = con.execute("SELECT raw, result FROM ai_cache WHERE key=?", (ck,)).fetchone()
    finally:
        con.close()
    if hit:
        res = json.loads(hit[1])
        cid = _log(**base, output=hit[0], result=hit[1], status="cached", message="answered before")
        return {"call": cid, "status": "cached", "result": res, "message": "answered before", "cached": True}

    calls, spent = _month(skill)
    if sk["monthly_cap"] and calls >= sk["monthly_cap"]:
        return blocked(f"this month's limit of {sk['monthly_cap']} calls is reached")
    if sk["budget_usd"] and spent >= sk["budget_usd"]:
        return blocked(f"this month's budget of ${sk['budget_usd']:.2f} is used up")
    left = _paused(skill)
    if left:
        return blocked(f"paused after repeated errors; tries again in {int(left // 60) + 1} min")
    key = CF.key_for(prov["id"])
    if not key:
        return blocked("the provider's key cannot be read; enter it again in Settings")

    user_msg = mod.build(p, _examples(mod, p) if skill == "arbitrate" else [])
    out, err = None, None
    for attempt in range(2):
        try:
            out = P.call(prov, key, sk["model"], mod.SYSTEM, user_msg, mod.SCHEMA)
            break
        except P.ProviderError as e:
            err = e
            if not e.retry or attempt:
                break
            time.sleep(2)
    if out is None:
        cid = _log(**base, status="error", message=err.message if err else "no answer")
        return {"call": cid, "status": "error", "result": None, "message": err.message if err else "no answer", "cached": False}
    cost = P.cost(prov, sk["model"], out["tokens_in"], out["tokens_out"])
    meter = {"tokens_in": out["tokens_in"], "tokens_out": out["tokens_out"], "cost": cost, "seconds": out["seconds"]}
    try:
        res = mod.check(out["text"], p)
    except (ValueError, TypeError, AttributeError) as e:
        cid = _log(**base, **meter, output=out["text"][:2000], status="invalid", message=f"answer discarded: {e}"[:200])
        return {"call": cid, "status": "invalid", "result": None, "message": "the answer broke the rules and was discarded",
                "cached": False}
    rj = json.dumps(res, ensure_ascii=False)
    cid = _log(**base, **meter, output=out["text"][:2000], result=rj, status="ok")
    con = db.trust_rw()
    try:
        con.execute("INSERT INTO ai_cache(key, skill, version, raw, result, created_at) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(key) DO NOTHING", (ck, skill, mod.VERSION, out["text"][:2000], rj, db.now()))
        con.commit()
    finally:
        con.close()
    return {"call": cid, "status": "ok", "result": res, "message": "", "cached": False}


# ------------------------------------------------------------------ what people decided
DECISIONS = ("adopted", "modified", "rejected")


def decide(call_id: str, decision: str, user: str, final: str | None = None) -> dict:
    """Record what a person did with a suggestion. A settled reading becomes an example for later requests."""
    if decision not in DECISIONS:
        raise CF.ConfigError(422, "decision must be adopted, modified or rejected")
    con = db.trust_rw()
    try:
        r = con.execute("SELECT id, skill, input, result, room_id, rel FROM ai_call WHERE id=?", (call_id,)).fetchone()
        if not r:
            raise CF.ConfigError(404, "no such AI suggestion")
        now = db.now()
        con.execute("UPDATE ai_call SET decision=?, final=?, decided_by=?, decided_at=? WHERE id=?",
                    (decision, final, user, now, call_id))
        if r[1] == "arbitrate" and decision in ("adopted", "modified") and final:
            con.execute("INSERT INTO ai_example(id, skill, input, answer, room_id, rel, by_user, at, call_id) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex[:12], "arbitrate", r[2], final, r[4], r[5], user, now, call_id))
        con.commit()
    finally:
        con.close()
    return {"decided": decision}


# ------------------------------------------------------------------ how it is doing
def stats() -> dict:
    since = month_start()
    con = db.trust_rw()
    try:
        out = {}
        for skill in CF.SKILLS:
            rows = con.execute("SELECT status, decision, cost FROM ai_call WHERE skill=? AND created_at>=? "
                               "AND COALESCE(created_by,'')<>'evaluation'", (skill, since)).fetchall()
            c = {"calls": 0, "cached": 0, "blocked": 0, "errors": 0, "invalid": 0, "spend": 0.0,
                 "adopted": 0, "modified": 0, "rejected": 0}
            for st, dec, cost in rows:
                c["calls"] += st in ("ok", "invalid")
                c["cached"] += st == "cached"
                c["blocked"] += st == "blocked"
                c["errors"] += st == "error"
                c["invalid"] += st == "invalid"
                c["spend"] += cost or 0.0
                if dec in DECISIONS:
                    c[dec] += 1
            decided = c["adopted"] + c["modified"] + c["rejected"]
            c["adoption"] = round(100 * c["adopted"] / decided, 1) if decided else None
            c["spend"] = round(c["spend"], 4)
            c["paused_s"] = int(_paused(skill))
            out[skill] = c
        memory = {"cache": con.execute("SELECT COUNT(*) FROM ai_cache").fetchone()[0],
                  "examples": con.execute("SELECT COUNT(*) FROM ai_example").fetchone()[0],
                  "rules": con.execute("SELECT COUNT(*) FROM correction_rule WHERE enabled=1").fetchone()[0]}
    finally:
        con.close()
    return {"skills": out, "memory": memory}


def examples(limit: int = 100) -> list:
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT id, skill, input, answer, rel, by_user, at FROM ai_example ORDER BY at DESC LIMIT ?",
                           (limit,)).fetchall()
    finally:
        con.close()
    return [{"id": r[0], "skill": r[1], "input": json.loads(r[2]), "answer": r[3], "rel": r[4], "by": r[5], "at": r[6]} for r in rows]


def delete_example(eid: str):
    con = db.trust_rw()
    try:
        con.execute("DELETE FROM ai_example WHERE id=?", (eid,))
        con.commit()
    finally:
        con.close()


def evaluate(skill: str, pid: str, model: str, limit: int = 30) -> dict:
    """Iron rule 10: try a model on the places people settled, before it is used. Stored with the settings."""
    mod = SKILLS[skill]
    s = CF.load()
    prov = CF.provider(s, pid)
    if not prov:
        raise CF.ConfigError(422, "choose one of the connected providers")
    key = CF.key_for(pid)
    if not key:
        raise CF.ConfigError(409, "the provider's key cannot be read; enter it again")
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT input, answer FROM ai_example WHERE skill=? ORDER BY at DESC LIMIT ?", (skill, limit)).fetchall()
    finally:
        con.close()
    if not rows:
        raise CF.ConfigError(409, "there are no confirmed examples to test on yet")
    right = 0
    for inp_raw, answer in rows:
        p = json.loads(inp_raw)
        base = {"skill": skill, "version": mod.VERSION, "provider": prov["kind"], "model": model, "input": inp_raw,
                "created_by": "evaluation"}
        try:
            out = P.call(prov, key, model, mod.SYSTEM, mod.build(p, []), mod.SCHEMA)
        except P.ProviderError as e:
            _log(**base, status="error", message=e.message)
            continue
        meter = {"tokens_in": out["tokens_in"], "tokens_out": out["tokens_out"],
                 "cost": P.cost(prov, model, out["tokens_in"], out["tokens_out"]), "seconds": out["seconds"]}
        try:
            res = mod.check(out["text"], p)
        except (ValueError, TypeError, AttributeError):
            _log(**base, **meter, output=out["text"][:2000], status="invalid", message="evaluation")
            continue
        _log(**base, **meter, output=out["text"][:2000], result=json.dumps(res, ensure_ascii=False), status="ok", message="evaluation")
        right += bool(mod.correct(res, answer))
    score = round(100 * right / len(rows), 1)
    s = CF.load()
    s["evals"][CF.eval_key(skill, pid, model)] = {"score": score, "n": len(rows), "at": db.now()}
    CF.save(s)
    return {"score": score, "n": len(rows)}


def example_count(skill: str) -> int:
    con = db.trust_rw()
    try:
        return con.execute("SELECT COUNT(*) FROM ai_example WHERE skill=?", (skill,)).fetchone()[0]
    finally:
        con.close()
