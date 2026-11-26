"""Distillation inside the real container, as a brand-new installation (CI job "docker"; also runnable on a Mac):

    docker compose exec -T fidelity python scripts/docker_distill_e2e.py

Found 2026-11-26: on the owner's Mac (Docker, fresh install) every file of a real link failed although the same files
passed on the Windows VM — copy-restricted PDFs were refused because a setting only existed on the VM. The VM tests
could not see it. This script reads the kinds of PDF the library holds with the container's own settings (none: a new
installation), OCR models and libraries, through the same reader the runs use, and fails if any kind does not come out
as a scored result:

  - an ordinary text PDF
  - a copy-restricted PDF (copying not permitted: the owner's decision is to read it)
  - a scanned PDF (pages are pictures: OCR)
Exit code 0 when all pass; the report is printed as JSON."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEXT = [
    ("SECTION 4 INSTALLATION", "4.1 SCOPE This Section sets out requirements for the installation of consumer piping. "
     "4.2 GENERAL Piping shall be installed so that it is protected against damage. 4.2.1 Clearances The clearance "
     "between a pipe and an electrical cable shall be not less than 100 mm. 4.2.2 Depth of cover The depth of cover "
     "shall be not less than 300 mm under footpaths and 450 mm under driveways."),
    ("SECTION 5 TESTING", "5.1 SCOPE This Section specifies tests. 5.2 PRESSURE TEST The installation shall be tested "
     "at 7 kPa for not less than 5 minutes. 5.3 LEAKAGE No leakage shall be detected. Table 5.1 gives test pressures "
     "of 2.75 kPa, 7 kPa and 14 kPa for the three classes of installation."),
]


def _text_pdf(path, **save):
    import pymupdf
    doc = pymupdf.open()
    for head, body in TEXT * 3:
        page = doc.new_page()
        page.insert_text((72, 80), head, fontsize=14)
        page.insert_textbox(pymupdf.Rect(72, 100, 520, 760), body, fontsize=11)
    doc.save(path, **save)
    doc.close()


def _scan_pdf(src, path):
    """Each page replaced by a picture of itself: what a scanner produces (no text layer)."""
    import pymupdf
    s, out = pymupdf.open(src), pymupdf.open()
    for p in s:
        pix = p.get_pixmap(dpi=200)
        page = out.new_page(width=p.rect.width, height=p.rect.height)
        page.insert_image(page.rect, pixmap=pix)
    out.save(path)
    s.close()
    out.close()


def main() -> int:
    import pymupdf

    from app.distill import scoring as SC
    from app.distill import triage as T
    from app.distill.office import distill_any
    work = tempfile.mkdtemp(prefix="fidelity-e2e-")
    src, out, cache = (os.path.join(work, x) for x in ("src", "out", "cache"))
    for d in (src, out, cache):
        os.makedirs(d)
    files = {"text.pdf": "text", "protected.pdf": "protected", "scan.pdf": "scan"}
    _text_pdf(os.path.join(src, "text.pdf"))
    _text_pdf(os.path.join(src, "protected.pdf"), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner",
              user_pw="", permissions=int(pymupdf.PDF_PERM_PRINT))
    _scan_pdf(os.path.join(src, "text.pdf"), os.path.join(src, "scan.pdf"))
    report = {"read_protected_by_default": T.ocr_protected_enabled(), "files": {}}
    ok = report["read_protected_by_default"]
    for name, kind in files.items():
        try:
            r = distill_any(os.path.join(src, name), name, out, "", cache, log=lambda m: None)
            c = SC.classify(r)
            row = {"kind": kind, "verdict": r.get("verdict"), "outcome": c.get("outcome"), "reason": c.get("reason"),
                   "accuracy": c.get("accuracy"), "triage": (r.get("triage") or {}).get("class")}
        except Exception as e:                              # noqa: BLE001 - the report says which kind broke
            row = {"kind": kind, "error": f"{type(e).__name__}: {e}"[:300], "outcome": "error"}
        # a kind passes when it is a scored result (any accuracy: these are synthetic pages), never refused
        row["pass"] = row.get("outcome") == "result" and row.get("accuracy") is not None
        ok = ok and row["pass"]
        report["files"][name] = row
    report["ok"] = ok
    print(json.dumps(report, ensure_ascii=False, indent=1))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
