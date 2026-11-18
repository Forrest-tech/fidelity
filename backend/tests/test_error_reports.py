"""F-25: staff wrong-answer reports become regression entries; re-running adds nothing twice."""
import json

import collect_error_reports as C

REPORT = """```
question: What is the minimum width of a required exit?
answer_given: 900 mm (D2D13)
sources_cited: NCC 2025 Volume One · 045 Part D2, p.229
user_says: it is 1 m and the clause is D2D15
recheck: confirmed wrong
```
"""


def test_reports_are_collected_once(tmp_path):
    rep = tmp_path / "_error_reports"
    rep.mkdir()
    (rep / "2026-11-18_0930_exit width.md").write_text(REPORT, encoding="utf-8")
    (rep / "2026-11-18_0931_empty.md").write_text("nothing useful", encoding="utf-8")
    bank = tmp_path / "regression.json"
    r1 = C.collect(str(rep), str(bank))
    assert r1["added"] == ["2026-11-18_0930_exit width.md"] and r1["skipped_unreadable"] == ["2026-11-18_0931_empty.md"]
    e = json.loads(bank.read_text(encoding="utf-8"))["entries"][0]
    assert e["status"] == "reported" and e["user_says"].startswith("it is 1 m") and e["recheck"] == "confirmed wrong"
    assert C.collect(str(rep), str(bank))["added"] == []               # idempotent


def test_wrapped_lines_are_joined():
    r = C.parse("question: a long\n  question text\nrecheck: unclear\n")
    assert r == {"question": "a long question text", "recheck": "unclear"}
