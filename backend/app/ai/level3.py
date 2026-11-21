# -*- coding: utf-8 -*-
"""Reading arbitration at its higher levels: asked by default after a run (level 2), and adopted automatically for
plain text (level 3).

Level 3 is the one place where an AI answer goes into a result without a person deciding first, so it is fenced in:

    only text      both readings are words without digits, there are exactly two, the AI chose one with confidence of at
                   least 0.9, and the chosen word is in the word list built from verified documents while the other is not.
                   Numbers, formulas and tables never get here.
    earned         an administrator can switch it on only after at least 300 suggestions were decided by people, 98% of
                   them taken, and no sampled check found an automatic adoption wrong in the last 90 days.
    marked         an adoption is saved as a correction rule for that one document, marked as made by the AI, so it shows,
                   can be undone and is counted like any rule.
    sampled        the first 20 adoptions, then one in ten, are listed for a person to check.
    falls back     one adoption found wrong (a sampled check, or a person undoing it) puts the skill back to level 2 at once.
                   At level 2, if people take fewer than 70% of the last 50 suggestions, it goes back to level 1.
"""
from __future__ import annotations

import threading
import time
import traceback
import zlib

from .. import db
from ..distill import glossary
from ..jobs import corrections as CO
from ..jobs import rooms as R
from . import config as CF

AUTO_USER = "AI (automatic)"
PROMOTE_MIN = 300
PROMOTE_RATE = 98.0
WRONG_DAYS = 90
L2_WINDOW = 50
L2_FLOOR = 70.0
MIN_CONFIDENCE = 0.9
SAMPLE_FIRST = 20
SAMPLE_EVERY = 10
AFTER_RUN_LIMIT = 50


# ------------------------------------------------------------------ the record that earns (or loses) a level
def record() -> dict:
    """What people decided about reading-arbitration suggestions, all time (tests of models not counted)."""
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT decision, COUNT(*) FROM ai_call WHERE skill='arbitrate' AND decision IN "
                           "('adopted','modified','rejected') AND COALESCE(created_by,'')<>'evaluation' GROUP BY decision").fetchall()
        wrong = con.execute("SELECT MAX(checked_at), COUNT(*) FROM correction_rule WHERE auto=1 AND check_result='wrong' "
                            "AND checked_at>=?", (time.time() - WRONG_DAYS * 86400,)).fetchone()
    finally:
        con.close()
    c = {d: n for d, n in rows}
    decided = sum(c.values())
    return {"decided": decided, "adopted": c.get("adopted", 0),
            "adoption": round(100 * c.get("adopted", 0) / decided, 1) if decided else None,
            "wrong_recent": wrong[1] or 0, "last_wrong_at": wrong[0]}


def eligibility() -> dict:
    r = record()
    missing = []
    if r["decided"] < PROMOTE_MIN:
        missing.append({"code": "decided", "have": r["decided"], "need": PROMOTE_MIN})
    if r["adoption"] is None or r["adoption"] < PROMOTE_RATE:
        missing.append({"code": "adoption", "have": r["adoption"], "need": PROMOTE_RATE})
    if r["wrong_recent"]:
        missing.append({"code": "wrong", "have": r["wrong_recent"], "at": r["last_wrong_at"]})
    if not glossary.load():
        missing.append({"code": "glossary"})
    return {**r, "eligible": not missing, "missing": missing}


def demote(reason: str, to_level: int = 2):
    s = CF.load()
    sk = s["skills"]["arbitrate"]
    if sk["level"] <= to_level:
        return False
    s.setdefault("demotions", []).append({"at": db.now(), "from": sk["level"], "to": to_level, "reason": reason[:240]})
    s["demotions"] = s["demotions"][-20:]
    sk["level"] = to_level
    CF.save(s)
    return True


def review_level2():
    """At level 2, people taking fewer than 70% of the last 50 suggestions sends the skill back to level 1."""
    s = CF.load()
    if s["skills"]["arbitrate"]["level"] != 2:
        return
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT decision FROM ai_call WHERE skill='arbitrate' AND decision IN ('adopted','modified','rejected') "
                           "AND COALESCE(created_by,'')<>'evaluation' ORDER BY decided_at DESC LIMIT ?", (L2_WINDOW,)).fetchall()
    finally:
        con.close()
    if len(rows) >= L2_WINDOW and 100 * sum(1 for (d,) in rows if d == "adopted") / len(rows) < L2_FLOOR:
        demote(f"people took fewer than {L2_FLOOR:.0f}% of the last {L2_WINDOW} suggestions", to_level=1)


# ------------------------------------------------------------------ adopting
def eligible_answer(item: dict, result: dict | None, known: set | None = None) -> bool:
    """Only plain text, two readings, a confident choice, and the word list agrees with it."""
    if not result or result.get("choice") is None or result.get("needs_human"):
        return False
    cands = item.get("candidates") or []
    if len(cands) != 2 or any(ch.isdigit() for ch in "".join(cands)) or not item.get("in_text"):
        return False
    if (result.get("confidence") or 0) < MIN_CONFIDENCE:
        return False
    known = glossary.load() if known is None else known
    chosen = result.get("text") or ""
    other = cands[1 - cands.index(chosen)] if chosen in cands else None
    if other is None:
        return False
    return glossary.core(chosen) in known and glossary.core(other) not in known


def _sample(rule_id: str) -> bool:
    con = db.trust_rw()
    try:
        n = con.execute("SELECT COUNT(*) FROM correction_rule WHERE auto=1").fetchone()[0]
    finally:
        con.close()
    return n <= SAMPLE_FIRST or zlib.crc32(rule_id.encode()) % SAMPLE_EVERY == 0


def adopt(room: dict, rel: str, item: dict, ask_out: dict) -> dict | None:
    """Turn an eligible answer into a correction rule for this one document, marked as made by the AI."""
    chosen = ask_out["result"]["text"]
    if chosen == item["in_text"]:
        return None                                          # the result already reads the chosen word
    try:
        rule = CO.create(AUTO_USER, item["in_text"], chosen, "document", room["id"], rel)["rule"]
    except CO.CorrectionError:
        return None                                          # e.g. the same rule exists already
    sampled = _sample(rule["id"])
    now = db.now()
    con = db.trust_rw()
    try:
        con.execute("UPDATE correction_rule SET auto=1, call_id=?, sampled=? WHERE id=?", (ask_out["call"], 1 if sampled else 0, rule["id"]))
        con.execute("UPDATE ai_call SET decision='auto', final=?, decided_by=?, decided_at=? WHERE id=?",
                    (chosen, AUTO_USER, now, ask_out["call"]))
        con.commit()
    finally:
        con.close()
    CO.reapply(room["id"], rel)                              # so the file's marks say it was the AI
    return {**rule, "sampled": sampled}


def process_file(room: dict, rel: str, limit: int) -> dict:
    """Ask about a file's reading places that have no suggestion yet; at level 3 adopt the eligible answers."""
    from . import review as RV
    asked = adopted = 0
    s = CF.load()
    level = s["skills"]["arbitrate"]["level"] if s["enabled"] else 0
    if level < 2:
        return {"asked": 0, "adopted": 0, "stop": True}
    known = glossary.load()
    for it in RV.items(room, rel)["items"]:
        if asked >= limit:
            break
        if it["kind"] != "reading" or it.get("suggestion"):
            continue
        out = RV.ask(room, rel, it["i"], AUTO_USER, auto=True)
        asked += 1
        if out["status"] == "blocked":
            return {"asked": asked, "adopted": adopted, "stop": True}
        if level >= 3 and out["status"] in ("ok", "cached") and eligible_answer(it, out["result"], known):
            if adopt(room, rel, it, out):
                adopted += 1
    return {"asked": asked, "adopted": adopted, "stop": False}


def after_run(job: dict | None):
    """After a room's distilling run: ask about the new uncertain readings (level 2+) in the background."""
    import json
    if not job or not job.get("room_id"):
        return
    try:
        if json.loads(job.get("rel") or "{}").get("publish_from"):
            return
    except ValueError:
        return
    s = CF.load()
    if not s["enabled"] or s["skills"]["arbitrate"]["level"] < 2:
        return
    threading.Thread(target=_after_run, args=(job,), daemon=True, name="ai-after-run").start()


def _after_run(job: dict):
    try:
        room = R.get_room(job["room_id"])
        left = AFTER_RUN_LIMIT
        for r in R._files(room["id"]):
            if left <= 0:
                break
            if r["run_id"] != job["id"] or r["outcome"] != "result" or '"reading"' not in (r["findings"] or ""):
                continue
            out = process_file(room, r["rel"], left)
            left -= out["asked"]
            if out["stop"]:
                break
        review_level2()
    except Exception:                                        # noqa: BLE001 - never disturbs the queue
        traceback.print_exc()


def install_hooks():
    from ..jobs.queue import queue
    if after_run not in queue.after_done:
        queue.after_done.append(after_run)


# ------------------------------------------------------------------ people checking automatic adoptions
def on_undone(rule: dict, rel: str, user: str):
    """A person undid an automatic adoption: it was wrong, so the skill goes back to level 2."""
    if not rule.get("auto"):
        return
    con = db.trust_rw()
    try:
        con.execute("UPDATE correction_rule SET check_result='wrong', checked_by=?, checked_at=? WHERE id=? AND "
                    "COALESCE(check_result,'')<>'wrong'", (user, db.now(), rule["id"]))
        con.commit()
    finally:
        con.close()
    demote(f"{user} found an automatic adoption wrong in {rel.rsplit('/', 1)[-1]} (#{rule.get('num')})")


def check(rule_id: str, right: bool, user: str) -> dict:
    rule = CO.get_rule(rule_id)
    if not rule.get("auto"):
        raise CF.ConfigError(409, "this rule was not adopted automatically")
    if right:
        con = db.trust_rw()
        try:
            con.execute("UPDATE correction_rule SET check_result='right', checked_by=?, checked_at=? WHERE id=?",
                        (user, db.now(), rule_id))
            con.commit()
        finally:
            con.close()
    else:
        CO.undo(rule_id, rule["source_room"], rule["source_rel"], user)          # undoing it also demotes the skill
    return {"rule": CO.get_rule(rule_id)}


def checks() -> dict:
    """Automatic adoptions: the sampled ones waiting for a person, and the totals."""
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT r.id, r.num, r.find, r.replace_with, r.source_room, r.source_rel, r.created_at, m.name "
                           "FROM correction_rule r LEFT JOIN room m ON m.id=r.source_room WHERE r.auto=1 AND r.sampled=1 "
                           "AND r.check_result IS NULL ORDER BY r.created_at").fetchall()
        tot = con.execute("SELECT COUNT(*), SUM(CASE WHEN check_result='right' THEN 1 ELSE 0 END), "
                          "SUM(CASE WHEN check_result='wrong' THEN 1 ELSE 0 END) FROM correction_rule WHERE auto=1").fetchone()
    finally:
        con.close()
    pending = []
    for r in rows[:50]:
        before = after = ""
        try:
            row = next((x for x in CO._results(r[4]) if x["rel"] == r[5]), None)
            for text in (CO.raw_texts(r[4], row["out_dir"]).values() if row else []):
                i = text.find(r[2])
                if i >= 0:
                    before, after = " ".join(text[:i].split()[-6:]), " ".join(text[i + len(r[2]):].split()[:6])
                    break
        except Exception:                                    # noqa: BLE001 - context is a nicety
            pass
        pending.append({"rule": r[0], "num": r[1], "find": r[2], "replace": r[3], "room": r[7], "rel": r[5],
                        "at": r[6], "before": before, "after": after})
    return {"pending": pending, "total": tot[0] or 0, "right": tot[1] or 0, "wrong": tot[2] or 0}
