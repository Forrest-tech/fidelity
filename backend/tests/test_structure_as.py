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


# ------------------------------------------------------------------ 2026-11-25: two documents held back at review
def test_a_line_drawn_out_of_order_is_read_in_x_order_with_its_scripts_marked():
    """AS 3500.3:2003 Equation 5.4.6 drew "0.233)" right to left and read "C = m (.0013310 I − .0233)"."""
    from app.distill import pdf_extract as P
    raw = {"spans": [{"size": 11, "flags": 0, "font": "Times", "chars": [
        {"c": c, "origin": (x, 371.6)} for c, x in ((")", 328.0), ("3", 322.8), ("3", 317.3), ("2", 311.8), (".", 309.1), ("0", 303.6))]}]}
    assert "".join(s.text for s in P._reordered_spans(raw)) == "0.233)"
    assert not P._drawn_out_of_order({"dir": (0, -1), "spans": [{"text": "Licensed to", "origin": (20, 0), "bbox": (11, 0, 30, 9)}]})
    S = P.Span
    eq = [S("C", False, False, 11, 371.6), S("p", False, False, 7, 374.4), S(" = m (0.0133", False, False, 11, 371.6),
          S("10", False, False, 7, 366.6), S("I", False, False, 11, 371.6), S("60", False, False, 7, 374.4),
          S(" − 0.233) . . . 5.4.6", False, False, 11, 371.6)]
    assert "".join(s.text for s in P._mark_scripts(eq)) == "C<sub>p</sub> = m (0.0133 <sup>10</sup>I<sub>60</sub> − 0.233) . . . 5.4.6"


class _Row:
    def __init__(self, cells, bbox):
        self.cells, self.bbox = cells, bbox


class _Table:
    def __init__(self, rows, bbox):
        self.rows, self.bbox = rows, bbox


class _Page:
    rotation = 0

    def __init__(self, words):
        self.words = words

    def get_text(self, kind):
        return self.words


def _stc_table():
    """AS/NZS 3500.4:2018 Table 6.5.1.2(A) as the grid finder returned it: labels and the last column as None."""
    xs = [(80, 160), (160, 220), (220, 280), (280, 340), (340, 400), (400, 460), (460, 516)]
    cell = lambda j, y: (xs[j][0], y, xs[j][1], y + 12)           # noqa: E731
    trows = [_Row([None, cell(1, 130), None, None, None, None, None], (80, 130, 516, 142)),
             _Row([cell(j, 150) for j in range(7)], (80, 150, 516, 162)),
             _Row([None] + [cell(j, 170) for j in range(1, 6)] + [None], (80, 170, 516, 182))]
    rows = [[None, "Orientation west from true north", None, None, None, None, None],
            ["(Note 3)", "90° to >75°", "75° to >60°", "60° to >45°", ">45° to 60°", ">60° to 75°", ">75° to 90°"],
            [None, "10", "10", "9", "10", "10", None]]
    w = lambda x0, y, t: (x0, y, x0 + 5 * len(t), y + 10, t)      # noqa: E731
    words = [w(165, 131, "Orientation"), w(225, 131, "west"), w(250, 131, "from"), w(272, 131, "true"), w(294, 131, "north"),
             w(345, 131, "Orientation"), w(405, 131, "east"), w(430, 131, "from"), w(452, 131, "true"), w(474, 131, "north"),
             w(85, 171, "1"), w(92, 171, "or"), w(104, 171, "2"), w(111, 171, "bedrooms"),
             w(190, 171, "10"), w(250, 171, "10"), w(310, 171, "9"), w(370, 171, "10"), w(430, 171, "10"), w(485, 171, "10")]
    return _Page(words), _Table(trows, (80, 125, 516, 185)), rows


def test_a_table_that_lost_figures_gets_its_cells_back_from_the_page():
    from app.distill import pdf_extract as P
    page, t, rows = _stc_table()
    out = P._fill_missing(page, t, rows)
    assert out[2] == ["1 or 2 bedrooms", "10", "10", "9", "10", "10", "10"]
    assert out[0][4] == "Orientation east from true north" and out[0][2] is None     # spanning heading stays one


def test_a_table_with_all_its_figures_or_on_a_turned_page_is_left_alone():
    from app.distill import pdf_extract as P
    page, t, rows = _stc_table()
    page.words = [w for w in page.words if w[0] > 120 and not (w[0] > 480 and w[4] == "10")]   # nothing lost: no change
    assert P._fill_missing(page, t, rows) == rows
    page, t, rows = _stc_table()
    page.rotation = 90
    assert P._fill_missing(page, t, rows) == rows
