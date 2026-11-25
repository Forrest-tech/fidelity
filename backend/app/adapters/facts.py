# -*- coding: utf-8 -*-
"""Library facts for adapter packs (spec F-19, 6.6), read from the published Markdown's front matter.

Nothing here is typed by hand: counts, editions held, drafts, chapter folders and flagged documents
come from the files themselves, so a regenerated pack never states a stale fact.
"""
from __future__ import annotations

import collections
import os
import re

_KV = re.compile(r'^([a-z_]+):\s*(.*)$')


def _longpath(p: str) -> str:
    p = os.path.abspath(p)
    return "\\\\?\\" + p if os.name == "nt" and not p.startswith("\\\\?\\") else p


def front_matter(path: str) -> dict:
    """Front matter of one file as plain strings (quotes removed); {} when there is none."""
    with open(_longpath(path), encoding="utf-8", errors="replace") as f:
        head = f.read(6000)
    if not head.startswith("---"):
        return {}
    end = head.find("\n---", 3)
    out = {}
    for line in head[3:end if end > 0 else len(head)].splitlines():
        m = _KV.match(line.strip())
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] == '"':
                v = v[1:-1].replace('\\"', '"')
            out[m.group(1)] = v
    return out


_RANGE = re.compile(r"\[([A-Z][A-Z0-9]*)(?:–([A-Z][A-Z0-9]*))?\]")
_PAGES = re.compile(r" p(\d+)(?:-(\d+))?\.md$")


def folder_map(doc_path: str, files: list) -> list:
    """Sub-folders of a chapter-folder document with the clause and page range each covers, read
    from the chapter file names, e.g. ('10 Section D Access and egress/', 'D1O1', 'S15C6', 212, 267, 7)."""
    groups = {}
    for f in files:
        rest = f[len(doc_path):]
        sub = rest.split("/")[0] + "/" if "/" in rest else ""
        g = groups.setdefault(sub, {"first": "", "last": "", "p0": None, "p1": None, "n": 0})
        g["n"] += 1
        name = rest.split("/")[-1]
        m = _RANGE.search(name)
        if m:
            g["first"] = g["first"] or m.group(1)
            g["last"] = m.group(2) or m.group(1)
        p = _PAGES.search(name)
        if p:
            a, b = int(p.group(1)), int(p.group(2) or p.group(1))
            g["p0"] = a if g["p0"] is None else min(g["p0"], a)
            g["p1"] = b if g["p1"] is None else max(g["p1"], b)
    return [{"folder": k, **v} for k, v in sorted(groups.items())]


def _flags(fm: dict) -> set:
    return {f.strip() for f in fm.get("flags", "").strip("[]").split(",") if f.strip()}


def scan(root: str) -> dict:
    """Walk a local copy of the library. Paths are reported relative to `root` with '/'."""
    docs = {}                 # (relative source path) -> document record
    files = 0
    top = collections.Counter()
    for dirpath, dirs, fns in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("_"))      # _pending, _staging are not library
        for fn in sorted(fns):
            if not fn.endswith(".md"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            fm = front_matter(full)
            files += 1
            top[rel.split("/")[0] if "/" in rel else "."] += 1
            key = fm.get("source_relative_path") or rel
            d = docs.setdefault(key, {
                "document": fm.get("document", "").split(" — ")[0] or os.path.splitext(fn)[0],
                "source_filename": fm.get("source_filename", ""),
                "std_id": fm.get("std_id", ""), "std_year": fm.get("std_year", ""),
                "std_kind": fm.get("std_kind", ""), "status": fm.get("status", ""),
                "edition_status": fm.get("edition_status", ""), "jurisdiction": fm.get("jurisdiction", ""),
                "edition": fm.get("edition", ""), "superseded_by": fm.get("superseded_by", ""),
                "files": [], "flags": set(), "audit": set()})
            d["files"].append(rel)
            d["flags"] |= _flags(fm)
            d["audit"].add(fm.get("audit_status", ""))
    out_docs = []
    for key, d in sorted(docs.items()):
        if len(d["files"]) == 1:
            path, layout = d["files"][0], "file"
        else:
            # the document folder sits beside where the source sits: <source dir>/<document folder>/...
            src_dir = os.path.dirname(key).replace(os.sep, "/")
            first = d["files"][0]
            # front matter keeps the source path in lower case ("as 3500/2021/…"); the library keeps the source's
            # case ("AS 3500/2021/…"): compare without case and keep the library's spelling
            inside = bool(src_dir) and first.lower().startswith(src_dir.lower() + "/")
            rest = first[len(src_dir) + 1:] if inside else first
            path = (first[:len(src_dir)] + "/" if inside else "") + rest.split("/")[0] + "/"
            layout = "folder"
        out_docs.append({**d, "source_relative_path": key, "path": path, "layout": layout,
                         "n_files": len(d["files"]), "flags": sorted(d["flags"]), "audit": sorted(d["audit"]),
                         "map": folder_map(path, sorted(d["files"])) if layout == "folder" else []})
    return {"files": files, "documents": out_docs, "top_folders": dict(sorted(top.items()))}


def summarise(lib: dict) -> dict:
    docs = lib["documents"]
    latest = {}
    for d in docs:
        sid = d["std_id"]
        if sid and not d["status"].upper().startswith("DRAFT") and d["std_year"]:
            if sid not in latest or d["std_year"] > latest[sid]["std_year"]:
                latest[sid] = d
    return {
        "files": lib["files"],
        "n_documents": len(docs),
        "top_folders": lib["top_folders"],
        "folders": [d for d in docs if d["layout"] == "folder"],
        "latest_editions": [latest[k] for k in sorted(latest)],
        # every edition the library holds, with the folder to open (2026-11-25: Grok said AS 3500.1:2018 was not
        # held because its folder is named "3500.1-2018 …" without "AS" and a file-name search missed it)
        "editions_held": sorted(({"edition": d["edition"], "edition_status": d["edition_status"],
                                  "superseded_by": d["superseded_by"], "path": d["path"]}
                                 for d in docs if d["edition"] and not d["status"].upper().startswith("DRAFT")),
                                key=lambda e: (e["edition"].split(":")[0], e["edition"], e["path"])),
        "drafts": [d for d in docs if d["status"].upper().startswith("DRAFT")],
        "unreadable_formulas": [d for d in docs if "unreadable_formula" in d["flags"]],
        "pending_review": [d for d in docs if "pending_review" in d["audit"]],
        "pending_by_folder": collections.Counter(
            d["path"].split("/")[0] if "/" in d["path"] else "." for d in docs if "pending_review" in d["audit"]
        ).most_common(),
        "protected": [d for d in docs if "protected" in d["flags"] or "metadata_only" in d["flags"]],
        "ocr": [d for d in docs if "ocr" in d["flags"]],
        "jurisdictions": sorted({d["jurisdiction"] for d in docs if d["jurisdiction"]}),
    }


def resolve(lib: dict, source_filename: str):
    """The library path of a document named by its source file (follows it into a chapter folder)."""
    want = source_filename.lower()
    for d in lib["documents"]:
        names = {d["source_filename"], os.path.basename(d["source_relative_path"])}
        names |= {os.path.splitext(n)[0] for n in names}
        if want in {n.lower() for n in names if n}:
            return d
    return None
