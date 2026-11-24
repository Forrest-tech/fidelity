import json
"""Staging, promote and rollback (F-18) against an in-memory store."""
import pytest

from app.distill.publish import PublishError, Publisher


class FakeStore:
    def __init__(self):
        self.files = {}
        self.log = []

    def upload(self, path, data):
        self.files[path] = bytes(data)
        self.log.append(("upload", path))

    def list(self, path):
        return {p: len(d) for p, d in self.files.items() if p == path or p.startswith(path + "/")}

    def move(self, src, dst):
        moved = {p: d for p, d in self.files.items() if p == src or p.startswith(src + "/")}
        if not moved:
            raise FileNotFoundError(src)
        for p in moved:
            del self.files[p]
        for p, d in moved.items():
            self.files[dst + p[len(src):]] = d
        self.log.append(("move", src, dst))

    def delete(self, path):
        for p in list(self.list(path)):
            del self.files[p]


def make(tmp_path, run="r1", store=None):
    st = store or FakeStore()
    return st, Publisher(st, "/kb", "/staging", "/archive", run, str(tmp_path))


def test_live_is_untouched_until_promote(tmp_path):
    st, pub = make(tmp_path)
    pub.stage("2025/Doc", {"a.md": b"new-a", "b.md": b"new-b"})
    assert not [p for p in st.files if p.startswith("/kb")]
    assert not any(e[0] == "upload" and e[1].startswith("/kb") for e in st.log)
    pub.promote()
    assert st.files["/kb/2025/Doc/a.md"] == b"new-a"
    assert not [p for p in st.files if p.startswith("/staging")]


def test_previous_version_is_archived_and_rollback_restores_it(tmp_path):
    st, pub = make(tmp_path, "r1")
    st.files["/kb/2025/Doc/a.md"] = b"old-a"
    st.files["/kb/2025/Doc/c.md"] = b"old-c"
    pub.stage("2025/Doc", {"a.md": b"new-a"})
    pub.promote()
    assert st.files["/kb/2025/Doc/a.md"] == b"new-a" and "/kb/2025/Doc/c.md" not in st.files   # replaced as a whole
    assert st.files["/archive/r1/2025/Doc/c.md"] == b"old-c"
    pub.rollback()
    assert st.files["/kb/2025/Doc/a.md"] == b"old-a" and st.files["/kb/2025/Doc/c.md"] == b"old-c"
    assert pub.docs["2025/Doc"]["state"] == "rolled_back"


def test_rollback_of_a_new_document_removes_it(tmp_path):
    st, pub = make(tmp_path)
    pub.stage("Brand New.pdf.md", {"": b"x"})
    pub.promote()
    assert st.files["/kb/Brand New.pdf.md"] == b"x"
    pub.rollback()
    assert not [p for p in st.files if p.startswith("/kb")]


def test_failed_validation_promotes_nothing(tmp_path):
    st, pub = make(tmp_path)
    st.files["/kb/Good/a.md"] = b"old"
    pub.stage("Good", {"a.md": b"new"})
    pub.stage("Bad", {"a.md": b"new", "b.md": b"new"})
    del st.files["/staging/r1/Bad/b.md"]                  # simulate a lost upload
    with pytest.raises(PublishError):
        pub.promote()
    assert st.files["/kb/Good/a.md"] == b"old"            # nothing moved, not even the good document


def test_document_switching_between_single_file_and_folder(tmp_path):
    st, pub = make(tmp_path)
    st.files["/kb/2025/Doc/001.md"] = b"old chapter"      # was a folder, is now a single file
    pub.stage("2025/Doc.pdf.md", {"": b"single"})
    pub.promote(replaces={"2025/Doc.pdf.md": ["2025/Doc"]})
    assert st.files["/kb/2025/Doc.pdf.md"] == b"single" and "/kb/2025/Doc/001.md" not in st.files
    pub.rollback()
    assert st.files["/kb/2025/Doc/001.md"] == b"old chapter" and "/kb/2025/Doc.pdf.md" not in st.files


def test_manifest_allows_rollback_from_a_later_session(tmp_path):
    st, pub = make(tmp_path)
    st.files["/kb/D/a.md"] = b"old"
    pub.stage("D", {"a.md": b"new"})
    pub.promote()
    again = Publisher.load(st, pub.manifest_path, str(tmp_path))
    again.rollback()
    assert st.files["/kb/D/a.md"] == b"old"


def test_overlapping_folders_are_refused(tmp_path):
    with pytest.raises(PublishError):
        Publisher(FakeStore(), "/kb", "/kb/staging", "/archive", "r", str(tmp_path))


# ------------------------------------------------- S-2 drills: the network drops while the live folder is changed
class FlakyStore(FakeStore):
    """Fails chosen moves with a dropped connection, either before the server acts or after (answer lost)."""

    def __init__(self, fail):
        super().__init__()
        self.fail = list(fail)          # ("before" | "after") per move call; then normal

    def move(self, src, dst):
        mode = self.fail.pop(0) if self.fail else None
        if mode == "before":
            raise ConnectionError("connection reset by peer")
        super().move(src, dst)
        if mode == "after":
            raise TimeoutError("the answer never came")


@pytest.mark.parametrize("fail", [["before"], ["after"], ["before", "before"], ["after", "before"], ["before", "after"]])
def test_promote_survives_a_dropped_connection_at_any_move(tmp_path, monkeypatch, fail):
    monkeypatch.setattr(Publisher, "BACKOFF", (0, 0, 0, 0, 0))
    st = FlakyStore([])
    st.files["/kb/2025/Doc/a.md"] = b"old"
    _, pub = make(tmp_path, store=st)
    pub.stage("2025/Doc", {"a.md": b"new"})
    st.fail = fail
    pub.promote()
    assert st.files["/kb/2025/Doc/a.md"] == b"new"
    assert st.files["/archive/r1/2025/Doc/a.md"] == b"old"          # the previous version is kept, once
    assert pub.docs["2025/Doc"]["archived"] == ["2025/Doc"]
    pub.rollback()
    assert st.files["/kb/2025/Doc/a.md"] == b"old"


def test_promote_gives_up_on_an_error_that_is_not_the_network(tmp_path, monkeypatch):
    monkeypatch.setattr(Publisher, "BACKOFF", (0, 0, 0, 0, 0))

    class Refusing(FakeStore):
        def move(self, src, dst):
            raise PermissionError("no write access")
    st = Refusing()
    _, pub = make(tmp_path, store=st)
    pub.stage("2025/Doc", {"a.md": b"new"})
    with pytest.raises(PermissionError):
        pub.promote()
    assert not [p for p in st.files if p.startswith("/kb")]


def test_rollback_survives_a_dropped_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(Publisher, "BACKOFF", (0, 0, 0, 0, 0))
    st = FlakyStore([])
    st.files["/kb/2025/Doc/a.md"] = b"old"
    _, pub = make(tmp_path, store=st)
    pub.stage("2025/Doc", {"a.md": b"new"})
    pub.promote()
    st.fail = ["after", "before"]
    pub.rollback()
    assert st.files["/kb/2025/Doc/a.md"] == b"old"


# --------------------- only the library folder stays: no archive folder, staging gone after each publish (2026-11-23)
class HistoryStore(FakeStore):
    """Like Dropbox: a delete goes to the account's deleted files, restorable by revision; empty folders can go."""

    def __init__(self):
        super().__init__()
        self.deleted, self.folders, self.rev, self.versions = {}, set(), 0, {}

    def upload(self, path, data):
        super().upload(path, data)
        parts = path.split("/")
        self.folders |= {"/".join(parts[:i]) for i in range(2, len(parts))}

    def revisions(self, path):
        out = []
        for p in self.list(path):
            self.rev += 1
            self.versions[f"r{self.rev}"] = self.files[p]
            out.append([p, f"r{self.rev}"])
        return out

    def delete(self, path):
        for p in list(self.list(path)):
            self.deleted[p] = self.files.pop(p)

    def restore(self, tokens):
        for p, rev in tokens:
            self.files[p] = self.versions[rev]

    def drop_empty(self, path):
        if not self.list(path):
            self.folders = {f for f in self.folders if not (f == path or f.startswith(path + "/"))}


def test_a_publish_leaves_only_the_library_folder_and_can_still_be_undone(tmp_path):
    st = HistoryStore()
    st.files["/kb/2025/Doc/a.md"] = b"old"
    _, pub = make(tmp_path, store=st)
    pub.stage("2025/Doc", {"a.md": b"new", "b.md": b"new-b"})
    pub.promote()
    assert st.files["/kb/2025/Doc/a.md"] == b"new"
    assert not [p for p in st.files if not p.startswith("/kb/")]              # no archive, nothing left in staging
    assert not [f for f in st.folders if f.startswith("/staging")]            # the staging folder itself is gone
    assert st.deleted == {"/kb/2025/Doc/a.md": b"old"}                        # the old version is in the history
    pub.rollback()
    assert st.files == {"/kb/2025/Doc/a.md": b"old"}


def test_a_withdrawn_copy_comes_back_from_the_history(tmp_path):
    st = HistoryStore()
    st.files["/kb/2025/Copy.pdf.md"] = b"copy"
    _, pub = make(tmp_path, store=st)
    assert pub.withdraw("2025/Copy.pdf.md") == ["2025/Copy.pdf.md"]
    assert not st.files
    pub.rollback()
    assert st.files == {"/kb/2025/Copy.pdf.md": b"copy"}


def test_the_way_back_is_recorded_before_anything_is_deleted(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(Publisher, "BACKOFF", (0, 0, 0, 0, 0))

    class DropsOnDelete(HistoryStore):
        def delete(self, path):
            raise ConnectionError("reset")
    st = DropsOnDelete()
    st.files["/kb/2025/Doc/a.md"] = b"old"
    _, pub = make(tmp_path, store=st)
    pub.stage("2025/Doc", {"a.md": b"new"})
    with pytest.raises(ConnectionError):
        pub.promote()
    rec = json.load(open(pub.manifest_path, encoding="utf-8"))
    assert rec["docs"]["2025/Doc"]["trashed"][0]["tokens"] == [["/kb/2025/Doc/a.md", "r1"]]
    assert st.files["/kb/2025/Doc/a.md"] == b"old"                            # nothing lost


def test_an_old_undo_record_still_restores_from_the_archive_folder(tmp_path):
    st = HistoryStore()
    st.files["/archive/r0/2025/Doc/a.md"] = b"old"
    st.files["/kb/2025/Doc/a.md"] = b"new"
    _, pub = make(tmp_path, run="r0", store=st)
    pub.docs = {"2025/Doc": {"files": {"a.md": 3}, "state": "promoted", "archived": ["2025/Doc"]}}
    pub.rollback()
    assert st.files["/kb/2025/Doc/a.md"] == b"old"


def test_each_publishing_run_writes_a_numbered_release_note(tmp_path):
    """Requirements v3 R-1: what this release added, replaced and withdrew, with files and clauses, who accepted it
    and how to undo it."""
    s = FakeStore()
    one = Publisher(s, "/kb", "/kb_staging", "/kb_archive", "run1", str(tmp_path / "publish"))
    fm = b'---\nclauses: [5.1, 5.2, 5.3]\n---\nbody'
    one.stage("AS 3500/2021/doc", {"a.md": fm, "b.md": b'---\nclauses: [6.1]\n---\nx'})
    one.by = "wang@example.com"
    one.promote()
    two = Publisher(s, "/kb", "/kb_staging", "/kb_archive", "run2", str(tmp_path / "publish"))
    two.stage("AS 3500/2021/doc", {"a.md": fm})
    two.stage("2025/new", {"": b"single file"})
    two.promote()
    rel = tmp_path / "releases"
    names = sorted(p.name for p in rel.iterdir())
    assert names == ["0001-run1.json", "0001-run1.md", "0002-run2.json", "0002-run2.md"]
    r1 = json.loads((rel / "0001-run1.json").read_text(encoding="utf-8"))
    assert r1["release"] == 1 and r1["accepted_by"] == "wang@example.com"
    assert r1["documents"] == [{"key": "AS 3500/2021/doc", "change": "added", "files_before": 0, "files": 2, "clauses": 4}]
    r2 = json.loads((rel / "0002-run2.json").read_text(encoding="utf-8"))
    assert r2["totals"] == {"added": 1, "replaced": 1, "withdrawn": 0} and "--rollback run2" in r2["undo"]
    assert "| AS 3500/2021/doc | replaced |" in (rel / "0002-run2.md").read_text(encoding="utf-8")
    assert two.release_note() is None                                   # one note per run


def test_the_system_page_lists_releases_newest_first(tmp_path, monkeypatch):
    from app import config
    from app.api import system as SYS
    rel = tmp_path / "work" / "releases"
    rel.mkdir(parents=True)
    for n in (1, 2, 3):
        (rel / f"{n:04d}-r{n}.json").write_text(json.dumps({"release": n, "run": f"r{n}"}), encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    assert [r["release"] for r in SYS.releases(limit=2)["releases"]] == [3, 2]
