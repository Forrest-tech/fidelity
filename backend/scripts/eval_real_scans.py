# -*- coding: utf-8 -*-
"""Measured OCR accuracy on real scans (requirements v2, Q-1; app/distill/evaluate.py).

For every edition a room holds both as a native text PDF and as a scan, the scan's distilled text is compared with
the native copy's, page by page. Writes a JSON and a Markdown report with figures only (no standards text).

Usage (from backend/):  python scripts/eval_real_scans.py <room_id> [--out ../docs/benchmarks/real-scans-<date>]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.distill import evaluate as EV  # noqa: E402
from app.distill import run as RN  # noqa: E402
from app.jobs import rooms as R  # noqa: E402
from app.jobs import sync_job as SJ  # noqa: E402


def _parser(path: str) -> str:
    files = EV.markdown_files(path)
    if not files:
        return ""
    with open(files[0], encoding="utf-8", errors="ignore") as f:
        head = f.read(4000)
    return head.split("parser:", 1)[1].split("\n", 1)[0].strip() if "parser:" in head else ""


def pairs(room_id: str) -> list[dict]:
    base = os.path.join(SJ.room_dir(room_id), "out")
    by_edition: dict = {}
    for r in R._files(room_id):
        e = r["edition"]
        if not r["out_dir"] or not e.get("key") or e.get("amendment") is not None:
            continue
        path = RN.longpath(os.path.join(base, r["out_dir"]))
        name = r["rel"].rsplit("/", 1)[-1].lower()
        native = "pymupdf" in _parser(path) and "printed" not in name and "searchable" not in name
        by_edition.setdefault(e["key"], []).append({"rel": r["rel"], "path": path, "native": native,
                                                    "designation": e["designation"], "parser": _parser(path)})
    out = []
    for key, files in sorted(by_edition.items()):
        truth = next((f for f in files if f["native"]), None)
        if not truth:
            continue
        tp = EV.pages_of(EV.markdown_files(truth["path"]))
        for f in files:
            if f is truth:
                continue
            res = EV.compare_documents(tp, EV.pages_of(EV.markdown_files(f["path"])))
            low = f["rel"].lower()
            kind = ("another program's OCR layer" if "searchable" in low else
                    "our OCR (two engines)" if "ocr" in f["parser"] else "native text (another copy)")
            out.append({"edition": f["designation"], "copy": f["rel"].rsplit("/", 1)[-1], "read_by": kind,
                        "truth": truth["rel"].rsplit("/", 1)[-1], **{k: v for k, v in res.items() if k != "worst"},
                        "worst_pages": [(w["page"], round(w["number_recall"], 3)) for w in res.get("worst", [])]})
    return out


def to_markdown(rows: list[dict], when: str) -> str:
    lines = [f"# OCR accuracy on real scans — {when}", "",
             "Each scan is compared, page by page, with a native text PDF of the same edition held in the same room "
             "(`app/distill/evaluate.py`). Figures only; no standards text. Order-free measures lead: tables come out "
             "row by row from OCR and column by column from a text layer, so the character error rate mostly measures "
             "reading order.", "",
             "| Edition | Copy | Read by | Pages compared | Word recall | Number recall | Extra numbers | Pages with every number | CER (order-sensitive) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r.get("pages"):
            continue
        lines.append(f"| {r['edition']} | {r['copy']} | {r['read_by']} | {r['pages']} of {r['test_pages']} | "
                     f"{r['word_recall'] * 100:.1f}% | {r['number_recall'] * 100:.1f}% | {r['number_extra']} | "
                     f"{r['pages_all_numbers']} | {r['cer'] * 100:.1f}% |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("room")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    rows = pairs(a.room)
    when = _dt.date.today().isoformat()
    md = to_markdown(rows, when)
    print(md)
    if a.out:
        with open(a.out + ".json", "w", encoding="utf-8") as f:
            json.dump({"date": when, "rows": rows}, f, ensure_ascii=False, indent=1)
        with open(a.out + ".md", "w", encoding="utf-8") as f:
            f.write(md)


if __name__ == "__main__":
    main()
