"""python -m app.acceptance <command>

  generate --sources DIR --model deepseek:deepseek-chat --out BANK [--pages N] [--superseded DIR]
  answer   --bank BANK --library DIR --model SPEC --out RUN.json
  grade    --bank BANK --sources DIR --run RUN.json [--run RUN2.json ...] --out REPORT.md

Sources are the ORIGINAL PDFs (read only); the library is a folder of distilled Markdown (as published)."""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys


def _sources(*dirs) -> dict[str, str]:
    out = {}
    for d in dirs:
        if d:
            for p in glob.glob(os.path.join(d, "**", "*.pdf"), recursive=True):
                out[os.path.basename(p)] = p
    return out


def cmd_generate(a):
    from . import generate as G
    from .ask import Model
    m = Model(a.model)
    bank, rejected = [], []
    for path in sorted(_sources(a.sources).values()):
        ok, bad = G.from_document(m, path, a.pages)
        bank += ok
        rejected += bad
    for path in sorted(_sources(a.superseded).values()) if a.superseded else []:
        ok, bad = G.from_document(m, path, a.pages_superseded, kind_override="D superseded edition")
        bank += ok
        rejected += bad
    bank += G.traps(bank, _sources(a.sources), a.not_held)
    G.save(bank, a.out, {"version": dt.date.today().isoformat(), "generator": m.name,
                         "method": "docs/acceptance/PHASE_F.md", "rejected": len(rejected)})
    with open(a.out.replace(".json", ".rejected.json"), "w", encoding="utf-8") as f:
        json.dump(rejected, f, ensure_ascii=False, indent=1)
    print(f"{len(bank)} questions -> {a.out}; {len(rejected)} proposals rejected; tokens {m.tokens_in}+{m.tokens_out}")


def cmd_answer(a):
    from . import answer as A
    from .ask import Model
    from .library import Search, load
    qs = json.load(open(a.bank, encoding="utf-8"))["questions"]
    if a.only:
        qs = qs[:a.only]
    units = [u for root in a.library for u in load(root)]
    print(f"library: {len(units)} page units")
    m = Model(a.model)
    rows = A.run(m, qs, Search(units), workers=a.workers, pack=a.pack)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"model": m.name, "library": a.library, "tokens": [m.tokens_in, m.tokens_out], "answers": rows},
                  f, ensure_ascii=False, indent=1)
    print(f"{len(rows)} answers -> {a.out}; tokens {m.tokens_in}+{m.tokens_out}")


def cmd_grade(a):
    from .grade import grade_one, summary
    from .report import write
    bank = {q["id"]: q for q in json.load(open(a.bank, encoding="utf-8"))["questions"]}
    src = _sources(a.sources, a.superseded)
    runs = []
    for path in a.run:
        r = json.load(open(path, encoding="utf-8"))
        rows = [grade_one(bank[x["id"]], x, src) for x in r["answers"]]
        runs.append({"name": a.label[len(runs)] if a.label and len(a.label) > len(runs) else r["model"],
                     "file": path, "model": r["model"], "rows": rows, "summary": summary(rows), "answers": r["answers"]})
    write(a.out, bank, runs)
    for r in runs:
        print(r["name"], json.dumps(r["summary"]))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.acceptance")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--sources", required=True)
    g.add_argument("--superseded")
    g.add_argument("--model", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--pages", type=int, default=60)
    g.add_argument("--pages-superseded", type=int, default=12)
    g.add_argument("--not-held", nargs="*", default=[])
    s = sub.add_parser("answer")
    s.add_argument("--bank", required=True)
    s.add_argument("--library", action="append", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--workers", type=int, default=6)
    s.add_argument("--only", type=int, default=0)
    s.add_argument("--pack", help="instruction pack to answer under (default: adapters/dist/grok)")
    r = sub.add_parser("grade")
    r.add_argument("--bank", required=True)
    r.add_argument("--sources", required=True)
    r.add_argument("--superseded")
    r.add_argument("--run", action="append", required=True)
    r.add_argument("--label", action="append")
    r.add_argument("--out", required=True)
    a = p.parse_args(argv)
    {"generate": cmd_generate, "answer": cmd_answer, "grade": cmd_grade}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
