# -*- coding: utf-8 -*-
"""The correction library: rules people confirmed, applied to the distilled results of every room.

How a result is kept:
    <room folder>/raw/<out_dir>   the result exactly as the distiller wrote it
    <room folder>/out/<out_dir>   the same with the rules applied; this is what is compared and accepted

The raw copy is refreshed whenever a file is distilled again, and the rules are applied to it afresh, so a rule
can be switched off, or undone in one document, without distilling anything again.

A person stays in control of numbers: a number rule only applies where its context matches exactly, and its changes
are sampled for review. Until three documents have been checked every change is shown for checking, afterwards one
document in five (chosen by a fixed hash, so the choice does not change between runs). A change waiting for a check
counts as a number difference, so with the room's number guard on the file is not accepted automatically.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
import zlib

from .. import db
from ..distill import rules as RU
from . import sync_job as S

SAMPLE_FIRST = 3          # documents that must be checked before sampling starts
SAMPLE_EVERY = 5          # afterwards one document in this many is shown for checking
MAX_VIEW = 3_000_000      # characters of a result shown on the page


class CorrectionError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ------------------------------------------------------------------ rules
def _rule(r) -> dict:
    return {"id": r["id"], "num": r["num"], "find": r["find"], "replace": r["replace_with"], "before": r["before_ctx"] or "",
            "after": r["after_ctx"] or "", "kind": r["kind"], "scope": r["scope"], "series": r["series"], "doc": r["doc"],
            "enabled": bool(r["enabled"]), "reverts": r["reverts"] or 0, "source_room": r["source_room"],
            "source_rel": r["source_rel"], "created_by": r["created_by"], "created_at": r["created_at"],
            "auto": bool(_col(r, "auto")), "sampled": bool(_col(r, "sampled")), "check_result": _col(r, "check_result")}


def _col(r, k):
    try:
        return r[k]
    except (IndexError, KeyError):
        return None


def all_rules(enabled_only: bool = False) -> list:
    con = db.trust_rw()
    try:
        rows = con.execute("SELECT * FROM correction_rule" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY num").fetchall()
    finally:
        con.close()
    return [_rule(r) for r in rows]


def get_rule(rule_id: str) -> dict:
    con = db.trust_rw()
    try:
        r = con.execute("SELECT * FROM correction_rule WHERE id=?", (rule_id,)).fetchone()
    finally:
        con.close()
    if not r:
        raise CorrectionError(404, "no such correction rule")
    return _rule(r)


def _pairs(table: str) -> set:
    con = db.trust_rw()
    try:
        return {(r[0], r[1], r[2]) for r in con.execute(f"SELECT rule_id, room_id, rel FROM {table}").fetchall()}
    finally:
        con.close()


# ------------------------------------------------------------------ result files
def _paths(room_id: str, out_dir: str) -> tuple[str, str]:
    base = S.room_dir(room_id)
    return os.path.join(base, "raw", out_dir), os.path.join(base, "out", out_dir)


def _md_files(base: str) -> list:
    """Relative paths of the Markdown files of one result ("" when the result is a single file)."""
    from ..distill.run import longpath
    lp = longpath(base)
    if os.path.isfile(lp):
        return [""] if base.lower().endswith(".md") else []
    out = []
    for root, _, names in os.walk(lp):
        for fn in sorted(names):
            if fn.lower().endswith(".md"):
                out.append(os.path.relpath(os.path.join(root, fn), lp).replace(os.sep, "/"))
    return out


def _read(base: str, inner: str) -> str:
    from ..distill.run import longpath
    with open(longpath(os.path.join(base, inner) if inner else base), encoding="utf-8", errors="replace") as f:
        return f.read()


def _write(base: str, inner: str, text: str):
    from ..distill.run import longpath
    p = longpath(os.path.join(base, inner) if inner else base)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, p)


def _copy(src: str, dst: str):
    from ..distill.run import longpath
    s, d = longpath(src), longpath(dst)
    if os.path.isdir(d):
        shutil.rmtree(d)
    elif os.path.exists(d):
        os.remove(d)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    if os.path.isdir(s):
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)


def _ensure_raw(room_id: str, out_dir: str) -> str | None:
    """The raw copy of a result; made from the current result the first time (it has no rules applied yet)."""
    from ..distill.run import longpath
    raw, out = _paths(room_id, out_dir)
    if not os.path.exists(longpath(raw)):
        if not os.path.exists(longpath(out)):
            return None
        _copy(out, raw)
    return raw


def raw_texts(room_id: str, out_dir: str) -> dict:
    raw = _ensure_raw(room_id, out_dir)
    if not raw:
        return {}
    return {inner: _read(raw, inner) for inner in _md_files(raw)}


def _results(room_id: str | None = None) -> list:
    """Every file that has a result, in every room (or in one)."""
    con = db.trust_rw()
    try:
        sql = ("SELECT f.room_id, f.rel, f.out_dir, f.confirmed, f.corrections, r.name AS room_name FROM room_file f "
               "JOIN room r ON r.id = f.room_id WHERE f.outcome='result' AND f.out_dir IS NOT NULL")
        rows = con.execute(sql + (" AND f.room_id=?" if room_id else ""), (room_id,) if room_id else ()).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def _row(room_id: str, rel: str) -> dict:
    r = next((x for x in _results(room_id) if x["rel"] == rel), None)
    if r is None:
        raise CorrectionError(404, "this file has no result in this room")
    return r


# ------------------------------------------------------------------ applying
def _sampled(rule_id: str, room_id: str, rel: str, checked_docs: int) -> bool:
    if checked_docs < SAMPLE_FIRST:
        return True
    return zlib.crc32(f"{rule_id}|{room_id}|{rel}".encode("utf-8")) % SAMPLE_EVERY == 0


def reapply(room_id: str, rel: str, rules: list | None = None) -> dict:
    """Apply the rules that hold for this file to its raw result and store what changed. Returns the summary."""
    r = _row(room_id, rel)
    raw = _ensure_raw(room_id, r["out_dir"])
    if not raw:
        return {"corrections": [], "checks": 0, "changed": False}
    _, out = _paths(room_id, r["out_dir"])
    exempt, checked = _pairs("correction_exempt"), _pairs("correction_check")
    rules = [x for x in (rules if rules is not None else all_rules(enabled_only=True))
             if x["enabled"] and RU.applies_to(x, rel) and (x["id"], room_id, rel) not in exempt]
    per_rule: dict = {}
    changed = False
    for inner in _md_files(raw):
        text = _read(raw, inner)
        new, done = RU.apply(text, rules)
        for rid, n in done.items():
            per_rule[rid] = per_rule.get(rid, 0) + n
        if os.path.exists(os.path.join(out, inner) if inner else out):
            if _read(out, inner) != new:
                _write(out, inner, new)
                changed = True
    checked_docs = {}
    for rid, _, _ in checked:
        checked_docs[rid] = checked_docs.get(rid, 0) + 1
    items = []
    for x in rules:
        if x["id"] not in per_rule:
            continue
        need = (x["kind"] == "number" and (x["id"], room_id, rel) not in checked
                and _sampled(x["id"], room_id, rel, checked_docs.get(x["id"], 0)))
        items.append({"rule": x["id"], "num": x["num"], "find": x["find"], "replace": x["replace"], "kind": x["kind"],
                      "count": per_rule[x["id"]], "check": need, "auto": bool(x.get("auto"))})
    checks = sum(1 for i in items if i["check"])
    old = json.loads(r["corrections"]) if r["corrections"] else []
    con = db.trust_rw()
    try:
        # a result that changed after it was accepted has to be accepted again
        con.execute("UPDATE room_file SET corrections=?, rule_checks=?, updated_at=? WHERE room_id=? AND rel=?",
                    (json.dumps(items, ensure_ascii=False), checks, db.now(), room_id, rel))
        if changed:
            con.execute("UPDATE room_file SET confirmed=0 WHERE room_id=? AND rel=?", (room_id, rel))
        con.commit()
    finally:
        con.close()
    return {"corrections": items, "checks": checks, "changed": changed or old != items}


def on_new_result(room_id: str, rel: str):
    """A file was distilled (again): keep its raw result and apply the rules to it."""
    from ..distill.run import longpath
    try:
        r = _row(room_id, rel)
    except CorrectionError:
        return
    raw, out = _paths(room_id, r["out_dir"])
    if not os.path.exists(longpath(out)):
        return
    _copy(out, raw)
    reapply(room_id, rel)


# ------------------------------------------------------------------ finding where a rule applies
def matches(rule: dict, skip: tuple | None = None) -> list:
    """Documents (in every room) where this rule finds its text now, with how many places."""
    out = []
    for r in _results():
        if (r["room_id"], r["rel"]) == skip or not RU.applies_to(rule, r["rel"]):
            continue
        n = sum(RU.count(rule, t) for t in raw_texts(r["room_id"], r["out_dir"]).values())
        if n:
            out.append({"room_id": r["room_id"], "room": r["room_name"], "rel": r["rel"], "places": n})
    return out


def affected(rule: dict) -> list:
    """Documents a change to this rule touches: where it finds its text, or where it is applied now."""
    found = {(m["room_id"], m["rel"]): m for m in matches(rule)}
    for r in _results():
        items = json.loads(r["corrections"]) if r["corrections"] else []
        if any(i["rule"] == rule["id"] for i in items) and (r["room_id"], r["rel"]) not in found:
            found[(r["room_id"], r["rel"])] = {"room_id": r["room_id"], "room": r["room_name"], "rel": r["rel"], "places": 0}
    return sorted(found.values(), key=lambda m: (m["room"], m["rel"]))


def _draft(user_find: str, replace: str, scope: str, room_id: str, rel: str) -> dict:
    try:
        RU.check(user_find, replace, scope)
    except RU.RuleError as e:
        raise CorrectionError(422, str(e))
    r = _row(room_id, rel)
    texts = list(raw_texts(room_id, r["out_dir"]).values())
    kind = "number" if RU.is_number(user_find, replace) else "text"
    before = after = ""
    if kind == "number":
        try:
            before, after = RU.context(texts, user_find)
        except RU.RuleError as e:
            raise CorrectionError(422, str(e))
    series = RU.series_of(rel)
    if scope == "series" and not series:
        raise CorrectionError(422, "the file name does not say which standard this is; choose this document or all")
    rule = {"id": "draft", "num": 0, "find": user_find, "replace": replace, "before": before, "after": after, "kind": kind,
            "scope": scope, "series": series if scope == "series" else None,
            "doc": RU.doc_key(rel) if scope == "document" else None, "enabled": True}
    here = sum(RU.count(rule, t) for t in texts)
    if not here:
        raise CorrectionError(422, "this text does not appear in the document (as a whole word)")
    return {"rule": rule, "here": here}


def preview(user_find: str, replace: str, scope: str, room_id: str, rel: str) -> dict:
    d = _draft(user_find, replace, scope, room_id, rel)
    others = matches(d["rule"], skip=(room_id, rel))
    return {"kind": d["rule"]["kind"], "before": d["rule"]["before"], "after": d["rule"]["after"],
            "series": RU.series_of(rel), "here": d["here"], "others": others,
            "other_places": sum(m["places"] for m in others)}


def create(user: str, user_find: str, replace: str, scope: str, room_id: str, rel: str) -> dict:
    """Save a confirmed fix as a rule and apply it to the document it was made in.

    The other documents it would change are returned; they change when the person applies the rule to them."""
    d = _draft(user_find, replace, scope, room_id, rel)
    rule = d["rule"]
    con = db.trust_rw()
    try:
        dup = con.execute("SELECT num FROM correction_rule WHERE find=? AND replace_with=? AND COALESCE(before_ctx,'')=? "
                          "AND COALESCE(after_ctx,'')=? AND scope=? AND COALESCE(series,'')=? AND COALESCE(doc,'')=?",
                          (rule["find"], rule["replace"], rule["before"], rule["after"], rule["scope"], rule["series"] or "",
                           rule["doc"] or "")).fetchone()
        if dup:
            raise CorrectionError(409, f"the same rule already exists (#{dup[0]})")
        num = con.execute("SELECT COALESCE(MAX(num),0)+1 FROM correction_rule").fetchone()[0]
        rid = uuid.uuid4().hex[:12]
        now = db.now()
        con.execute("INSERT INTO correction_rule(id,num,find,replace_with,before_ctx,after_ctx,kind,scope,series,doc,enabled,"
                    "reverts,source_room,source_rel,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,1,0,?,?,?,?,?)",
                    (rid, num, rule["find"], rule["replace"], rule["before"], rule["after"], rule["kind"], rule["scope"],
                     rule["series"], rule["doc"], room_id, rel, user, now, now))
        # the person looked at this place when making the rule: it counts as checked
        con.execute("INSERT INTO correction_check(rule_id, room_id, rel, by_user, at) VALUES(?,?,?,?,?)", (rid, room_id, rel, user, now))
        con.commit()
    finally:
        con.close()
    reapply(room_id, rel)
    saved = get_rule(rid)
    others = matches(saved, skip=(room_id, rel))
    return {"rule": saved, "others": others}


def apply_everywhere(rule_id: str) -> dict:
    """Bring every document the rule touches up to date (after it was made, switched off or on)."""
    rule = get_rule(rule_id)
    docs = affected(rule)
    changed = 0
    for m in docs:
        if reapply(m["room_id"], m["rel"])["changed"]:
            changed += 1
    return {"documents": len(docs), "changed": changed}


def set_enabled(rule_id: str, enabled: bool) -> dict:
    get_rule(rule_id)
    con = db.trust_rw()
    try:
        con.execute("UPDATE correction_rule SET enabled=?, updated_at=? WHERE id=?", (1 if enabled else 0, db.now(), rule_id))
        con.commit()
    finally:
        con.close()
    rule = get_rule(rule_id)
    return {"rule": rule, "affected": affected(rule)}


def undo(rule_id: str, room_id: str, rel: str, user: str) -> dict:
    """A person undid a rule in one document: restore the original text there and do not apply it there again."""
    rule = get_rule(rule_id)
    _row(room_id, rel)
    con = db.trust_rw()
    try:
        exists = con.execute("SELECT 1 FROM correction_exempt WHERE rule_id=? AND room_id=? AND rel=?",
                             (rule_id, room_id, rel)).fetchone()
        if not exists:
            con.execute("INSERT INTO correction_exempt(rule_id, room_id, rel, by_user, at) VALUES(?,?,?,?,?)",
                        (rule_id, room_id, rel, user, db.now()))
            con.execute("UPDATE correction_rule SET reverts=COALESCE(reverts,0)+1, updated_at=? WHERE id=?", (db.now(), rule_id))
        con.commit()
    finally:
        con.close()
    out = reapply(room_id, rel)
    if rule["auto"]:                                        # an automatic adoption a person undid was wrong
        from ..ai import level3
        level3.on_undone(rule, rel, user)
    return out


def confirm(rule_id: str, room_id: str, rel: str, user: str) -> dict:
    """A person checked a number rule's change in this document and found it right."""
    get_rule(rule_id)
    _row(room_id, rel)
    con = db.trust_rw()
    try:
        if not con.execute("SELECT 1 FROM correction_check WHERE rule_id=? AND room_id=? AND rel=?",
                           (rule_id, room_id, rel)).fetchone():
            con.execute("INSERT INTO correction_check(rule_id, room_id, rel, by_user, at) VALUES(?,?,?,?,?)",
                        (rule_id, room_id, rel, user, db.now()))
        con.commit()
    finally:
        con.close()
    return reapply(room_id, rel)


# ------------------------------------------------------------------ the library and one file
def library() -> dict:
    rules = all_rules()
    hits: dict = {}
    docs: dict = {}
    for r in _results():
        for i in json.loads(r["corrections"]) if r["corrections"] else []:
            hits[i["rule"]] = hits.get(i["rule"], 0) + i["count"]
            docs[i["rule"]] = docs.get(i["rule"], 0) + 1
    out = []
    for x in rules:
        h = hits.get(x["id"], 0)
        out.append({**x, "hits": h, "documents": docs.get(x["id"], 0),
                    "often_undone": x["reverts"] >= 3 or (x["reverts"] > 0 and x["reverts"] * 4 >= h + x["reverts"]),
                    "source_name": (x["source_rel"] or "").replace("\\", "/").rsplit("/", 1)[-1]})
    return {"rules": out, "total": len(out), "enabled": sum(1 for x in out if x["enabled"]),
            "disabled": sum(1 for x in out if not x["enabled"]), "often_undone": sum(1 for x in out if x["often_undone"])}


def file_view(room_id: str, rel: str) -> dict:
    """One file's result as it is now (rules applied), and the rules applied to it."""
    from ..distill.run import longpath
    r = _row(room_id, rel)
    _ensure_raw(room_id, r["out_dir"])
    _, out = _paths(room_id, r["out_dir"])
    if not os.path.exists(longpath(out)):
        raise CorrectionError(409, "the distilled result is no longer on this machine; run the room again")
    parts, size = [], 0
    for inner in _md_files(out):
        text = _read(out, inner)
        cut = size + len(text) > MAX_VIEW
        parts.append({"path": inner or RU.doc_key(rel) + ".md", "text": text[:max(0, MAX_VIEW - size)], "cut": cut})
        size += len(text)
        if cut:
            break
    return {"rel": rel, "series": RU.series_of(rel), "files": parts,
            "corrections": json.loads(r["corrections"]) if r["corrections"] else []}
