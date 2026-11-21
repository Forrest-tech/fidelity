# -*- coding: utf-8 -*-
"""What the top bar and the settings pages need: notifications (worked out, read per person), defaults for new rooms,
the audit log, changing one's own password, and the room summary the overview shows."""
import os

import pytest

from app import db
from app.api import appsettings as AS
from app.jobs import rooms as R
from tests.test_rooms import PW, _file_event, _load, clean, login, _mk  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def fresh_settings():
    if os.path.exists(AS.PATH):
        os.remove(AS.PATH)
    con = db.trust_rw()
    con.execute("DELETE FROM notification_read")
    con.commit()
    con.close()
    yield
    if os.path.exists(AS.PATH):
        os.remove(AS.PATH)


def _room_with(states):
    room = R.update_room(R.create_room("AS 3500", "t")["id"], {"source": "/as 3500"})
    evs = []
    for i, (acc, outcome) in enumerate(states):
        evs.append(_file_event(f"/f{i}.pdf", acc) if outcome == "result" else
                   {"t": 1.0, "type": "file", "rel": f"/f{i}.pdf", "kind": "pdf", "outcome": "unprocessable", "reason": "download"})
    _load(room["id"], evs)
    return R.get_room(room["id"])


# ------------------------------------------------------------------ notifications
def test_files_to_review_and_files_that_cannot_be_processed_are_notified(login):
    room = _room_with([(99.5, "result"), (97.0, "result"), (96.0, "result"), (None, "unprocessable")])
    c = login("viewer")
    d = c.get("/api/v1/notifications").json()
    by = {n["type"]: n for n in d["items"]}
    assert by["review"]["n"] == 2 and by["review"]["to"] == f"/distill?room={room['id']}&state=below"
    assert by["unprocessable"]["n"] == 1 and by["unprocessable"]["tone"] == "bad"
    assert d["unread"] == 2 and all(not n["read"] for n in d["items"])


def test_reading_is_remembered_per_person_and_a_viewer_may_do_it(login):
    _room_with([(97.0, "result"), (None, "unprocessable")])
    v, r = login("viewer"), login("reviewer")
    key = v.get("/api/v1/notifications").json()["items"][0]["key"]
    after = v.post("/api/v1/notifications/read", json={"keys": [key]})
    assert after.status_code == 200 and after.json()["unread"] == 1
    assert r.get("/api/v1/notifications").json()["unread"] == 2          # someone else's reading does not count
    assert v.post("/api/v1/notifications/read", json={"all": True}).json()["unread"] == 0
    assert v.post("/api/v1/notifications/read", json={"keys": [key]}).json()["unread"] == 0   # twice is harmless
    assert v.post("/api/v1/notifications/read", json={"keys": ["no-such-key"]}).status_code == 200


def test_a_new_problem_is_unread_again(login):
    room = _room_with([(97.0, "result")])
    v = login("viewer")
    v.post("/api/v1/notifications/read", json={"all": True})
    _load(room["id"], [_file_event("/g.pdf", 96.0)], job="j2")
    d = v.get("/api/v1/notifications").json()
    assert d["unread"] == 1 and [n["n"] for n in d["items"] if n["type"] == "review"] == [2]


def test_archived_rooms_are_quiet_and_nothing_means_an_empty_list(login):
    v = login("viewer")
    assert v.get("/api/v1/notifications").json() == {"items": [], "unread": 0}
    room = _room_with([(97.0, "result")])
    con = db.trust_rw()
    con.execute("UPDATE room SET archived=1 WHERE id=?", (room["id"],))
    con.commit()
    con.close()
    assert v.get("/api/v1/notifications").json()["unread"] == 0


def test_notifications_need_a_signed_in_person():
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get("/api/v1/notifications").status_code == 401


# ------------------------------------------------------------------ defaults for new rooms
def test_defaults_are_used_for_new_rooms_and_checked(login):
    a = login("admin")
    assert a.get("/api/v1/app-settings/defaults").json()["threshold"] == 99.0
    for bad in ({"threshold": 49.9}, {"threshold": 100.01}, {"mode": "publish"}):
        assert a.put("/api/v1/app-settings/defaults", json=bad).status_code == 422, bad
    for edge in (50, 100):
        assert a.put("/api/v1/app-settings/defaults", json={"threshold": edge}).json()["threshold"] == edge
    got = a.put("/api/v1/app-settings/defaults", json={"threshold": 98.5, "number_guard": False, "mode": "upload"}).json()
    assert (got["threshold"], got["number_guard"], got["mode"]) == (98.5, False, "upload")
    room = R.create_room(None, "t")
    assert (room["threshold"], room["number_guard"], room["mode"]) == (98.5, False, "upload")


def test_only_administrators_change_the_defaults(login):
    for role in ("viewer", "reviewer"):
        assert login(role).put("/api/v1/app-settings/defaults", json={"threshold": 90}).status_code == 403
    assert login("reviewer").get("/api/v1/app-settings/defaults").status_code == 200


def test_a_broken_settings_file_falls_back_to_the_defaults():
    with open(AS.PATH, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert AS.defaults() == AS.DEFAULTS
    with open(AS.PATH, "w", encoding="utf-8") as f:
        f.write('{"room_defaults": {"threshold": 97, "other": 1}}')
    assert AS.defaults() == {**AS.DEFAULTS, "threshold": 97}


# ------------------------------------------------------------------ audit log
def test_the_audit_log_is_for_administrators_and_lists_newest_first(login):
    room = _room_with([(99.5, "result")])
    con = db.trust_rw()
    con.execute("UPDATE room SET archived_by='a@example.com', archived_at=? WHERE id=?", (db.now(), room["id"]))
    con.commit()
    con.close()
    assert login("reviewer").get("/api/v1/audit").status_code == 403
    ev = login("admin").get("/api/v1/audit").json()["events"]
    assert ev and ev[0]["what"] == "archived" and ev[0]["detail"] == "AS 3500"
    ats = [e["at"] for e in ev]
    assert ats == sorted(ats, reverse=True)


# ------------------------------------------------------------------ one's own password
def test_changing_ones_own_password(login):
    import asyncio
    from fastapi.testclient import TestClient
    from app.main import app
    asyncio.run(_mk("pw-change@example.com", "viewer"))
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", data={"username": "pw-change@example.com", "password": PW}).status_code in (200, 204)
    assert c.post("/api/v1/account/password", json={"current": "wrong-password-x", "new": "another-long-pass"}).status_code == 400
    assert c.post("/api/v1/account/password", json={"current": PW, "new": PW}).status_code == 422
    assert c.post("/api/v1/account/password", json={"current": PW, "new": "short"}).status_code == 422
    assert c.post("/api/v1/account/password", json={"current": PW, "new": "a-brand-new-password"}).json() == {"changed": True}
    fresh = TestClient(app)
    assert fresh.post("/api/v1/auth/login", data={"username": "pw-change@example.com", "password": PW}).status_code == 400
    assert fresh.post("/api/v1/auth/login", data={"username": "pw-change@example.com", "password": "a-brand-new-password"}).status_code in (200, 204)


# ------------------------------------------------------------------ the summary the pages show
def test_room_summary_has_the_average_accuracy_and_no_live_line_when_idle():
    room = R.summary(_room_with([(99.0, "result"), (97.0, "result"), (None, "unprocessable")]))
    assert room["accuracy_avg"] == 98.0
    assert room["job"] is None or "live" not in room["job"]
    assert R.summary(R.create_room(None, "t"))["accuracy_avg"] is None
