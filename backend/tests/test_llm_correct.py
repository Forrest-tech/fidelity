"""F-14 layer 4: the local model may only pick a reading an engine (or the glossary) gave; never numbers."""
import json

from app.distill import llm_correct as L
from app.distill import ocr as O


def answer(choice):
    return lambda prompt: json.dumps({"choice": choice})


def test_model_picks_one_engine_reading_and_it_is_logged():
    a, b, log = L.resolve("the point Ioad is set", "the point load is set", ("rapidocr", "tesseract"),
                          ask=answer("load"), known=set())
    assert a == b == "the point load is set"
    assert log == [{"rule": "llm", "engine": "rapidocr", "from": "Ioad", "to": "load", "model": L.MODEL}]


def test_an_invented_value_is_rejected():
    a, b, log = L.resolve("the Ioad here", "the lcad here", ask=answer("road"), known=set())
    assert (a, b) == ("the Ioad here", "the lcad here") and log[0]["rejected"] == "road"


def test_numbers_are_never_decided_by_the_model():
    calls = []
    a, b, log = L.resolve("riser 190 mm", "riser 180 mm", ask=lambda p: calls.append(p) or "{}", known=set())
    assert (a, b, log, calls) == ("riser 190 mm", "riser 180 mm", [], [])


def test_model_down_leaves_the_span_for_review():
    def boom(prompt):
        raise OSError("connection refused")
    a, b, log = L.resolve("the Ioad", "the load", ask=boom, known=set())
    assert (a, b) == ("the Ioad", "the load") and "skipped" in log[0]


def test_a_glossary_word_is_an_allowed_candidate():
    a, b, log = L.resolve("the lcad", "the Ioad", ask=answer("load"), known={"load"})
    assert a == b == "the load"


def test_layer_is_off_unless_configured(monkeypatch):
    monkeypatch.setattr(L, "URL", "")
    assert not L.enabled()

    class E:
        def __init__(self, n, t):
            self.name, self.t = n, t

        def read(self, img):
            return self.t, 0.97
    words = "The design point load is set out in the table below for each floor " * 5
    r = O.ocr_image(None, 1, [E("a", words.replace("load", "Ioad", 1)), E("b", words)])
    assert r.status == "review"                     # without the model the disagreement stays for a person
    monkeypatch.setattr(L, "URL", "http://model")
    monkeypatch.setattr(L, "ask_ollama", lambda prompt, **k: json.dumps({"choice": "load"}))
    r = O.ocr_image(None, 1, [E("a", words.replace("load", "Ioad", 1)), E("b", words)])
    assert r.status == "ok" and any(c["rule"] == "llm" for c in r.corrections)
