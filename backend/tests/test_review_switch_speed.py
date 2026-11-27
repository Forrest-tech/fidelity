# -*- coding: utf-8 -*-
"""2026-11-26 findings on the owner's Mac: a container read one file at a time, a confirmed number difference held a
file back for ever, a new input mixed with the old input's results, and "复核 · 对比" could not show where a
difference is. One test per root cause."""
import json
import os

import pytest

from app import db
from app.jobs import capacity, page_review as PR, rooms as R
from app.ai import review as RV

SRC = "/as 3500"
DST = "/Transfer_Md/as 3500"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    db.init_trust()
    con = db.trust_rw()
    for t in ("room_file", "room", "job"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    monkeypatch.setenv("FIDELITY_CAPACITY_POINTS", "2")
    yield


def _load(room_id, events, job="j1"):
    con = db.trust_rw()
    for ev in events:
        R.apply_event(con, room_id, job, ev)
    con.commit()
    con.close()


def _ev(rel, acc, **kw):
    ev = {"t": 1.0, "type": "file", "rel": rel, "kind": "pdf", "outcome": "result", "accuracy": acc, "diffs": 0,
          "number_diffs": 0, "parts": {}, "pages": 3}
    ev.update(kw)
    return ev


# ------------------------------------------------------------------ 1. capacity inside a container
def test_available_memory_is_memavailable_not_free(tmp_path):
    p = tmp_path / "meminfo"
    p.write_text("MemTotal:       16000000 kB\nMemFree:          300000 kB\nMemAvailable:   12000000 kB\n")
    assert capacity._meminfo("MemAvailable", str(p)) == 12000000 * 1024
    assert capacity._meminfo("Nope", str(p)) is None


def test_a_container_memory_limit_counts(tmp_path):
    (tmp_path / "memory.max").write_text(str(8 * 1024 ** 3))
    (tmp_path / "memory.current").write_text(str(2 * 1024 ** 3))
    assert capacity._cgroup_memory(str(tmp_path)) == (8 * 1024 ** 3, 2 * 1024 ** 3)
    (tmp_path / "memory.max").write_text("max")
    assert capacity._cgroup_memory(str(tmp_path)) == (None, None)


def test_a_mid_size_machine_reads_several_files_at_once(monkeypatch):
    monkeypatch.delenv("FIDELITY_CAPACITY_POINTS", raising=False)
    monkeypatch.setattr(capacity, "auto_points", lambda: 4)
    assert capacity.points(avail=8 * 1024 ** 3) == 4          # 8 GB available: no longer limited to 1
    assert capacity.points(avail=1 * 1024 ** 3) == 1          # really short of memory: one at a time
    m = capacity.machine()
    assert {"cpus", "memory_gb", "arch", "emulated", "points"} <= set(m)


# ------------------------------------------------------------------ 2. a confirmed number place no longer holds a file
def _held_room():
    r = R.create_room(None, "t")
    r = R.update_room(r["id"], {"source": SRC, "threshold": 95})
    found = [{"kind": "numbers", "page": 2, "detail": "missing: 7, 14"}, {"kind": "text", "page": 3, "detail": "x"},
             {"kind": "numbers", "page": 3, "detail": "missing: 2.75"}]
    _load(r["id"], [_ev("/a.pdf", 99.4, number_diffs=2, diffs=3, findings=found)])
    return r


def test_number_places_hold_a_file_until_a_person_confirms_each():
    r = _held_room()
    state = lambda: next(f for f in R._files(r["id"]) if f["rel"] == "/a.pdf")
    assert R.derive_state(state(), R.get_room(r["id"])) == "below"
    RV.mark_known(R.get_room(r["id"]), "/a.pdf", 0, True, "t")
    assert R.derive_state(state(), R.get_room(r["id"])) == "below"           # one of two confirmed
    RV.mark_known(R.get_room(r["id"]), "/a.pdf", 1, True, "t")                # a text place does not count
    assert R.open_numbers(state()) == 1
    RV.mark_known(R.get_room(r["id"]), "/a.pdf", 2, True, "t")
    assert R.open_numbers(state()) == 0
    assert R.derive_state(state(), R.get_room(r["id"])) == "ok"              # 99.4 >= 95, nothing open
    R.update_room(r["id"], {"threshold": 99.5})
    assert R.derive_state(state(), R.get_room(r["id"])) == "below"           # the threshold still decides


def test_a_new_result_with_other_places_forgets_the_old_confirmations():
    r = _held_room()
    for i in (0, 2):
        RV.mark_known(R.get_room(r["id"]), "/a.pdf", i, True, "t")
    _load(r["id"], [_ev("/a.pdf", 99.4, number_diffs=1, findings=[{"kind": "numbers", "page": 1, "detail": "missing: 9"}])], job="j2")
    row = next(f for f in R._files(r["id"]) if f["rel"] == "/a.pdf")
    assert R.open_numbers(row) == 1


# ------------------------------------------------------------------ 3. a new input archives the old input's results
def test_a_new_input_keeps_the_old_results_as_an_archived_room():
    r = R.create_room("Room 1", "t")
    r = R.update_room(r["id"], {"source": SRC, "dest": DST, "threshold": 97})
    _load(r["id"], [_ev("/a.pdf", 99.0), _ev("/b.pdf", 98.0)])
    out = R.switch_source(r["id"], "/AS 5601", "t@example.com")
    new, old = out["room"], out["archived"]
    assert new["id"] != r["id"] and new["name"] == "Room 1" and new["source"]["link"] == "/AS 5601"
    assert new["dest"]["link"] == DST and new["threshold"] == 97 and new["position"] == r["position"]
    assert R._files(new["id"]) == []                                            # the room starts clean
    assert old["archived"] and old["name"] == "Room 1 · as 3500" and len(R._files(old["id"])) == 2
    s = R.summary(R.get_room(old["id"]))
    assert s["source_label"] == "as 3500" and s["accuracy_avg"] == 98.5 and "runs" in s
    assert [x["id"] for x in R.list_rooms()] == [new["id"]]


def test_a_room_without_results_just_changes_its_input():
    r = R.update_room(R.create_room(None, "t")["id"], {"source": SRC})
    out = R.switch_source(r["id"], "/AS 5601", "t")
    assert out["archived"] is None and out["room"]["id"] == r["id"] and out["room"]["source"]["link"] == "/AS 5601"


def test_the_input_cannot_change_during_a_run():
    r = R.update_room(R.create_room(None, "t")["id"], {"source": SRC})
    _load(r["id"], [_ev("/a.pdf", 99.0)])
    con = db.trust_rw()
    con.execute("INSERT INTO job(id,kind,rel,status,progress,message,created_at,updated_at,room_id) "
                "VALUES('jx','dropbox_sync','','running',0,'',0,0,?)", (r["id"],))
    con.commit()
    con.close()
    with pytest.raises(R.RoomError) as e:
        R.switch_source(r["id"], "/AS 5601", "t")
    assert e.value.status == 409


def test_a_shared_sub_folder_link_is_named_after_its_folder():
    link = ("https://www.dropbox.com/scl/fo/dupzzyjrmxqrc9e7g2h4z/AA7YUQUEZ7f9ArfOc2OC7fo/gas%20regulation"
            "?rlkey=64lsf2nvd54gym0ds64ivypw4")
    assert R.source_label({"link": link}) == "gas regulation"
    assert R.source_label({"link": "/a/b/AS 5601", "path": "/a/b/AS 5601"}) == "AS 5601"


# ------------------------------------------------------------------ 4. the page comparison
def test_a_page_of_distilled_text_is_found_by_its_unit_marker():
    text = ("<!-- unit: p0001 | src: p.1 | chars: 5 | flags: - -->\nfirst\n<!-- /unit -->\n"
            "<!-- unit: p0002 | src: p.2 | chars: 5 | flags: - -->\nsecond 7 kPa\n<!-- /unit -->\n"
            "<!-- unit: p0004 | src: p.4 | chars: 5 | flags: - -->\nfourth\n<!-- /unit -->\n")
    assert PR.page_text(text, 2) == "second 7 kPa"
    assert PR.page_text(text, 3) == "second 7 kPa"        # inside the unit that started on page 2
    assert PR.page_text(text, 4) == "fourth"


def test_the_page_view_marks_the_missing_numbers_on_the_source_page(monkeypatch, tmp_path):
    import pymupdf
    r = R.update_room(R.create_room(None, "t")["id"], {"source": SRC})
    pdf = tmp_path / "a.pdf"
    doc = pymupdf.open()
    for body in ("Scope of the standard.", "The test pressure is 7 kPa for 14 minutes."):
        doc.new_page().insert_text((72, 100), body, fontsize=11)
    doc.save(str(pdf))
    doc.close()
    found = [{"kind": "numbers", "page": 2, "detail": "missing: 14"}]
    _load(r["id"], [_ev("/a.pdf", 99.0, number_diffs=1, findings=found, out_dir="a.pdf.md")])
    out = os.path.join(R.S.room_dir(r["id"]), "out", "a.pdf.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("---\ndocument: a\n---\n<!-- unit: p0001 | src: p.1 | chars: 5 | flags: - -->\nScope of the standard.\n"
                "<!-- /unit -->\n<!-- unit: p0002 | src: p.2 | chars: 5 | flags: - -->\nThe test pressure is 7 kPa for "
                "minutes.\n<!-- /unit -->\n")
    monkeypatch.setattr(PR, "source_copy", lambda room, row: str(pdf))
    got = PR.page(r["id"], "/a.pdf", 2)
    assert got["has_source"] and got["pages"] == 2 and "7 kPa for minutes" in got["distilled"]
    assert "14 minutes" in got["source_text"] and got["pages_with_findings"] == [2]
    (it,) = got["items"]
    (v,) = it["values"]
    assert v["value"] == "14" and v["in_result"] is False and len(v["boxes"]) == 1
    x0, y0, x1, y1 = v["boxes"][0]
    assert 0 < x0 < x1 < 1 and 0 < y0 < y1 < 1
    assert PR.image(r["id"], "/a.pdf", 2)[:4] == b"\x89PNG"
    assert PR.page(r["id"], "/a.pdf", 1)["items"] == []
