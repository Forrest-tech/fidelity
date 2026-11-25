"""Requirements v3 V-3 and V-4.

V-3 canary: the same 50 questions every week (drawn once, stratified by category, fixed by a seed), graded by the
fixed rules, and the share answered right plotted on a p-chart (statistical process control). A week below the lower
control limit — three standard errors under the long-run rate — is a real drop, not noise, and raises an alert.

    python -m app.acceptance canary --bank BANK --sources DIR --run RUN.json [--history FILE] [--alert]

V-4 cross-model check: the same questions answered by two independent models (e.g. Grok and DeepSeek); every
question where they give different figures or cite different pages goes on a review list for a person.

    python -m app.acceptance crosscheck --bank BANK --run A.json --run B.json --out REVIEW.md
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import math
import os
import random

from .grade import grade_one
from .text import numbers

SIZE = 50
SEED = "fidelity canary v1"
SIGMA = 3.0


def pick(bank: list[dict], size: int = SIZE, seed: str = SEED) -> list[int]:
    """Fixed question ids: each category gets its share of `size` (at least one), drawn with a fixed seed."""
    by = collections.defaultdict(list)
    for q in sorted(bank, key=lambda q: q["id"]):
        by[q["cat"][:1]].append(q)
    rnd = random.Random(seed)
    total = sum(len(v) for v in by.values())
    out = []
    for cat in sorted(by):
        k = max(1, round(size * len(by[cat]) / total))
        out += [q["id"] for q in rnd.sample(by[cat], min(k, len(by[cat])))]
    return sorted(out)[:size]


def score(bank: list[dict], answers: list[dict], sources: dict[str, str], ids: list[int]) -> dict:
    qs = {q["id"]: q for q in bank}
    got = {a["id"]: a for a in answers}
    rows = [grade_one(qs[i], got[i], sources) for i in ids if i in got]
    graded = [r for r in rows if r["pass"] is not None]
    return {"n": len(graded), "passed": sum(1 for r in graded if r["pass"]),
            "failed_ids": [r["id"] for r in graded if not r["pass"]], "missing": len(ids) - len(rows)}


def limits(history: list[dict], n: int) -> dict:
    """p-chart for a sample of n: centre = pooled rate of all earlier weeks; LCL = centre − 3·√(p(1−p)/n)."""
    k = sum(h["passed"] for h in history)
    m = sum(h["n"] for h in history)
    if not m:
        return {"centre": None, "lcl": None}
    p = k / m
    return {"centre": round(p, 4), "lcl": round(max(0.0, p - SIGMA * math.sqrt(p * (1 - p) / max(n, 1))), 4)}


def record(history_path: str, entry: dict) -> dict:
    """Adds this run to the history and says whether it is below the lower control limit of the earlier runs."""
    hist = []
    if os.path.exists(history_path):
        with open(history_path, encoding="utf-8") as f:
            hist = [json.loads(line) for line in f if line.strip()]
    lim = limits(hist, entry["n"])
    rate = entry["passed"] / entry["n"] if entry["n"] else 0.0
    out = {**entry, "rate": round(rate, 4), **lim,
           "below_lcl": lim["lcl"] is not None and rate < lim["lcl"],
           "at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    os.makedirs(os.path.dirname(os.path.abspath(history_path)), exist_ok=True)
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    return out


def alert_text(entry: dict) -> tuple[str, str]:
    return ("Fidelity canary below its control limit",
            f"The weekly canary ({entry['model']}) scored {entry['passed']}/{entry['n']} ({entry['rate']:.1%}), "
            f"below the lower control limit {entry['lcl']:.1%} (long-run rate {entry['centre']:.1%}).\n"
            f"Questions answered wrong: {entry['failed_ids']}\n"
            "Something changed in the library, the skill or the model. History: docs/acceptance/canary.jsonl.")


def alert(entry: dict) -> None:
    """Mail the administrators the way the watchdog does (scripts/alert_mail.py); never fails the run."""
    import subprocess
    import sys
    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "alert_mail.py")
    subprocess.run([sys.executable, script, *alert_text(entry)], check=False, timeout=120)


# ------------------------------------------------------------------ V-4
def _cite(a: dict) -> tuple[str, int] | None:
    c = a.get("citations") or []
    c = c[0] if isinstance(c, list) and c else c if isinstance(c, dict) else None
    return (c.get("document", ""), int(c.get("page") or 0)) if c else None


def _main(a: dict) -> str:
    vals = a.get("values") or []
    n = numbers(vals[0]) if vals else []
    return n[0] if n else ""


def disagree(a: dict, b: dict) -> list[str]:
    """Where two models' answers to one question differ in substance: status, figures, or the page they rest on."""
    out = []
    if (a.get("status") or "") != (b.get("status") or ""):
        out.append(f"status {a.get('status')} vs {b.get('status')}")
    # the main figure: the first number of the first value. Extra context figures one model adds ("1.25 % (1:80)",
    # "DN 50 vent … 75 mm") are not a disagreement; a different main figure is.
    fa, fb = _main(a), _main(b)
    if fa != fb:
        out.append(f"main figure {fa or '—'} vs {fb or '—'}")
    ca, cb = _cite(a), _cite(b)
    if ca and cb and abs(ca[1] - cb[1]) > 1:
        out.append(f"cited page {ca[1]} vs {cb[1]}")
    return out


def crosscheck(bank: list[dict], run_a: dict, run_b: dict) -> list[dict]:
    qs = {q["id"]: q for q in bank}
    b = {x["id"]: x for x in run_b["answers"]}
    rows = []
    for x in run_a["answers"]:
        y = b.get(x["id"])
        if y is None or x.get("error") or y.get("error"):
            continue
        why = disagree(x, y)
        rows.append({"id": x["id"], "q": qs.get(x["id"], {}).get("q", ""), "agree": not why, "why": "; ".join(why),
                     "a": " ".join(x.get("values") or []), "b": " ".join(y.get("values") or [])})
    return rows


def write_review(path: str, rows: list[dict], name_a: str, name_b: str):
    diff = [r for r in rows if not r["agree"]]
    lines = [f"# Cross-model review list — {name_a} vs {name_b}", "",
             f"{len(rows) - len(diff)}/{len(rows)} questions answered alike. The {len(diff)} below differ in status, "
             "figures or cited page: a person checks each against the source page.", "",
             f"| Q | Question | {name_a} | {name_b} | Difference |", "|---|---|---|---|---|"]
    for r in diff:
        q = r["q"].replace("|", "/")
        lines.append(f"| {r['id']} | {q[:140]} | {r['a']} | {r['b']} | {r['why']} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
