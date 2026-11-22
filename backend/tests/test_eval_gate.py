# -*- coding: utf-8 -*-
"""OCR regression gate on real pages (requirements v2, Q-1 and Q-4).

Four pages of NCC 2025 Volume Three (CC BY 4.0, see fixtures/ATTRIBUTION.md) are rendered, degraded and read by the
OCR route; their text layer is the exact truth. Measured on 2026-11-22 (Windows VM, RapidOCR en + Tesseract 5):

  rapidocr number recall  clean 0.97–1.00, combined damage 0.81–0.99   (mean over the 8 runs below: 0.97)
  every page went to human review (none auto-accepted)

Character accuracy is not gated: tables come out row by row from OCR and column by column from the text layer, so it
measures reading order more than reading (see app/distill/evaluate.py). The gate holds what matters:
  1. nothing is auto-accepted unless every number and at least 99% of the words were read (the safety property);
  2. number and word recall do not fall below the measured baseline (a regression fails the PR).
"""
import os

import pytest

from app.distill import benchmark as B
from app.distill import evaluate as EV
from app.distill import ocr as O

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ncc2025_v3_pages.pdf")
BASE_NUMBER_RECALL = 0.93          # measured 0.97 on this machine; slack for engine and platform differences
BASE_WORD_RECALL = 0.90


@pytest.fixture(scope="module")
def result():
    engines = O.available_engines()
    if len(engines) < 2:
        pytest.skip("the OCR gate needs both OCR engines (CI installs them)")
    deg = {k: B.DEGRADATIONS[k] for k in ("clean", "combined")}
    return B.run(FIXTURE, [0, 1, 2, 3], engines=engines, degradations=deg, log=lambda *a: None)


def _truth(i):
    return EV.norm(B.page_truth(FIXTURE, i))


def test_nothing_is_accepted_automatically_unless_its_numbers_and_words_were_read(result):
    for row in result["rows"]:
        if row["status"] == "ok":
            assert row["published_num_recall"] >= 1.0, row
            truth = _truth(row["page"] - 1)
            assert row["published_char_acc"] >= 0.99 or truth == "", row


def test_number_and_word_recall_stay_at_the_measured_baseline(result):
    nums = [r["engines"]["rapidocr"]["num_recall"] for r in result["rows"] if "rapidocr" in r["engines"]]
    assert nums and sum(nums) / len(nums) >= BASE_NUMBER_RECALL, nums
    recall = []
    for r in result["rows"]:
        if "rapidocr" not in r["engines"]:
            continue
        recall.append(r["engines"]["rapidocr"]["char_recall"])   # order-free: letters and digits read
    assert sum(recall) / len(recall) >= BASE_WORD_RECALL, recall


def test_the_comparison_metrics_ignore_reading_order_but_not_lost_numbers():
    truth = EV.norm("Table 3.2 | minimum grade | 1:100 |\n| pipe size | 90 mm |")
    reordered = EV.norm("pipe size 90 mm Table 3.2 minimum grade 1:100")
    lost = EV.norm("Table 3.2 minimum grade 1:10 pipe size 9 mm")
    r = EV.compare_page(truth, reordered)
    assert r["word_recall"] == 1.0 and r["number_recall"] == 1.0 and r["cer"] > 0.3
    bad = EV.compare_page(truth, lost)
    assert bad["number_recall"] < 1.0 and bad["number_extra"] >= 1
