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
