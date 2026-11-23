# -*- coding: utf-8 -*-
"""Render the adapter packs (spec F-19, 6.6): one template, one pack per AI tool, facts from the library.

    python -m app.adapters.build --library <local copy of the library> [--out adapters/dist] [--tools grok,claude]
                                 [--house adapters/house_rules.trial.yaml]

--house names a second rules file whose keys replace those in house_rules.yaml, e.g. a trial skill that reads
another library folder under its own name, next to the skill staff use every day.

The library copy is only read. Packs are written to --out; a build report lists starting points that
could not be found so the owner can fix house_rules.yaml.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import jinja2
import yaml

from . import facts as F

VERSION = "1"
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ADAPTERS = os.path.join(_REPO, "adapters")


def load_config(adapters_dir: str = ADAPTERS, overlay: str | None = None):
    with open(os.path.join(adapters_dir, "house_rules.yaml"), encoding="utf-8") as f:
        house = yaml.safe_load(f)
    if overlay:
        with open(overlay, encoding="utf-8") as f:
            house.update(yaml.safe_load(f) or {})
    with open(os.path.join(adapters_dir, "tools.yaml"), encoding="utf-8") as f:
        tools = yaml.safe_load(f)
    return house, tools


def render(library_root: str, out_dir: str, tools_wanted=None, adapters_dir: str = ADAPTERS, today=None,
           house_overlay: str | None = None) -> dict:
    house, tools = load_config(adapters_dir, house_overlay)
    lib = F.scan(library_root)
    summary = F.summarise(lib)
    starts, missing = [], []
    for s in house.get("starting_points") or []:
        d = F.resolve(lib, s["source"])
        if d:
            starts.append({"note": s["note"], "path": d["path"], "layout": d["layout"], "n_files": d["n_files"]})
        else:
            missing.append(s["source"])
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(adapters_dir), keep_trailing_newline=True,
                             undefined=jinja2.StrictUndefined, autoescape=False)
    tpl = env.get_template("template.md.j2")
    generated = (today or dt.date.today()).isoformat()
    written = {}
    for key, tool in tools.items():
        if tools_wanted and key not in tools_wanted:
            continue
        text = tpl.render(tool=tool, tool_key=key, h=house, f=summary, starting_points=starts,
                          generated=generated, version=VERSION)
        text = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        path = os.path.join(out_dir, *tool["output"].split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written[key] = os.path.relpath(path, out_dir).replace(os.sep, "/")
    report = {"generated": generated, "version": VERSION, "library_files": summary["files"],
              "documents": summary["n_documents"], "packs": written, "starting_points_missing": missing,
              "install": {k: t["install"] for k, t in tools.items() if k in written}}
    with open(os.path.join(out_dir, "build-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--library", required=True, help="local copy of the published library (read only)")
    ap.add_argument("--out", default=os.path.join(ADAPTERS, "dist"))
    ap.add_argument("--tools", default="", help="comma-separated subset of adapters/tools.yaml")
    ap.add_argument("--house", default=None, help="rules file whose keys replace those in house_rules.yaml")
    a = ap.parse_args(argv)
    rep = render(a.library, a.out, [t for t in a.tools.split(",") if t] or None, house_overlay=a.house)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
