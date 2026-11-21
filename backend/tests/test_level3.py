# -*- coding: utf-8 -*-
"""Reading arbitration at level 3: earned, only plain text agreed by the word list, marked, sampled for checking, and
falling back to level 2 the moment an adoption is found wrong."""
import json
import os
import time

import pytest

from app import db
from app.ai import config as CF
from app.ai import gate as G
from app.ai import level3 as L3
from app.ai import providers as P
from app.ai import review as RV
from app.distill import glossary
from app.jobs import corrections as CO
from app.jobs import rooms as R
from app.jobs import sync_job as S
from tests.test_ai import Fake

KNOWN = {"fitted", "mounted", "pipe", "valve"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(CF, "SETTINGS_PATH", str(tmp_path / "ai_settings.json"))
    monkeypatch.setattr(CF, "KEYS_PATH", str(tmp_path / "ai_keys.json"))
    monkeypatch.setattr(CF, "SECRET_PATH", str(tmp_path / "ai_secret.key"))
    monkeypatch.setattr(S, "room_dir", lambda rid: str(tmp_path / "rooms" / rid))
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    monkeypatch.setattr(glossary, "load", lambda path=None: KNOWN)
    db.init_trust()
    con = db.trust_rw()
    for t in ("ai_call", "ai_cache", "ai_example", "room_file", "room", "job", "correction_rule", "correction_exempt", "correction_check"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    return tmp_path


def _ai(level=2):
    p = CF.add_provider("anthropic", "sk-ant-test-1234567890abcd")
    s = CF.load()
    s["enabled"] = True
    for name in CF.SKILLS:
        s["skills"][name].update(provider=p["id"], model="claude-opus-5-5", level=min(level, CF.MAX_LEVEL[name]))
    s["scope"] = {"allowed_prefixes": ["/as 3500"], "block_licensed": True}
    CF.save(s)                                            # written directly: the tests set level 3 without earning it


def _decisions(n, adopted):
    """n human decisions on reading-arbitration suggestions, `adopted` of them taken."""
    con = db.trust_rw()
    for i in range(n):
        con.execute("INSERT INTO ai_call(id, skill, status, decision, decided_at, created_by, created_at) VALUES(?,?,?,?,?,?,?)",
                    (f"d{i}", "arbitrate", "ok", "adopted" if i < adopted else "rejected", time.time() - i, "wang", time.time()))
    con.commit()
    con.close()


def _file(room_id, rel, text, findings, job="j1"):
    out_dir = "src" + rel + ".md"
    p = os.path.join(S.room_dir(room_id), "out", out_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(text)
    con = db.trust_rw()
    R.apply_event(con, room_id, job, {"t": 1, "type": "file", "rel": rel, "outcome": "result", "accuracy": 97.0, "out_dir": out_dir,
                                      "content_hash": "h" + rel, "single_file": True, "n_files": 1, "verdict": "REVIEW",
                                      "findings": findings})
    con.commit()
    con.close()
    CO.on_new_result(room_id, rel)
    return p


def _room():
    r = R.create_room("scans", "t")
    return R.update_room(r["id"], {"source": "/as 3500"})


READ = lambda a, b: {"kind": "reading", "page": 1, "detail": f"{a} / {b}", "a": a, "b": b}  # noqa: E731
ANSWER = {"choice": 1, "confidence": 0.95, "reason": "a real word", "needs_human": False}


# ------------------------------------------------------------------ earning it
def test_level_3_must_be_earned(env):
    _ai()
    with pytest.raises(CF.ConfigError) as e:
        CF.update({"skills": {"arbitrate": {"level": 3}}}, user="admin")
    assert e.value.status == 409 and "decided" in e.value.message
    _decisions(300, 290)                                  # 96.7%: not enough
    assert [m["code"] for m in L3.eligibility()["missing"]] == ["adoption"]
    _decisions_extra = 0
    con = db.trust_rw()
    con.execute("UPDATE ai_call SET decision='adopted' WHERE decision='rejected' AND id IN ('d290','d291','d292','d293','d294','d295')")
    con.commit()
    con.close()
    el = L3.eligibility()
    assert el["eligible"] and el["adoption"] == 98.7
    s = CF.update({"skills": {"arbitrate": {"level": 3}}}, user="admin@example.com")
    assert s["skills"]["arbitrate"]["level"] == 3 and s["skills"]["arbitrate"]["promoted_by"] == "admin@example.com"
    with pytest.raises(CF.ConfigError):
        CF.update({"skills": {"transcribe": {"level": 3}}})                      # never for formulas


def test_only_plain_text_agreed_by_the_word_list_is_adopted():
    item = {"candidates": ["fittcd", "fitted"], "in_text": "fittcd"}
    assert L3.eligible_answer(item, {"choice": 1, "text": "fitted", "confidence": 0.95, "needs_human": False}, KNOWN)
    assert not L3.eligible_answer(item, {"choice": 1, "text": "fitted", "confidence": 0.8, "needs_human": False}, KNOWN)
    assert not L3.eligible_answer(item, {"choice": 0, "text": "fittcd", "confidence": 0.95, "needs_human": False}, KNOWN)
    assert not L3.eligible_answer({"candidates": ["l50", "150"], "in_text": "l50"},
                                  {"choice": 1, "text": "150", "confidence": 0.99, "needs_human": True}, KNOWN)
    assert not L3.eligible_answer({"candidates": ["pipe", "valve"], "in_text": "pipe"},              # both known words
                                  {"choice": 1, "text": "valve", "confidence": 0.99, "needs_human": False}, KNOWN)
    assert not L3.eligible_answer({"candidates": ["a", "b", "fitted"], "in_text": "a"},
                                  {"choice": 2, "text": "fitted", "confidence": 0.99, "needs_human": False}, KNOWN)


# ------------------------------------------------------------------ after a run
def test_after_a_run_level_2_asks_and_level_3_adopts_and_marks(env, monkeypatch):
    room = _room()
    p = _file(room["id"], "/scan.pdf", "---\nx: 1\n---\n\nEach pipe is fittcd to the wall. A valve is mountcd here.\n",
              [READ("fittcd", "fitted"), READ("mountcd", "mounted"), READ("l50", "150")])
    fake = Fake(ANSWER)
    monkeypatch.setattr(P, "call", fake)
    _ai(level=2)
    L3._after_run({"id": "j1", "room_id": room["id"]})
    assert len(fake.calls) == 3 and "fitted" not in open(p, encoding="utf-8").read().split("---")[-1].split("Each")[1][:12]
    con = db.trust_rw()
    con.execute("DELETE FROM ai_call")
    con.execute("DELETE FROM ai_cache")
    con.commit()
    con.close()
    _ai(level=3)
    L3._after_run({"id": "j1", "room_id": room["id"]})
    body = open(p, encoding="utf-8").read()
    assert "Each pipe is fitted to the wall. A valve is mounted here." in body
    lib = CO.library()["rules"]
    assert {r["find"] for r in lib} == {"fittcd", "mountcd"}                     # never the number
    assert all(r["auto"] and r["created_by"] == L3.AUTO_USER and r["scope"] == "document" for r in lib)
    marks = CO.file_view(room["id"], "/scan.pdf")["corrections"]
    assert all(m["auto"] for m in marks)
    assert {i["rel"] for i in L3.checks()["pending"]} == {"/scan.pdf"}          # the first ones are all checked by a person
    assert G.stats()["skills"]["arbitrate"]["adopted"] == 0                      # automatic is not a person taking it


def test_a_run_of_another_job_or_a_publish_is_left_alone(env, monkeypatch):
    room = _room()
    _file(room["id"], "/scan.pdf", "fittcd\n", [READ("fittcd", "fitted")], job="j0")
    fake = Fake(ANSWER)
    monkeypatch.setattr(P, "call", fake)
    _ai(level=3)
    L3._after_run({"id": "j1", "room_id": room["id"]})
    assert fake.calls == []
    L3.after_run({"id": "j0", "room_id": room["id"], "rel": json.dumps({"publish_from": "x.json"})})
    time.sleep(0.2)
    assert fake.calls == []


# ------------------------------------------------------------------ falling back
def _adopted(env, monkeypatch):
    room = _room()
    p = _file(room["id"], "/scan.pdf", "Each pipe is fittcd to the wall.\n", [READ("fittcd", "fitted")])
    monkeypatch.setattr(P, "call", Fake(ANSWER))
    _ai(level=3)
    L3._after_run({"id": "j1", "room_id": room["id"]})
    return room, p, L3.checks()["pending"][0]


def test_a_sampled_check_found_right_keeps_it(env, monkeypatch):
    _, p, item = _adopted(env, monkeypatch)
    L3.check(item["rule"], True, "wang")
    assert L3.checks()["pending"] == [] and L3.checks()["right"] == 1 and CF.load()["skills"]["arbitrate"]["level"] == 3


def test_a_sampled_check_found_wrong_undoes_it_and_falls_back_to_level_2(env, monkeypatch):
    _, p, item = _adopted(env, monkeypatch)
    assert item["before"] == "Each pipe is" and item["after"] == "to the wall."
    L3.check(item["rule"], False, "wang")
    assert "fittcd" in open(p, encoding="utf-8").read()
    s = CF.load()
    assert s["skills"]["arbitrate"]["level"] == 2 and "found an automatic adoption wrong" in s["demotions"][-1]["reason"]
    assert s["demotions"][-1]["code"] == "found_wrong" and s["demotions"][-1]["args"]["num"]      # so the screen can say it in Chinese too
    assert L3.checks()["wrong"] == 1 and not L3.eligibility()["eligible"]


def test_undoing_an_automatic_adoption_in_the_fix_panel_also_falls_back(env, monkeypatch):
    room, p, item = _adopted(env, monkeypatch)
    CO.undo(item["rule"], room["id"], "/scan.pdf", "li")
    assert CF.load()["skills"]["arbitrate"]["level"] == 2


def test_level_2_falls_back_to_1_when_people_rarely_take_its_suggestions(env):
    _ai(level=2)
    _decisions(50, 30)                                   # 60%
    L3.review_level2()
    s = CF.load()
    assert s["skills"]["arbitrate"]["level"] == 1 and "fewer than 70%" in s["demotions"][-1]["reason"]
    assert s["demotions"][-1]["code"] == "low_adoption" and s["demotions"][-1]["args"]["floor"] == "70"


def test_sampling_checks_the_first_twenty_then_one_in_ten(env):
    con = db.trust_rw()
    for i in range(30):
        con.execute("INSERT INTO correction_rule(id, num, find, replace_with, kind, scope, enabled, auto) VALUES(?,?,?,?,?,?,1,1)",
                    (f"r{i}", i, "a", "b", "text", "document"))
    con.commit()
    con.close()
    picked = [L3._sample(f"x{i}") for i in range(300)]
    assert 10 < sum(picked) < 60


def test_the_api_lists_checks_for_reviewers(env, monkeypatch, login):
    _adopted(env, monkeypatch)
    c = login("reviewer")
    got = c.get("/api/v1/ai/auto-checks").json()
    assert len(got["pending"]) == 1
    assert c.post(f"/api/v1/ai/auto-checks/{got['pending'][0]['rule']}", json={"right": True}).json()["right"] == 1
    assert login("viewer").post(f"/api/v1/ai/auto-checks/{got['pending'][0]['rule']}", json={"right": True}).status_code == 403


from tests.test_rooms import login, _mk  # noqa: E402,F401
