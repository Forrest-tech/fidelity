# -*- coding: utf-8 -*-
"""Comparing a new result with the live copy before accepting it, picking folders, and room defaults."""
import os
import types

import pytest

from app import db
from app.distill import live as L
from app.jobs import rooms as R
from app.jobs import sync_job as S

FM = '---\ndocument: "Guide"\naudit_status: auto_verified\n---\n\n# Guide\n\nPipe size 12 mm.\nCover 30 mm.\n'


class FakeLive:
    """An output folder held in memory: {key: bytes} for single files, {key/inner: bytes} for folders."""

    def __init__(self, files: dict):
        self.files = {k.lower(): v for k, v in files.items()}
        self.reads = []

    def listing(self, key):
        key = key.lower()
        if key in self.files:
            return {"": len(self.files[key])}
        return {k[len(key) + 1:]: len(v) for k, v in self.files.items() if k.startswith(key + "/")}

    def read(self, key, inner=""):
        self.reads.append((key, inner))
        return self.files[(key + ("/" + inner if inner else "")).lower()]

    def existing(self):
        return set(self.files)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ------------------------------------------------------------------ comparing
def test_a_document_not_in_the_output_folder_is_new_and_shows_its_text_as_added(tmp_path):
    p = tmp_path / "a.pdf.md"
    _write(str(p), FM)
    out = L.compare(str(p), "as 3500/a.pdf.md", FakeLive({}))
    assert out["status"] == "new" and out["files"][0]["status"] == "new"
    assert out["added"] == len(FM.split("\n")) and out["removed"] == 0
    assert all(x["op"] in "+@" for x in out["files"][0]["lines"])


def test_only_the_acceptance_lines_differing_counts_as_the_same():
    from app.distill import accept as AC
    live = FakeLive({"as 3500/a.pdf.md": AC.accept_markdown(FM, "wang", "t", 99.5, False).encode()})
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.pdf.md")
        _write(p, FM)
        out = L.compare(p, "as 3500/a.pdf.md", live)
    assert out["status"] == "same" and out["files"][0]["lines"] == []


def test_a_changed_number_shows_as_one_line_removed_and_one_added(tmp_path):
    p = tmp_path / "a.pdf.md"
    _write(str(p), FM.replace("12 mm", "15 mm"))
    out = L.compare(str(p), "as 3500/a.pdf.md", FakeLive({"as 3500/a.pdf.md": FM.encode()}))
    assert out["status"] == "changed" and (out["added"], out["removed"]) == (1, 1)
    lines = out["files"][0]["lines"]
    assert {"op": "-", "text": "Pipe size 12 mm."} in lines and {"op": "+", "text": "Pipe size 15 mm."} in lines
    assert {"op": " ", "text": "Cover 30 mm."} in lines                 # context around the change


def test_a_folder_result_compares_each_file_and_says_what_is_new_or_gone(tmp_path):
    base = tmp_path / "book"
    _write(str(base / "index.md"), FM)
    _write(str(base / "ch2.md"), "two\n")
    live = FakeLive({"as 3500/book/index.md": FM.encode(), "as 3500/book/ch1.md": b"one\n"})
    out = L.compare(str(base), "as 3500/book", live)
    st = {f["path"]: f["status"] for f in out["files"]}
    assert st == {"ch1.md": "removed", "ch2.md": "new", "index.md": "same"} and out["status"] == "changed"


def test_a_long_difference_is_cut_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "MAX_DIFF_LINES", 10)
    p = tmp_path / "a.md"
    _write(str(p), "\n".join(f"line {i}" for i in range(100)))
    out = L.compare(str(p), "a.md", FakeLive({}))
    f = out["files"][0]
    assert len(f["lines"]) == 10 and f["truncated"] and f["added"] == 100


def test_a_missing_result_is_reported(tmp_path):
    with pytest.raises(L.LiveError) as e:
        L.compare(str(tmp_path / "gone.md"), "gone.md", FakeLive({}))
    assert e.value.status == 409


def test_impact_counts_new_and_replaced_documents():
    live = FakeLive({"as 3500/a.pdf.md": b"x", "as 3500/book/index.md": b"y"})
    assert L.impact(["as 3500/a.pdf.md", "As 3500/Book", "as 3500/c.pdf.md"], live) == {"new": 1, "replaces": 2}


def test_google_drive_output_cannot_be_compared_yet():
    with pytest.raises(L.LiveError) as e:
        L.open_live("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp")
    assert e.value.status == 422


# ------------------------------------------------------------------ picking a folder
class _Folder:
    def __init__(self, name, path):
        self.name, self.path_display = name, path


def _fake_dropbox(monkeypatch, tree):
    import dropbox
    monkeypatch.setattr(dropbox.files, "FolderMetadata", _Folder)

    class Dbx:
        def files_list_folder(self, path):
            if path not in tree:
                raise dropbox.exceptions.ApiError("rid", "not_found", "not found", None)
            return types.SimpleNamespace(entries=[_Folder(n, (path or "") + "/" + n) for n in tree[path]] + [object()],
                                         has_more=False)

        def files_get_metadata(self, path):
            return types.SimpleNamespace(path_display=path.upper())

    return Dbx()


def test_subfolders_lists_only_folders_sorted(monkeypatch):
    dbx = _fake_dropbox(monkeypatch, {"": ["Zeta", "as 3500"], "/as 3500": ["2018", "2003"]})
    top = L.subfolders("/", dbx=dbx)
    assert top == {"path": "/", "folders": [{"name": "as 3500", "path": "/as 3500"}, {"name": "Zeta", "path": "/Zeta"}]}
    sub = L.subfolders("as 3500/", dbx=dbx)
    assert [f["name"] for f in sub["folders"]] == ["2003", "2018"] and sub["path"] == "/AS 3500"


def test_subfolders_refuses_climbing_and_reports_a_missing_folder(monkeypatch):
    dbx = _fake_dropbox(monkeypatch, {"": []})
    with pytest.raises(L.LiveError) as e:
        L.subfolders("/a/../b", dbx=dbx)
    assert e.value.status == 422
    with pytest.raises(L.LiveError) as e:
        L.subfolders("/nope", dbx=dbx)
    assert e.value.status == 404


# ------------------------------------------------------------------ rooms
@pytest.fixture
def clean(monkeypatch, tmp_path):
    db.init_trust()
    con = db.trust_rw()
    for t in ("room_file", "room", "job"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    monkeypatch.setattr(S, "room_dir", lambda rid: str(tmp_path / "rooms" / rid))
    return tmp_path


def test_a_room_without_a_name_is_named_in_the_persons_language(clean):
    assert R.create_room(None, "t", "Room")["name"] == "Room 1"
    assert R.create_room(None, "t", "Room")["name"] == "Room 2"
    assert R.create_room(None, "t")["name"] == "蒸馏室 3"
    assert R.create_room(None, "t", "   ")["name"] == "蒸馏室 4"
    assert R.create_room("Mine", "t", "Room")["name"] == "Mine"


def test_the_output_folder_must_be_outside_the_input_folder(clean):
    r = R.create_room(None, "t")
    R.update_room(r["id"], {"source": "/as 3500"})
    with pytest.raises(R.RoomError) as e:
        R.update_room(r["id"], {"dest": "/AS 3500/out"})
    assert e.value.status == 422
    with pytest.raises(R.RoomError):
        R.update_room(r["id"], {"source": "/Transfer_Md", "dest": "/"})
    assert R.update_room(r["id"], {"dest": "/Transfer_Md/as 3500"})["dest"]["link"] == "/Transfer_Md/as 3500"


def _room_with_result(tmp_path, text=FM):
    room = R.create_room(None, "t")
    room = R.update_room(room["id"], {"source": "/as 3500", "dest": "/Transfer_Md", "threshold": 99})
    _write(os.path.join(S.room_dir(room["id"]), "out", "_pending", "as 3500", "a.pdf.md"), text)
    ev = {"t": 1.0, "type": "file", "rel": "/a.pdf", "kind": "pdf", "outcome": "result", "accuracy": 99.5, "diffs": 0,
          "number_diffs": 0, "parts": {}, "pages": 5, "out_dir": "_pending/as 3500/a.pdf.md", "content_hash": "h",
          "single_file": True, "n_files": 1, "verdict": "PASS"}
    con = db.trust_rw()
    R.apply_event(con, room["id"], "j0", ev)
    R.apply_event(con, room["id"], "j0", {**ev, "rel": "/c.pdf", "outcome": "unprocessable", "accuracy": None, "out_dir": None})
    con.commit()
    con.close()
    return R.get_room(room["id"])


def test_a_room_compares_a_file_with_the_live_copy(clean, monkeypatch):
    room = _room_with_result(clean, FM.replace("12 mm", "15 mm"))
    seen = []
    monkeypatch.setattr(L, "open_live", lambda link: seen.append(link) or FakeLive({"as 3500/a.pdf.md": FM.encode()}))
    out = R.compare_file(room, "/a.pdf")
    assert seen == ["/Transfer_Md"] and out["status"] == "changed" and out["key"] == "as 3500/a.pdf.md"
    assert out["state"] == "ok" and out["accuracy"] == 99.5
    with pytest.raises(R.RoomError) as e:
        R.compare_file(room, "/c.pdf")                       # nothing to compare
    assert e.value.status == 409
    with pytest.raises(R.RoomError) as e:
        R.compare_file(room, "/nope.pdf")
    assert e.value.status == 404


def test_a_room_says_how_many_accepted_files_are_new(clean, monkeypatch):
    room = _room_with_result(clean)
    monkeypatch.setattr(L, "open_live", lambda link: FakeLive({}))
    assert R.accept_impact(room) == {"new": 1, "replaces": 0}
    monkeypatch.setattr(L, "open_live", lambda link: FakeLive({"as 3500/a.pdf.md": b"x"}))
    assert R.accept_impact(room) == {"new": 0, "replaces": 1}


def test_comparing_needs_an_output_folder(clean):
    room = _room_with_result(clean)
    room = R.update_room(room["id"], {"dest": None})
    with pytest.raises(R.RoomError) as e:
        R.compare_file(room, "/a.pdf")
    assert e.value.status == 422
