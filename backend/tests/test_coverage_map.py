"""Coverage map (requirements v3 C-1): NCC's own referenced-documents table against the library's front matter."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import coverage_map as CM  # noqa: E402


def _lib(tmp_path):
    sched = tmp_path / "lib" / "2025" / "NCC 2025 Volume Three" / "13 Schedule 2 Referenced documents"
    sched.mkdir(parents=True)
    (sched / "NCC 2025 Volume Three · 045 Referenced documents p200-217.md").write_text(
        "---\nstd_id: \"NCC Volume Three\"\n---\n"
        "| No. | Date | Title | Volume One | Volume Two | Housing Provisions | Volume Three |\n"
        "|---|---|---|---|---|---|---|\n"
        "| AS/NZS 3500 Part 1 | 2025 | Plumbing and drainage — Water services | N/A | N/A | N/A | B1D3, B1D5 |\n"
        "| AS/NZS 3500 Part 0 | 2021 | Plumbing and drainage — Glossary of terms | A1G4 | A1G4 | N/A | A1G4 |\n"
        "| AS 1056 Part 1 | 1991 | Storage water heaters | N/A | N/A | N/A | B2D2 |\n"
        "| ABCB Housing Provisions | 2025 | not a standard | N/A | N/A | N/A | N/A |\n", encoding="utf-8")
    for std, year, folder in (("AS/NZS 3500.1", "2021", "AS 3500/2021/AS NZS 3500.1-2021"),
                              ("AS/NZS 3500.0", "2021", "AS 3500/2021/AS NZS 3500.0-2021"),
                              ("AS 3500.1", "2018", "AS 3500/2018/3500.1-2018")):
        d = tmp_path / "lib" / folder
        d.mkdir(parents=True)
        (d / "x.md").write_text(f'---\nstd_id: "{std}"\nstd_year: "{year}"\n---\nbody\n', encoding="utf-8")
    return str(tmp_path / "lib")


def test_each_called_up_edition_is_held_in_another_edition_or_missing(tmp_path):
    rows = {r["std"]: r for r in CM.build(_lib(tmp_path))}
    assert set(rows) == {"AS/NZS 3500.1", "AS/NZS 3500.0", "AS 1056.1"}       # non-standards are left out
    assert rows["AS/NZS 3500.1"]["status"] == "other edition" and rows["AS/NZS 3500.1"]["held_years"] == ["2018", "2021"]
    assert rows["AS/NZS 3500.1"]["clauses"] == ["B1D3", "B1D5"]
    assert rows["AS/NZS 3500.0"]["status"] == "held"
    assert rows["AS 1056.1"]["status"] == "not held"


def test_the_report_puts_gaps_first_and_counts_them(tmp_path):
    text = CM.render(CM.build(_lib(tmp_path)), "NCC 2025")
    assert "**3 standards called up** · held in that edition **1** · held only in another edition **1** · not held **1**" in text
    body = text.split("|---|")[-1]
    assert body.index("AS/NZS 3500.1") < body.index("AS 1056.1") < body.index("AS/NZS 3500.0")
