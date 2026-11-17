"""Output format of the distillation pipeline (spec 6.5, F-6, F-7, F-8)."""
import os
import re

import pymupdf
import pytest

from app.distill import run as R


def _make_pdf(base, pages=6):
    pdf = str(base / "Test Standard 2025.pdf")
    doc = pymupdf.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 90), "Section %d Scope" % i if i % 2 else "Part %d.1 Rules" % i, fontsize=16, fontname="hebo")
        y = 130
        for line in ("The maximum height is 2400 mm and the load is 5.5 kPa.", "Clause %d.%d applies to all buildings." % (i, i)):
            page.insert_text((72, y), line, fontsize=11)
            y += 18
    doc.set_toc([[1, "Section 1 Scope", 1], [1, "Section 3 Scope", 3], [1, "Section 5 Scope", 5]])
    doc.save(pdf)
    return pdf


def _run(base, monkeypatch=None, limit=None):
    pdf = _make_pdf(base)
    out, cache = str(base / "out"), str(base / "cache")
    os.makedirs(out), os.makedirs(cache)
    if limit is not None:
        R.SINGLE_FILE_MAX_CHARS = limit
    try:
        res = R.distill_pdf(pdf, "Test Standard 2025.pdf", out, "/2025", cache, log=lambda *_: None)
    finally:
        R.SINGLE_FILE_MAX_CHARS = 100000
    return res, out


@pytest.fixture(scope="module")
def distilled(tmp_path_factory):
    # a tiny threshold forces the chapter-folder layout
    return _run(tmp_path_factory.mktemp("big"), limit=10)


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("small"))


def test_passes_verification(distilled):
    res, _ = distilled
    assert res["verdict"] == "PASS", res["report"]


def test_unit_markers_replace_page_tags(distilled):
    _, out = distilled
    texts = [open(os.path.join(d, f), encoding="utf-8").read() for d, _, fs in os.walk(out) for f in fs]
    body = "\n".join(texts)
    assert re.search(r"<!-- unit: p0001 \| src: p\.1 \| chars: \d+ \| flags: - -->", body)
    assert body.count("<!-- unit:") == body.count("<!-- /unit -->") >= 6
    assert not re.search(r"^\[p\.\d+\]$", body, re.M)


def test_chapter_files_start_with_document_name(distilled):
    _, out = distilled
    names = [f for _, _, fs in os.walk(out) for f in fs]
    assert names and all(n.startswith("Test Standard 2025 · ") for n in names), names


def test_no_auxiliary_files(distilled):
    _, out = distilled
    names = [f for _, _, fs in os.walk(out) for f in fs]
    assert not [n for n in names if n.startswith("_") or "README" in n.upper() or "catalog" in n.lower()]


def test_small_document_is_a_single_file(small):
    res, out = small
    assert res["verdict"] == "PASS" and res["single_file"]
    assert res["out_dir"] == "Test Standard 2025.pdf.md"
    assert [f for _, _, fs in os.walk(out) for f in fs] == ["Test Standard 2025.pdf.md"]
    body = open(os.path.join(out, res["out_dir"]), encoding="utf-8").read()
    assert body.count("<!-- unit:") == 6


def test_front_matter_has_library_and_new_keys(small):
    res, out = small
    fm = open(os.path.join(out, res["out_dir"]), encoding="utf-8").read().split("---")[1]
    for key in ("format_version: 2", "edition_status: published", "std_year: \"2025\"", "source_filename:",
                "source_relative_path:", "source_file_hash:", "audit_status: auto_verified", "units: 6",
                "languages: [en]", "jurisdiction:"):
        assert key in fm, key


def test_unreadable_marker_is_the_full_text_the_verifier_strips():
    """Regression: a second, shorter UNREADABLE_MARK once shadowed the real one, so verification
    counted the marker as extra text and every document with formulas failed."""
    from app.distill import structure as S
    from app.distill import verify as V
    assert S.UNREADABLE_MARK.endswith("check source page]")
    assert any(rx.search(S.UNREADABLE_MARK) for rx in V._INJECTED)


def test_small_diagonal_watermark_is_not_content(tmp_path):
    pdf = str(tmp_path / "Marked Standard 2025.pdf")
    doc = pymupdf.open()
    for i in range(1, 5):
        pg = doc.new_page()
        pg.insert_text((72, 90), "Section %d Scope" % i, fontsize=16, fontname="hebo")
        pg.insert_text((72, 130), "The maximum height is 2400 mm.", fontsize=11)
        pt = pymupdf.Point(150, 600)
        pg.insert_text(pt, "PUBLIC COMMENT DRAFT", fontsize=30, morph=(pt, pymupdf.Matrix(45)), color=(0.8, 0.8, 0.8))
    doc.set_toc([[1, "Section 1 Scope", 1]])
    doc.save(pdf)
    out, cache = str(tmp_path / "out"), str(tmp_path / "cache")
    os.makedirs(out), os.makedirs(cache)
    res = R.distill_pdf(pdf, "Marked Standard 2025.pdf", out, "/2025", cache, log=lambda *_: None)
    assert res["verdict"] == "PASS", res["report"]
    body = open(os.path.join(out, res["out_dir"]), encoding="utf-8").read()
    assert "2400 mm" in body and "COMMENT" not in body.split("---", 2)[2]
