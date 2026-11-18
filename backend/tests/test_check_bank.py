"""The acceptance bank checker: an expected answer must be on its page in the PDF AND the Markdown."""
import pymupdf

import check_bank as C


def setup(tmp_path, md_text):
    src = tmp_path / "src"
    src.mkdir()
    doc = pymupdf.open()
    for t in ("Cover", "D3D14 maximum riser 190 mm and minimum 115 mm"):
        doc.new_page().insert_text((50, 72), t, fontsize=11)
    doc.save(src / "Vol.pdf")
    lib = tmp_path / "lib" / "Vol"
    lib.mkdir(parents=True)
    (lib / "Vol · 01 Part D3 [D3D14] p2.md").write_text(
        '---\nsource_filename: "Vol.pdf"\nclauses: [D3D14]\nedition_status: published\n---\n\n'
        f"<!-- unit: p0002 | src: p.2 | chars: 9 | flags: - -->\n\n{md_text}\n\n<!-- /unit -->\n", encoding="utf-8")
    return C.Sources(str(src)), C.Library(str(tmp_path / "lib"))


def bank(*ground):
    return {"questions": [{"id": 1, "ground": list(ground)}]}


def test_grounded_when_on_both(tmp_path):
    s, lib = setup(tmp_path, "D3D14 maximum riser **190 mm** and minimum 115 mm")
    r = C.check(bank({"doc": "Vol.pdf", "page": 2, "contains": ["190 mm", "115 mm"], "clause": "D3D14"}), s, lib)
    assert r[0]["ok"], r


def test_fails_when_markdown_lost_a_value(tmp_path):
    s, lib = setup(tmp_path, "D3D14 maximum riser 190 mm and minimum")
    r = C.check(bank({"doc": "Vol.pdf", "page": 2, "contains": ["115 mm"]}), s, lib)
    assert not r[0]["ok"] and "published Markdown" in r[0]["problems"][0]


def test_fails_when_expected_answer_is_not_in_the_source(tmp_path):
    s, lib = setup(tmp_path, "anything")
    r = C.check(bank({"doc": "Vol.pdf", "page": 2, "contains": ["200 mm"]}), s, lib)
    assert any("source page" in p for p in r[0]["problems"])


def test_absent_and_draft_grounds(tmp_path):
    s, lib = setup(tmp_path, "x")
    assert C.check(bank({"absent_in_library": "3500.2"}), s, lib)[0]["ok"]
    assert not C.check(bank({"absent_in_library": "Part D3"}), s, lib)[0]["ok"]
    assert not C.check(bank({"doc": "Vol.pdf", "edition_status": "draft"}), s, lib)[0]["ok"]
