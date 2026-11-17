"""Output format of the distillation pipeline (spec 6.5, F-6, F-7, F-8)."""
import os
import re

import pymupdf
import pytest

from app.distill import run as R


@pytest.fixture(scope="module")
def distilled(tmp_path_factory):
    base = tmp_path_factory.mktemp("distill")
    pdf = str(base / "Test Standard 2025.pdf")
    doc = pymupdf.open()
    toc = []
    for i in range(1, 7):
        page = doc.new_page()
        page.insert_text((72, 90), "Section %d Scope" % i if i % 2 else "Part %d.1 Rules" % i, fontsize=16, fontname="hebo")
        y = 130
        for line in ("The maximum height is 2400 mm and the load is 5.5 kPa.", "Clause %d.%d applies to all buildings." % (i, i)):
            page.insert_text((72, y), line, fontsize=11)
            y += 18
    doc.set_toc([[1, "Section 1 Scope", 1], [1, "Section 3 Scope", 3], [1, "Section 5 Scope", 5]])
    doc.save(pdf)
    out = str(base / "out")
    cache = str(base / "cache")
    os.makedirs(out), os.makedirs(cache)
    res = R.distill_pdf(pdf, "Test Standard 2025.pdf", out, "/2025", cache, log=lambda *_: None)
    return res, out


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
