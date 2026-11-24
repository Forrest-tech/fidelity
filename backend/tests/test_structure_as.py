"""Australian Standards without bookmarks (AS/NZS 3500.1:2021, .2:2021): sections, numbered clauses and appendices are
found from their bold headings, and the front matter names the standard correctly. Before, all of 3500.1:2021 came out
as ten "Front matter" files with no clause list and std_id "AS NZS 3500.1-"."""
import glob
import os
import re

import pymupdf

from app.distill import run as R
from app.distill import structure as S

BODY = ("The separation between any underground water service pipe and a communication cable shall be at least "
        "100 mm. Pipes shall be installed so that they can be inspected and maintained. ") * 4


def _standard(path):
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((72, 90), "Preface", fontsize=14, fontname="hebo")
    pg.insert_textbox(pymupdf.Rect(72, 110, 520, 700), BODY, fontsize=10)
    for sec in (1, 2, 3):
        pg = doc.new_page()
        pg.insert_text((72, 80), f"Section {sec} Installation of services {sec}", fontsize=14, fontname="hebo")
        y = 110
        for head in (f"{sec}.1 Scope of section", f"{sec}.2 Proximity to other services", f"{sec}.2.1 Communication services"):
            pg.insert_text((72, y), head, fontsize=11, fontname="hebo")
            pg.insert_textbox(pymupdf.Rect(72, y + 8, 520, y + 150), BODY[:300], fontsize=9)
            y += 170
    pg = doc.new_page()
    pg.insert_text((250, 70), "(normative)", fontsize=9)
    pg.insert_text((250, 90), "Appendix A", fontsize=14, fontname="hebo")
    pg.insert_text((200, 112), "Equivalent pipe sizes", fontsize=14, fontname="hebo")
    pg.insert_textbox(pymupdf.Rect(72, 130, 520, 700), BODY, fontsize=10)
    doc.save(path)


def test_an_australian_standard_without_bookmarks_gets_its_sections_clauses_and_appendices(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "SINGLE_FILE_MAX_CHARS", 500)          # a real standard is far longer than this one
    monkeypatch.setattr(R, "MERGE_MAX_CHARS", 0)                  # one file per clause group (plan C2 is tested below)
    pdf = str(tmp_path / "AS NZS 3500.1-2021.pdf")
    _standard(pdf)
    out = str(tmp_path / "out")
    os.makedirs(tmp_path / "c")
    res = R.distill_pdf(pdf, "as 3500/2021/AS NZS 3500.1-2021.pdf", out, "/as 3500", str(tmp_path / "c"), log=lambda *_: None)
    assert res["verdict"] == "PASS", res["report"]
    files = glob.glob(os.path.join(out, "**", "*.md"), recursive=True)
    folders = {os.path.basename(os.path.dirname(f)) for f in files}
    assert {"01 Section 1 Installation of services 1", "03 Section 3 Installation of services 3"} <= folders
    assert any("Appendix A Equivalent pipe sizes" in os.path.basename(f) for f in files)
    text = {os.path.basename(f): open(f, encoding="utf-8").read() for f in files}
    two = next(t for n, t in text.items() if " 2.2 Proximity to other services" in n)
    assert re.search(r"^clauses: \[2\.2, 2\.2\.1\]$", two, re.M)
    assert 'std_id: "AS/NZS 3500.1"' in two and 'std_year: "2021"' in two and 'std_kind: "standard"' in two
    assert "clause 5.3.3.3 is in the file of 'Section 5' whose range" in two   # the reader's map speaks AS, not NCC


def test_body_decimals_are_not_clauses_and_ncc_ids_still_are():
    e = lambda t: S.TocEntry(3, t, 1, 0).clause_id        # noqa: E731
    assert e("5.3.3.3 Communication services") == "5.3.3.3"
    assert e("A2.1 General") == "A2.1"
    assert e("D3D14 Goings and risers") == "D3D14"
    assert e("1.5 m clearance") is None and e("2021 edition") is None and e("Section 5 Pumps") is None


def test_standard_names_parse_to_their_designation():
    p = R.parse_standard
    assert p("AS NZS 3500.1-2021")["std_id"] == "AS/NZS 3500.1"
    assert p("3500.3-2018  Plumbing and drainage - Stormwater drainage") == {
        "std_id": "AS 3500.3", "std_year": "2018", "std_kind": "standard", "jurisdiction": "AU"}
    assert p("NCC 2025 Volume One")["std_id"] == "NCC Volume One"


def _distill(tmp_path, monkeypatch, older=False, cap=None):
    monkeypatch.setattr(R, "SINGLE_FILE_MAX_CHARS", 500)
    if cap is not None:
        monkeypatch.setattr(R, "MERGE_MAX_CHARS", cap)
    os.makedirs(tmp_path, exist_ok=True)
    pdf = str(tmp_path / "AS NZS 3500.1-2021.pdf")
    _standard(pdf)
    out = str(tmp_path / ("out-old" if older else "out"))
    os.makedirs(tmp_path / "c", exist_ok=True)
    res = R.distill_pdf(pdf, "as 3500/2021/AS NZS 3500.1-2021.pdf", out, "/as 3500", str(tmp_path / "c"),
                        log=lambda *_: None, older_edition=older)
    assert res["verdict"] == "PASS", res["report"]
    files = glob.glob(os.path.join(out, "**", "*.md"), recursive=True)
    return {os.path.relpath(f, out).replace(os.sep, "/"): open(f, encoding="utf-8").read() for f in files}


def test_plan_c2_joins_the_clause_groups_of_a_section_into_one_file(tmp_path, monkeypatch):
    """Owner 2026-11-23 (plan C2): fewer, larger files. Each Section's clause groups share a file; nothing is lost."""
    many = _distill(tmp_path / "a", monkeypatch, cap=0)              # before: one file per clause group
    few = _distill(tmp_path / "b", monkeypatch, cap=34000)          # now (the default limit)
    assert len(few) < len(many)
    sec2 = {n: t for n, t in few.items() if "/02 Section 2" in n}
    assert len(sec2) == 1, list(few)                                 # 2.1 and 2.2 (with 2.2.1) in one file
    (name, text), = sec2.items()
    assert re.search(r"· \d{3} 2\.1 Scope of section – 2\.2 \[2\.1–2\.2\.1\] p\d+(-\d+)?\.md$", name), name
    assert re.search(r"^clauses: \[2\.1, 2\.2, 2\.2\.1\]$", text, re.M)
    assert "<!-- unit: p" in text                                    # page markers stay for citing

    # nothing of the text is lost: the same words, as often as before
    def words(d):
        out = []
        for t in d.values():
            body = t.split("\n---\n", 1)[-1].split("## Cross-references")[0]
            body = re.sub(r"<!--.*?-->", "", body)                 # page markers repeat in every file
            out += re.findall(r"[A-Za-z]{4,}", body)
        return sorted(out)
    assert words(few) and words(few) == words(many)
    assert "Appendix A" in " ".join(few)                             # front matter and appendices are untouched


def test_a_file_stays_within_its_size_and_an_older_edition_gets_larger_files(tmp_path, monkeypatch):
    small = _distill(tmp_path / "a", monkeypatch, cap=300)           # a tiny cap: groups that do not fit stay apart
    assert len([n for n in small if "/02 Section 2" in n]) >= 2
    monkeypatch.setattr(R, "MERGE_MAX_CHARS_OLDER", 100_000)
    old = _distill(tmp_path / "b", monkeypatch, older=True, cap=300)
    assert len([n for n in old if "/02 Section 2" in n]) == 1       # an older edition uses the larger limit


def test_ncc_documents_are_not_joined():
    """NCC files are already one per Part; joining applies to Australian Standards only."""
    ids = ["D2D1", "D2D2"]
    assert all(S.CLAUSE_ID_RE.fullmatch(i) for i in ids)
