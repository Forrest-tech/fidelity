# -*- coding: utf-8 -*-
"""Downloads carry on from where a dropped connection left them (2026-11-27, the owner: a 146 MB file began at 0)."""
from app.distill import dropbox_io as D

DATA = bytes(range(256)) * 40


class Resp:
    def __init__(self, body, status):
        self.body, self.status_code = body, status

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    def close(self):
        pass


class Dbx:
    """Answers a Range request with the rest of the file (206), or ignores it (200) like a server without ranges."""

    def __init__(self, honour=True, headers=None):
        self.honour, self.headers, self.asked = honour, headers or {}, []

    def clone(self, headers=None):
        c = Dbx(self.honour, headers)
        c.asked = self.asked
        return c

    def files_download(self, path):
        rng = self.headers.get("Range")
        self.asked.append(rng)
        if rng and self.honour:
            start = int(rng.split("=")[1].rstrip("-"))
            return {"path": path}, Resp(DATA[start:], 206)
        return {"path": path}, Resp(DATA, 200)


def test_a_partial_download_is_carried_on(tmp_path):
    lp = str(tmp_path / "a.pdf")
    (tmp_path / "a.pdf.part").write_bytes(DATA[:4000])
    dbx = Dbx()
    D.download(dbx, "/src", "/a.pdf", lp, len(DATA))
    assert dbx.asked == ["bytes=4000-"] and open(lp, "rb").read() == DATA


def test_a_server_that_sends_the_whole_file_is_not_appended(tmp_path):
    lp = str(tmp_path / "a.pdf")
    (tmp_path / "a.pdf.part").write_bytes(DATA[:4000])
    D.download(Dbx(honour=False), "/src", "/a.pdf", lp, len(DATA))
    assert open(lp, "rb").read() == DATA


def test_no_partial_copy_downloads_from_the_start_and_restart_forgets(tmp_path):
    lp = str(tmp_path / "a.pdf")
    dbx = Dbx()
    D.download(dbx, "/src", "/a.pdf", lp, len(DATA))
    assert dbx.asked == [None] and open(lp, "rb").read() == DATA
    (tmp_path / "a.pdf.part").write_bytes(b"x")
    D.restart(lp)
    assert not (tmp_path / "a.pdf").exists() and not (tmp_path / "a.pdf.part").exists()


def test_a_partial_copy_as_large_as_the_file_is_not_used(tmp_path):
    lp = str(tmp_path / "a.pdf")
    (tmp_path / "a.pdf.part").write_bytes(b"y" * len(DATA))
    dbx = Dbx()
    D.download(dbx, "/src", "/a.pdf", lp, len(DATA))
    assert dbx.asked == [None] and open(lp, "rb").read() == DATA
