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


def test_a_rerun_into_the_same_output_leaves_no_files_from_the_earlier_run(tmp_path, monkeypatch):
    """Seen 2026-11-23: files of an older chapter layout stayed in the output folder and were published next to the
    new ones. A re-run replaces the document's folder as a whole."""
    monkeypatch.setattr(R, "SINGLE_FILE_MAX_CHARS", 100)          # split the fixture into a chapter folder
    out, cache = tmp_path / "out", tmp_path / "cache"
    cache.mkdir()
    R.distill_pdf(FIXTURE, "2025/ncc2025_v3_pages.pdf", str(out), "/2025", str(cache), log=lambda *_: None)
    first = _digest(out)
    docs = {p.split(os.sep)[1] for p in first if os.sep in p and p.count(os.sep) >= 2}
    assert docs, first
    leftover = os.path.join(str(out), "2025", sorted(docs)[0], "old layout · 001 Front matter (part 1 of 10) p1-7.md")
    with open(leftover, "w", encoding="utf-8") as fh:
        fh.write("from an earlier run")
    R.distill_pdf(FIXTURE, "2025/ncc2025_v3_pages.pdf", str(out), "/2025", str(cache), log=lambda *_: None)
    assert not os.path.exists(leftover)
    assert _digest(out) == first
