# -*- coding: utf-8 -*-
"""The correction library: exact rules, scoped to a document, a standard series or everything, applied to every
room's results, undoable per document, with number fixes sampled for a person to check."""
import json
import os

import pytest

from app import db
from app.distill import rules as RU
from app.jobs import corrections as C
from app.jobs import rooms as R
from app.jobs import sync_job as S

FM = '---\ndocument: "Watre services"\n---\n\n'


# ------------------------------------------------------------------ the text engine
@pytest.mark.parametrize("rel,want", [
    ("/2003/AS 3500.1-2003 Water services.pdf", "AS 3500.1"),
    ("/x/AS_NZS 3500.1_2018.pdf", "AS 3500.1"),
    ("/x/AS-NZS 3500.1:2018 Water.pdf", "AS 3500.1"),
    ("/as 3500/2018/Part 1.pdf", "AS 3500"),               # the folder says it when the name does not
    ("/NCC 2025 Volume One.pdf", "NCC"),
    ("/misc/notes.pdf", None),
    ("/ISO 9001 2015.pdf", "ISO 9001"),
])
def test_the_series_comes_from_the_file_name_without_the_year(rel, want):
    assert RU.series_of(rel) == want


def _r(find, replace, kind="text", before="", after="", scope="all", **kw):
    return {"id": kw.get("id", "r"), "find": find, "replace": replace, "kind": kind, "before": before, "after": after,
            "scope": scope, "series": kw.get("series"), "doc": kw.get("doc")}


def test_a_text_rule_changes_whole_words_only_and_leaves_the_front_matter():
    text = FM + "Watre supply. Watres are not Watre-proof.\n"
    new, done = RU.apply(text, [_r("Watre", "Water")])
    assert new.startswith(FM)                                      # front matter untouched
    assert new.endswith("Water supply. Watres are not Water-proof.\n") and done == {"r": 2}


def test_a_number_rule_applies_only_where_its_context_matches_exactly():
    rule = _r("l50", "150", kind="number", before="diameter ", after=" mm")
    text = "Pipe diameter l50 mm.\nCover l50 mm.\nThe diameter l50 mm again.\n"
    new, done = RU.apply(text, [rule])
    assert new == "Pipe diameter 150 mm.\nCover l50 mm.\nThe diameter 150 mm again.\n" and done == {"r": 2}


def test_a_number_rule_takes_its_context_from_the_one_place_it_was_checked():
    before, after = RU.context([FM + "Pipe diameter l50 mm minimum.\n"], "l50")
    assert (before, after) == ("Pipe diameter ", " mm minimum.")
    with pytest.raises(RU.RuleError, match="2 times"):
        RU.context(["l50 and l50"], "l50")
    with pytest.raises(RU.RuleError, match="does not appear"):
        RU.context(["nothing"], "l50")
    with pytest.raises(RU.RuleError, match="needs some text"):
        RU.context(["x\nl50\ny"], "l50")


@pytest.mark.parametrize("find,replace,scope,msg", [
    ("", "x", "all", "enter the text"), ("a\nb", "x", "all", "one line"), ("a", "a", "all", "same"),
    ("a", "b", "room", "scope"), ("a" * 201, "b", "all", "at most"),
])
def test_rules_are_checked_before_they_are_saved(find, replace, scope, msg):
    with pytest.raises(RU.RuleError, match=msg):
        RU.check(find, replace, scope)


def test_scope_decides_where_a_rule_applies():
    s = _r("a", "b", scope="series", series="AS 3500.1")
    assert RU.applies_to(s, "/2015/AS 3500.1-2015.pdf") and not RU.applies_to(s, "/AS 3500.2-2015.pdf")
    d = _r("a", "b", scope="document", doc="as 3500.1-2015.pdf")
    assert RU.applies_to(d, "/other room/AS 3500.1-2015.pdf") and not RU.applies_to(d, "/AS 3500.1-2018.pdf")
    assert RU.applies_to(_r("a", "b"), "/anything.pdf")


# ------------------------------------------------------------------ rooms
@pytest.fixture
def lib(monkeypatch, tmp_path):
    db.init_trust()
    con = db.trust_rw()
    for t in ("room_file", "room", "job", "correction_rule", "correction_exempt", "correction_check"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    monkeypatch.setattr(S, "room_dir", lambda rid: str(tmp_path / "rooms" / rid))
    return tmp_path


def _result(room_id, rel, text):
    out_dir = "src" + rel + ".md"
    p = os.path.join(S.room_dir(room_id), "out", out_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    ev = {"t": 1.0, "type": "file", "rel": rel, "kind": "pdf", "outcome": "result", "accuracy": 99.6, "diffs": 0,
          "number_diffs": 0, "parts": {}, "pages": 3, "out_dir": out_dir, "content_hash": "h" + rel, "single_file": True,
          "n_files": 1, "verdict": "PASS"}
    con = db.trust_rw()
    R.apply_event(con, room_id, "j", ev)
    con.commit()
    con.close()
    C.on_new_result(room_id, rel)
    return p


def _text(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _room(name):
    r = R.create_room(name, "t")
    return R.update_room(r["id"], {"source": "/as 3500", "threshold": 99})


A03, A15, B = "/AS 3500.1-2003 Water.pdf", "/AS 3500.1-2015 Water.pdf", "/AS 3500.2-2015 Sanitary.pdf"


def test_a_confirmed_fix_becomes_a_rule_for_the_same_series(lib):
    r1, r2 = _room("one"), _room("two")
    p1 = _result(r1["id"], A03, FM + "Watre pressure.\n")
    p2 = _result(r2["id"], A15, FM + "Watre heaters and Watre meters.\n")
    p3 = _result(r2["id"], B, FM + "Watre traps.\n")
    pv = C.preview("Watre", "Water", "series", r1["id"], A03)
    assert pv["kind"] == "text" and pv["series"] == "AS 3500.1" and pv["here"] == 1
    assert [(m["rel"], m["places"]) for m in pv["others"]] == [(A15, 2)]          # not the AS 3500.2 document
    out = C.create("wang", "Watre", "Water", "series", r1["id"], A03)
    assert out["rule"]["num"] == 1 and [m["rel"] for m in out["others"]] == [A15]
    assert "Water pressure" in _text(p1) and "Watre" in _text(p2)                  # others change when applied
    assert C.apply_everywhere(out["rule"]["id"]) == {"documents": 2, "changed": 1}
    assert _text(p2).endswith("Water heaters and Water meters.\n") and "Watre traps" in _text(p3)
    lib_ = C.library()
    assert lib_["total"] == 1 and lib_["rules"][0]["hits"] == 3 and lib_["rules"][0]["documents"] == 2
    with pytest.raises(C.CorrectionError) as e:                                     # the same rule twice
        C.create("li", "Watre", "Water", "series", r2["id"], A15)
    assert e.value.status == 422 or e.value.status == 409


def test_undoing_a_rule_in_one_document_restores_it_and_counts(lib):
    r1 = _room("one")
    p1 = _result(r1["id"], A03, FM + "Watre pressure.\n")
    p2 = _result(r1["id"], A15, FM + "Watre heaters.\n")
    rid = C.create("wang", "Watre", "Water", "series", r1["id"], A03)["rule"]["id"]
    C.apply_everywhere(rid)
    C.undo(rid, r1["id"], A15, "li")
    assert "Watre heaters" in _text(p2) and "Water pressure" in _text(p1)
    C.apply_everywhere(rid)                                                         # an undone place stays undone
    assert "Watre heaters" in _text(p2)
    assert C.get_rule(rid)["reverts"] == 1


def test_switching_a_rule_off_and_applying_it_restores_every_document(lib):
    r1 = _room("one")
    p1 = _result(r1["id"], A03, FM + "Watre pressure.\n")
    rid = C.create("wang", "Watre", "Water", "all", r1["id"], A03)["rule"]["id"]
    out = C.set_enabled(rid, False)
    assert [m["rel"] for m in out["affected"]] == [A03] and "Water pressure" in _text(p1)
    C.apply_everywhere(rid)
    assert "Watre pressure" in _text(p1)


def test_a_new_result_gets_the_rules_too(lib):
    r1 = _room("one")
    _result(r1["id"], A03, FM + "Watre pressure.\n")
    C.create("wang", "Watre", "Water", "series", r1["id"], A03)
    p = _result(r1["id"], A15, FM + "Watre heaters.\n")                            # distilled after the rule exists
    assert "Water heaters" in _text(p)
    p = _result(r1["id"], A03, FM + "Watre pressure, again.\n")                    # distilled again: new raw copy
    assert "Water pressure, again." in _text(p)


def test_number_fixes_are_held_for_a_check_until_a_person_confirms_them(lib):
    r1 = _room("one")
    _result(r1["id"], A03, FM + "Pipe diameter l50 mm minimum.\n")
    p2 = _result(r1["id"], A15, FM + "Pipe diameter l50 mm minimum.\n")
    rule = C.create("wang", "l50", "150", "series", r1["id"], A03)["rule"]
    assert rule["kind"] == "number" and rule["before"] == "Pipe diameter "
    C.apply_everywhere(rule["id"])
    assert "diameter 150 mm" in _text(p2)
    states = {f["rel"]: f for f in R.find_files(R.get_room(r1["id"]))["files"]}
    assert states[A03]["state"] == "ok" and states[A03]["corrected"] == 1          # checked when the rule was made
    assert states[A15]["state"] == "below" and states[A15]["checks"] == 1          # sampled: waits for a person
    C.confirm(rule["id"], r1["id"], A15, "li")
    assert {f["rel"]: f["state"] for f in R.find_files(R.get_room(r1["id"]))["files"]}[A15] == "ok"


def test_after_three_checked_documents_only_some_are_sampled(lib, monkeypatch):
    assert all(C._sampled("r", "room", f"/{i}.pdf", 0) for i in range(20))
    picked = [C._sampled("r", "room", f"/{i}.pdf", C.SAMPLE_FIRST) for i in range(200)]
    assert 10 < sum(picked) < 80 and picked == [C._sampled("r", "room", f"/{i}.pdf", 3) for i in range(200)]


def test_a_number_fix_without_a_unique_place_is_refused(lib):
    r1 = _room("one")
    _result(r1["id"], A03, FM + "l50 mm and l50 mm.\n")
    with pytest.raises(C.CorrectionError) as e:
        C.preview("l50", "150", "series", r1["id"], A03)
    assert e.value.status == 422 and "2 times" in e.value.message
    assert C.preview("l50 mm and", "150 mm and", "series", r1["id"], A03)["here"] == 1


def test_an_accepted_file_that_a_rule_changes_must_be_accepted_again(lib):
    r1 = _room("one")
    _result(r1["id"], A03, FM + "Watre pressure.\n")
    p2 = _result(r1["id"], A15, FM + "Watre heaters.\n")
    con = db.trust_rw()
    R.apply_event(con, r1["id"], "j2", {"t": 2, "type": "published", "rel": A15})
    con.commit()
    con.close()
    assert {f["rel"]: f["state"] for f in R.find_files(R.get_room(r1["id"]))["files"]}[A15] == "published"
    rid = C.create("wang", "Watre", "Water", "series", r1["id"], A03)["rule"]["id"]
    C.apply_everywhere(rid)
    assert "Water heaters" in _text(p2)
    assert {f["rel"]: f["state"] for f in R.find_files(R.get_room(r1["id"]))["files"]}[A15] == "ok"


def test_the_page_sees_the_result_and_its_corrections(lib):
    r1 = _room("one")
    _result(r1["id"], A03, FM + "Watre pressure.\n")
    C.create("wang", "Watre", "Water", "document", r1["id"], A03)
    v = C.file_view(r1["id"], A03)
    assert v["series"] == "AS 3500.1" and "Water pressure" in v["files"][0]["text"]
    assert [(c["find"], c["replace"], c["count"], c["check"]) for c in v["corrections"]] == [("Watre", "Water", 1, False)]


def test_series_scope_needs_a_standard_in_the_name(lib):
    r1 = _room("one")
    _result(r1["id"], "/notes.pdf", FM + "Watre.\n")
    with pytest.raises(C.CorrectionError, match="which standard"):
        C.preview("Watre", "Water", "series", r1["id"], "/notes.pdf")
    assert C.preview("Watre", "Water", "document", r1["id"], "/notes.pdf")["here"] == 1


def test_the_events_reader_applies_rules_to_new_results(lib):
    r1 = _room("one")
    _result(r1["id"], A03, FM + "Watre pressure.\n")
    C.create("wang", "Watre", "Water", "series", r1["id"], A03)
    out_dir = "src" + A15 + ".md"
    p = os.path.join(S.room_dir(r1["id"]), "out", out_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(FM + "Watre heaters.\n")
    ev = os.path.join(str(lib), "ev.jsonl")
    with open(ev, "w", encoding="utf-8") as f:
        f.write(json.dumps({"t": 1, "type": "file", "rel": A15, "outcome": "result", "accuracy": 99.9, "out_dir": out_dir,
                            "content_hash": "x", "single_file": True, "n_files": 1, "verdict": "PASS"}) + "\n")
    R.EventReader(r1["id"], "j", ev).poll()
    assert "Water heaters" in _text(p)
