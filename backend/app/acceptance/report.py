"""A Markdown report: one table per run, the questions two runs disagree on, and every failure with its reason."""
from __future__ import annotations


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def write(path: str, bank: dict, runs: list[dict]):
    L = ["# Acceptance run", "", "Graded by fixed rules (`app/acceptance/grade.py`): figure and unit right, citation's quote "
         "found on the cited page of the original PDF (±1 page), edition status stated for superseded editions, traps "
         "refused. 95% interval: Wilson.", "", "| Run | Passed | Rate | 95% interval | Traps | Failures: search missed the page / answer wrong | Not answered (call failed) |",
         "|---|---|---|---|---|---|---|"]
    for r in runs:
        s = r["summary"]
        b = s["blame"]
        L.append(f"| {r['name']} | {s['passed']}/{s['questions']} | {_pct(s['rate'])} | {_pct(s['ci95'][0])}–{_pct(s['ci95'][1])} "
                 f"| {s['traps'][0]}/{s['traps'][1]} | {sum(v for k, v in b.items() if k.startswith('library'))} / "
                 f"{b.get('answer', 0)} | {s.get('not_answered', 0)} |")
    L += ["", "## By category", "", "| Category | " + " | ".join(r["name"] for r in runs) + " |",
          "|---|" + "---|" * len(runs)]
    cats = sorted({c for r in runs for c in r["summary"]["by_category"]})
    for c in cats:
        L.append(f"| {c} | " + " | ".join(
            f"{r['summary']['by_category'].get(c, {}).get('passed', 0)}/{r['summary']['by_category'].get(c, {}).get('of', 0)}"
            for r in runs) + " |")
    if len(runs) >= 2:
        a, b = runs[0], runs[1]
        pa = {x["id"]: x for x in a["rows"]}
        dis = [x for x in b["rows"] if x["id"] in pa and None not in (x["pass"], pa[x["id"]]["pass"])
               and pa[x["id"]]["pass"] != x["pass"]]
        L += ["", f"## {a['name']} and {b['name']} disagree on {len(dis)} question(s)", "",
              "These go to a person first: one of the two runs is wrong on each.", ""]
        for x in dis[:80]:
            q = bank[x["id"]]
            L.append(f"- **Q{x['id']}** ({q['cat']}) {q['q']}  \n  {a['name']}: {'pass' if pa[x['id']]['pass'] else 'FAIL — ' + pa[x['id']]['why']}; "
                     f"{b['name']}: {'pass' if x['pass'] else 'FAIL — ' + x['why']}")
    for r in runs:
        ans = {x["id"]: x for x in r["answers"]}
        fails = [x for x in r["rows"] if x["pass"] is False]
        L += ["", f"## Failures — {r['name']} ({len(fails)})", ""]
        for x in fails[:150]:
            q, a = bank[x["id"]], ans.get(x["id"], {})
            g = q.get("ground", {})
            L.append(f"- **Q{x['id']}** ({q['cat']}) {q['q']}  \n  expected: {q['expected']}"
                     + (f" — {g.get('designation')} cl. {g.get('clause')} p.{g.get('page')}" if g.get("page") else "")
                     + f"  \n  got: {(a.get('answer') or a.get('error') or '')[:300]}  \n  why: {x['why']}"
                     + (f" ({x['blame']})" if x.get("blame") else ""))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
