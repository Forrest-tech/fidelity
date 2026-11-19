"""Review unreadable formulas (spec Phase 6).

    python scripts/formulas.py list <pdf>                      # every unreadable formula: page, order, position
    python scripts/formulas.py read <pdf> [--page N]           # run the formula OCR engines (Mac mini) -> candidates
    python scripts/formulas.py approve <pdf> --page N --k K --latex "<checked LaTeX>" --reviewer <name>

Approving records the transcription against the PDF's content hash in data/formula_approvals.json; the
next distillation replaces that marker with the LaTeX, labelled "transcribed from the source image;
reviewed <date> by <reviewer>". Check the LaTeX against the source page before approving.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.distill import formula as F  # noqa: E402
from app.distill.run import dropbox_content_hash  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["list", "read", "approve"])
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int)
    ap.add_argument("--k", type=int)
    ap.add_argument("--latex")
    ap.add_argument("--reviewer")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        items = [i for i in F.locate(a.pdf) if not a.page or i["page"] == a.page]
        for i in items:
            print(f"p.{i['page']}#{i['k']}  bbox={i['bbox']}")
        print(f"{len(items)} unreadable formula line(s)")
    elif a.cmd == "read":
        res = F.recover(a.pdf, log=lambda *_: None)
        items = [i for i in res["items"] if not a.page or i["page"] == a.page]
        print(json.dumps({"engines": res.get("engines"), "skipped": res.get("skipped"), "items": items},
                         ensure_ascii=False, indent=1))
    else:
        if not (a.page and a.k and a.latex and a.reviewer):
            ap.error("approve needs --page, --k, --latex and --reviewer")
        known = {(i["page"], i["k"]) for i in F.locate(a.pdf)}
        if (a.page, a.k) not in known:
            ap.error(f"no unreadable formula p.{a.page}#{a.k} in this PDF (see: list)")
        rec = F.approve(dropbox_content_hash(a.pdf), a.page, a.k, a.latex, a.reviewer)
        print(f"approved p.{a.page}#{a.k}: {rec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
