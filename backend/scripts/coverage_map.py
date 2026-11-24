"""Coverage map (requirements v3 C-1): the documents NCC calls up, against the editions the library holds.

    python scripts/coverage_map.py <local copy of Md_Library> [--out ../docs/coverage/NCC2025.md] [--ncc "NCC 2025"]

Reads the national "Schedule 2 Referenced documents" tables of the distilled NCC volumes (the NCC's own list, an
official source) and the front matter of every library file (std_id, std_year). Prints and writes one row per
called-up document: held in that edition / held in another edition / not held.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys

LP = "\\\\?\\" if os.name == "nt" else ""
ROW = re.compile(r"^\| (?P<no>[^|]+?) \| (?P<date>[^|]*?) \| (?P<title>[^|]*?) \|(?P<rest>.*)\|\s*$")
STD = re.compile(r"^(?P<prefix>AS/NZS|AS|NZS|ISO|AS ISO|AS/NZS ISO|AS/NZS IEC|AS IEC)\s+(?P<num>[\w.]+)(?:\s+Part\s+(?P<part>[\w.]+))?",
                 re.I)


def norm_id(no: str) -> str | None:
    """'AS/NZS 3500 Part 1' -> 'AS/NZS 3500.1'; 'AS 1056 Part 1' -> 'AS 1056.1'; other documents -> None."""
    m = STD.match(no.strip())
    if not m:
        return None
    pid = m.group("prefix").upper().replace("AS ISO", "AS ISO")
    return f"{pid} {m.group('num')}" + (f".{m.group('part')}" if m.group("part") else "")


def key(std_id: str) -> str:
    """Compare standards regardless of AS vs AS/NZS (a standard became joint between editions)."""
    return re.sub(r"^(AS/NZS|AS|NZS)\s+", "", std_id.strip(), flags=re.I).upper()


def referenced(library: str, ncc: str) -> list[dict]:
    rows = {}
    base = LP + os.path.abspath(os.path.join(library, ncc.split()[-1]))   # "2025" folder
    for r, _, fs in os.walk(base):
        rel = os.path.relpath(r, base).replace("\\", "/")
        # the national schedules only (a state's Schedule 2 lists its variations; reported separately later)
        if "Schedule 2 Referenced documents" not in rel or "/ss" in rel.lower():
            continue
        vol = rel.split("/")[0]
        for f in fs:
            if not f.endswith(".md"):
                continue
            for line in open(os.path.join(r, f), encoding="utf-8"):
                m = ROW.match(line)
                if not m or m.group("no").strip() in ("No.", "---"):
                    continue
                sid = norm_id(m.group("no"))
                year = re.search(r"(19|20)\d{2}", m.group("date") or "")
                if not sid or not year:
                    continue
                clauses = sorted({c.strip() for c in m.group("rest").split("|") for c in c.split(",")
                                  if c.strip() and c.strip() != "N/A"})
                k = (key(sid), year.group(0))
                e = rows.setdefault(k, {"std": sid, "year": year.group(0), "title": m.group("title").strip(),
                                        "clauses": set(), "volumes": set()})
                e["clauses"].update(clauses)
                e["volumes"].add(vol)
    return list(rows.values())


def held(library: str) -> dict:
    """{standard key: {year: [paths]}} from the front matter of every library file (first 40 lines)."""
    out = collections.defaultdict(lambda: collections.defaultdict(set))
    base = LP + os.path.abspath(library)
    for r, _, fs in os.walk(base):
        for f in fs:
            if not f.endswith(".md"):
                continue
            sid = year = None
            with open(os.path.join(r, f), encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i > 40:
                        break
                    if line.startswith("std_id:"):
                        sid = line.split(":", 1)[1].strip().strip('"')
                    elif line.startswith("std_year:"):
                        year = line.split(":", 1)[1].strip().strip('"')
            if sid and year:
                doc = os.path.relpath(r, base).replace("\\", "/").split("/")
                out[key(sid)][year].add("/".join(doc[:3]))
    return out


def build(library: str, ncc: str = "NCC 2025") -> list[dict]:
    have = held(library)
    rows = []
    for e in sorted(referenced(library, ncc), key=lambda x: (x["std"], x["year"])):
        h = have.get(key(e["std"]), {})
        status = "held" if e["year"] in h else ("other edition" if h else "not held")
        rows.append({**e, "clauses": sorted(e["clauses"]), "volumes": sorted(e["volumes"]), "status": status,
                     "held_years": sorted(h)})
    return rows


def render(rows: list[dict], ncc: str) -> str:
    c = collections.Counter(r["status"] for r in rows)
    lines = [f"# Coverage map — documents {ncc} calls up vs the library (requirements v3 C-1)", "",
             f"Source: the national *Schedule 2 Referenced documents* tables of the distilled {ncc} volumes. "
             "Library: front matter (`std_id`, `std_year`) of every file. Regenerate with `scripts/coverage_map.py`.", "",
             f"**{len(rows)} standards called up** · held in that edition **{c['held']}** · held only in another edition "
             f"**{c['other edition']}** · not held **{c['not held']}**", "",
             "| Standard | Edition called up | Status | Library holds | NCC clauses (sample) |", "|---|---|---|---|---|"]
    order = {"other edition": 0, "not held": 1, "held": 2}
    for r in sorted(rows, key=lambda r: (order[r["status"]], r["std"])):
        cl = ", ".join(r["clauses"][:6]) + (" …" if len(r["clauses"]) > 6 else "")
        lines.append(f"| {r['std']} | {r['year']} | {r['status']} | {', '.join(r['held_years']) or '—'} | {cl} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("library")
    ap.add_argument("--ncc", default="NCC 2025")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    rows = build(a.library, a.ncc)
    text = render(rows, a.ncc)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w", encoding="utf-8", newline="\n").write(text)
    c = collections.Counter(r["status"] for r in rows)
    print(f"{len(rows)} called up: held {c['held']}, other edition {c['other edition']}, not held {c['not held']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
