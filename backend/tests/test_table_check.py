"""Table cell check (spec 6.4): a planted table error must be caught."""
from app.distill.pdf_extract import Page, Table
from app.distill.structure import table_grid, table_md
from app.distill.verify import check_tables

ROWS = [["Element", "Rating", "Thickness"],
        ["Wall A", "60/60/60", "90 mm"],
        ["Wall B", "90/90/90", "110 mm"],
        ["Floor", "120/120/120", "150 mm"]]


def page():
    return Page(number=1, label=None, items=[Table(page=1, bbox=(0, 0, 100, 100), rows=[list(r) for r in ROWS])])


def check(md):
    return check_tables([page()], {1: md}, table_grid)


def test_correct_table_passes():
    md, _ = table_md(page().items[0])
    r = check(md)
    assert r["ok"] and r["tables"] == 1 and r["cells"] == 12


def test_swapped_cells_in_a_row_are_caught():
    md, _ = table_md(page().items[0])
    bad = md.replace("| Wall A | 60/60/60 | 90 mm |", "| Wall A | 90 mm | 60/60/60 |")
    r = check(bad)
    assert not r["ok"] and r["mismatches"] == 2


def test_value_moved_to_another_row_is_caught():
    md, _ = table_md(page().items[0])
    bad = md.replace("90/90/90", "TMP").replace("60/60/60", "90/90/90").replace("TMP", "60/60/60")
    assert not check(bad)["ok"]


def test_dropped_row_is_caught():
    md, _ = table_md(page().items[0])
    bad = "\n".join(l for l in md.split("\n") if "Wall B" not in l)
    r = check(bad)
    assert not r["ok"] and "rows" in r["examples"][0]["problem"]


def test_missing_table_is_caught():
    assert not check("no table here")["ok"]


def test_escaped_pipe_in_cell_is_handled():
    rows = [["A", "B"], ["x|y", "2"]]
    pg = Page(number=1, label=None, items=[Table(page=1, bbox=(0, 0, 1, 1), rows=rows)])
    md, _ = table_md(pg.items[0])
    assert check_tables([pg], {1: md}, table_grid)["ok"]
