# -*- coding: utf-8 -*-
"""Distillation rooms: file states, thresholds, folder roll-ups, the queue (priority, capacity, output conflicts), the API."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.auth.models import Role, User
from app.auth.schemas import UserCreate
from app.auth.users import UserManager
from app.jobs import capacity, rooms as R
from app.jobs.queue import JobQueue, queue
from app.main import app
from app.migrate import upgrade
from app.orm import SessionLocal
from fastapi_users.db import SQLAlchemyUserDatabase

PW = "correct-horse-battery"
SRC = "/as 3500"
DST = "/Transfer_Md/as 3500"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    db.init_trust()
    con = db.trust_rw()
    for t in ("room_file", "room"):
        con.execute(f"DELETE FROM {t}")
    con.execute("DELETE FROM job")
    con.commit()
    con.close()
    monkeypatch.setenv("FIDELITY_CAPACITY_POINTS", "2")
    yield


def _file_event(rel, acc, **kw):
    ev = {"t": 1.0, "type": "file", "rel": rel, "kind": "pdf", "outcome": "result", "accuracy": acc, "diffs": 0,
          "number_diffs": 0, "parts": {}, "pages": 10}
    ev.update(kw)
    return ev


def _load(room_id, events, job="j1"):
    con = db.trust_rw()
    for ev in events:
        R.apply_event(con, room_id, job, ev)
    con.commit()
    con.close()


def _room(**fields):
    r = R.create_room(None, "t@example.com")
    return R.update_room(r["id"], fields) if fields else r


# ------------------------------------------------------------------ rooms
def test_rooms_get_default_names_and_can_be_renamed():
    a, b = R.create_room(None, "t"), R.create_room(None, "t")
    assert (a["name"], b["name"]) == ("蒸馏室 1", "蒸馏室 2")
    assert R.update_room(a["id"], {"name": "AS 3500"})["name"] == "AS 3500"
    with pytest.raises(R.RoomError):
        R.update_room(a["id"], {"name": "  "})


def test_locations_and_settings_are_validated():
    r = _room()
    with pytest.raises(R.RoomError):
        R.update_room(r["id"], {"source": "C:/Users/x"})
    with pytest.raises(R.RoomError):
        R.update_room(r["id"], {"threshold": 20})
    with pytest.raises(R.RoomError):
        R.update_room(r["id"], {"mode": "publish"})
    ok = R.update_room(r["id"], {"source": SRC, "dest": DST, "threshold": 98.5, "mode": "upload"})
    assert ok["source"]["kind"] == "dropbox" and ok["threshold"] == 98.5 and ok["mode"] == "upload"
    assert R.update_room(r["id"], {"dest": None})["dest"] is None


def test_running_a_room_needs_its_input_and_for_upload_its_output():
    r = _room()
    with pytest.raises(R.RoomError):
        R.submit_run(r["id"])
    R.update_room(r["id"], {"source": SRC, "mode": "upload"})
    with pytest.raises(R.RoomError):
        R.submit_run(r["id"])
    R.update_room(r["id"], {"mode": "distill"})
    jid = R.submit_run(r["id"])
    assert jid and queue.get(jid)["room_id"] == r["id"]
    with pytest.raises(R.RoomError):                        # one queued or running run per room
        R.submit_run(r["id"])


# ------------------------------------------------------------------ states
def test_state_follows_the_threshold_without_a_rerun():
    r = _room(source=SRC)
    _load(r["id"], [{"t": 1, "type": "listing", "files": [{"rel": "/a.pdf", "size": 1, "kind": "pdf"},
                                                          {"rel": "/b.pdf", "size": 1, "kind": "pdf"},
                                                          {"rel": "/c.pdf", "size": 1, "kind": "pdf"}]},
                    _file_event("/a.pdf", 99.4), _file_event("/b.pdf", 97.0),
                    _file_event("/c.pdf", None, outcome="unprocessable", reason="download")])
    c = R.counts(R.get_room(r["id"]))
    assert (c["ok"], c["below"], c["unprocessable"], c["total"]) == (1, 1, 1, 3)
    assert c["finished"] == 3 and c["rate"] == 100.0
    R.update_room(r["id"], {"threshold": 97})
    c = R.counts(R.get_room(r["id"]))
    assert (c["ok"], c["below"]) == (2, 0)                   # same results, new judgement


def test_number_guard_holds_back_a_file_with_a_number_difference():
    r = _room(source=SRC)
    _load(r["id"], [_file_event("/a.pdf", 99.9, number_diffs=1, diffs=1)])
    assert R.counts(R.get_room(r["id"]))["below"] == 1
    R.update_room(r["id"], {"number_guard": False})
    assert R.counts(R.get_room(r["id"]))["ok"] == 1


def test_pending_processing_and_unchanged_files():
    r = _room(source=SRC)
    _load(r["id"], [{"t": 1, "type": "listing", "files": [{"rel": "/a.pdf", "size": 5, "kind": "pdf"},
                                                          {"rel": "/b.pdf", "size": 5, "kind": "pdf"}]},
                    {"t": 2, "type": "start", "rel": "/a.pdf"}])
    c = R.counts(R.get_room(r["id"]))
    assert (c["pending"], c["processing"]) == (1, 1) and c["finished"] == 0
    _load(r["id"], [_file_event("/a.pdf", 100.0), {"t": 3, "type": "unchanged", "rel": "/b.pdf"}])
    assert R.counts(R.get_room(r["id"]))["ok"] == 1


def test_a_file_removed_from_the_source_before_it_was_distilled_disappears_but_results_stay():
    r = _room(source=SRC)
    _load(r["id"], [{"t": 1, "type": "listing", "files": [{"rel": "/a.pdf", "size": 1, "kind": "pdf"}, {"rel": "/b.pdf", "size": 1, "kind": "pdf"}]},
                    _file_event("/a.pdf", 100.0)])
    _load(r["id"], [{"t": 5, "type": "listing", "files": []}])
    rels = {f["rel"] for f in R.find_files(R.get_room(r["id"]))["files"]}
    assert rels == {"/a.pdf"}


def test_a_scanned_file_makes_later_runs_of_the_room_take_two_points():
    r = _room(source=SRC)
    assert r["points"] == 1
    _load(r["id"], [_file_event("/s.pdf", 80.0, scan=True)])
    assert R.get_room(r["id"])["points"] == 2


def test_event_reader_reads_only_complete_lines_and_continues_where_it_stopped(tmp_path):
    r = _room(source=SRC)
    path = tmp_path / "e.jsonl"
    rd = R.EventReader(r["id"], "j", str(path))
    assert rd.poll() == 0                                    # no file yet
    path.write_text(json.dumps({"t": 1, "type": "listing", "files": [{"rel": "/a.pdf", "kind": "pdf"}]}) + "\n" + '{"t": 2, "type": "fi',
                    encoding="utf-8")
    assert rd.poll() == 1                                    # the half-written second line waits
    with open(path, "a", encoding="utf-8") as f:
        f.write('le", "rel": "/a.pdf", "kind": "pdf", "outcome": "result", "accuracy": 100.0}\n')
    assert rd.poll() == 1
    assert R.counts(R.get_room(r["id"]))["ok"] == 1


# ------------------------------------------------------------------ folder tree
def test_folder_roll_ups_mirror_the_source_structure():
    r = _room(source=SRC)
    files = ["/2003/a.pdf", "/2003/amend/b.pdf", "/2003/amend/c.pdf", "/2018/d.pdf", "/top.pdf"]
    _load(r["id"], [{"t": 1, "type": "listing", "files": [{"rel": f, "size": 1, "kind": "pdf"} for f in files]},
                    _file_event("/2003/a.pdf", 100.0), _file_event("/2003/amend/b.pdf", 90.0),
                    _file_event("/2003/amend/c.pdf", None, outcome="unprocessable", reason="unreadable")])
    room = R.get_room(r["id"])
    top = R.children(room, "")
    assert [f["name"] for f in top["folders"]] == ["2003", "2018"] and [f["name"] for f in top["files"]] == ["top.pdf"]
    y2003 = top["folders"][0]["counts"]
    assert (y2003["total"], y2003["ok"], y2003["below"], y2003["unprocessable"]) == (4 - 1, 1, 1, 1)
    inner = R.children(room, "/2003")
    assert [f["name"] for f in inner["folders"]] == ["amend"] and [f["name"] for f in inner["files"]] == ["a.pdf"]
    only_bad = R.children(room, "", state="below")
    assert [f["name"] for f in only_bad["folders"]] == ["2003"] and only_bad["files"] == []
    found = R.find_files(room, q="amend")
    assert found["total"] == 2


# ------------------------------------------------------------------ queue
def _q(kind="dropbox_sync", **kw):
    return queue.submit(kind, "{}", "queued", **kw)


def test_higher_priority_goes_first_then_oldest():
    q = JobQueue()
    a = _q(points=1, priority=1)
    b = _q(points=1, priority=2)
    c = _q(points=1, priority=1)
    assert [q._claim()["id"], q._claim()["id"]] == [b, a]      # capacity 2: two start, in this order
    assert q._claim() is None                                  # the third waits for a free point
    assert queue.get(c)["status"] == "queued"


def test_capacity_points_hold_jobs_back_and_an_oversized_job_runs_alone():
    q = JobQueue()
    heavy = _q(points=2)
    light = _q(points=1)
    assert q._claim()["id"] == heavy
    assert q._claim() is None                                  # 2 of 2 points in use
    con = db.trust_rw()
    con.execute("UPDATE job SET status='done' WHERE id=?", (heavy,))
    con.commit()
    con.close()
    assert q._claim()["id"] == light
    big = _q(points=5)                                         # bigger than the machine
    assert q._claim() is None                                  # waits while anything runs
    con = db.trust_rw()
    con.execute("UPDATE job SET status='done' WHERE id=?", (light,))
    con.commit()
    con.close()
    assert q._claim()["id"] == big


def test_two_runs_never_write_the_same_output_folder_at_once():
    q = JobQueue()
    a = _q(points=1, dest_key="dropbox:/out")
    b = _q(points=1, dest_key="dropbox:/out")
    c = _q(points=1, dest_key="dropbox:/other")
    assert q._claim()["id"] == a
    assert q._claim()["id"] == c                               # b is skipped, c may go
    assert q._claim() is None and queue.get(b)["status"] == "queued"


def test_jobs_that_do_not_count_against_capacity_still_run():
    q = JobQueue()
    _q(points=2)
    _q(points=2)
    other = _q("parse", points=0)
    claimed = {q._claim()["id"], q._claim()["id"]}
    assert other in claimed


def test_capacity_grows_with_memory():
    assert capacity.auto_points(4 * 1024 ** 3, 4) == 2
    assert capacity.auto_points(32 * 1024 ** 3, 12) == 12
    assert capacity.auto_points(1 * 1024 ** 3, 1) == 1


def test_move_to_front_makes_a_waiting_room_next():
    q = JobQueue()
    r1, r2 = _room(source=SRC), _room(source=SRC)
    _q(points=2)                                               # fills the machine
    q._claim()
    j1, j2 = R.submit_run(r1["id"]), R.submit_run(r2["id"])
    R.move_to_front(r2["id"])
    view = R.queue_view()
    assert [x["job"] for x in view["queued"]] == [j2, j1] and view["queued"][0]["priority"] == 2


# ------------------------------------------------------------------ archive
def test_archive_needs_everything_settled():
    r = _room(source=SRC)
    assert "nothing has been distilled yet" in R.archive_blockers(R.get_room(r["id"]))
    _load(r["id"], [{"t": 1, "type": "listing", "files": [{"rel": "/a.pdf", "size": 1, "kind": "pdf"}, {"rel": "/b.pdf", "size": 1, "kind": "pdf"}]},
                    _file_event("/a.pdf", 100.0), _file_event("/b.pdf", 90.0)])
    with pytest.raises(R.RoomError) as e:
        R.set_archived(r["id"], True, "t")
    assert e.value.status == 409 and "below the threshold" in e.value.message
    R.update_room(r["id"], {"threshold": 85})
    assert R.set_archived(r["id"], True, "t")["archived"] is True
    assert [x["id"] for x in R.list_rooms(archived=True)] == [r["id"]] and R.list_rooms() == []
    assert R.set_archived(r["id"], False, "t")["archived"] is False


# ------------------------------------------------------------------ API
async def _mk(email, role):
    async with SessionLocal() as s:
        try:
            await UserManager(SQLAlchemyUserDatabase(s, User)).create(UserCreate(email=email, password=PW, role=role, is_verified=True))
        except Exception:
            pass


@pytest.fixture()
def login():
    upgrade()
    for r in Role:
        asyncio.run(_mk("room-%s@example.com" % r.value, r))

    def do(role):
        c = TestClient(app)
        assert c.post("/api/v1/auth/login", data={"username": "room-%s@example.com" % role, "password": PW}).status_code in (200, 204)
        return c
    return do


def test_api_create_configure_run_and_browse(login):
    c = login("reviewer")
    room = c.post("/api/v1/rooms", json={}).json()
    rid = room["id"]
    assert room["name"] == "蒸馏室 1" and room["counts"]["total"] == 0
    assert c.patch(f"/api/v1/rooms/{rid}", json={"name": "AS 3500", "source": SRC, "threshold": 98}).json()["name"] == "AS 3500"
    assert c.patch(f"/api/v1/rooms/{rid}", json={"source": "C:/x"}).status_code == 422
    assert c.post(f"/api/v1/rooms/{rid}/run", json={}).status_code == 200
    assert c.post(f"/api/v1/rooms/{rid}/run", json={}).status_code == 409
    q = c.get("/api/v1/queue").json()
    assert q["capacity"] == 2 and len(q["queued"]) + len(q["running"]) == 1
    got = c.get("/api/v1/rooms").json()["rooms"]
    assert got[0]["job"]["status"] == "queued" and got[0]["job"]["position"] == 1
    assert c.get(f"/api/v1/rooms/{rid}/tree").json()["folders"] == []
    assert c.get(f"/api/v1/rooms/{rid}/files?state=nope").status_code == 422
    assert c.post(f"/api/v1/rooms/{rid}/cancel").status_code == 200
    assert c.get(f"/api/v1/rooms/{rid}/archive-check").json()["blockers"]


def test_api_viewer_can_read_but_not_change(login):
    c = login("viewer")
    assert c.get("/api/v1/rooms").status_code == 200
    assert c.post("/api/v1/rooms", json={}).status_code == 403
