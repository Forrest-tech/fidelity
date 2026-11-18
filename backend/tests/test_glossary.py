"""Glossary correction layer (F-14): learned from verified documents, only chooses an engine's reading."""
import json

from app.distill import glossary as G
from app.distill import ocr as O

VERIFIED = "---\ndocument: \"A\"\naudit_status: auto_verified\n---\n\n<!-- unit: p0001 | src: p.1 | chars: 9 | flags: - -->\n\n"
PENDING = "---\ndocument: \"B\"\naudit_status: pending_review\n---\n\n"


def write_tree(tmp_path):
    (tmp_path / "pub").mkdir()
    (tmp_path / "pub" / "a.pdf.md").write_text(VERIFIED + "The point load, load and (load) on the floor. " * 3, encoding="utf-8")
    (tmp_path / "pub" / "b.pdf.md").write_text(PENDING + "Ioad Ioad Ioad Ioad", encoding="utf-8")
    (tmp_path / "pub" / "_pending").mkdir()
    (tmp_path / "pub" / "_pending" / "c.pdf.md").write_text(VERIFIED + "zzzz zzzz zzzz", encoding="utf-8")
    return str(tmp_path / "pub")


def test_built_only_from_verified_published_documents(tmp_path):
    g = G.build(write_tree(tmp_path))
    assert g["documents"] == 1
    assert g["words"]["load"] == 9 and "Ioad" not in g["words"] and "zzzz" not in g["words"]
    assert "unit:" not in g["words"]                       # markers are not words


def test_resolve_picks_the_known_reading_and_logs_it():
    a, b, log = G.resolve("the point Ioad is 2.7 kN", "the point load is 2.7 kN", {"load", "point"}, ("rapidocr", "tesseract"))
    assert a == b == "the point load is 2.7 kN"
    assert log == [{"rule": "glossary", "engine": "rapidocr", "from": "Ioad", "to": "load"}]


def test_resolve_never_chooses_between_two_known_or_two_unknown_words():
    known = {"load", "lead"}
    assert G.resolve("load", "lead", known)[2] == []        # both known: a person decides
    assert G.resolve("qwop", "qwap", known)[2] == []        # neither known
    assert G.resolve("load", "loading", known)[2] == []     # too different
    assert G.resolve("100", "700", {"100"})[2] == []        # numbers are never guessed
    assert G.resolve("D2D13", "D2D18", {"D2D13"})[2] == []  # nor clause numbers


def test_glossary_lets_a_page_with_one_misread_word_pass(tmp_path, monkeypatch):
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"words": {"load": 9}}), encoding="utf-8")
    monkeypatch.setattr(G, "DEFAULT_PATH", str(path))
    G._cache.clear()

    class E:
        def __init__(self, name, text):
            self.name, self.text = name, text

        def read(self, img):
            return self.text, 0.97

    words = "The design point load is 2.7 kN on the floor " * 30
    r = O.ocr_image(None, 1, [E("rapidocr", words.replace("load", "Ioad", 1)), E("tesseract", words)])
    assert r.status == "ok" and "Ioad" not in r.text
    assert any(c["rule"] == "glossary" for c in r.corrections)
    G._cache.clear()
