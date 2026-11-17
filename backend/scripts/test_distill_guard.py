# -*- coding: utf-8 -*-
"""Iron-rule test: the Dropbox writer must never write into the source folder.

    python scripts/test_distill_guard.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.distill.dropbox_io import SafeWriter, IronRuleViolation  # noqa: E402


class FakeDbx:
    def __init__(self):
        self.calls = []
        self.deleted = []

    def files_delete_v2(self, path):
        self.deleted.append(path)

    def files_upload(self, data, path, mode=None, mute=None):
        self.calls.append(path)


def main():
    bs = chr(92)
    fk = FakeDbx()
    w = SafeWriter(fk, "/transfer_md", ["/2025"])
    cases = {
        "/Transfer_Md/2025/NCC/001.md": True,
        "/transfer_md/_catalog.md": True,
        "/2025/evil.md": False,
        "/2025/ss/x.md": False,
        "/transfer_md/../2025/x.md": False,
        "/transfer_md": False,
        "/transfer_mdx/a.md": False,
        "/TRANSFER_MD/.." + bs + "2025" + bs + "x.md": False,
        "//2025/x.md": False,
        "/transfer_md/./../2025/ss/y.md": False,
    }
    failed = 0
    for p, expect in cases.items():
        try:
            w.upload(p, b"x")
            got = True
        except IronRuleViolation:
            got = False
        if got != expect:
            failed += 1
            print("FAIL", p, "allowed" if got else "refused")
    for dest, src in [("/", "/2025"), ("/2025/out", "/2025"), ("/x", "/")]:
        try:
            SafeWriter(fk, dest, [src])
            failed += 1
            print("FAIL overlap allowed", dest, src)
        except IronRuleViolation:
            pass
    # delete uses the same guard: allowed inside the output root, refused in the source
    for p, expect in {"/transfer_md/2025/doc/old.md": True, "/2025/NCC 2025 Volume One.pdf": False,
                      "/transfer_md/../2025/ss/x.pdf": False, "/transfer_md": False}.items():
        try:
            w.delete(p)
            got = True
        except IronRuleViolation:
            got = False
        if got != expect:
            failed += 1
            print("FAIL delete", p, "allowed" if got else "refused")
    if any(c.lower().startswith("/2025") for c in fk.calls + fk.deleted):
        failed += 1
        print("FAIL: an upload reached the source folder")
    print("guard tests:", "ALL PASS" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
