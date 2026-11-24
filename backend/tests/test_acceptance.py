"""Phase F acceptance harness: the grading rules are fixed and re-check citations on the ORIGINAL page; a generated
question is kept only when its figures, quote and clause are on that page; the search steers to the edition asked."""
import pymupdf

from app.acceptance import generate as G
from app.acceptance import grade as GR
from app.acceptance.grade import grade_one, summary, wilson
from app.acceptance.library import Search, Unit
from app.acceptance.text import contains_value, norm

PAGE = ("5.3.3.3 Communication services\nThe separation between any underground water service pipe and a communication "
        "cable shall be at least 100 mm.\n5.3.3.4 Gas services\nA clearance of 600 mm applies where the gas pipe is "
        "not protected.")


def _pdf(tmp_path, name="AS NZS 3500.1-2021.pdf"):
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), "Cover", fontsize=11)
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 800), PAGE, fontsize=10)
    p = tmp_path / name
    doc.save(p)
    return str(p)


def test_values_match_however_they_are_written():
    assert contains_value("at least 100mm from the cable", "100 mm")
    assert contains_value("**1 000** kPa", "1000 kPa")
    assert contains_value("between 15 and 50 kPa", "15 kPa")
    assert not contains_value("at least 100 m", "100 mm")              # the unit matters
    assert not contains_value("at least 150 mm", "100 mm")
    assert norm("DN 65 – DN 80") == "dn65 - dn80"


Q = {"id": 1, "cat": "A", "q": "Under AS/NZS 3500.1:2021, Clause 5.3.3.3, what separation from a communication cable?",
     "expected": "100 mm", "ground": {"doc": "AS NZS 3500.1-2021.pdf", "designation": "AS/NZS 3500.1:2021", "page": 2,
                                      "values": ["100 mm"], "quote": "shall be at least 100 mm", "clause": "5.3.3.3"}}


def _answer(**kw):
    a = {"id": 1, "model": "m", "status": "answered", "answer": "At least 100 mm (Clause 5.3.3.3).", "values": ["100 mm"],
         "edition_used": "AS/NZS 3500.1:2021", "retrieved": [{"source": "AS NZS 3500.1-2021.pdf", "page": 2}],
         "citations": [{"document": "AS/NZS 3500.1:2021", "clause": "5.3.3.3", "page": 2,
                        "quote": "communication cable shall be at least 100 mm"}]}
    return {**a, **kw}


def test_a_right_answer_with_a_citation_on_the_source_page_passes(tmp_path):
    src = {"AS NZS 3500.1-2021.pdf": _pdf(tmp_path)}
    assert grade_one(Q, _answer(), src)["pass"]


def test_a_citation_whose_quote_is_not_on_the_source_page_fails(tmp_path):
    src = {"AS NZS 3500.1-2021.pdf": _pdf(tmp_path)}
    bad = _answer(citations=[{"document": "AS/NZS 3500.1:2021", "clause": "5.3.3.3", "page": 2,
                              "quote": "communication cable shall be at least 300 mm from any drain"}])
    r = grade_one(Q, bad, src)
    assert not r["pass"] and "citation" in r["why"]
    wrong_page = _answer(citations=[{**_answer()["citations"][0], "page": 9}])
    assert not grade_one(Q, wrong_page, src)["pass"]
    wrong_edition = _answer(citations=[{**_answer()["citations"][0], "document": "AS/NZS 3500.1:2018"}])
    assert not grade_one(Q, wrong_edition, src)["pass"]


def test_a_wrong_figure_fails_and_says_whether_search_or_answer_is_to_blame(tmp_path):
    src = {"AS NZS 3500.1-2021.pdf": _pdf(tmp_path)}
    r = grade_one(Q, _answer(answer="At least 150 mm.", values=["150 mm"]), src)
    assert not r["pass"] and r["blame"] == "answer"
    r = grade_one(Q, _answer(answer="Not found", values=[], status="not_found", retrieved=[]), src)
    assert r["blame"].startswith("library search")


def test_traps_pass_only_when_refused_without_a_figure():
    t = {"id": 2, "cat": "F trap: clause does not exist", "q": "Clause 21.4.7?", "expected": "Not found",
         "trap": "not_found", "ground": {}}
    assert grade_one(t, {"id": 2, "status": "not_found", "answer": "Not found in the knowledge base", "values": []}, {})["pass"]
    assert not grade_one(t, {"id": 2, "status": "answered", "answer": "300 mm", "values": ["300 mm"]}, {})["pass"]


def test_a_superseded_edition_must_be_named_as_superseded(tmp_path):
    src = {"AS NZS 3500.1-2021.pdf": _pdf(tmp_path)}
    d = {**Q, "cat": "D superseded edition"}
    assert not grade_one(d, _answer(), src)["pass"]
    assert grade_one(d, _answer(answer="At least 100 mm; note this edition is superseded by the 2021 edition."), src)["pass"]


def test_wilson_interval_needs_about_300_clean_answers_for_one_percent():
    assert wilson(300, 300)[0] > 0.987 and wilson(100, 100)[0] < 0.97
    s = summary([{"pass": True, "cat": "A"}, {"pass": False, "cat": "F trap", "blame": "answer"}])
    assert s["passed"] == 1 and s["traps"] == [0, 1] and s["blame"] == {"answer": 1}


def test_a_generated_question_is_kept_only_when_everything_is_on_the_page(tmp_path):
    p = _pdf(tmp_path)
    good = {"kind": "A", "question": "Under AS/NZS 3500.1:2021, Clause 5.3.3.3, what separation?", "answer": "100 mm",
            "values": ["100 mm"], "quote": "communication cable shall be at least 100 mm", "clause": "5.3.3.3"}
    assert G._check(good, p, 2, "AS/NZS 3500.1:2021", "3500.1") is None
    assert G._check({**good, "values": ["150 mm"]}, p, 2, "", "3500.1") == "a value is not on the page"
    assert G._check({**good, "quote": "cable shall be at least 100 mm from drains always"}, p, 2, "", "3500.1") \
        == "the quote is not on the page"
    assert G._check({**good, "clause": "5.3.9"}, p, 2, "", "3500.1") == "the clause is not printed on the page"
    assert G._check({**good, "kind": "B"}, p, 2, "", "3500.1") == "a topic question names its clause"
    assert G._check({**good, "question": "What separation?"}, p, 2, "", "3500.1") == "the question does not name the standard"


def test_search_steers_to_the_part_and_edition_asked():
    u = lambda doc, year, text: Unit("p", f"{doc} · 038 5.3 Proximity.md", doc, doc + ".pdf", "", year, "published",  # noqa: E731
                                     "5.3", "5.3.3.3", 40, text)
    units = [u("AS NZS 3500.1-2021", "2021", "communication cable separation 100 mm"),
             u("3500.1-2018 Water services", "2018", "communication cable separation 100 mm"),
             u("AS NZS 3500.2-2021", "2021", "communication cable separation drains")]
    s = Search(units)
    assert s.top("AS/NZS 3500.1:2021 communication cable separation", 1)[0].year == "2021"
    assert "2018" in s.top("AS/NZS 3500.1:2018 communication cable separation", 1)[0].document


def test_a_quote_may_join_fragments_but_every_fragment_must_be_on_the_page(tmp_path):
    src = {"AS NZS 3500.1-2021.pdf": _pdf(tmp_path)}
    joined = "The separation between any underground water service pipe ... shall be at least 100 mm."
    assert grade_one(Q, _answer(citations=[{**_answer()["citations"][0], "quote": joined}]), src)["pass"]
    forged = "The separation between any underground water service pipe ... shall be at least 150 mm from drains."
    assert not grade_one(Q, _answer(citations=[{**_answer()["citations"][0], "quote": forged}]), src)["pass"]


def test_quotes_of_the_library_markdown_count_but_forged_table_figures_do_not(tmp_path):
    src = {"AS NZS 3500.1-2021.pdf": _pdf(tmp_path)}
    heading = "### 5.3.3.3 Communication services · p.2\n\nThe separation between any underground water service pipe"
    assert grade_one(Q, _answer(citations=[{**_answer()["citations"][0], "quote": heading}]), src)["pass"]
    row = "The separation between any underground water service pipe ... cable | 100 mm | 600 mm"
    assert grade_one(Q, _answer(citations=[{**_answer()["citations"][0], "quote": row}]), src)["pass"]
    forged = "The separation between any underground water service pipe ... cable | 100 mm | 750 mm"
    assert not grade_one(Q, _answer(citations=[{**_answer()["citations"][0], "quote": forged}]), src)["pass"]


def _table_pdf(tmp_path):
    doc = pymupdf.open()
    pg = doc.new_page()
    # a table as the PDF's text layer gives it: cell by cell, column after column
    pg.insert_textbox(pymupdf.Rect(50, 50, 550, 800),
                      "Table 7.2 Minimum gradients\nKerb channels:\nwithout concrete gutter\n1:150\n"
                      "with concrete gutter or high-class surfacing\n1:200\nPaved surfaces exceeding 200 m2 forming "
                      "part of a catchment area", fontsize=10)
    p = tmp_path / "AS NZS 3500.3-2021.pdf"
    doc.save(str(p))
    return str(p)


def test_a_table_quoted_as_one_line_is_found_on_its_page_but_a_wrong_figure_is_not(tmp_path):
    """Requirements v3 V-2: a quote of table cells joined in another order (or with stray punctuation) is on the page
    when all its figures and nearly all its words are; one figure that is not on the page fails it."""
    src = _table_pdf(tmp_path)
    ok = "Kerb channels: without concrete gutter 1:150 with concrete gutter or high-class surfacing 1:200. ."
    assert GR._quote_on_page(src, 1, ok, "B")
    assert not GR._quote_on_page(src, 1, ok.replace("1:150", "1:100"), "B")      # a figure that is not there
    assert not GR._quote_on_page(src, 1, "Box gutters shall be fastened at 40 mm centres along each edge", "B")


def test_the_exact_page_score_counts_right_figures_cited_on_their_own_page(tmp_path):
    src = _table_pdf(tmp_path)
    q = {"id": 1, "cat": "B", "ground": {"doc": "AS NZS 3500.3-2021.pdf", "designation": "AS/NZS 3500.3:2021",
                                          "page": 1, "values": ["1:150"]}}
    a = {"status": "answered", "answer": "Minimum 1:150.", "values": ["1:150"],
         "citations": [{"document": "AS/NZS 3500.3:2021", "page": 1, "quote": "Kerb channels: without concrete gutter 1:150"}]}
    r = GR.grade_one(q, a, {"AS NZS 3500.3-2021.pdf": src})
    assert r["pass"] and r["page_exact"]
    s = GR.summary([r])
    assert s["page_exact"]["exact"] == 1 and s["page_exact"]["value_right_page_wrong"] == 0
