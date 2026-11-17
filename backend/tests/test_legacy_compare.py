"""Pytest adapter for scripts/unit_tests.py: one case per original check."""
import pytest

import unit_tests as legacy
from legacy_adapter import collect

FUNCS = ["test_normalize", "test_strip_md", "test_salvage", "test_align",
         "test_numbers", "test_coverage_score", "test_count", "test_dup",
         "test_page", "test_perf", "test_concurrent", "test_locate",
         "test_reviewer_registry", "test_msg_headers_preserved"]
CHECKS = collect(legacy, FUNCS)



@pytest.mark.parametrize("ok,detail", [(c[1], c[2]) for c in CHECKS],
                         ids=[c[0] for c in CHECKS])
def test_check(ok, detail):
    assert ok, detail
