"""Requirements v3 H-3: 20 published pages a week, drawn so nobody can pick easy ones, compared by a person with the
source page; the error rate is judged by its upper 95 % bound."""
import pymupdf
import pytest

from app import db
from app.ops import spot_check as SC


def _md(i, status="auto_verified"):
    body = "".join(f"<!-- unit: p{p:04d} | src: p.{p} | chars: 300 | flags: - -->\n\nPage {p} of file {i}. "
                   + "The separation shall be at least 100 mm. " * 8 + "\n\n" for p in (3, 4))
    return (f"---\ndocument: \"Doc {i}\"\naudit_status: {status}\nsource_relative_path: \"as 3500/doc{i}.pdf\"\n"
            f"source_file_hash: h{i}\n---\n{body}")


class FakeLibrary:
    def __init__(self, n=40, pdf=None):
        self.texts = {f"/lib/as 3500/doc{i}/f{i}.md": _md(i, "pending_review" if i % 5 == 0 else "auto_verified")
                      for i in range(n)}
        self.reads, self.pdf = 0, pdf

    def files(self):
        return sorted(self.texts)

    def read(self, path):
        self.reads += 1
        return self.texts[path]

    def source(self, rel, want_hash):
        return self.pdf


@pytest.fixture(autouse=True)
def clean():
    db.init_trust()
    con = db.trust_rw()
    con.execute("DELETE FROM spot_check")
    con.commit()
    con.close()


def test_a_week_draws_twenty_reviewable_pages_and_keeps_them():
    lib = FakeLibrary()
    first = SC.draw("2026-W48", lib)
    assert len(first) == SC.SIZE
    assert all(r["page"] in (3, 4) and "100 mm" in r["text"] and r["source"].endswith(".pdf") for r in first)
    assert not any(r["lib_path"].endswith(("f0.md", "f5.md")) for r in first)      # pending review is not "passed"
    again = SC.draw("2026-W48", FakeLibrary())
    assert [r["lib_path"] for r in again] == [r["lib_path"] for r in first]


def test_the_draw_is_fixed_by_the_week_not_by_who_asks():
    SC.draw("2026-W48", FakeLibrary())
    con = db.trust_rw()
    con.execute("DELETE FROM spot_check")
    con.commit()
    con.close()
    a = [r["lib_path"] for r in SC.draw("2026-W48", FakeLibrary())]
    b = [r["lib_path"] for r in SC.draw("2026-W49", FakeLibrary())]
    assert a != b and a == [r["lib_path"] for r in SC.draw("2026-W48", FakeLibrary())]


def test_a_wrong_page_needs_a_note_and_the_summary_uses_the_upper_bound():
    items = SC.draw("2026-W48", FakeLibrary())
    with pytest.raises(SC.SpotError):
        SC.record(items[0]["id"], "wrong", "", "r@example.com")
    with pytest.raises(SC.SpotError):
        SC.record(items[0]["id"], "maybe", "", "r@example.com")
    for it in items:
        SC.record(it["id"], "ok", "", "r@example.com")
    s = SC.summary()
    assert (s["checked"], s["wrong"]) == (20, 0)
    assert s["error_upper95"] > SC.TARGET and not s["meets_target"]      # 20 clean pages cannot show ≤ 1 % yet
    assert s["clean_pages_needed"] > 300
    SC.record(items[1]["id"], "wrong", "Table 5.3 shows 150 mm, the library 100 mm", "r@example.com")
    assert SC.summary()["wrong"] == 1


def test_the_source_page_is_rendered_from_the_pdf(tmp_path):
    p = tmp_path / "doc.pdf"
    d = pymupdf.open()
    for i in range(5):
        d.new_page().insert_text((50, 72), f"page {i + 1}")
    d.save(p)
    lib = FakeLibrary(pdf=str(p))
    it = SC.draw("2026-W48", lib)[0]
    assert SC.page_image(it["id"], lib)[:8] == b"\x89PNG\r\n\x1a\n"


def test_api_reads_for_everyone_signed_in_and_refuses_a_bad_week(monkeypatch):
    from fastapi.testclient import TestClient

    from app.auth.users import current_user
    from app.main import app

    class U:
        email, role = "r@example.com", "reviewer"
    monkeypatch.setattr(SC, "_library", lambda: FakeLibrary())
    app.dependency_overrides[current_user] = lambda: U()
    try:
        c = TestClient(app)
        assert c.get("/api/v1/spot-check?week=48").status_code == 422
        r = c.get("/api/v1/spot-check?week=2026-W48").json()
        assert len(r["items"]) == 20 and r["summary"]["target"] == 0.01
    finally:
        app.dependency_overrides.clear()
