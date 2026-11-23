# -*- coding: utf-8 -*-
"""How often the AI picks the right reading, measured against known truth (requirements v2, Q-1 / §9).

Where the two OCR engines disagreed on a real scan, the AI is asked to choose (the same prompt and rules as the live
"arbitrate" skill). The scan's edition also exists as a native text PDF in the room, so each case can be decided:
the case counts when exactly one candidate occurs on the matching page of the native copy. The AI is right when it
picks that one, wrong when it picks the other, and abstains when it answers -1.

Usage (from backend/):  python scripts/eval_arbitration.py <room_id> "<scan rel>" "<native rel>" [--max 150]
                        [--model deepseek-chat] [--out ../docs/benchmarks/ai-arbitration-<date>]
Figures only are written; no document text.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai import config as CF  # noqa: E402
from app.ai import providers as P  # noqa: E402
from app.ai.skills import arbitrate as A  # noqa: E402
from app.distill import evaluate as EV  # noqa: E402
from app.distill import run as RN  # noqa: E402
from app.jobs import rooms as R  # noqa: E402
from app.jobs import sync_job as SJ  # noqa: E402


def _pages(room_id, row):
    return EV.pages_of(EV.markdown_files(RN.longpath(os.path.join(SJ.room_dir(room_id), "out", row["out_dir"]))))


def _words(s: str) -> set:
    return set(re.findall(r"[a-z0-9][a-z0-9.,:/()\-]*", s.lower()))


def _norm(c: str) -> str:
    return EV.norm(c).strip(" .,;:")


def cases(room_id, scan_rel, native_rel):
    rows = {r["rel"]: r for r in R._files(room_id)}
    scan, native = rows[scan_rel], rows[native_rel]
    sp, tp = _pages(room_id, scan), _pages(room_id, native)
    pair = {p: q for p, q, _ in EV.align(tp, sp)}
    out = []
    for f in json.loads(scan["findings"] or "[]"):
        if f.get("kind") != "reading" or f.get("page") not in pair:
            continue
        a, b = _norm(f.get("a") or ""), _norm(f.get("b") or "")
        if not a or not b or a == b:
            continue
        truth = " " + tp[pair[f["page"]]] + " "
        a_in, b_in = (" " + a + " ") in truth, (" " + b + " ") in truth
        if a_in == b_in:
            continue                                   # both or neither on the native page: cannot be decided
        page = sp[f["page"]]
        at = max(page.find(a), page.find(b))
        before, after = (page[max(0, at - 120):at], page[at + max(len(a), len(b)):][:120]) if at >= 0 else ("", "")
        out.append({"page": f["page"], "candidates": [a, b], "right": 0 if a_in else 1, "before": before, "after": after,
                    "digits": bool(re.search(r"\d", a + b))})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("room")
    ap.add_argument("scan")
    ap.add_argument("native")
    ap.add_argument("--max", type=int, default=150)
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    s = CF.load()
    prov = next(p for p in s["providers"] if p["kind"] == "deepseek")
    key = CF.key_for(prov["id"])
    cs = cases(a.room, a.scan, a.native)[: a.max]
    tally = {"words": {"right": 0, "wrong": 0, "abstain": 0, "confident_right": 0, "confident_wrong": 0},
             "digits": {"right": 0, "wrong": 0, "abstain": 0, "confident_right": 0, "confident_wrong": 0}}
    cost, t0 = 0.0, time.time()
    for c in cs:
        p = A.payload(c["before"], c["candidates"], c["after"], c["page"])
        try:
            out = P.call(prov, key, a.model, A.SYSTEM, A.build(p, []), A.SCHEMA)
            res = json.loads(out["text"])
            cost += P.cost(prov, a.model, out["tokens_in"], out["tokens_out"]) or 0
        except Exception as e:                       # noqa: BLE001 - one failed call is an abstention
            res = {"choice": -1, "confidence": 0, "error": str(e)[:80]}
        t = tally["digits" if c["digits"] else "words"]
        ch = res.get("choice", -1)
        conf = float(res.get("confidence") or 0)
        if ch not in (0, 1):
            t["abstain"] += 1
        elif ch == c["right"]:
            t["right"] += 1
            t["confident_right"] += conf >= 0.9
        else:
            t["wrong"] += 1
            t["confident_wrong"] += conf >= 0.9
    for t in tally.values():
        decided = t["right"] + t["wrong"]
        t["n"] = decided + t["abstain"]
        t["accuracy_when_decided"] = round(t["right"] / decided, 4) if decided else None
        cd = t["confident_right"] + t["confident_wrong"]
        t["accuracy_at_0.9"] = round(t["confident_right"] / cd, 4) if cd else None
        t["coverage_at_0.9"] = round(cd / t["n"], 4) if t["n"] else None
    report = {"date": _dt.date.today().isoformat(), "model": a.model, "scan": a.scan.rsplit("/", 1)[-1],
              "truth": a.native.rsplit("/", 1)[-1], "cases": len(cs), "seconds": round(time.time() - t0),
              "cost_usd": round(cost, 4), "tally": tally}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if a.out:
        with open(a.out + ".json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
