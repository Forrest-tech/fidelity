"""Iron rule: the Dropbox writer must never write/delete in the source folder."""
import pytest

from app.distill.dropbox_io import IronRuleViolation, SafeWriter
from app.distill import dropbox_io as D

BS = chr(92)


class FakeDbx:
    def __init__(self):
        self.calls = []
        self.deleted = []

    def files_delete_v2(self, path):
        self.deleted.append(path)

    def files_upload(self, data, path, mode=None, mute=None):
        self.calls.append(path)


def make():
    fk = FakeDbx()
    return fk, SafeWriter(fk, "/transfer_md", ["/2025"])


UPLOADS = {
    "/Transfer_Md/2025/NCC/001.md": True,
    "/transfer_md/_catalog.md": True,
    "/2025/evil.md": False,
    "/2025/ss/x.md": False,
    "/transfer_md/../2025/x.md": False,
    "/transfer_md": False,
    "/transfer_mdx/a.md": False,
    "/TRANSFER_MD/.." + BS + "2025" + BS + "x.md": False,
    "//2025/x.md": False,
    "/transfer_md/./../2025/ss/y.md": False,
}
DELETES = {
    "/transfer_md/2025/doc/old.md": True,
    "/2025/NCC 2025 Volume One.pdf": False,
    "/transfer_md/../2025/ss/x.pdf": False,
    "/transfer_md": False,
}


@pytest.mark.parametrize("path,allowed", UPLOADS.items())
def test_upload_guard(path, allowed):
    fk, w = make()
    if allowed:
        w.upload(path, b"x")
    else:
        with pytest.raises(IronRuleViolation):
            w.upload(path, b"x")
        assert fk.calls == []


@pytest.mark.parametrize("path,allowed", DELETES.items())
def test_delete_guard(path, allowed):
    fk, w = make()
    if allowed:
        w.delete(path)
    else:
        with pytest.raises(IronRuleViolation):
            w.delete(path)
        assert fk.deleted == []


@pytest.mark.parametrize("dest,src", [("/", "/2025"), ("/2025/out", "/2025"), ("/x", "/")])
def test_overlapping_roots_refused(dest, src):
    with pytest.raises(IronRuleViolation):
        SafeWriter(FakeDbx(), dest, [src])


class FakeDbx2(FakeDbx):
    def __init__(self):
        super().__init__()
        self.moves = []

    def files_move_v2(self, src, dst, autorename=False, allow_ownership_transfer=False):
        self.moves.append((src, dst))


def make3():
    fk = FakeDbx2()
    return fk, SafeWriter(fk, "/kb", ["/2025"], extra_roots=["/kb_staging", "/kb_archive"])


@pytest.mark.parametrize("src,dst,allowed", [
    ("/kb_staging/r1/Doc", "/kb/Doc", True),
    ("/kb/Doc", "/kb_archive/r1/Doc", True),
    ("/kb_staging/r1/Doc", "/2025/Doc", False),          # into the source
    ("/2025/Doc.pdf", "/kb/Doc.pdf", False),              # out of the source
    ("/kb_staging/r1/Doc", "/elsewhere/Doc", False),      # outside every output root
    ("/kb", "/kb_archive/x", False),                      # a root itself is not movable
])
def test_move_guard(src, dst, allowed):
    fk, w = make3()
    if allowed:
        w.move(src, dst)
        assert fk.moves == [(src, dst)]
    else:
        with pytest.raises(IronRuleViolation):
            w.move(src, dst)
        assert fk.moves == []


def test_staging_inside_source_or_overlapping_source_is_refused():
    with pytest.raises(IronRuleViolation):
        SafeWriter(FakeDbx2(), "/kb", ["/2025"], extra_roots=["/2025/staging"])
    with pytest.raises(IronRuleViolation):
        SafeWriter(FakeDbx2(), "/kb", ["/2025"], extra_roots=["/"])


def test_upload_to_staging_allowed_but_not_to_source():
    fk, w = make3()
    w.upload("/kb_staging/r1/Doc/a.md", b"x")
    with pytest.raises(IronRuleViolation):
        w.upload("/2025/a.md", b"x")


# ---------------------------------------------- bulk upload: parallel sessions, one commit, per-file retry (2026-11-23)
class _Res:
    def __init__(self, ok):
        self.ok = ok

    def is_failure(self):
        return not self.ok


class _BatchDbx:
    def __init__(self, drop_first=0, lose_commit_answer=False):
        self.sessions, self.files, self.drop, self.lose = {}, {}, drop_first, lose_commit_answer

    def files_upload_session_start(self, data, close=False):
        import requests
        if self.drop:
            self.drop -= 1
            raise requests.exceptions.SSLError("EOF occurred in violation of protocol")
        sid = f"s{len(self.sessions)}"
        self.sessions[sid] = data

        class R:
            session_id = sid
        return R()

    def files_upload_session_finish_batch_v2(self, entries):
        import requests
        first = not any(e.commit.path in self.files for e in entries)
        for e in entries:
            self.files[e.commit.path] = self.sessions[e.cursor.session_id]
        if self.lose and first:
            raise requests.exceptions.ConnectionError("the answer never came")

        class R:
            pass
        r = R()
        r.entries = [_Res(not self.lose) for _ in entries]      # a second commit of the same sessions fails
        return r

    def files_get_metadata(self, path):
        class M:
            size = len(self.files[path])
        return M()


def test_bulk_upload_retries_one_file_and_commits_once(monkeypatch):
    from app.distill import sync as SY
    monkeypatch.setattr(SY, "_BACKOFF", (0, 0, 0, 0, 0, 0))
    dbx = _BatchDbx(drop_first=2)
    w = D.SafeWriter(dbx, "/Transfer_Md", ["/AS 3500"], extra_roots=["/Transfer_Md_staging"])
    items = {f"/Transfer_Md_staging/r1/doc/{i}.md": f"text {i}".encode() for i in range(30)}
    w.upload_many(items, workers=4)
    assert dbx.files == items


def test_bulk_upload_whose_commit_answer_was_lost_is_still_done(monkeypatch):
    from app.distill import sync as SY
    monkeypatch.setattr(SY, "_BACKOFF", (0, 0, 0, 0, 0, 0))
    dbx = _BatchDbx(lose_commit_answer=True)
    w = D.SafeWriter(dbx, "/Transfer_Md", ["/AS 3500"], extra_roots=["/Transfer_Md_staging"])
    items = {f"/Transfer_Md_staging/r1/doc/{i}.md": b"x" * i for i in range(5)}
    w.upload_many(items)
    assert dbx.files == items


def test_bulk_upload_stays_inside_the_output_folder():
    w = D.SafeWriter(_BatchDbx(), "/Transfer_Md", ["/AS 3500"])
    with pytest.raises(D.IronRuleViolation):
        w.upload_many({"/Transfer_Md/ok.md": b"1", "/AS 3500/evil.md": b"2"})


class _LockedBatch(_BatchDbx):
    """Seen 2026-11-24: a batch commit refused all 28 files of one document (another write held the lock)."""
    def __init__(self, single_fails=0):
        super().__init__()
        self.single_fails, self.singles = single_fails, []

    def files_upload_session_finish_batch_v2(self, entries):
        class R:
            pass
        r = R()
        r.entries = [_Res(False) for _ in entries]
        for e in r.entries:
            e.get_failure = lambda: "too_many_write_operations"
        return r

    def files_get_metadata(self, path):
        raise LookupError(path)

    def files_upload(self, data, path, mode=None, mute=True):
        if self.single_fails:
            self.single_fails -= 1
            raise RuntimeError("path/conflict")
        self.singles.append(path)
        self.files[path] = data


def test_files_a_batch_commit_refused_are_sent_again_one_by_one(monkeypatch):
    from app.distill import sync as SY
    monkeypatch.setattr(SY, "_BACKOFF", (0, 0))
    dbx = _LockedBatch()
    w = D.SafeWriter(dbx, "/Transfer_Md", ["/AS 3500"], extra_roots=["/Transfer_Md_staging"])
    items = {f"/Transfer_Md_staging/r1/doc/{i}.md": f"t{i}".encode() for i in range(4)}
    w.upload_many(items)
    assert dbx.files == items and len(dbx.singles) == 4


def test_a_file_refused_again_fails_the_document_with_the_reason(monkeypatch):
    from app.distill import sync as SY
    monkeypatch.setattr(SY, "_BACKOFF", (0, 0))
    dbx = _LockedBatch(single_fails=99)
    w = D.SafeWriter(dbx, "/Transfer_Md", ["/AS 3500"], extra_roots=["/Transfer_Md_staging"])
    with pytest.raises(RuntimeError) as e:
        w.upload_many({"/Transfer_Md_staging/r1/doc/a.md": b"a"})
    assert "too_many_write_operations" in str(e.value) and "path/conflict" in str(e.value)
