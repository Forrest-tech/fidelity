# -*- coding: utf-8 -*-
"""Standards by edition (requirements v2, D-1 to D-5). The names are the real ones from the AS 3500 source folder."""
from app.distill import accept as AC
from app.distill import editions as E


def _id(rel, text=""):
    e = E.identify(rel, text)
    return e["designation"], e["amendment"], e["consolidated"], e["basis"]


def test_identity_comes_from_the_name_in_all_the_ways_people_write_it():
    assert _id("/1990/AS3500.1 - 1990.pdf")[0] == "AS 3500.1:1990"
    assert _id("/1990/AS 3500.3-1990 National Plumbing and Drainage code.pdf")[0] == "AS 3500.3:1990"
    assert _id("/2021/AS NZS 3500.1-2021.pdf")[0] == "AS/NZS 3500.1:2021"
    assert _id("/2021/AS-NZS_3500.0-2021 Printed Converted to Searchable.pdf")[0] == "AS/NZS 3500.0:2021"
    assert _id("/2018/3500.1-2018  Plumbing and drainage - Water services-已解锁.pdf")[0] == "AS 3500.1:2018"
    assert _id("/2018/3500.2-2018_V3  Plumbing and drainage - Sanitary plumbing and drainage.pdf")[0] == "AS 3500.2:2018"


def test_a_name_without_a_year_takes_the_folder_year_and_the_document_beats_both():
    assert _id("/2003/AS 3500.1 Plumbing and drainage - Water services.pdf")[::3] == ("AS 3500.1:2003", "folder")
    # filed under 2018, but its own title page says it is the 2003 edition
    text = "Australian/New Zealand Standard\nPlumbing and drainage\nPart 0: Glossary of terms\nAS/NZS 3500.0:2003\n"
    assert _id("/2018/AS 3500.0 Plumbing and drainage - Glossary of terms.pdf", text)[::3] == ("AS/NZS 3500.0:2003", "document")


def test_amendments_and_consolidated_texts_are_told_apart_from_the_edition():
    d, amd, cons, _ = _id("/2003/AS NZS 3500.1-2003 Amdt 1-2005 Plumbing and drainage - Water services.pdf",
                          "Amendment No. 1 (2005) to AS/NZS 3500.1:2003 Plumbing and drainage")
    assert (d, amd, cons) == ("AS/NZS 3500.1:2003", 1, False)
    assert _id("/2003/AS 3500.2-2003 Plumbing and Drainage - Sanitary Plumbing and Drainage Amended.pdf")[2] is True
    assert _id("/2018/3500.4-2018  Plumbing and drainage - Heated water services (Amendment 1 included).pdf")[2] is True


def test_a_file_that_names_no_standard_has_no_edition():
    assert E.identify("/notes/site visit.pdf")["designation"] == ""
    (r,) = E.registry([{"rel": "/notes/site visit.pdf", "edition": E.identify("/notes/site visit.pdf")}])
    assert r["edition"]["status"] == "" and r["edition"]["copy_of"] is None


def _rows(*specs):
    rows = []
    for rel, outcome, acc, confirmed in specs:
        rows.append({"rel": rel, "outcome": outcome, "accuracy": acc, "confirmed": confirmed,
                     "edition": E.identify(rel)})
    return {r["rel"]: r for r in E.registry(rows)}


def test_the_best_copy_of_an_edition_is_published_and_the_others_point_to_it():
    rows = _rows(("/2021/AS-NZS_3500.4-2021 Printed.pdf", "result", 84.7, 0),
                 ("/2021/AS-NZS_3500.4-2021 Printed Converted to Searchable.pdf", "result", 99.6, 1),
                 ("/2018/3500.2-2018_V3  Sanitary.pdf", "unprocessable", None, 0),
                 ("/2018/3500.2-2018_V3  Sanitary-已解锁.pdf", "result", 99.9, 1))
    best = "/2021/AS-NZS_3500.4-2021 Printed Converted to Searchable.pdf"
    assert rows[best]["edition"]["copy_of"] is None and rows[best]["edition"]["copies"] == 2
    assert rows["/2021/AS-NZS_3500.4-2021 Printed.pdf"]["edition"]["copy_of"] == best
    assert rows["/2018/3500.2-2018_V3  Sanitary.pdf"]["edition"]["copy_of"] == "/2018/3500.2-2018_V3  Sanitary-已解锁.pdf"


def test_older_editions_are_superseded_by_the_latest_one_in_the_library():
    rows = _rows(("/2015/AS 3500.1-2015.pdf", "result", 99.9, 1),
                 ("/2021/AS NZS 3500.1-2021.pdf", "result", 99.9, 1),
                 ("/2003/AS NZS 3500.1-2003 Amdt 2-2010 Water services.pdf", "result", 99.9, 1),
                 ("/2015/AS 3500.2-2015.pdf", "result", 99.9, 1))
    assert rows["/2021/AS NZS 3500.1-2021.pdf"]["edition"]["status"] == "current"
    e = rows["/2015/AS 3500.1-2015.pdf"]["edition"]
    assert (e["status"], e["superseded_by"]) == ("superseded", "AS/NZS 3500.1:2021")
    assert e["designation"] == "AS/NZS 3500.1:2015"           # the joint prefix the 2003 amendment's name shows
    assert rows["/2003/AS NZS 3500.1-2003 Amdt 2-2010 Water services.pdf"]["edition"]["status"] == "superseded"
    assert rows["/2015/AS 3500.2-2015.pdf"]["edition"]["status"] == "current"   # nothing newer of Part 2 here


FM = '---\ndocument: "AS 3500.1-2015"\nedition_status: published\naudit_status: auto_verified\n---\n\n# Scope\n'


def test_a_superseded_edition_is_stamped_and_says_so_at_the_top():
    rows = _rows(("/2015/AS 3500.1-2015.pdf", "result", 99.9, 1), ("/2021/AS NZS 3500.1-2021.pdf", "result", 99.9, 1))
    ed = rows["/2015/AS 3500.1-2015.pdf"]["edition"]
    out = AC.accept_markdown(FM, "a", "t", 99.9, False, ed)
    assert 'edition: "AS 3500.1:2015"' in out and "edition_status: superseded" in out
    assert 'superseded_by: "AS/NZS 3500.1:2021"' in out and out.count("edition_status:") == 1
    assert "Superseded edition." in out and out.endswith("# Scope\n")
    again = AC.accept_markdown(out, "a", "t", 99.9, False, ed)
    assert again == out                                       # stamping twice changes nothing
    now_current = dict(ed, status="current", superseded_by="")
    cur = AC.accept_markdown(out, "a", "t", 99.9, False, now_current)
    assert "Superseded edition." not in cur and "superseded_by" not in cur and "edition_status: published" in cur


def test_without_an_edition_the_front_matter_is_left_as_it_was():
    assert AC.accept_markdown(FM, "a", "t", 99.9, False, None) == AC.accept_markdown(FM, "a", "t", 99.9, False)


GATE_HELD = ('---\ndocument: "AS 3500.3-1990"\nstd_id: "AS 3500.3- National Plumbing and Drainage code"\nstd_year: "1990"\n'
             'audit_status: pending_review\nverified: "FAIL — not trusted"\n---\n\nBody\n')


def test_a_file_the_gate_held_but_a_person_accepted_no_longer_says_fail():
    ed = {"designation": "AS 3500.3:1990", "prefix": "AS", "number": "3500.3", "year": "1990", "amendment": None,
          "status": "current", "superseded_by": ""}
    out = AC.accept_markdown(GATE_HELD, "wang", "2026-11-22", 99.9, False, ed)
    assert "audit_status: human_accepted" in out and "FAIL" not in out
    assert "met the room's threshold" in out and "99.9% accuracy" in out
    assert 'std_id: "AS 3500.3"' in out and out.count("std_id:") == 1 and out.count("std_year:") == 1
    # a file the gate passed keeps its status
    passed = GATE_HELD.replace("pending_review", "auto_verified").replace('"FAIL — not trusted"', '"PASS"')
    assert "audit_status: auto_verified" in AC.accept_markdown(passed, "wang", "t", 99.9, False, ed)
