# -*- coding: utf-8 -*-
"""Licence stamps are read from the vendor's watermark (IR-5, D-6). The lines below are the forms found on the real
AS 3500 files; the licensees are made up."""
from app.distill import licence as L

PERSONAL = ("Licensed to Mr Sam Example on 19 July 2011. 1 user personal user licence only. Storage, distribution or "
            "use on network prohibited (10224823).")
COMMITTEE = "Licensed to Pat Example on 22 Dec 2003. For Committee WS-014 use only"
ACCESSED = "Accessed by EXAMPLE ENGINEERS PTY LTD on 07 Jun 2017 (Document currency not guaranteed when printed)"


def test_each_stamp_form_is_read_with_its_kind():
    (p,) = L.stamps(PERSONAL)
    assert (p["type"], p["who"], p["date"], p["kind"]) == ("licensed", "Mr Sam Example", "19 July 2011", "personal")
    assert p["network_prohibited"] is True
    (c,) = L.stamps(COMMITTEE)
    assert (c["who"], c["terms"], c["kind"]) == ("Pat Example", "For Committee WS-014 use only", "committee")
    (a,) = L.stamps(ACCESSED)
    assert (a["type"], a["who"], a["date"], a["kind"]) == ("accessed", "EXAMPLE ENGINEERS PTY LTD", "07 Jun 2017",
                                                          "organisation")


def test_the_holder_is_the_stamp_on_most_pages():
    text = "\n".join([ACCESSED] * 5 + [COMMITTEE] * 2 + ["plain text"])
    h = L.holder(text)
    assert h["who"] == "EXAMPLE ENGINEERS PTY LTD" and h["count"] == 5
    assert len(L.stamps(text)) == 2


def test_a_document_without_a_stamp_has_no_holder():
    assert L.holder("3.2.1 Pipes shall be 20 mm minimum.") is None
    assert L.stamps("") == []


def test_redaction_removes_the_licensee_and_keeps_the_rest():
    out = L.redact(f"Clause 1.\n{PERSONAL}\n{ACCESSED}\nClause 2.")
    assert "Sam Example" not in out and "EXAMPLE ENGINEERS" not in out
    assert "Licensed to [licensee] on 19 July 2011" in out and "Accessed by [licensee] on 07 Jun 2017" in out
    assert out.startswith("Clause 1.") and out.endswith("Clause 2.")
