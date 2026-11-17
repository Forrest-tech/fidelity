import sys

import pytest
from fastapi import HTTPException

from app.api.ingest import safe_name
from app.sandbox import IsolatedTimeout, run_isolated


@pytest.mark.parametrize("raw,want", [("a.pdf", "a.pdf"), ("../../etc/x.pdf", "x.pdf"),
                                      ("C:\Windows\evil.docx", "evil.docx")])
def test_safe_name_strips_paths(raw, want):
    assert safe_name(raw) == want


@pytest.mark.parametrize("raw", ["", ".hidden.pdf", "run.exe", "x.PS1", "dir/"])
def test_safe_name_rejects(raw):
    with pytest.raises(HTTPException):
        safe_name(raw)


def test_isolated_runs_and_scrubs_env(monkeypatch):
    monkeypatch.setenv("FIDELITY_SECRET", "topsecret")
    rc, out, _ = run_isolated([sys.executable, "-I", "-c", "import os;print(os.environ.get('FIDELITY_SECRET'))"])
    assert rc == 0 and out.strip() == b"None"


def test_isolated_timeout_kills():
    with pytest.raises(IsolatedTimeout):
        run_isolated([sys.executable, "-I", "-c", "import time;time.sleep(30)"], timeout=1)
