"""Several files at once: downloads run ahead of the readers (bounded), files are read in parallel worker processes,
every file's step is in the live status, a changed source still stops everything, and the queue gives a run as many
slots as the machine has free."""
import json
import threading
import time

import pytest

from app import db
from app.distill import backends as B
from app.distill import pipeline as P
from app.distill import sync as SY
from app.jobs import capacity
from app.jobs.queue import JobQueue

from tests.test_backends_sync import FakeDest, FakeSource, MemStore


DOCS = {f"/Doc{i}.md": f"# Doc {i}\n\nStep {i} uses {10 + i} mm board.\n" for i in range(6)}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    src = FakeSource(dict(DOCS))
    store = MemStore()
    monkeypatch.setattr(B, "open_source", lambda link: src)
    monkeypatch.setattr(B, "open_dest", lambda link, s: FakeDest(store))
    import collections
    monkeypatch.setattr(SY.shutil, "disk_usage", lambda p: collections.namedtuple("u", "total used free")(1, 0, 1 << 40))
    live = tmp_path / "live.json"

    def run(*extra):
        return SY.main(["--source-link", "x", "--dest-link", "y", "--work", str(tmp_path / "work"),
                        "--live", str(live), *extra])
    return src, store, run, live


def test_two_reader_processes_publish_every_file(world):
    src, store, run, live = world
    assert run("--workers", "2") == 0
    for i in range(6):
        assert f"{10 + i} mm board".encode() in store.files[f"/out/src/Doc{i}.md.md"]
    st = json.loads(live.read_text(encoding="utf-8"))
    assert st["stage"] == "finished" and st["done"] == 6 and st["active"] == {} and st["queued"] == []
    assert st["counts"].get("PASS") == 6 and st["workers"] == 2


def test_a_changed_source_still_stops_a_parallel_run(world):
    src, store, run, live = world
    src.change_on_identity = "/Doc2.md"
    with pytest.raises(SystemExit, match="SOURCE CHANGED"):
        run("--workers", "2")
    assert not any(k.startswith("/out/src/") for k in store.files)        # nothing reached the live folder
    assert json.loads(live.read_text(encoding="utf-8"))["active"] == {}  # nothing shows as busy afterwards


def test_downloads_run_ahead_of_the_reader_but_stay_bounded(world, monkeypatch):
    """One reader (a thread): while it reads a file the next ones are already downloading, but never more than
    workers + 1 files are downloaded and not yet read."""
    src, store, run, live = world
    lock, state = threading.Lock(), {"ahead": 0, "max_ahead": 0, "overlap": False, "reading": 0}
    real_download, real_read = src.download, P.read_file

    def download(rel, entry, lp):
        with lock:
            state["ahead"] += 1
            state["max_ahead"] = max(state["max_ahead"], state["ahead"])
            if state["reading"]:
                state["overlap"] = True                   # a download while a file is being read
        time.sleep(0.05)
        real_download(rel, entry, lp)

    def read(*a):
        with lock:
            state["reading"] += 1
        time.sleep(0.15)
        try:
            return real_read(*a)
        finally:
            with lock:
                state["reading"] -= 1
                state["ahead"] -= 1

    src.download = download
    monkeypatch.setattr(P, "read_file", read)
    assert run("--workers", "1") == 0
    assert state["overlap"] is True
    assert state["max_ahead"] <= 2                        # workers + 1


def test_live_status_follows_a_file_through_its_steps():
    lv = P.LiveState(None, workers=2)
    lv.set(stage="running", total=3, queued=["/a.pdf", "/b.pdf", "/c.pdf"])
    lv.file("/a.pdf", stage="downloading", bytes=0, size=100)
    assert "/a.pdf" not in lv.s["queued"] and lv.s["active"]["/a.pdf"]["stage"] == "downloading"
    lv.file("/a.pdf", stage="reading")
    lv.message("/a.pdf", "  scanned document: OCR of 40 page(s) with 2 engine(s)")
    lv.message("/a.pdf", "  OCR page 12/40")
    a = lv.s["active"]["/a.pdf"]
    assert (a["stage"], a["page"], a["pages"], a["scan"]) == ("ocr", 12, 40, True)
    lv.message("/a.pdf", "  extracted 40 pages in 31s")
    assert lv.s["active"]["/a.pdf"]["stage"] == "checking"
    lv.done("/a.pdf", "PASS")
    assert lv.s["active"] == {} and lv.s["done"] == 1 and lv.s["counts"] == {"PASS": 1}
    assert lv.s["queued"] == ["/b.pdf", "/c.pdf"]


def test_bytes_received_are_reported_while_downloading(tmp_path):
    lv = P.LiveState(None)
    lp = str(tmp_path / "f.pdf")
    stop = P.watch_download(lv, "/f.pdf", lp, 1000)
    with open(lp + ".part", "wb") as f:
        f.write(b"x" * 400)
    for _ in range(30):
        if lv.s["active"].get("/f.pdf", {}).get("bytes") == 400:
            break
        time.sleep(0.1)
    stop()
    assert lv.s["active"]["/f.pdf"]["bytes"] == 400


# ------------------------------------------------------------------ the queue's slots
def _fresh_queue():
    db.init_trust()
    con = db.trust_rw()
    con.execute("DELETE FROM job WHERE status IN ('queued', 'running')")
    con.commit()
    con.close()
    return JobQueue()


def test_a_run_alone_takes_the_free_slots(monkeypatch):
    monkeypatch.setattr(capacity, "points", lambda: 6)
    q = _fresh_queue()
    q.submit("roomrun", json.dumps({"parallel": True, "unit_points": 2}), "queued", points=2)
    job = q._claim()
    assert job["points"] == 6                             # three files at once, two points each


def test_slots_are_capped_per_run(monkeypatch):
    monkeypatch.setattr(capacity, "points", lambda: 16)
    monkeypatch.setenv("FIDELITY_MAX_PARALLEL", "3")
    q = _fresh_queue()
    q.submit("roomrun", json.dumps({"parallel": True, "unit_points": 1}), "queued", points=1)
    first = q._claim()
    assert first["points"] == 3                           # at most FIDELITY_MAX_PARALLEL files
    q.submit("roomrun", json.dumps({"parallel": True, "unit_points": 1}), "queued", points=1)
    second = q._claim()
    assert second["points"] == 3                          # 13 points still free: it gets its own three


def test_a_run_that_cannot_read_in_parallel_keeps_its_points(monkeypatch):
    monkeypatch.setattr(capacity, "points", lambda: 8)
    q = _fresh_queue()
    q.submit("roomrun", json.dumps({"source_link": "x"}), "queued", points=1)
    assert q._claim()["points"] == 1


def test_a_scan_takes_two_points_so_scans_are_read_one_at_a_time(world, monkeypatch):
    """Two points: two text files are read side by side, but a scan (OCR) takes both, so it is read alone."""
    src, store, run, live = world
    monkeypatch.setenv("FIDELITY_READ_IN_THREADS", "1")
    scans = {"/Doc0.md", "/Doc1.md", "/Doc2.md"}
    monkeypatch.setattr(SY, "_cost", lambda lp: 2 if any(lp.replace("\\", "/").endswith(s) for s in scans) else 1)
    cond, state = threading.Condition(), {"now": [], "max_text": 0, "scan_with_other": False}
    real_read = P.read_file

    def read(lp, rel_local, out, cache, prot, rel):
        with cond:
            state["now"].append(rel)
            if any(r in scans for r in state["now"]) and len(state["now"]) > 1:
                state["scan_with_other"] = True
            state["max_text"] = max(state["max_text"], sum(1 for r in state["now"] if r not in scans))
            cond.notify_all()
            if rel not in scans:                          # hold a text file until a second one is read beside it (or 3 s)
                cond.wait_for(lambda: state["max_text"] >= 2, timeout=3)
        try:
            return real_read(lp, rel_local, out, cache, prot, rel)
        finally:
            with cond:
                state["now"].remove(rel)

    monkeypatch.setattr(P, "read_file", read)
    assert run("--workers", "2") == 0
    assert len([k for k in store.files if k.startswith("/out/src/")]) == 6
    assert state["scan_with_other"] is False              # a scan never shares the two points
    assert state["max_text"] == 2                         # text files do


def test_a_waiting_scan_is_passed_at_most_twice(world, monkeypatch):
    """A scan that waits for its two points lets at most two text files go first; then it gets the points."""
    src, store, run, live = world
    src.docs = {f"/T{i}.md": f"# T{i}\n\nText {i}.\n" for i in range(8)}
    src.docs["/T2_scan.md"] = "# Scan\n\nScanned.\n"         # sorts after T0, T1, T2: text files are being read
    monkeypatch.setenv("FIDELITY_READ_IN_THREADS", "1")
    monkeypatch.setattr(SY, "_cost", lambda lp: 2 if "_scan" in lp else 1)
    order, lock = [], threading.Lock()
    real_read = P.read_file

    def read(lp, rel_local, out, cache, prot, rel):
        with lock:
            order.append(rel)
        time.sleep(0.3 if rel != "/T2_scan.md" else 0.05)
        return real_read(lp, rel_local, out, cache, prot, rel)

    # two text files are being read when the scan is downloaded, so it has to wait for its points
    monkeypatch.setattr(P, "read_file", read)
    assert run("--workers", "2") == 0
    assert len(order) == 9
    i = order.index("/T2_scan.md")
    assert 3 <= i <= 5 < len(order) - 1      # it did wait, at most two files passed it, and it was not left to the end


def test_a_file_the_web_side_has_no_result_for_is_read_again(world, tmp_path):
    """A run whose events were lost (its supervisor died) left results in the room's own ledger that the page never
    received; those files were then skipped as "unchanged" and showed as never distilled for good."""
    src, store, run, live = world
    room = tmp_path / "room"
    ev = tmp_path / "e.jsonl"
    assert run("--dry-run", "--room-dir", str(room), "--events", str(ev)) == 0
    (room / "known.json").write_text(json.dumps(["/Doc0.md", "/Doc1.md"]), encoding="utf-8")   # the page has two
    ev2 = tmp_path / "e2.jsonl"
    assert run("--dry-run", "--room-dir", str(room), "--events", str(ev2)) == 0
    evs = [json.loads(l) for l in ev2.read_text(encoding="utf-8").splitlines()]
    assert {e["rel"] for e in evs if e["type"] == "unchanged"} == {"/Doc0.md", "/Doc1.md"}
    assert {e["rel"] for e in evs if e["type"] == "file"} == {f"/Doc{i}.md" for i in range(2, 6)}


def test_the_start_of_a_run_rides_out_a_dropped_connection(world, monkeypatch):
    """Seen for days: the TLS connection to Dropbox drops (SSLEOFError) while signing in and listing; one drop
    used to end the run at once."""
    import ssl
    src, store, run, live = world
    monkeypatch.setattr(SY, "_BACKOFF", (0, 0, 0))
    real, calls = src.snapshot, {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
        return real()

    src.snapshot = flaky
    assert run("--workers", "1") == 0
    assert calls["n"] >= 3 and "/out/src/Doc0.md.md" in store.files
