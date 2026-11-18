"""Collect staff wrong-answer reports into the regression set (spec F-25).

The adapter packs tell the AI to save a report in <logs>/_error_reports/ whenever a user says an answer
is wrong. Copy that folder locally (read only), then:

    python scripts/collect_error_reports.py --reports <local _error_reports> [--bank ../docs/acceptance/regression.json]

New reports are appended with status "reported"; a maintainer sets "confirmed" (then fixes the cause
and adds an `expected` answer) or "rejected". Reports already collected are skipped, so it can re-run.
"""
import argparse
import json
import os
import re
import sys

FIELDS = ("question", "answer_given", "sources_cited", "user_says", "recheck")
_LINE = re.compile(r"^\s*(" + "|".join(FIELDS) + r")\s*:\s*(.*)$")


def parse(text: str) -> dict:
    out, cur = {}, None
    for line in text.splitlines():
        if line.strip().startswith("```"):
            continue
        m = _LINE.match(line)
        if m:
            cur = m.group(1)
            out[cur] = m.group(2).strip()
        elif cur and line.strip():
            out[cur] += " " + line.strip()          # wrapped continuation lines
    return out


def collect(reports_dir: str, bank_path: str) -> dict:
    bank = {"entries": []}
    if os.path.exists(bank_path):
        with open(bank_path, encoding="utf-8") as f:
            bank = json.load(f)
    seen = {e["report"] for e in bank["entries"]}
    added, skipped = [], []
    for fn in sorted(os.listdir(reports_dir)):
        if not fn.endswith(".md") or fn in seen:
            continue
        with open(os.path.join(reports_dir, fn), encoding="utf-8", errors="replace") as f:
            r = parse(f.read())
        if not r.get("question"):
            skipped.append(fn)
            continue
        entry = {"report": fn, "status": "reported", **{k: r.get(k, "") for k in FIELDS}, "expected": ""}
        bank["entries"].append(entry)
        added.append(fn)
    os.makedirs(os.path.dirname(os.path.abspath(bank_path)), exist_ok=True)
    with open(bank_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(bank, f, ensure_ascii=False, indent=1)
    return {"added": added, "skipped_unreadable": skipped, "total": len(bank["entries"])}


def main(argv=None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reports", required=True)
    ap.add_argument("--bank", default=os.path.join(here, "..", "..", "docs", "acceptance", "regression.json"))
    a = ap.parse_args(argv)
    print(json.dumps(collect(a.reports, a.bank), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
