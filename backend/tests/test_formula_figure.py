"""Phase 6: formulas become reviewed transcriptions (never auto-published); figures get a notice."""
import pymupdf

from app.distill import formula as F
from app.distill.structure import UNREADABLE_MARK


def body(page, *texts):
    return f"<!-- unit: p{page:04d} | src: p.{page} | chars: 10 | flags: - -->\n\n" + "\n\n".join(texts) + "\n\n<!-- /unit -->"


def test_approved_formula_replaces_its_marker_only():
    b = body(161, "HDH " + UNREADABLE_MARK + " FH", "second " + UNREADABLE_MARK) + "\n\n" + body(162, UNREADABLE_MARK)
    appr = {"h1": {"p.161#2": {"latex": "x = 4 + y", "reviewer": "kim", "date": "2026-11-19"}}}
    out, n = F.apply_approved(b, "h1", appr)
    assert n == 1
    assert out.count(UNREADABLE_MARK) == 2                                  # p.161#1 and p.162#1 stay marked
    assert "second $$x = 4 + y$$ *(formula transcribed from the source image; reviewed 2026-11-19 by kim)*" in out
    assert F.apply_approved(b, "other-hash", appr) == (b, 0)                # tied to the exact source file


def test_approve_records_reviewer_and_date(tmp_path):
    p = str(tmp_path / "a.json")
    import datetime as dt
    rec = F.approve("h", 5, 1, " a+b ", "lee", path=p, today=dt.date(2026, 11, 19))
    assert rec == {"latex": "a+b", "reviewer": "lee", "date": "2026-11-19"}
    assert F.load_approvals(p)["h"]["p.5#1"]["reviewer"] == "lee"


def test_candidates_need_two_engines_agreeing(tmp_path):
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((72, 100), "x \x01 y", fontsize=12)                     # control char = unreadable glyph
    path = str(tmp_path / "f.pdf")
    doc.save(path)

    class E:
        def __init__(self, name, out):
            self.name, self.out = name, out

        def read(self, img):
            return self.out
    one = F.recover(path, [E("a", "x+y")], log=lambda *_: None)
    if one["items"]:                                                         # the PDF writer may drop control chars
        assert one["items"][0]["agreed"] is None                            # a single reading is never "agreed"
        two = F.recover(path, [E("a", "x + y"), E("b", "x+y")], log=lambda *_: None)
        assert two["items"][0]["agreed"] == "x + y"
        diff = F.recover(path, [E("a", "x+y"), E("b", "x-y")], log=lambda *_: None)
        assert diff["items"][0]["agreed"] is None
    assert F.recover(path, [], log=lambda *_: None)["skipped"]


def test_figure_pages_get_a_notice(tmp_path):
    from PIL import Image
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "text only")
    p2 = doc.new_page()
    img = tmp_path / "fig.png"
    Image.new("RGB", (400, 300), "gray").save(img)
    p2.insert_image(pymupdf.Rect(72, 72, 472, 372), filename=str(img))
    path = str(tmp_path / "fig.pdf")
    doc.save(path)
    assert F.figure_pages(path) == {2}
    out = F.add_figure_notices(body(1, "a") + "\n\n" + body(2, "b"), {2})
    assert out.count(F.FIGURE_NOTICE) == 1 and out.index(F.FIGURE_NOTICE) > out.index("src: p.2")
    assert F.add_figure_notices(out, {2}).count(F.FIGURE_NOTICE) == 1     # idempotent


def test_verifier_ignores_the_added_text():
    from app.distill.verify import _INJECTED
    t = "a $$x$$ *(formula transcribed from the source image; reviewed 2026-11-19 by kim)* b\n" + F.FIGURE_NOTICE
    for rx in _INJECTED:
        t = rx.sub("", t)
    assert t.split() == ["a", "b"]
