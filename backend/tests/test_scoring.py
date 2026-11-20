# -*- coding: utf-8 -*-
"""One percentage per file; "no result" is a different thing from "low accuracy"."""
from app.distill import scoring as S


def _pdf_report(**over):
    rep = {"page_count": 100, "pages": {"ok": True, "missing": []},
           "headings": {"ok": True, "unmatched": 0, "total": 50, "examples": []},
           "chars": {"recall": 1.0, "pages_below_99_5": [], "ok": True},
           "extra_text": {"pages": [], "ok": True},
           "numbers": {"recall": 1.0, "pages_with_missing": [], "ok": True},
           "tables": {"ok": True, "cells": 200, "mismatches": 0, "examples": []},
           "unreadable": {"lines": 0, "pages": []},
           "source_unchanged": {"ok": True}}
    rep.update(over)
    return {"verdict": "PASS", "report": rep}


def test_perfect_file_is_100_and_ok():
    c = S.classify(_pdf_report())
    assert c["outcome"] == "result" and c["accuracy"] == 100.0 and c["diffs"] == 0
    assert S.decide(c["accuracy"], c["number_diffs"], 99) == "ok"


def test_numbers_weigh_more_than_headings():
    a = S.classify(_pdf_report(numbers={"recall": 0.9, "pages_with_missing": [[5, ["10"]]], "ok": False}))
    b = S.classify(_pdf_report(headings={"ok": False, "unmatched": 5, "total": 50, "examples": ["p.3 1.1 SCOPE"]}))
    assert a["accuracy"] < b["accuracy"]                       # a 10% loss on numbers hurts more than 10% on headings
    assert a["accuracy"] == 97.0 and b["accuracy"] == 98.0


def test_threshold_is_applied_later_and_changes_without_a_rerun():
    c = S.classify(_pdf_report(chars={"recall": 0.985, "pages_below_99_5": [[0.9, 7, 40]], "ok": False}))
    assert c["accuracy"] == 99.4
    assert S.decide(c["accuracy"], c["number_diffs"], 99) == "ok"
    assert S.decide(c["accuracy"], c["number_diffs"], 99.5) == "below"


def test_number_guard_keeps_a_file_below_even_when_the_percentage_is_high():
    c = S.classify(_pdf_report(numbers={"recall": 0.9995, "pages_with_missing": [[59, ["0133"]]], "ok": False}))
    assert c["accuracy"] >= 99 and c["number_diffs"] == 1
    assert S.decide(c["accuracy"], c["number_diffs"], 99, number_guard=True) == "below"
    assert S.decide(c["accuracy"], c["number_diffs"], 99, number_guard=False) == "ok"


def test_whole_missing_pages_cost_more_than_a_missing_letter():
    c = S.classify(_pdf_report(pages={"ok": False, "missing": [4, 5]}))
    assert c["parts"]["text"] == 0.98


def test_checks_that_do_not_apply_do_not_punish_the_file():
    rep = _pdf_report()["report"]
    rep["headings"] = {"ok": True, "unmatched": 0}              # no total: not applicable
    rep["tables"] = {"ok": True, "cells": 0, "mismatches": 0}   # no tables
    c = S.classify({"verdict": "PASS", "report": rep})
    assert c["parts"]["headings"] is None and c["parts"]["tables"] is None and c["accuracy"] == 100.0


def test_scanned_file_scores_by_how_closely_the_two_engines_agree():
    rep = {"route": "ocr", "pages": [{"page": i, "status": "ok" if i != 3 else "review", "agreement": 1.0 if i != 3 else 0.0}
                                      for i in range(1, 11)],
           "review_pages": [3], "source_unchanged": {"ok": True}}
    c = S.classify({"verdict": "REVIEW", "report": rep})
    assert c["outcome"] == "result" and c["accuracy"] == 90.0 and c["basis"] == "ocr_agreement"
    assert c["findings"] == [{"kind": "text", "page": 3, "detail": "the two OCR engines disagree"}]


def test_a_file_that_could_not_be_read_has_no_percentage_and_a_reason():
    c = S.classify(None, error="download: requests.exceptions.SSLError: Max retries exceeded")
    assert c["outcome"] == "unprocessable" and c["accuracy"] is None and c["reason"] == "download"
    assert S.classify(None, error="MemoryError")["reason"] == "resources"
    assert S.classify(None, error="No space left on device")["reason"] == "resources"
    assert S.classify(None, error="SOURCE CHANGED during the run")["reason"] == "source_changed"
    assert S.classify(None, error="MuPDF error: format error")["reason"] == "unreadable"
    assert S.classify(None, error="something odd")["reason"] == "other"


def test_protected_and_changed_files_are_not_scored():
    prot = S.classify({"verdict": "SKIP", "triage": {"class": "protected", "reason": "copying is not permitted"}})
    assert prot["outcome"] == "unprocessable" and prot["reason"] == "protected" and prot["accuracy"] is None
    chg = _pdf_report(source_unchanged={"ok": False})
    c = S.classify(chg)
    assert c["outcome"] == "unprocessable" and c["reason"] == "source_changed"


def test_findings_list_the_places_that_cost_accuracy():
    c = S.classify(_pdf_report(
        numbers={"recall": 0.99, "pages_with_missing": [[20, ["4554", "0"]]], "ok": False},
        headings={"ok": False, "unmatched": 1, "total": 50, "examples": ["p.131 APPENDIX G"]},
        unreadable={"lines": 1, "pages": [59]}))
    kinds = {(f["kind"], f["page"]) for f in c["findings"]}
    assert {("numbers", 20), ("headings", 131), ("formula", 59)} <= kinds
    assert c["number_diffs"] == 1 and c["diffs"] == 3      # a flagged formula is listed but is not a number difference
