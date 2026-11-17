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
