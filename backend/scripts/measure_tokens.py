"""Token cost of the library layout (spec Q-3), measured on a local copy of the published library.

    python scripts/measure_tokens.py --library <local copy> --out ../docs/benchmarks/token-cost

Tokens are estimated as characters / 4 (a common rule for English; real tokenisers differ by about
±15 %). Listing cost uses the ~330 tokens per entry measured with the Grok Dropbox connector.
"""
import argparse
import json
import os
import statistics
import sys

CHARS_PER_TOKEN = 4
LIST_TOKENS_PER_ENTRY = 330
TARGET = (10_000, 30_000)


def measure(root: str) -> dict:
    files, folders = [], {}
    for dirpath, dirs, fns in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith("_")]
        entries = len(dirs) + len([f for f in fns if f.endswith(".md")])
        folders[os.path.relpath(dirpath, root).replace(os.sep, "/")] = entries
        for fn in fns:
            if fn.endswith(".md"):
                p = os.path.abspath(os.path.join(dirpath, fn))
                size = os.path.getsize("\\\\?\\" + p if os.name == "nt" else p)
                files.append({"path": os.path.relpath(p, root).replace(os.sep, "/"), "tokens": size // CHARS_PER_TOKEN})
    toks = sorted(f["tokens"] for f in files)
    q = statistics.quantiles(toks, n=20) if len(toks) >= 2 else toks * 19
    biggest = sorted(files, key=lambda f: -f["tokens"])[:10]
    lst = sorted(folders.values())
    return {
        "files": len(files),
        "tokens": {"min": toks[0], "p5": int(q[0]), "median": int(statistics.median(toks)), "p95": int(q[18]),
                   "max": toks[-1], "total": sum(toks)},
        "share_in_target": round(sum(TARGET[0] <= t <= TARGET[1] for t in toks) / len(toks), 3),
        "share_below_target": round(sum(t < TARGET[0] for t in toks) / len(toks), 3),
        "share_above_target": round(sum(t > TARGET[1] for t in toks) / len(toks), 3),
        "biggest": biggest,
        "listing_tokens": {"median_folder": int(statistics.median(lst) * LIST_TOKENS_PER_ENTRY),
                           "max_folder": lst[-1] * LIST_TOKENS_PER_ENTRY},
    }


def to_markdown(m: dict, label: str) -> str:
    t = m["tokens"]
    lines = [f"# Token cost of the library layout — {label}", "",
             f"{m['files']} files. Tokens estimated as characters / {CHARS_PER_TOKEN}; listing cost "
             f"{LIST_TOKENS_PER_ENTRY} tokens per entry (Grok Dropbox connector, measured).", "",
             "| Per file | min | p5 | median | p95 | max |", "|---|---|---|---|---|---|",
             f"| tokens | {t['min']:,} | {t['p5']:,} | {t['median']:,} | {t['p95']:,} | {t['max']:,} |", "",
             f"- In the 10k–30k target: **{m['share_in_target']:.0%}**; below: {m['share_below_target']:.0%}; "
             f"above: {m['share_above_target']:.0%}.",
             f"- Listing a folder: median {m['listing_tokens']['median_folder']:,} tokens, "
             f"largest {m['listing_tokens']['max_folder']:,} tokens.", "", "Largest files:", ""]
    lines += [f"- {b['tokens']:,} — `{b['path']}`" for b in m["biggest"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--library", required=True)
    ap.add_argument("--out", required=True, help="output path without extension")
    ap.add_argument("--label", default="library snapshot")
    a = ap.parse_args(argv)
    m = measure(a.library)
    with open(a.out + ".json", "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    with open(a.out + ".md", "w", encoding="utf-8", newline="\n") as f:
        f.write(to_markdown(m, a.label))
    print(to_markdown(m, a.label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
