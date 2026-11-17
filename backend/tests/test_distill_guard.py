"""Iron rule: the Dropbox writer must never write/delete in the source folder."""
import pytest

from app.distill.dropbox_io import IronRuleViolation, SafeWriter

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
