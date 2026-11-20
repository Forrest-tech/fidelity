# -*- coding: utf-8 -*-
"""Regression tests for the distillation failures found on the AS 3500 batch:
run-in headings, margin stamps glued to a heading, stacked table values, split decimals,
and pages stored rotated by 90 degrees."""
from collections import Counter

import pymupdf

from app.distill import structure as S
from app.distill.pdf_extract import Page, Row, Span, to_view
from app.distill.verify import _explain_split_decimals


def _row(text, page=1, bold=False, y=0):
    return Row(page, (50, y, 500, y + 10), [Span(text, False, bold, 10)])


def _page(rows, number=1):
    pg = Page(number=number, label=None)
    pg.items = list(rows)
    return pg


def test_run_in_heading_is_split_from_its_body():
    pages = [_page([_row("1.1 SCOPE This Standard sets out materials and products.", y=10),
                    _row("second line of the paragraph", y=22)])]
    entries = [S.TocEntry(1, "1.1 SCOPE", 1, 0)]
    assert S.match_headings(pages, entries) == []
    head = entries[0].row
    assert head.kind == "heading" and head.text == "1.1 SCOPE"
    body = pages[0].items[1]
    assert body.kind == "row" and body.text == "This Standard sets out materials and products."
    assert [it.text for it in pages[0].items][-1] == "second line of the paragraph"


def test_margin_stamp_in_front_of_a_heading_is_split_off():
    stamp = "Accessed by NORMAN DISNEY & YOUNG on 10 Jul 2012 [AVAILABLE SUPERSEDED]"
    pages = [_page([_row(f"{stamp} 1.9 SAFETY The works covered by this Standard shall comply.", y=10)])]
    entries = [S.TocEntry(1, "1.9 SAFETY", 1, 0)]
    assert S.match_headings(pages, entries) == []
    assert entries[0].row.text.endswith("1.9 SAFETY") or entries[0].row.text == "1.9 SAFETY"
    assert "The works covered" in pages[0].items[-1].text
    assert "Accessed by" not in pages[0].items[-1].text


def test_heading_listed_before_its_predecessor_in_reading_order_is_still_found():
    # two-column page: the left column ends with 1.9, the right column starts with 1.4
    pages = [_page([_row("1.9 SAFETY", y=10), _row("1.4 DEFINITIONS", y=20)])]
    entries = [S.TocEntry(2, "1.4 DEFINITIONS", 1, 0), S.TocEntry(2, "1.9 SAFETY", 1, 1)]
    assert S.match_headings(pages, entries) == []


def test_one_letter_typo_in_a_bookmark_does_not_lose_the_heading():
    pages = [_page([_row("2.10.6 Chemical admixtures Chemical admixtures used in concrete shall comply.", y=10)])]
    entries = [S.TocEntry(3, "2.10.6 Chemical admiztures", 1, 0)]
    assert S.match_headings(pages, entries) == []


def test_stacked_values_in_a_cell_are_not_joined_but_a_wrapped_slash_number_is():
    assert S._join_wrapped_numbers("50\n40\n40") == "50\n40\n40"
    assert S._join_wrapped_numbers("1.50\n0.50") == "1.50\n0.50"
    assert S._join_wrapped_numbers("90/90/90\n120/120/120") == "90/90/90\n120/120/120"
    assert S._join_wrapped_numbers("120/120/1\n20") == "120/120/120"


def test_decimal_in_a_typeset_formula_explains_its_scattered_fragments():
    missing = Counter({"4554": 1, "0": 2, "03": 1})
    md = Counter({"0.4554": 1, "0.03": 1})
    assert _explain_split_decimals(missing, md, Counter()) == Counter()
    # fragments that the Markdown does not account for stay missing
    assert _explain_split_decimals(Counter({"7": 1}), md, Counter()) == Counter({"7": 1})


def test_rotated_page_coordinates_are_converted_to_the_displayed_page():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.set_rotation(90)
    x0, y0, x1, y1 = to_view(page, (186, 720, 195, 740))
    assert 0 <= x0 < x1 <= page.rect.width and 0 <= y0 < y1 <= page.rect.height
    assert (round(x0), round(y0)) == (102, 186)
    plain = doc.new_page(width=595, height=842)
    assert to_view(plain, (1, 2, 3, 4)) == (1, 2, 3, 4)
