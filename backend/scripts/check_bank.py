"""Ground the acceptance question bank on the sources (plan section 2, owner decision 2).

Every question carries `ground` entries: {"doc": source PDF name, "page": N, "contains": [...]}
(optionally "unreadable": true when the page must carry the unreadable-formula marker). The check
passes only when every string is on that page of the ORIGINAL PDF and in that page's unit of the
published Markdown — so no expected answer rests on anyone's memory.

    python scripts/check_bank.py --bank ../docs/acceptance/question_bank.json \
        --sources ../data/work/src/2025 --library ../data/work/transfer_md_snapshot
    python scripts/check_bank.py find --sources ... "NCC 2025 Volume One.pdf" "D3D14"   # pages containing a text
"""
import argparse
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.adapters.facts import front_matter  # noqa: E402

_UNIT = re.compile(r"<!-- unit: p\d+ \| src: p\.(\d+) .*?-->(.*?)<!-- /unit -->", re.S)
_DASH = str.maketrans({"–": "-", "—": "-", "‑": "-", "−": "-", " ": " ", " ": " ", " ": " ",
                       " ": " ", "’": "'", "‘": "'", "“": '"', "”": '"'})


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_DASH)
    s = re.sub(r"[*_|`]", " ", s)                       # Markdown emphasis and table pipes
    return re.sub(r"\s+", " ", s).strip().lower()


def _lp(p):
    p = os.path.abspath(p)
    return "\\\\?\\" + p if os.name == "nt" else p


class Sources:
    def __init__(self, folder):
        self.folder, self.cache = folder, {}

    def path(self, doc):
        for dp, _, fns in os.walk(self.folder):
            if doc in fns:
                return os.path.join(dp, doc)
        raise FileNotFoundError(doc)

    def page(self, doc, n):
        key = (doc, n)
        if key not in self.cache:
            import pymupdf
            with pymupdf.open(self.path(doc)) as d:
                self.cache[key] = norm(d[n - 1].get_text()) if 1 <= n <= d.page_count else ""
        return self.cache[key]

    def find(self, doc, text):
        import pymupdf
        t = norm(text)
        with pymupdf.open(self.path(doc)) as d:
            return [i + 1 for i in range(d.page_count) if t in norm(d[i].get_text())]


class Library:
    def __init__(self, root):
        self.units = {}                   # (doc, page) -> [(file, text)]
        self.clauses = {}                 # (doc, clause) -> file
        self.paths = []                   # every library file (relative)
        self.edition = {}                 # doc -> {edition_status}
        for dp, dirs, fns in os.walk(root):
            dirs[:] = [x for x in dirs if not x.startswith("_")]
            for fn in fns:
                if not fn.endswith(".md"):
                    continue
                full = os.path.join(dp, fn)
                fm = front_matter(full)
                doc = fm.get("source_filename", "")
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                self.paths.append(rel)
                self.edition.setdefault(doc, set()).add(fm.get("edition_status", ""))
                with open(_lp(full), encoding="utf-8", errors="replace") as f:
                    body = f.read()
                for m in _UNIT.finditer(body):
                    self.units.setdefault((doc, int(m.group(1))), []).append((rel, norm(m.group(2))))
                for c in fm.get("clauses", "").strip("[]").split(","):
                    if c.strip():
                        self.clauses.setdefault((doc, c.strip()), rel)


def check(bank, src: Sources, lib: Library):
    results = []
    for q in bank["questions"]:
        problems = []
        if not q.get("ground"):
            problems.append("no ground entries")
        for g in q.get("ground", []):
            if "absent_in_library" in g:           # trap: the library must NOT hold this document
                hit = [p for p in lib.paths if g["absent_in_library"].lower() in p.lower()]
                if hit:
                    problems.append(f"'{g['absent_in_library']}' is in the library: {hit[0]}")
                continue
            if "edition_status" in g and "page" not in g:
                if g["edition_status"] not in lib.edition.get(g["doc"], set()):
                    problems.append(f"{g['doc']}: edition_status {g['edition_status']} not found")
                continue
            doc, page = g["doc"], g["page"]
            pdf = src.page(doc, page)
            md = " ".join(t for _, t in lib.units.get((doc, page), []))
            if not md:
                problems.append(f"{doc} p.{page}: no unit in the library")
            for s in g.get("contains", []):
                if norm(s) not in pdf:
                    problems.append(f"{doc} p.{page}: '{s}' not on the source page")
                if md and norm(s) not in md:
                    problems.append(f"{doc} p.{page}: '{s}' not in the published Markdown")
            if g.get("unreadable") and "not readable" not in md:
                problems.append(f"{doc} p.{page}: unreadable-formula marker missing")
            if g.get("clause") and (doc, g["clause"]) not in lib.clauses:
                problems.append(f"{doc}: clause {g['clause']} not listed in any file's front matter")
        results.append({"id": q["id"], "ok": not problems, "problems": problems})
    return results


def main(argv=None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", default=os.path.join(here, "..", "..", "data", "work", "src", "2025"))
    ap.add_argument("--library", default=os.path.join(here, "..", "..", "data", "work", "transfer_md_snapshot"))
    ap.add_argument("--bank", default=os.path.join(here, "..", "..", "docs", "acceptance", "question_bank.json"))
    if argv and argv[0] == "find":
        ap.add_argument("cmd")
        ap.add_argument("doc")
        ap.add_argument("text")
        a = ap.parse_args(argv)
        print(Sources(a.sources).find(a.doc, a.text))
        return 0
    a = ap.parse_args(argv)
    with open(a.bank, encoding="utf-8") as f:
        bank = json.load(f)
    res = check(bank, Sources(a.sources), Library(a.library))
    bad = [r for r in res if not r["ok"]]
    for r in bad:
        print(f"Q{r['id']}: " + "; ".join(r["problems"]))
    print(f"{len(res) - len(bad)}/{len(res)} questions grounded")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
