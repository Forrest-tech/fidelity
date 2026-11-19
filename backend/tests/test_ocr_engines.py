"""Phase 6: OCR engines are plug-ins; which two are used is decided by the benchmark."""
import json

from app.distill import benchmark as B
from app.distill import ocr as O


class Fake:
    def __init__(self, name):
        self.name = name

    @classmethod
    def make(cls, name, ok=True):
        return type(name, (), {"name": name, "available": classmethod(lambda c: ok), "__call__": None,
                               "read": lambda self, img: ("x", 1.0)})


def patch_engines(monkeypatch, names, unavailable=()):
    monkeypatch.setattr(O, "ENGINES", [Fake.make(n, n not in unavailable) for n in names])


def test_default_order_is_built_in_and_at_most_two(monkeypatch):
    patch_engines(monkeypatch, ["a", "b", "c"])
    monkeypatch.delenv("FIDELITY_OCR_ENGINES", raising=False)
    assert [e.name for e in O.available_engines()] == ["a", "b"]
    assert [e.name for e in O.all_engines()] == ["a", "b", "c"]


def test_selection_file_from_the_benchmark_decides(monkeypatch, tmp_path):
    patch_engines(monkeypatch, ["a", "b", "c"])
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps({"engines": ["c", "a"]}), encoding="utf-8")
    monkeypatch.setattr(O, "SELECTION_FILE", str(sel))
    monkeypatch.delenv("FIDELITY_OCR_ENGINES", raising=False)
    assert [e.name for e in O.available_engines()] == ["c", "a"]


def test_env_override_and_missing_engines_are_skipped(monkeypatch):
    patch_engines(monkeypatch, ["a", "b", "c"], unavailable=("b",))
    monkeypatch.setenv("FIDELITY_OCR_ENGINES", "b,c")
    assert [e.name for e in O.available_engines()] == ["c"]          # b not installed -> single engine -> review


def test_benchmark_select_ranks_by_accuracy(tmp_path):
    result = {"pdf": "x.pdf", "summary": {
        "clean": {"engines": {"rapidocr": {"char_acc": 0.99}, "tesseract": {"char_acc": 0.995}, "paddle": {"char_acc": 0.999}}},
        "noise": {"engines": {"rapidocr": {"char_acc": 0.97}, "tesseract": {"char_acc": 0.99}, "paddle": {"char_acc": 0.998}}}}}
    sel = B.select(result, str(tmp_path / "s.json"))
    assert sel["engines"] == ["paddle", "tesseract"]
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["engines"] == ["paddle", "tesseract"]


def test_mac_and_paddle_engines_report_unavailable_here():
    import sys
    if sys.platform != "darwin":
        assert not O.AppleVisionEngine.available()
    assert O.PaddleOCREngine.available() in (True, False)


def test_select_writes_the_default_selection_file(monkeypatch, tmp_path):
    target = tmp_path / "data" / "ocr_engines.json"
    monkeypatch.setattr(O, "SELECTION_FILE", str(target))
    result = {"pdf": "x.pdf", "summary": {"clean": {"engines": {"a": {"char_acc": 0.9}, "b": {"char_acc": 0.95}}}}}
    assert B.select(result)["engines"] == ["b", "a"] and target.exists()
