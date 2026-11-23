"""Requirements v2 Q-5: the same source with the same pipeline gives the same output, byte for byte. Checked on the
real NCC 2025 pages in the fixture (CC BY 4.0) and measured on AS/NZS 3500.3:2021 (identical twice, 2026-11-23)."""
import hashlib
import os

from app.distill import run as R

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ncc2025_v3_pages.pdf")


def _digest(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def test_distilling_the_same_source_twice_gives_identical_files(tmp_path):
    runs = []
    for k in (1, 2):
        cache = tmp_path / f"cache{k}"            # nothing reused between the two runs
        cache.mkdir()
        out = tmp_path / f"out{k}"
        R.distill_pdf(FIXTURE, "2025/ncc2025_v3_pages.pdf", str(out), "/2025", str(cache), log=lambda *_: None)
        runs.append(_digest(out))
    assert runs[0] and runs[0] == runs[1]
