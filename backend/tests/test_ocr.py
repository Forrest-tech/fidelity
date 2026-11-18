"""OCR framework: correction rules, two-engine vote, review routing, synthetic benchmark."""
import os

import pymupdf
import pytest

from app.distill import benchmark as B
from app.distill import ocr as O
from app.distill.correct import correct_text
from app.distill.scan import distill_scan


# ------------------------------------------------------------------ correction rules
@pytest.mark.parametrize("src,want", [
    ("wall thickness 2S mm", "wall thickness 25 mm"),
    ("load 1O0 kPa", "load 100 kPa"),
    ("span l50 mm", "span 150 mm"),
    ("value 12l5", "value 1215"),
    ("fire-\nresistance level", "fireresistance level"),
    ("ﬁre rating", "fire rating"),
])
def test_corrections_applied_and_logged(src, want):
    out, log = correct_text(src)
    assert out == want and log


@pytest.mark.parametrize("src", ["3D model", "ISO 9001", "Class 2S building", "Section B1", "Part D2D13", "BS 476", "SO2 levels", "25 mm"])
def test_corrections_leave_ordinary_text_alone(src):
    out, log = correct_text(src)
    assert out == src and log == []


# ------------------------------------------------------------------ voting and routing
class Fake:
    def __init__(self, name, text, conf=0.98):
        self.name, self.text, self.conf = name, text, conf

    def read(self, img):
        return self.text, self.conf


TXT = "Clause 3.2 The minimum width is 1000 mm.\nTable 4 applies."


def test_two_engines_agreeing_and_confident_are_accepted():
    r = O.ocr_image(None, 1, [Fake("a", TXT), Fake("b", TXT)])
    assert r.status == "ok" and r.agreement == 1.0


def test_disagreement_goes_to_review_with_the_spans():
    r = O.ocr_image(None, 1, [Fake("a", TXT), Fake("b", TXT.replace("1000", "1600"))])
    assert r.status == "review" and ("1000", "1600") in r.disagreements


def test_low_confidence_goes_to_review():
    r = O.ocr_image(None, 1, [Fake("a", TXT, 0.7), Fake("b", TXT, 0.99)])
    assert r.status == "review" and any("low confidence" in x for x in r.reasons)


def test_single_engine_is_never_auto_accepted():
    r = O.ocr_image(None, 1, [Fake("a", TXT, 0.99)])
    assert r.status == "review" and any("only one" in x for x in r.reasons)


def test_no_engine_installed_goes_to_review():
    assert O.ocr_image(None, 1, []).status == "review"


# ------------------------------------------------------------------ scan route end to end (fake engines)
def scanned_pdf(path, pages=2):
    doc = pymupdf.open()
    for _ in range(pages):
        pg = doc.new_page()
        pm = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
        pm.set_rect(pm.irect, (240, 240, 240))
        pg.insert_image(pymupdf.Rect(50, 50, 500, 700), pixmap=pm)
    doc.save(path)
    return path


def test_scan_route_publishes_only_when_every_page_is_accepted(tmp_path):
    pdf = scanned_pdf(str(tmp_path / "Scan 2020.pdf"))
    out, cache = tmp_path / "out", tmp_path / "cache"
    out.mkdir(), cache.mkdir()
    good = distill_scan(pdf, "Scan 2020.pdf", str(out), "/s", str(cache), log=lambda *_: None,
                        engines=[Fake("a", TXT), Fake("b", TXT)])
    assert good["verdict"] == "PASS" and not good["out_dir"].startswith("_pending")
    body = open(os.path.join(out, good["out_dir"]), encoding="utf-8").read()
    assert "flags: ocr -->" in body and "audit_status: auto_verified" in body

    bad = distill_scan(pdf, "Scan 2020.pdf", str(out), "/s", str(cache), log=lambda *_: None,
                       engines=[Fake("a", TXT), Fake("b", TXT.replace("Table 4", "Table 9"))])
    assert bad["verdict"] == "REVIEW" and bad["out_dir"].startswith("_pending")
    assert bad["report"]["review_pages"] == [1, 2]
    body = open(os.path.join(out, bad["out_dir"]), encoding="utf-8").read()
    assert "ocr_review" in body and "audit_status: pending_review" in body


def test_images_are_routed_to_ocr(tmp_path):
    from PIL import Image
    from app.distill import office
    p = tmp_path / "photo.png"
    Image.new("L", (200, 100), 255).save(p)
    out, cache = tmp_path / "out", tmp_path / "cache"
    out.mkdir(), cache.mkdir()
    r = office.distill_any(str(p), "photo.png", str(out), "/s", str(cache), log=lambda *_: None)
    assert r["report"]["route"] == "ocr" and r["verdict"] in ("PASS", "REVIEW")


# ------------------------------------------------------------------ benchmark maths
def test_char_accuracy_and_number_recall():
    assert B.char_accuracy("abc def", "abc  def") == 1.0
    assert B.char_accuracy("abcdefghij", "abcdefghiX") == pytest.approx(0.9)
    assert B.number_recall("1000 mm and 25 kPa", "1000 mm and 26 kPa") == 0.5


def test_degradations_change_the_image():
    from PIL import Image
    im = Image.new("L", (100, 100), 255)
    im.paste(0, (30, 30, 70, 70))              # something to blur, rotate and shrink
    for d in ("skew", "blur", "noise", "low_res"):
        p = B.DEGRADATIONS[d]
        out = B.degrade(im, p.get("angle", 0), p.get("blur", 0), p.get("noise", 0), p.get("dpi", 300) / 300)
        assert out.size != im.size or list(out.getdata()) != list(im.getdata())


@pytest.mark.skipif(not O.RapidOCREngine.available(), reason="RapidOCR not installed")
def test_real_engine_reads_a_clean_rendered_page(tmp_path):
    p = str(tmp_path / "t.pdf")
    doc = pymupdf.open()
    pg = doc.new_page(width=400, height=160)
    pg.insert_text((20, 60), "The minimum width is 1000 mm.", fontsize=16)
    pg.insert_text((20, 100), "Clause 3.2 applies to Class 2.", fontsize=16)
    doc.save(p)
    res = B.run(p, [0], engines=[O.RapidOCREngine()], degradations={"clean": {}}, log=lambda *_: None)
    eng = res["rows"][0]["engines"]["rapidocr"]
    assert eng["char_acc"] >= 0.95 and eng["num_recall"] == 1.0


class Boom:
    name = "boom"

    def read(self, img):
        raise RuntimeError("out of memory")


def test_engine_crash_sends_page_to_review_not_the_run_down():
    r = O.ocr_image(None, 1, [Fake("a", TXT), Boom()])
    assert r.status == "review" and any("boom failed" in x for x in r.reasons)


def test_english_model_is_used_only_when_its_hash_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "MODEL_DIR", str(tmp_path))
    assert O.en_rec_model() is None                                  # missing
    (tmp_path / O.EN_REC["file"]).write_bytes(b"x" * O.EN_REC["size"])
    assert O.en_rec_model() is None                                  # right size, wrong content


def test_tesseract_found_in_standard_windows_folder(tmp_path, monkeypatch):
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(O.shutil, "which", lambda _: None)
    monkeypatch.setattr(O, "TESSERACT_WIN", (str(tmp_path / "nope.exe"), str(exe)))
    assert O.tesseract_cmd() == str(exe)


def test_capital_k_after_a_number_becomes_si_kilo():
    out, log = correct_text("point load is 2.7 KN and 3.0 KPa; KN alone and Class K2 stay")
    assert out == "point load is 2.7 kN and 3.0 kPa; KN alone and Class K2 stay"
    assert [l["rule"] for l in log] == ["si_prefix_case", "si_prefix_case"]


def test_spacing_only_differences_are_not_disagreements():
    agree, diffs = O.agreement("above 25 m. and Ioad", "above 25m. and load")
    assert diffs == [("Ioad", "load")] and 0.75 <= agree < 1.0


def test_rapidocr_runs_without_the_angle_classifier():
    if not O.RapidOCREngine.available():
        pytest.skip("RapidOCR not installed")
    from PIL import Image
    O.RapidOCREngine._eng = None
    O.RapidOCREngine().read(Image.new("L", (200, 60), 255))
    assert O.RapidOCREngine._eng.use_angle_cls is False


def test_dollar_misread_in_clause_ids_only():
    out, log = correct_text("see $17C7(2)(a) and $2C26a; fee $250 and $1,200 stay")
    assert out == "see S17C7(2)(a) and S2C26a; fee $250 and $1,200 stay"
    assert [l["rule"] for l in log] == ["clause_id_dollar", "clause_id_dollar"]


def test_typographic_variants_are_not_disagreements():
    agree, diffs = O.agreement('the “vertical” face -- and ’s', 'the "vertical" face — and \'s')
    assert agree == 1.0 and diffs == []
