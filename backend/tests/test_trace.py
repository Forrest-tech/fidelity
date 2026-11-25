"""Requirements v3 R-3: a citation is followed back to library version, library file, page, source PDF (same bytes)
and the PDF's page; a chain that breaks says at which link."""
import json

import pymupdf

from app.acceptance import trace as T
from app.distill.run import dropbox_content_hash

PAGE = ("5.3.3.3 Communication services\nThe separation between any underground water service pipe and a communication "
        "cable shall be at least 100 mm.")
QUOTE = "The separation between any underground water service pipe and a communication cable shall be at least 100 mm."
FILE = "AS NZS 3500.1-2021 · 008 5.1 Scope [5.1–5.17] p2.md"


def _setup(tmp_path, pdf_text=PAGE, published=True):
    src = tmp_path / "src" / "AS NZS 3500.1-2021.pdf"
    src.parent.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), "Cover", fontsize=11)
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 800), pdf_text, fontsize=10)
    doc.save(src)
    lib = tmp_path / "lib" / "AS 3500"
    d = lib / "2021" / "AS NZS 3500.1-2021" / "06 Section 5"
    d.mkdir(parents=True)
    (d / FILE).write_text(
        "---\ndocument: \"AS NZS 3500.1-2021\"\nsource_filename: \"AS NZS 3500.1-2021.pdf\"\n"
        "source_relative_path: \"as 3500/2021/AS NZS 3500.1-2021.pdf\"\n"
        f"source_file_hash: {dropbox_content_hash(str(src))}\nstd_year: \"2021\"\n---\n"
        f"<!-- unit: p0002 | src: p.2 | chars: 99 | flags: - -->\n\n{PAGE}\n", encoding="utf-8")
    pub, rel = tmp_path / "publish", tmp_path / "releases"
    pub.mkdir()
    rel.mkdir()
    files = {"06 Section 5/" + FILE: 100} if published else {}
    (pub / "publish-20261124-063620.json").write_text(json.dumps(
        {"run": "20261124-063620", "docs": {"AS 3500/2021/AS NZS 3500.1-2021": {"files": files}}}), encoding="utf-8")
    (rel / "0001-20261124-063620.json").write_text(json.dumps({"release": 1, "run": "20261124-063620"}), encoding="utf-8")
    return str(lib), {"AS NZS 3500.1-2021.pdf": str(src)}, str(pub), str(rel)


def _answer(page=2, quote=QUOTE, doc="AS/NZS 3500.1:2021"):
    return {"id": 1, "status": "answered", "edition_used": "AS/NZS 3500.1:2021",
            "citations": [{"document": doc, "page": page, "quote": quote}]}


def test_a_good_citation_is_traced_link_by_link(tmp_path):
    lib, src, pub, rel = _setup(tmp_path)
    [r] = T.run([_answer()], lib, src, pub, rel)
    assert r["ok"] and r["version"] == "release 1" and r["library_file"] == FILE
    assert (r["library_page"], r["pdf_page"]) == (2, 2)


def test_the_chain_says_where_it_breaks(tmp_path):
    lib, src, pub, rel = _setup(tmp_path)
    assert T.run([_answer(doc="AS 3500.4:2018")], lib, src, pub, rel)[0]["broken_at"].startswith("library file")
    assert T.run([_answer(quote="shall be at least 300 mm from the gas pipe")], lib, src, pub, rel)[0][
        "broken_at"].startswith("library page")


def test_a_file_no_publish_record_lists_has_no_version(tmp_path):
    lib, src, pub, rel = _setup(tmp_path, published=False)
    assert T.run([_answer()], lib, src, pub, rel)[0]["broken_at"].startswith("library version")


def test_a_library_page_that_differs_from_the_source_page_breaks_the_chain(tmp_path):
    """The library says 100 mm, the PDF (same bytes as recorded) does not: the last link fails."""
    lib, src, pub, rel = _setup(tmp_path)
    other = tmp_path / "other.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page().insert_text((50, 72), "Something else entirely", fontsize=11)
    doc.save(other)
    assert T.run([_answer()], lib, {"AS NZS 3500.1-2021.pdf": str(other)}, pub, rel)[0]["broken_at"].startswith(
        "source PDF: its bytes differ")


def test_designation_is_read_from_what_answers_write():
    assert T.designation("AS NZS 3500.1-2021 · 007 4.1 Scope p28-38.md") == ("3500.1", "2021")
    assert T.designation("AS/NZS 3500.2", "AS/NZS 3500.2:2018 (superseded)") == ("3500.2", "2018")
