"""Pytest adapter for scripts/test_router.py: one case per original check."""
import pytest

import test_router as legacy
from legacy_adapter import collect

FUNCS = ["test_classify", "test_unsupported_marks_human",
         "test_missing_file_graceful", "test_text_roundtrip",
         "test_cad_marks_confirm", "test_dwg_tmp_cleanup", "test_constants",
         "test_ocr_page_timeout", "test_instance_lock_survives_hooks"]
CHECKS = collect(legacy, FUNCS)


@pytest.mark.parametrize("ok,detail", [(c[1], c[2]) for c in CHECKS],
                         ids=[c[0] for c in CHECKS])
def test_check(ok, detail):
    assert ok, detail
