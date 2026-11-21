# -*- coding: utf-8 -*-
"""Formula transcription (image crop only, numbers checked against local OCR, a person approves) and rule suggestions
(one wider rule, or a text-only pattern checked in code and previewed, approved by a person)."""
import json
import os

import pytest

from app import db
from app.ai import config as CF
from app.ai import formulas as FX
from app.ai import gate as G
from app.ai import providers as P
from app.ai import review as RV
from app.ai import suggestions as SG
from app.ai.skills import suggest as SK
from app.ai.skills import transcribe as TR
from app.distill import formula as FM
from app.distill import rules as RU
from app.distill.structure import UNREADABLE_MARK
from app.jobs import corrections as CO
from app.jobs import rooms as R
from app.jobs import sync_job as S
from tests.test_ai import Fake


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(CF, "SETTINGS_PATH", str(tmp_path / "ai_settings.json"))
    monkeypatch.setattr(CF, "KEYS_PATH", str(tmp_path / "ai_keys.json"))
    monkeypatch.setattr(CF, "SECRET_PATH", str(tmp_path / "ai_secret.key"))
    monkeypatch.setattr(S, "room_dir", lambda rid: str(tmp_path / "rooms" / rid))
    monkeypatch.setattr(FM, "APPROVALS", str(tmp_path / "formula_approvals.json"))
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    db.init_trust()
    con = db.trust_rw()
    for t in ("ai_call", "ai_cache", "ai_example", "room_file", "room", "job", "correction_rule", "correction_exempt",
              "correction_check", "rule_suggestion"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    return tmp_path


def _ai(level=1, prefixes=("/as 3500",)):
    p = CF.add_provider("anthropic", "sk-ant-test-1234567890abcd")
    CF.update({"enabled": True, "skills": {s: {"provider": p["id"], "model": "claude-opus-5-5", "level": min(level, CF.MAX_LEVEL[s])}
                                           for s in CF.SKILLS},
               "scope": {"allowed_prefixes": list(prefixes), "block_licensed": True}})


def _room(name, source="/as 3500"):
    r = R.create_room(name, "t")
    return R.update_room(r["id"], {"source": source})


def _result(room_id, rel, text, findings=None, content_hash=None):
    out_dir = "src" + rel + ".md"
    p = os.path.join(S.room_dir(room_id), "out", out_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    ev = {"t": 1, "type": "file", "rel": rel, "kind": "pdf", "outcome": "result", "accuracy": 99.5, "out_dir": out_dir,
          "content_hash": content_hash or ("h" + rel), "single_file": True, "n_files": 1, "verdict": "PASS",
          "findings": findings or []}
    con = db.trust_rw()
    R.apply_event(con, room_id, "j", ev)
    con.commit()
    con.close()
    CO.on_new_result(room_id, rel)
    return p


def _text(p):
    return open(p, encoding="utf-8").read()


# ------------------------------------------------------------------ pattern rules
@pytest.mark.parametrize("pattern,replace,msg", [
    (r"\d+", "x", "numbers"), (r"l5", "15", "numbers"), (r"[0-9]a", "a", "numbers"), (r"\b(\w+)cd\b", r"\g<1>9", None),
    (r"a.*b", "ab", "any text"), (r"(a+)+b", "b", "repeated"), (r"(\w)\1", "x", "refer back"), (r"\b(\w+)cd\b", r"\2ed", "refers to a part"),
    (r"(", "x", "not a valid"), (r"x?", "y", "empty"),
])
def test_patterns_are_safe_and_never_touch_numbers(pattern, replace, msg):
    if msg is None:
        with pytest.raises(RU.RuleError, match="numbers"):
            RU.check_pattern(pattern, "9")
        return
    with pytest.raises(RU.RuleError, match=msg):
        RU.check_pattern(pattern, replace)


def test_a_pattern_skips_places_with_digits():
    rule = {"id": "p", "kind": "pattern", "find": r"\b(\w+)cd\b", "replace": r"\1ed", "scope": "all"}
    new, done = RU.apply("---\nx: 1\n---\nfittcd, connectcd and l2cd.\n", [rule])
    assert new.endswith("fitted, connected and l2cd.\n") and done == {"p": 2}


def test_a_suggested_pattern_must_get_the_known_cases_right():
    fixes = [{"wrong": "fittcd", "right": "fitted"}, {"wrong": "connectcd", "right": "connected"}, {"wrong": "mountcd", "right": "mounted"}]
    good = json.dumps({"pattern": r"\b(\w+t)cd\b", "replace": r"\1ed", "counterexamples": ["cd", "card"], "scope": "all", "reason": "c read for e"})
    assert SK.check(good, {"fixes": fixes})["accuracy"] == 100.0
    greedy = json.dumps({"pattern": r"cd", "replace": "ed", "counterexamples": ["cdrom", "abcd"], "scope": "all", "reason": "r"})
    with pytest.raises(ValueError, match="right on only"):
        SK.check(greedy, {"fixes": fixes})
    with pytest.raises(ValueError, match="any text"):
        SK.check(json.dumps({"pattern": r"t.*cd", "replace": "ted", "counterexamples": [], "scope": "all", "reason": ""}), {"fixes": fixes})


# ------------------------------------------------------------------ suggestions
def test_the_same_fix_saved_twice_becomes_one_wider_rule(env):
    r1, r2 = _room("one"), _room("two")
    _result(r1["id"], "/AS 3500.1-2003.pdf", "Watre here.\n")
    _result(r2["id"], "/AS 3500.2-2015.pdf", "Watre there.\n")
    _result(r2["id"], "/NCC 2025.pdf", "Watre everywhere.\n")
    a = CO.create("wang", "Watre", "Water", "series", r1["id"], "/AS 3500.1-2003.pdf")["rule"]
    b = CO.create("li", "Watre", "Water", "series", r2["id"], "/AS 3500.2-2015.pdf")["rule"]
    found = SG.scan("wang")
    assert found["widen"] == 1
    sg = SG.listing()[0]
    assert sg["kind"] == "widen" and sg["data"]["scope"] == "all"
    assert sg["preview"]["documents"] == 1                                 # only the NCC document still has it
    assert {s["old"] for s in sg["preview"]["samples"]} == {"Watre"}
    assert SG.scan("wang")["widen"] == 0                                   # not suggested twice
    out = SG.approve(sg["id"], "wang")
    keep, other = sorted([a["id"], b["id"]])
    assert out["rule"]["id"] == keep and out["rule"]["scope"] == "all" and not CO.get_rule(other)["enabled"]
    assert len(out["affected"]) == 3 and SG.listing() == []


def _three_fixes(env):
    r = _room("one")
    for rel, word in (("/a.pdf", "fittcd"), ("/b.pdf", "connectcd"), ("/c.pdf", "mountcd")):
        _result(r["id"], rel, f"The pipe is {word} here.\n")
        CO.create("wang", word, word[:-2] + "ed", "all", r["id"], rel)
    other = _result(r["id"], "/d.pdf", "Each valve is insertcd and the cd is fine.\n")
    return r, other


def test_three_fixes_of_the_same_kind_become_a_pattern_suggestion(env, monkeypatch):
    r, other = _three_fixes(env)
    assert SG.scan("wang")["pattern_needs_ai"] == 1                        # AI off: nothing is sent
    _ai()
    fake = Fake({"pattern": r"\b(\w+t)cd\b", "replace": r"\1ed", "counterexamples": ["cd", "card"], "scope": "all", "reason": "c read as e"})
    monkeypatch.setattr(P, "call", fake)
    assert SG.scan("wang")["pattern"] == 1
    assert "fittcd" in fake.calls[0]["user"] and "The pipe is" not in fake.calls[0]["user"]     # only the fixes are sent
    sg = next(s for s in SG.listing() if s["kind"] == "pattern")
    assert sg["data"]["accuracy"] == 100.0 and sg["preview"]["documents"] == 1
    assert sg["preview"]["samples"][0]["old"] == "insertcd" and sg["preview"]["samples"][0]["new"] == "inserted"
    out = SG.approve(sg["id"], "wang")
    assert out["rule"]["kind"] == "pattern"
    CO.apply_everywhere(out["rule"]["id"])
    assert "inserted and the cd is fine" in _text(other)


def test_a_pattern_that_breaks_the_rules_is_not_suggested(env, monkeypatch):
    _three_fixes(env)
    _ai()
    monkeypatch.setattr(P, "call", Fake({"pattern": r"cd", "replace": "ed", "counterexamples": ["cd"], "scope": "all", "reason": ""}))
    assert SG.scan("wang")["pattern_rejected"] == 1 and not [s for s in SG.listing() if s["kind"] == "pattern"]


def test_fixes_from_a_folder_not_allowed_are_not_sent(env, monkeypatch):
    _three_fixes(env)
    _ai(prefixes=("/NCC",))
    fake = Fake({})
    monkeypatch.setattr(P, "call", fake)
    assert SG.scan("wang")["pattern_not_allowed"] == 1 and fake.calls == []


def test_dismissing_a_suggestion_records_it(env, monkeypatch):
    _three_fixes(env)
    _ai()
    monkeypatch.setattr(P, "call", Fake({"pattern": r"\b(\w+t)cd\b", "replace": r"\1ed", "counterexamples": [], "scope": "all", "reason": ""}))
    SG.scan("wang")
    sg = SG.listing()[0]
    SG.dismiss(sg["id"], "wang")
    assert SG.listing() == [] and G.stats()["skills"]["suggest"]["rejected"] == 1
    assert SG.scan("wang")["pattern"] == 0                                 # a dismissed one does not come back


# ------------------------------------------------------------------ formulas
def test_a_transcription_must_only_use_numbers_the_local_ocr_sees():
    p = TR.payload(4, 1, "sha", "Cp = 0.0133 I10 m - 0.0233")
    ok = TR.check(json.dumps({"latex": r"C_p = 0.0133\,I_{10}\,m - 0.0233", "plain": "Cp = ...", "confidence": 0.9, "unsure": False}), p)
    assert ok["numbers_checked"] is True and ok["needs_human"] is True
    with pytest.raises(ValueError, match="0.0134"):
        TR.check(json.dumps({"latex": r"C_p = 0.0134 I_{10}", "plain": "", "confidence": 0.9, "unsure": False}), p)
    unchecked = TR.check(json.dumps({"latex": "x = 2", "plain": "", "confidence": 0.5, "unsure": True}), TR.payload(4, 1, "s", None))
    assert unchecked["numbers_checked"] is None


BODY = ("---\nx: 1\n---\n\n<!-- unit: p0004 | src: p.4 | chars: 10 | flags: - -->\nThe coefficient is "
        + UNREADABLE_MARK + " where m is the mass.\n<!-- /unit -->\n")


def _formula_room(env, monkeypatch):
    r = _room("one")
    p = _result(r["id"], "/AS 3500.1.pdf", BODY, findings=[{"kind": "formula", "page": 4, "detail": "text layer cannot be decoded"}],
                content_hash="HASH")
    monkeypatch.setattr(FX, "source_pdf", lambda rel, h: "/fake.pdf")
    monkeypatch.setattr(FX, "boxes", lambda pdf, h: {4: [{"k": 1, "bbox": [10, 10, 100, 30]}]})
    monkeypatch.setattr(FX, "crop", lambda pdf, page, bbox: b"PNG-crop")
    monkeypatch.setattr(FX, "ocr_text", lambda png: "Cp = 0.0133 I10 m - 0.0233")
    return R.get_room(r["id"]), p


def test_a_formula_is_transcribed_from_its_crop_and_approved_by_a_person(env, monkeypatch):
    room, p = _formula_room(env, monkeypatch)
    data = RV.items(room, "/AS 3500.1.pdf")
    assert data["items"][0]["formulas"] == [{"k": 1, "approved": None, "suggestion": None}]
    _ai()
    seen = {}

    def answer(p_, key, model, system, user, schema, timeout=P.TIMEOUT, image=None):
        seen["image"] = image
        seen["user"] = user
        return {"text": json.dumps({"latex": r"C_p = 0.0133 I_{10} m - 0.0233", "plain": "", "confidence": 0.9, "unsure": False}),
                "tokens_in": 1, "tokens_out": 1, "seconds": 0.1}

    monkeypatch.setattr(P, "call", answer)
    out = RV.ask(room, "/AS 3500.1.pdf", 0, "wang", k=1)
    assert out["status"] == "ok" and seen["image"] == b"PNG-crop" and out["result"]["numbers_checked"] is True
    assert '"before": "The coefficient is"' in seen["user"] and '"after": "where m is the mass."' in seen["user"]
    assert "ocr_text" not in G.examples() and "Cp = 0.0133" not in json.dumps(RV.items(room, "/AS 3500.1.pdf"))  # OCR text not kept
    FX.approve(room["id"], next(x for x in R._files(room["id"]) if x["rel"] == "/AS 3500.1.pdf"), 4, 1, out["result"]["latex"], "wang")
    text = _text(p)
    assert UNREADABLE_MARK not in text and "$$C_p = 0.0133 I_{10} m - 0.0233$$ *(formula transcribed from the source image; reviewed" in text
    assert RV.items(room, "/AS 3500.1.pdf")["items"][0]["formulas"][0]["approved"] == r"C_p = 0.0133 I_{10} m - 0.0233"
    assert FM.load_approvals()["HASH"]["p.4#1"]["reviewer"] == "wang"      # kept for every later run of this file


def test_a_transcription_with_an_invented_number_is_discarded(env, monkeypatch):
    room, _ = _formula_room(env, monkeypatch)
    _ai()
    monkeypatch.setattr(P, "call", Fake({"latex": "C_p = 0.0199", "plain": "", "confidence": 0.99, "unsure": False}))
    out = RV.ask(room, "/AS 3500.1.pdf", 0, "wang", k=1)
    assert out["status"] == "invalid" and out["result"] is None


def test_without_the_source_file_a_formula_cannot_be_looked_at(env, monkeypatch):
    room, _ = _formula_room(env, monkeypatch)
    monkeypatch.setattr(FX, "source_pdf", lambda rel, h: None)
    assert RV.items(room, "/AS 3500.1.pdf")["items"][0]["formulas"] is None
    with pytest.raises(CF.ConfigError, match="no longer on this machine"):
        FX.image(next(x for x in R._files(room["id"]) if x["rel"] == "/AS 3500.1.pdf"), 4, 1)


def test_skill_levels_are_limited(env):
    p = CF.add_provider("anthropic", "sk-ant-test-1234567890abcd")
    with pytest.raises(CF.ConfigError, match="0 to 1"):
        CF.update({"skills": {"transcribe": {"provider": p["id"], "model": "claude-opus-5-5", "level": 2}}})
