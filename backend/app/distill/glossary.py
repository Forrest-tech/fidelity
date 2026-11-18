# -*- coding: utf-8 -*-
"""Glossary learned from verified documents (spec F-14, correction layer 3).

Built from published Markdown whose front matter says `audit_status: auto_verified` (text-layer
documents that passed every check). It is used in one narrow place: where two OCR engines read a
word differently, and exactly one of the two readings is a known word, that reading is chosen.
It never introduces a value that no engine read, and every choice is logged.

    python -m app.distill.glossary build <published root> [--out data/glossary.json]
"""
from __future__ import annotations

import collections
import difflib
import json
import os
import re
import sys

MIN_COUNT = 3            # a word must appear this often in verified text to count as known
MAX_EDIT = 2             # the two readings may differ by at most this many characters
_TOKEN = re.compile(r"\S+")
_EDGE = re.compile(r"^[^\w]+|[^\w]+$")
_MARKUP = re.compile(r"<!--.*?-->|^---$|^\|[-| :]+\|$", re.M | re.S)

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_PATH = os.environ.get("FIDELITY_GLOSSARY") or os.path.join(_REPO, "data", "glossary.json")


def core(tok: str) -> str:
    """The word without surrounding punctuation ("load," -> "load", "(FRL)" -> "FRL")."""
    return _EDGE.sub("", tok)


def _verified_body(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0 or "audit_status: auto_verified" not in text[:end]:
        return None
    return _MARKUP.sub(" ", text[end + 4:])


def build(root: str) -> dict:
    counts = collections.Counter()
    docs = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith("_")]          # skip _pending, _staging ...
        for fn in files:
            if not fn.endswith(".md"):
                continue
            from .run import longpath
            with open(longpath(os.path.abspath(os.path.join(dirpath, fn))), encoding="utf-8", errors="replace") as f:
                body = _verified_body(f.read())
            if body is None:
                continue
            docs += 1
            counts.update(c for c in (core(t) for t in _TOKEN.findall(body)) if len(c) >= 2)
    words = {w: n for w, n in counts.items() if n >= MIN_COUNT}
    return {"documents": docs, "min_count": MIN_COUNT, "words": words}


_cache: dict = {}


def load(path: str | None = None) -> set:
    path = path or DEFAULT_PATH
    if path not in _cache:
        try:
            with open(path, encoding="utf-8") as f:
                _cache[path] = set(json.load(f)["words"])
        except (OSError, ValueError, KeyError):
            _cache[path] = set()
    return _cache[path]


def _edits(a: str, b: str) -> int:
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")


def _replace(text: str, spans: dict) -> str:
    out, last = [], 0
    for (s, e), new in sorted(spans.items()):
        out += [text[last:s], new]
        last = e
    return "".join(out + [text[last:]])


def resolve(a: str, b: str, known: set, names=("a", "b")):
    """Pick the glossary reading where the engines differ on single words.

    Returns (a2, b2, log). Only word-for-word replacements are considered; a reading is changed only
    when its counterpart is a known word, it is not, and they differ by <= MAX_EDIT characters.
    """
    if not known:
        return a, b, []
    ma, mb = list(_TOKEN.finditer(a)), list(_TOKEN.finditer(b))
    wa, wb = [m.group() for m in ma], [m.group() for m in mb]
    sa, sb, log = {}, {}, []
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "replace" or i2 - i1 != j2 - j1:
            continue
        for x, y in zip(range(i1, i2), range(j1, j2)):
            ta, tb = wa[x], wb[y]
            ca, cb = core(ta), core(tb)
            if ca == cb or not ca or not cb or _edits(ca, cb) > MAX_EDIT or min(len(ca), len(cb)) < 3:
                continue
            if any(ch.isdigit() for ch in ca + cb):      # numbers are never chosen from a glossary
                continue
            ka, kb = ca in known, cb in known
            if ka and not kb:
                sb[mb[y].span()] = tb.replace(cb, ca, 1)
                log.append({"rule": "glossary", "engine": names[1], "from": tb, "to": sb[mb[y].span()]})
            elif kb and not ka:
                sa[ma[x].span()] = ta.replace(ca, cb, 1)
                log.append({"rule": "glossary", "engine": names[0], "from": ta, "to": sa[ma[x].span()]})
    return _replace(a, sa), _replace(b, sb), log


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2 or argv[0] != "build":
        print(__doc__)
        return 2
    out = argv[argv.index("--out") + 1] if "--out" in argv else DEFAULT_PATH
    g = build(argv[1])
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=0, sort_keys=True)
    print(f"glossary: {len(g['words'])} words from {g['documents']} verified documents -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
