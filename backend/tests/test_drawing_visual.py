"""Drawings (F-12) and the sampled visual cross-check (spec 6.4)."""
import os

import pymupdf
import pytest

from app.distill import ocr as O
from app.distill import office
from app.distill import run as R
from app.distill.drawing import parse_title_block


def out_dirs(tmp_path):
    out, cache = tmp_path / "out", tmp_path / "cache"
    out.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    return str(out), str(cache)


# ------------------------------------------------------------------ drawings
def test_title_block_fields_are_parsed():
    tb = parse_title_block(["PROJECT: Riverside Apartments", "TITLE: Ground floor plan", "DWG NO: A-101",
                            "REV: C", "SCALE: 1:100 @ A1", "DATE: 12/03/2025"])
    assert tb == {"drawing_number": "A-101", "revision": "C", "scale": "1:100 @ A1", "date": "12/03/2025",
                  "project": "Riverside Apartments", "title": "Ground floor plan"}


def a1_drawing(path, with_block=True):
    doc = pymupdf.open()
    pg = doc.new_page(width=2384, height=1684)               # A1 landscape
    for i in range(400):                                      # vector linework
        pg.draw_line((50 + i * 5, 50), (50 + i * 5, 1200))
    pg.insert_text((200, 300), "Fire door FD60 to stair", fontsize=14)
    pg.insert_text((200, 340), "Ceiling height 2700", fontsize=14)
    if with_block:
        for k, t in enumerate(["PROJECT: Riverside Apartments", "TITLE: Ground floor plan", "DWG NO: A-101",
                               "REV: C", "SCALE: 1:100", "DATE: 12/03/2025"]):
            pg.insert_text((1700, 1350 + k * 40), t, fontsize=16)
    doc.save(path)
    return path


def test_pdf_drawing_route(tmp_path):
    out, cache = out_dirs(tmp_path)
    r = office.distill_any(a1_drawing(str(tmp_path / "A-101.pdf")), "A-101.pdf", out, "/d", cache, log=lambda *_: None)
    assert r["report"]["route"] == "drawing" and r["verdict"] == "PASS"
    body = open(os.path.join(out, r["out_dir"]), encoding="utf-8").read()
    assert 'drawing_number: "A-101"' in body and 'revision: "C"' in body
    assert "Fire door FD60 to stair" in body and "spatial relationships must be read from the original" in body


def test_drawing_without_title_block_goes_to_review(tmp_path):
    out, cache = out_dirs(tmp_path)
    r = office.distill_any(a1_drawing(str(tmp_path / "Sketch.pdf"), False), "Sketch.pdf", out, "/d", cache, log=lambda *_: None)
    assert r["verdict"] == "REVIEW" and r["out_dir"].startswith("_pending")


def test_dxf_text_and_block_attributes(tmp_path):
    import ezdxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("Smoke detector", dxfattribs={"insert": (10, 10)})
    msp.add_mtext("Slab thickness 200", dxfattribs={"insert": (10, 20)})
    blk = doc.blocks.new("TITLE")
    for tag in ("DWG_NO", "TITLE", "REV"):
        blk.add_attdef(tag, (0, 0))
    ins = msp.add_blockref("TITLE", (100, 0))
    ins.add_auto_attribs({"DWG_NO": "S-201", "TITLE": "Level 2 slab", "REV": "B"})
    p = str(tmp_path / "S-201.dxf")
    doc.saveas(p)
    out, cache = out_dirs(tmp_path)
    r = office.distill_any(p, "S-201.dxf", out, "/d", cache, log=lambda *_: None)
    body = open(os.path.join(out, r["out_dir"]), encoding="utf-8").read()
    assert "Smoke detector" in body and "Slab thickness 200" in body
    assert "DWG_NO: S-201" in body


# ------------------------------------------------------------------ visual cross-check
needs_ocr = pytest.mark.skipif(not O.available_engines(), reason="no OCR engine installed")
LINES = ["The minimum width of a required exit is 1000 mm.", "Sprinklers are required above 25 m.",
         "Table 3 lists fire resistance levels for walls.", "Doors in a fire wall must be self-closing.",
         "Clause D2D13 applies to Class 2 and Class 3 buildings."]


def honest_pdf(path):
    doc = pymupdf.open()
    pg = doc.new_page()
    for k, t in enumerate(LINES * 2):
        pg.insert_text((60, 80 + k * 24), t, fontsize=13)
    doc.save(path)
    return path


def lying_pdf(path):
    """Printed text is an image; the hidden text layer says something else (a wrong text layer)."""
    src = pymupdf.open(honest_pdf(path + ".src.pdf"))
    pix = src[0].get_pixmap(dpi=150)
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_image(pg.rect, pixmap=pix)
    for k in range(10):
        pg.insert_text((60, 80 + k * 24), "Qzx vbnm wrtp lkjh gfds 9876 zzzz qqqq xxxx", fontsize=13, render_mode=3)
    doc.save(path)
    return path


@needs_ocr
def test_visual_check_passes_a_true_text_layer(tmp_path):
    v = R.visual_check(honest_pdf(str(tmp_path / "ok.pdf")), 1, log=lambda *_: None, samples=1)
    assert v["ok"], v


@needs_ocr
def test_visual_check_catches_a_wrong_text_layer(tmp_path):
    v = R.visual_check(lying_pdf(str(tmp_path / "bad.pdf")), 1, log=lambda *_: None, samples=1)
    assert not v["ok"] and v["mismatched_pages"] == [1]


def test_visual_check_can_be_disabled():
    assert R.visual_check("unused.pdf", 3, samples=0)["skipped"] == "disabled"
