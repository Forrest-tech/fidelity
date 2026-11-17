import json

from app.distill.ledger import Ledger


def test_unchanged_file_is_skipped_changed_is_not(tmp_path):
    p = str(tmp_path / "ledger.json")
    L = Ledger(p, "/2025")
    assert not L.up_to_date("a.pdf", "h1", "v1")
    L.record("a.pdf", "h1", "v1", "PASS", "/out/a", 3)
    L2 = Ledger(p, "/2025")                       # survives a restart
    assert L2.up_to_date("a.pdf", "h1", "v1")
    assert not L2.up_to_date("a.pdf", "h2", "v1")  # source changed -> re-distill
    assert not L2.up_to_date("a.pdf", "h1", "v2")  # pipeline changed -> re-distill


def test_failed_documents_are_retried(tmp_path):
    L = Ledger(str(tmp_path / "l.json"), "/s")
    L.record("b.pdf", "h", "v1", "FAIL")
    assert not L.up_to_date("b.pdf", "h", "v1")


def test_removed_sources_are_reported_not_deleted(tmp_path):
    L = Ledger(str(tmp_path / "l.json"), "/s")
    L.record("a.pdf", "h", "v1", "PASS")
    L.record("b.pdf", "h", "v1", "PASS")
    assert L.removed(["a.pdf"]) == ["b.pdf"]
    assert "b.pdf" in L.docs                       # entry stays until an administrator confirms


def test_sources_are_independent_and_file_is_valid_json(tmp_path):
    p = str(tmp_path / "l.json")
    Ledger(p, "/a").record("x", "h", "v", "PASS")
    Ledger(p, "/b").record("y", "h", "v", "PASS")
    d = json.load(open(p, encoding="utf-8"))
    assert set(d) == {"/a", "/b"} and "x" in d["/a"] and "y" in d["/b"]
