# -*- coding: utf-8 -*-
"""Accepting distilled results into the knowledge base: the front matter says who accepted, the publish step is
atomic and undoable, rooms accept what qualifies, and nothing is sent without a judgement."""
import json

import pytest

from app import db
from app.distill import accept as AC
from app.jobs import rooms as R
from app.jobs.queue import queue

FM = '---\ndocument: "Guide"\naudit_status: pending_review\nverified: "REVIEW - 2 page(s) need a human check"\n---\n\nBody 12 mm.\n'


# ------------------------------------------------------------------ front matter
def test_a_result_that_did_not_pass_says_so_when_a_person_accepts_it():
    out = AC.accept_markdown(FM, "wang@example.com", "2026-11-20T10:00:00+11:00", 97.4, forced=True)
    assert "audit_status: human_accepted" in out and "pending_review" not in out
    assert 'accepted_by: "wang@example.com"' in out and "accuracy: 97.4" in out
    assert "accepted by wang@example.com on 2026-11-20" in out and "did not pass the automatic checks" in out
    assert out.endswith("\nBody 12 mm.\n")


def test_a_result_that_qualified_keeps_its_status_and_only_records_the_acceptance():
    text = FM.replace("pending_review", "auto_verified")
    out = AC.accept_markdown(text, "wang", "t", 99.6, forced=False)
    assert "audit_status: auto_verified" in out and 'accepted_by: "wang"' in out


def test_accepting_twice_does_not_duplicate_lines_and_text_without_front_matter_is_left_alone():
    once = AC.accept_markdown(FM, "a", "t1", 90.0, True)
    twice = AC.accept_markdown(once, "b", "t2", 91.0, True)
    assert twice.count("accepted_by:") == 1 and twice.count("accuracy:") == 1 and 'accepted_by: "b"' in twice
    assert AC.accept_markdown("no front matter\n", "a", "t", 1.0, True) == "no front matter\n"


def test_a_names_quotes_cannot_break_the_front_matter():
    out = AC.accept_markdown(FM, 'x" y', "t", 1.0, True)
    assert 'accepted_by: "x\\" y"' in out


def test_live_key_drops_the_local_pending_marker():
    assert AC.live_key("_pending\\as 3500\\2003\\a.pdf.md") == "as 3500/2003/a.pdf.md"
    assert AC.live_key("as 3500/2003/a.pdf.md") == "as 3500/2003/a.pdf.md"


def test_live_key_spells_the_first_folder_the_way_the_source_does():
    """The output mirrors the source: /Transfer_Md/AS 3500/2015/..., not /Transfer_Md/as 3500/2015/..."""
    assert AC.live_key(r"_pending\as 3500\2015\a.pdf.md", "AS 3500") == "AS 3500/2015/a.pdf.md"
    assert AC.live_key(r"as 3500\2015\AS 3500.1-2015", "AS 3500") == "AS 3500/2015/AS 3500.1-2015"
    assert AC.live_key("AS 3500/2015/x", "AS 3500") == "AS 3500/2015/x"
    assert AC.live_key("other/2015/x", "AS 3500") == "other/2015/x"           # only its own top folder
    assert AC.live_key("as 3500", "AS 3500") == "AS 3500"


# ------------------------------------------------------------------ the publish step of the sync (fake storage)
from tests.test_backends_sync import world, MemStore, FakeSource, FakeDest, _events  # noqa: E402,F401
import app.distill.sync as SY  # noqa: E402


def _distill(run, tmp_path):
    room = str(tmp_path / "room")
    ev = str(tmp_path / "e.jsonl")
    assert run("--dry-run", "--room-dir", room, "--events", ev) == 0
    files = {e["rel"]: e for e in _events(ev) if e["type"] == "file"}
    return room, files


def _plan(tmp_path, files, **extra):
    items = [{"rel": rel, "out_dir": e["out_dir"], "content_hash": e["content_hash"], "accuracy": e["accuracy"],
              "forced": False, "by": "wang@example.com", **extra.get(rel, {})} for rel, e in files.items()]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"items": items}), encoding="utf-8")
    return str(path), items


def test_events_say_where_each_result_is(world, tmp_path):
    _, _, run = world
    _, files = _distill(run, tmp_path)
    g = files["/Guide.md"]
    assert g["out_dir"] and g["content_hash"] and g["verdict"] and g["n_files"] == 1


def test_accepted_results_are_published_with_the_acceptance_recorded_and_can_be_rolled_back(world, tmp_path):
    src, store, run = world
    room, files = _distill(run, tmp_path)
    assert store.files == {}                                          # distilling alone publishes nothing
    plan, _ = _plan(tmp_path, files)
    ev = str(tmp_path / "p.jsonl")
    assert run("--room-dir", room, "--publish-from", plan, "--events", ev) == 0
    live = {k: v for k, v in store.files.items() if k.startswith("/out/")}
    assert set(live) == {"/out/src/Guide.md.md", "/out/src/Note.md.md"}
    assert b'accepted_by: "wang@example.com"' in live["/out/src/Guide.md.md"]
    assert {e["rel"] for e in _events(ev) if e["type"] == "published"} == {"/Guide.md", "/Note.md"}
    # the same --rollback as for a normal run undoes it
    stamp = next(e["run"] for e in _events(ev) if e["type"] == "published")
    run("--rollback", stamp)
    assert not any(k.startswith("/out/") for k in store.files)


def test_a_result_that_did_not_pass_is_marked_human_accepted_when_forced(world, tmp_path):
    _, store, run = world
    room, files = _distill(run, tmp_path)
    plan, _ = _plan(tmp_path, {"/Guide.md": files["/Guide.md"]}, **{"/Guide.md": {"forced": True}})
    assert run("--room-dir", room, "--publish-from", plan) == 0
    assert b"audit_status: human_accepted" in store.files["/out/src/Guide.md.md"]


def test_one_missing_result_does_not_stop_the_others(world, tmp_path):
    import os
    _, store, run = world
    room, files = _distill(run, tmp_path)
    os.remove(os.path.join(room, "out", files["/Guide.md"]["out_dir"]))
    plan, _ = _plan(tmp_path, files)
    ev = str(tmp_path / "p.jsonl")
    with pytest.raises(SystemExit, match=r"1 of 2 document\(s\) could not be sent to the output folder \(the others were\)"):
        run("--room-dir", room, "--publish-from", plan, "--events", ev)     # the job fails and says why, not "done"
    evs = _events(ev)
    assert [e["rel"] for e in evs if e["type"] == "publish_failed"] == ["/Guide.md"]
    assert "/out/src/Note.md.md" in store.files and "/out/src/Guide.md.md" not in store.files


def test_a_result_that_is_a_folder_of_several_files_is_published(world, tmp_path):
    r"""A long document is distilled into a folder of chapters. On Windows its files were read through the long
    (\\?\) path but named against the plain one, which failed every such document: nothing reached the output."""
    import os
    _, store, run = world
    room, files = _distill(run, tmp_path)
    base = os.path.join(room, "out", files["/Guide.md"]["out_dir"])
    os.remove(base)
    os.makedirs(os.path.join(base, "chapters"))
    for name, text in (("README.md", "# Guide\n"), ("chapters/01.md", "Step 1 uses 12 mm board.\n")):
        with open(os.path.join(base, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    plan, _ = _plan(tmp_path, {"/Guide.md": files["/Guide.md"]})
    assert run("--room-dir", room, "--publish-from", plan) == 0
    assert {k for k in store.files if k.startswith("/out/src/Guide.md.md/")} == {
        "/out/src/Guide.md.md/README.md", "/out/src/Guide.md.md/chapters/01.md"}
    assert store.files["/out/src/Guide.md.md/chapters/01.md"].startswith(b"Step 1 uses 12 mm")


def test_publishing_needs_an_output_folder_and_a_room_folder(world, tmp_path, monkeypatch):
    _, _, run = world
    plan = tmp_path / "p.json"
    plan.write_text('{"items": []}', encoding="utf-8")
    with pytest.raises(SystemExit):
        SY.main(["--source-link", "x", "--work", str(tmp_path / "w"), "--publish-from", str(plan), "--dry-run"])


# ------------------------------------------------------------------ rooms: accepting
@pytest.fixture(autouse=True)
def clean(monkeypatch):
    db.init_trust()
    con = db.trust_rw()
    for t in ("room_file", "room", "job"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    monkeypatch.setenv("FIDELITY_CAPACITY_POINTS", "2")


def _file(rel, acc, **kw):
    ev = {"t": 1.0, "type": "file", "rel": rel, "kind": "pdf", "outcome": "result", "accuracy": acc, "diffs": 0, "number_diffs": 0,
          "parts": {}, "pages": 5, "out_dir": "as 3500" + rel + ".md", "content_hash": "h" + rel, "single_file": True,
          "n_files": 1, "verdict": "PASS"}
    ev.update(kw)
    return ev


def _room(**fields):
    r = R.create_room(None, "t")
    base = {"source": "/as 3500", "dest": "/Transfer_Md/as 3500", "threshold": 99}
    base.update(fields)
    room = R.update_room(r["id"], base)
    con = db.trust_rw()
    for ev in (_file("/a.pdf", 99.5), _file("/b.pdf", 97.0), _file("/c.pdf", None, outcome="unprocessable", reason="download")):
        R.apply_event(con, room["id"], "j0", ev)
    con.commit()
    con.close()
    return room


def test_accept_all_that_qualify_queues_one_publish_and_marks_those_files_publishing():
    room = _room()
    out = R.accept(room["id"], "wang", all_ok=True)
    assert out["count"] == 1
    job = queue.get(out["job"])
    p = json.loads(job["rel"])
    assert p["room_id"] == room["id"] and p["dest_link"] == "/Transfer_Md/as 3500" and p["publish_from"].endswith(".json")
    assert job["dest_key"] == "dropbox:/transfer_md/as 3500"
    plan = json.load(open(p["publish_from"], encoding="utf-8"))
    assert [i["rel"] for i in plan["items"]] == ["/a.pdf"] and plan["items"][0]["by"] == "wang" and plan["items"][0]["forced"] is False
    states = {f["rel"]: f["state"] for f in R.find_files(R.get_room(room["id"]))["files"]}
    assert states == {"/a.pdf": "publishing", "/b.pdf": "below", "/c.pdf": "unprocessable"}


def test_a_file_below_the_threshold_needs_a_person_to_force_it():
    room = _room()
    with pytest.raises(R.RoomError) as e:
        R.accept(room["id"], "wang", rels=["/b.pdf"])
    assert e.value.status == 409 and "below the threshold" in e.value.message
    out = R.accept(room["id"], "wang", rels=["/b.pdf"], force=True)
    plan = json.load(open(json.loads(queue.get(out["job"])["rel"])["publish_from"], encoding="utf-8"))
    assert plan["items"][0]["forced"] is True


def test_nothing_without_a_result_can_be_accepted():
    room = _room()
    with pytest.raises(R.RoomError) as e:
        R.accept(room["id"], "wang", rels=["/c.pdf"], force=True)
    assert e.value.status == 409
    with pytest.raises(R.RoomError):
        R.accept(room["id"], "wang", rels=["/nope.pdf"])


def test_accepting_needs_an_output_folder_and_waits_for_a_running_room():
    room = _room(dest=None)
    with pytest.raises(R.RoomError) as e:
        R.accept(room["id"], "wang", all_ok=True)
    assert e.value.status == 422
    room = R.update_room(room["id"], {"dest": "/Transfer_Md"})
    R.accept(room["id"], "wang", all_ok=True)
    with pytest.raises(R.RoomError) as e:                              # a publish is already queued
        R.accept(room["id"], "wang", all_ok=True)
    assert e.value.status == 409


def test_events_from_the_publish_set_the_final_state():
    room = _room()
    R.accept(room["id"], "wang", all_ok=True)
    con = db.trust_rw()
    R.apply_event(con, room["id"], "j1", {"t": 5, "type": "published", "rel": "/a.pdf", "files": 1})
    con.commit()
    con.close()
    assert R.counts(R.get_room(room["id"]))["published"] == 1
    con = db.trust_rw()                                                 # a failed one goes back to what it was
    R.apply_event(con, room["id"], "j1", {"t": 6, "type": "publish_failed", "rel": "/a.pdf", "error": "boom"})
    con.commit()
    con.close()


def test_a_new_result_for_an_accepted_file_needs_accepting_again():
    room = _room()
    R.accept(room["id"], "wang", all_ok=True)
    con = db.trust_rw()
    R.apply_event(con, room["id"], "j1", {"t": 5, "type": "published", "rel": "/a.pdf"})
    R.apply_event(con, room["id"], "j2", _file("/a.pdf", 99.9))        # the source changed and was distilled again
    con.commit()
    con.close()
    st = {f["rel"]: f["state"] for f in R.find_files(R.get_room(room["id"]))["files"]}
    assert st["/a.pdf"] == "ok"


def test_a_room_set_to_upload_accepts_what_qualifies_when_its_run_finishes():
    room = _room(mode="upload")
    job = {"id": "d1", "room_id": room["id"], "rel": json.dumps({"source_link": "/as 3500", "dry_run": True})}
    R.after_run(job)
    q = R.queue_view()
    assert len(q["queued"]) + len(q["running"]) == 1
    # a room that only distills publishes nothing by itself, and a publishing job does not trigger another
    other = _room()
    R.after_run({"id": "d2", "room_id": other["id"], "rel": json.dumps({"dry_run": True})})
    R.after_run({"id": "d3", "room_id": room["id"], "rel": json.dumps({"publish_from": "x.json"})})
    assert len(R.queue_view()["queued"]) + len(R.queue_view()["running"]) == 1


def test_finishing_a_job_runs_the_follow_up_hooks():
    seen = []
    queue.after_done.append(seen.append)
    try:
        jid = queue.submit("dropbox_sync", "{}", "queued")
        queue._update(jid, status="running")
        assert seen == []
        queue._update(jid, status="done")
        assert [j["id"] for j in seen] == [jid]
    finally:
        queue.after_done.remove(seen.append)


def test_results_filed_under_a_lower_case_folder_are_published_under_the_sources_own_spelling(world, tmp_path):
    """Results distilled before the fix sit under "as 3500"; publishing them must still create "AS 3500"."""
    src, store, run = world
    room, files = _distill(run, tmp_path)
    src.name = "SRC"                                         # the source as the person spells it
    plan, _ = _plan(tmp_path, {"/Guide.md": files["/Guide.md"]})
    assert files["/Guide.md"]["out_dir"].replace("\\", "/").split("/")[-2:] == ["src", "Guide.md.md"]
    assert run("--room-dir", room, "--publish-from", plan) == 0
    assert "/out/SRC/Guide.md.md" in store.files and not any(k.startswith("/out/src/") for k in store.files)


def _editions_room():
    r = R.create_room(None, "t")
    room = R.update_room(r["id"], {"source": "/as 3500", "dest": "/Transfer_Md/as 3500", "threshold": 99})
    con = db.trust_rw()
    for ev in (_file("/2015/AS 3500.1-2015.pdf", 99.9), _file("/2021/AS NZS 3500.1-2021.pdf", 99.8),
               _file("/2021/SS/AS-NZS_3500.1-2021 Printed.pdf", 86.2),
               _file("/2018/3500.3-2018 Stormwater.pdf", None, outcome="unprocessable", reason="protected"),
               _file("/2018/3500.3-2018 Stormwater-已解锁.pdf", 99.7)):
        R.apply_event(con, room["id"], "j0", ev)
    con.execute("UPDATE room_file SET confirmed=1, confirmed_by='wang', confirmed_at=1795000000 WHERE rel LIKE '/2015/%'")
    con.commit()
    con.close()
    return room


def test_a_second_copy_of_an_edition_is_skipped_and_the_room_lists_editions():
    room = _editions_room()
    files = {f["rel"]: f for f in R.find_files(R.get_room(room["id"]))["files"]}
    printed = files["/2021/SS/AS-NZS_3500.1-2021 Printed.pdf"]
    assert printed["state"] == "skipped" and printed["covered_by"] == "/2021/AS NZS 3500.1-2021.pdf"
    assert printed["edition"]["designation"] == "AS/NZS 3500.1:2021" and printed["edition"]["status"] == "current"
    assert files["/2018/3500.3-2018 Stormwater.pdf"]["state"] == "skipped"
    old = files["/2015/AS 3500.1-2015.pdf"]
    assert old["state"] == "published" and old["edition"]["superseded_by"] == "AS/NZS 3500.1:2021"
    v = R.editions_view(R.get_room(room["id"]))
    assert (v["standards"], v["extra_copies"], v["superseded"], v["amendments"], v["published_twice"]) == (2, 2, 1, 0, 0)
    # the copy that does not represent its edition is never offered for acceptance
    out = R.accept(room["id"], "wang", all_ok=True)
    plan = json.load(open(json.loads(queue.get(out["job"])["rel"])["publish_from"], encoding="utf-8"))
    assert {i["rel"] for i in plan["items"]} == {"/2021/AS NZS 3500.1-2021.pdf", "/2018/3500.3-2018 Stormwater-已解锁.pdf"}
    assert all(i["edition"]["designation"] for i in plan["items"])


def test_restamping_sends_the_published_files_again_keeping_who_accepted_them():
    room = _editions_room()
    out = R.restamp(room["id"])
    plan = json.load(open(json.loads(queue.get(out["job"])["rel"])["publish_from"], encoding="utf-8"))
    (it,) = plan["items"]
    assert it["rel"] == "/2015/AS 3500.1-2015.pdf" and it["by"] == "wang" and it["at"].startswith("2026-")
    assert it["edition"]["status"] == "superseded" and it["forced"] is False
    f = {x["rel"]: x for x in R.find_files(R.get_room(room["id"]))["files"]}["/2015/AS 3500.1-2015.pdf"]
    assert f["state"] == "publishing"
