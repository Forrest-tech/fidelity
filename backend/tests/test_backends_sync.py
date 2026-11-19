"""Sync through any storage backend (Dropbox, Google Drive, mixed) and the Google Drive adapter."""
import itertools
import re

import pytest

from app.distill import backends as B
from app.distill import dropbox_io as D
from app.distill import gdrive_io as G
from app.distill import sync as SY


# ------------------------------------------------------------------ fake backends for the sync flow
class MemStore:
    def __init__(self):
        self.files = {}

    def upload(self, path, data):
        self.files[path] = data

    def move(self, src, dst):
        moved = {k: v for k, v in self.files.items() if k == src or k.startswith(src.rstrip("/") + "/")}
        if not moved:
            raise FileNotFoundError(src)
        for k, v in moved.items():
            del self.files[k]
            self.files[dst + k[len(src):]] = v

    def delete(self, path):
        for k in [k for k in self.files if k == path or k.startswith(path.rstrip("/") + "/")]:
            del self.files[k]

    def list(self, path):
        return {k: len(v) for k, v in self.files.items() if k == path or k.startswith(path.rstrip("/") + "/")}


class FakeSource:
    provider, root, label, name = "fake", "/src", "fake:/src", "src"

    def __init__(self, docs):
        self.docs = docs                       # rel -> text
        self.change_on_identity = None

    def _entry(self, rel):
        t = self.docs[rel]
        return {"rel": rel, "id": "id" + rel, "rev": str(hash(t) & 0xffff), "size": len(t), "content_hash": "h" + str(hash(t))}

    def snapshot(self):
        return {rel: self._entry(rel) for rel in self.docs}

    def download(self, rel, entry, lp):
        import os
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        open(lp, "w", encoding="utf-8").write(self.docs[rel])

    def local_matches(self, lp, entry):
        return False

    def verify_local(self, lp, entry):
        return True

    def identity(self, rel, entry):
        if self.change_on_identity == rel:
            return {"id": entry["id"], "rev": "changed", "size": entry["size"]}
        return {k: entry[k] for k in ("id", "rev", "size")}


class FakeDest:
    provider, root, stage_root, archive_root = "fake", "/out", "/out_staging", "/out_archive"

    def __init__(self, store):
        self.store = store


@pytest.fixture()
def world(monkeypatch, tmp_path):
    src = FakeSource({"/Guide.md": "# Guide\n\nStep 1 uses 12 mm board.\n", "/Note.md": "# Note\n\nKeep 900 mm clear.\n"})
    store = MemStore()
    monkeypatch.setattr(B, "open_source", lambda link: src)
    monkeypatch.setattr(B, "open_dest", lambda link, s: FakeDest(store))

    def run(*extra):
        return SY.main(["--source-link", "x", "--dest-link", "y", "--work", str(tmp_path / "work"), *extra])
    return src, store, run


def test_publishes_then_skips_unchanged(world):
    src, store, run = world
    assert run() == 0
    assert "/out/src/Guide.md.md" in store.files and "/out/src/Note.md.md" in store.files
    assert b"12 mm board" in store.files["/out/src/Guide.md.md"]
    before = dict(store.files)
    assert run() == 0
    assert store.files == before                            # unchanged sources: nothing re-published


def test_dry_run_uploads_nothing(world):
    _, store, run = world
    assert run("--dry-run") == 0 and store.files == {}


def test_source_changed_during_the_run_stops_it(world):
    src, store, run = world
    src.change_on_identity = "/Guide.md"
    with pytest.raises(SystemExit, match="SOURCE CHANGED"):
        run()


def test_rollback_restores_the_previous_version(world, capsys):
    src, store, run = world
    run()
    src.docs["/Guide.md"] = "# Guide\n\nStep 1 uses 16 mm board.\n"
    run()
    assert b"16 mm" in store.files["/out/src/Guide.md.md"]
    stamp = re.findall(r"--rollback (\d{8}-\d{6})", capsys.readouterr().out)[-1]
    run("--rollback", stamp)
    assert b"12 mm" in store.files["/out/src/Guide.md.md"]


def test_provider_is_chosen_from_the_link(monkeypatch):
    monkeypatch.setattr(B, "GDriveSource", lambda link: ("gdrive", link))
    monkeypatch.setattr(B, "DropboxSource", lambda link: ("dropbox", link))
    assert B.open_source("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp")[0] == "gdrive"
    assert B.open_source("gdrive:1AbCdEfGhIjKlMnOp")[0] == "gdrive"
    assert B.open_source("/2025")[0] == "dropbox"
    assert B.open_source("https://www.dropbox.com/scl/fo/x/y?rlkey=1")[0] == "dropbox"


# ------------------------------------------------------------------ an in-memory Google Drive
class FakeDrive:
    def __init__(self):
        self.items = {}
        self.ids = (f"id{i:012d}" for i in itertools.count())

    def add(self, name, parent, mime="text/plain", **kw):
        fid = next(self.ids)
        self.items[fid] = {"id": fid, "name": name, "mimeType": mime, "parents": [parent] if parent else [],
                           "trashed": False, **kw}
        return fid

    def files(self):
        return self

    def _ex(self, value):
        return type("Req", (), {"execute": lambda s: value})()

    def list(self, q, **kw):
        parent = re.search(r"'([^']+)' in parents", q).group(1)
        name = re.search(r"name = '((?:[^'\\]|\\.)*)'", q)
        folder = "mimeType = '" + G.FOLDER + "'" in q
        res = [f for f in self.items.values() if parent in f["parents"] and not f["trashed"]
               and (not name or f["name"] == name.group(1).replace("\\'", "'"))
               and (not folder or f["mimeType"] == G.FOLDER)]
        return self._ex({"files": [dict(f) for f in res]})

    def get(self, fileId, **kw):
        return self._ex(dict(self.items[fileId]))

    def create(self, body, media_body=None, **kw):
        fid = self.add(body["name"], body["parents"][0], body.get("mimeType", "text/markdown"))
        if media_body is not None:
            self.items[fid]["content"] = media_body._fd.getvalue()
        return self._ex({"id": fid})

    def update(self, fileId, body=None, media_body=None, addParents=None, removeParents=None, **kw):
        f = self.items[fileId]
        if body:
            f.update({k: v for k, v in body.items() if k in ("name", "trashed")})
        if addParents:
            f["parents"] = [p for p in f["parents"] if p != removeParents] + [addParents]
        if media_body is not None:
            f["content"] = media_body._fd.getvalue()
        return self._ex({"id": fileId})


@pytest.fixture()
def drive():
    d = FakeDrive()
    d.root = d.add("My Drive", None, G.FOLDER)
    d.src = d.add("Standards", d.root, G.FOLDER)
    sub = d.add("Fire", d.src, G.FOLDER)
    d.add("NCC.pdf", sub, "application/pdf", md5Checksum="abc123", size="2048", version="7")
    d.add("Memo", d.src, "application/vnd.google-apps.document", version="3")
    d.add("Survey form", d.src, "application/vnd.google-apps.form", version="1")
    d.out = d.add("Distilled", d.root, G.FOLDER)
    return d


def test_folder_links_are_parsed():
    assert G.folder_id("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp?usp=sharing") == "1AbCdEfGhIjKlMnOp"
    assert G.folder_id("https://drive.google.com/drive/u/0/folders/1AbCdEfGhIjKlMnOp") == "1AbCdEfGhIjKlMnOp"
    assert G.folder_id("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp") == "1AbCdEfGhIjKlMnOp"
    with pytest.raises(ValueError):
        G.folder_id("https://www.dropbox.com/scl/fo/x")


def test_snapshot_walks_folders_and_exports_google_files(drive):
    snap = G.snapshot(drive, drive.src)
    assert set(snap) == {"/Fire/NCC.pdf", "/Memo.docx"}                    # the form is skipped
    assert snap["/Fire/NCC.pdf"]["content_hash"] == "abc123" and snap["/Memo.docx"]["content_hash"] == "rev:3"


def test_store_writes_only_under_its_roots_and_trashes_on_delete(drive):
    st = G.GDriveStore(drive, {"/Distilled": drive.out})
    st.upload("/Distilled/Fire/NCC.pdf.md", b"# NCC")
    st.upload("/Distilled/Fire/NCC.pdf.md", b"# NCC v2")                 # same name: updated, not duplicated
    assert st.list("/Distilled") == {"/Distilled/Fire/NCC.pdf.md": 0}
    f = next(f for f in drive.items.values() if f["name"] == "NCC.pdf.md")
    assert f["content"] == b"# NCC v2"
    with pytest.raises(D.IronRuleViolation):
        st.upload("/Standards/evil.md", b"x")
    st.delete("/Distilled/Fire/NCC.pdf.md")
    assert f["trashed"] is True                                           # recoverable from the Drive trash


def test_move_between_roots(drive):
    stage = drive.add("Distilled_staging", drive.root, G.FOLDER)
    st = G.GDriveStore(drive, {"/Distilled": drive.out, "/Distilled_staging": stage})
    st.upload("/Distilled_staging/run1/a.md", b"a")
    st.move("/Distilled_staging/run1/a.md", "/Distilled/a.md")
    assert st.list("/Distilled") == {"/Distilled/a.md": 0} and st.list("/Distilled_staging/run1") == {}


def test_output_roots_create_siblings_and_refuse_overlap(drive):
    name, dest, stage, archive = G.output_roots(drive, drive.out, [drive.src])
    assert name == "Distilled" and drive.items[stage]["name"] == "Distilled_staging" \
        and drive.items[archive]["parents"] == [drive.root]
    inside = drive.add("out-inside-source", drive.src, G.FOLDER)
    with pytest.raises(D.IronRuleViolation, match="overlap"):
        G.output_roots(drive, inside, [drive.src])
    with pytest.raises(D.IronRuleViolation, match="overlap"):
        G.output_roots(drive, drive.src, [inside])                       # source inside the output
