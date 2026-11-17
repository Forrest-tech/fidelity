# -*- coding: utf-8 -*-
"""Distill a local mirror of a source folder into chapter-split Markdown.

  python -m app.distill.run --src <local mirror root> --out <output root> \
         [--source-prefix /2025] [--manifest manifest.json] [--only NAME]

The source folder is opened read-only. The output root receives, mirroring the
source tree:  <rel dir>/<document name>/<sub-folder>/<document name> · NNN <chapter>.md.
No auxiliary files (no README, catalog or index; spec F-6): folder and file names are the
index. A document whose verification fails is written under _pending/ instead, so it
never enters the trusted tree.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pickle
import re
import sys
import time

from . import structure as S
from .pdf_extract import extract_pdf
from .verify import verify_document

PIPELINE_VERSION = "distill-0.1"


def dropbox_content_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(4 * 1024 * 1024)
            if not b:
                break
            h.update(hashlib.sha256(b).digest())
    return h.hexdigest()


def longpath(p: str) -> str:
    """Windows extended-length path so deep output trees never hit the 260-char limit."""
    p = os.path.abspath(p)
    prefix = "\\\\?\\"
    return p if os.name != "nt" or p.startswith(prefix) else prefix + p


def _safe(name: str, limit=110) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:limit].rstrip(" .")


def doc_status(name: str) -> str:
    n = name.lower()
    if "pcd" in n or "public comment" in n:
        return "DRAFT — Public Comment Draft, not in force"
    if "draft" in n or "preview" in n:
        return "DRAFT — preview draft, not in force"
    return "Published edition"


def _term_letters(c: S.Chunk) -> str:
    """Glossary-style chunk: first letters of the defined terms it holds, e.g. 'A–C'."""
    letters = []
    for _, _, it in c.items:
        sp = getattr(it, "spans", None)
        if not sp or getattr(it, "kind", "") != "row":
            continue
        first = next((s for s in sp if s.text.strip()), None)
        t = first.text.strip() if first else ""
        if first and first.bold and t.endswith(":") and t[:1].isalpha() and not re.match(r"(Table|Figure|Note)", t):
            letters.append(t[0].upper())
    if len(letters) < 5:
        return ""
    return letters[0] if letters[0] == letters[-1] else f"{letters[0]}–{letters[-1]}"


def chunk_path(c: S.Chunk, l1_order: dict, doc_name: str = "") -> str:
    """Self-describing relative path inside the document folder — the folder and file
    names ARE the index (no auxiliary files):
        <NN Section/Schedule title>/<seq> <Part title> [first–last clause] p<from>-<to>.md"""
    sub = ""
    if c.l1 is not None and (c.l2 is not None or c.intro):
        sub = f"{l1_order[id(c.l1)]:02d} {_safe(c.l1.title, 48)}"
    if c.l2 is not None:
        t = c.l2.title
    elif c.l1 is not None:
        t = "Introduction" if c.intro else c.l1.title
    else:
        t = "Front matter"
    t = _safe(t, 64)          # fixed cap: keeps every path well under Windows/Dropbox limits
    ids = [e.clause_id for e in chunk_clauses(c) if e.clause_id]
    part = getattr(c, "part", None)
    if ids:
        t += f" [{ids[0]}–{ids[-1]}]" if ids[0] != ids[-1] else f" [{ids[0]}]"
    elif part and part[1] > 1:
        letters = _term_letters(c)
        t += f" ({letters})" if letters else f" (part {part[0]} of {part[1]})"
    p0, p1 = c.pages
    t += f" p{p0}-{p1}" if p0 != p1 else f" p{p0}"
    prefix = _safe(doc_name, 60) + " · " if doc_name else ""   # storage search matches file names only
    fn = f"{prefix}{c.seq:03d} {t}.md"
    return f"{sub}/{fn}" if sub else fn


def _yaml_str(s):
    return json.dumps(s, ensure_ascii=False)


def chunk_clauses(c: S.Chunk):
    out = []
    for _, _, it in c.items:
        if it is not None and getattr(it, "kind", "") == "heading" and it.toc.level >= 3:
            out.append(it.toc)
    return out


def distill_pdf(pdf_path, rel_path, out_root, source_prefix, cache_dir, log=print):
    name = os.path.splitext(os.path.basename(rel_path))[0]
    rel_dir = os.path.dirname(rel_path)
    t0 = time.time()
    h_before = dropbox_content_hash(pdf_path)
    cp = os.path.join(cache_dir, h_before + ".extract.pkl")
    if os.path.exists(cp):
        with open(cp, "rb") as f:
            pages, meta = pickle.load(f)
    else:
        pages, meta = extract_pdf(pdf_path)
        with open(cp, "wb") as f:
            pickle.dump((pages, meta), f)
    log(f"  extracted {len(pages)} pages in {time.time() - t0:.0f}s")

    entries = S.normalize_toc(meta["toc"])
    structure_source = "bookmarks"
    if not S.toc_is_usable(entries, len(pages)):
        entries = S.fallback_toc(pages)
        structure_source = "heading-detection (bookmarks unusable)"
    unmatched = S.match_headings(pages, entries)
    chunks = S.build_chunks(pages)

    status = doc_status(name)
    src_display = "/".join(x for x in [source_prefix.strip("/"), rel_path.replace(os.sep, "/")] if x)
    src_display = "/" + src_display
    generated = _dt.datetime.now().astimezone().isoformat(timespec="seconds")

    # clause -> file map (for cross references and the clause index)
    files = []
    clause_file = {}
    l1_order = {}
    for c in chunks:
        if c.l1 is not None and id(c.l1) not in l1_order:
            l1_order[id(c.l1)] = len(l1_order) + 1
    defs_dir = next((f"{n:02d} {_safe(c.l1.title, 48)}" for c in chunks if c.l1 is not None
                     and "definitions" in c.l1.title.lower()
                     for n in [l1_order[id(c.l1)]] if c.l2 is not None or c.intro), None)
    for c in chunks:
        fn = chunk_path(c, l1_order, name)
        files.append(fn)
        for e in chunk_clauses(c):
            if e.clause_id and e.clause_id not in clause_file and not re.match(S.STATE_RE + " ", e.title):
                clause_file[e.clause_id] = (fn, e)

    bodies = []
    for c, fn in zip(chunks, files):
        body = S.render_chunk(c)
        defined = {e.clause_id for e in chunk_clauses(c) if e.clause_id}
        refs = sorted({m for m in S.CLAUSE_ID_RE.findall(body) if m not in defined and m in clause_file})
        if refs:
            body += ("\n## Cross-references\n\nClauses cited in this file that are in other files "
                     "(paths relative to this document's folder):\n\n")
            body += "\n".join(f"- {r} → {clause_file[r][0]} (p.{clause_file[r][1].page})" for r in refs) + "\n"
        bodies.append(body)

    rep = verify_document(pdf_path, bodies, len(pages), set(meta["header_footer"]), unmatched)
    h_after = dropbox_content_hash(pdf_path)
    rep["source_unchanged"] = {"ok": h_before == h_after, "content_hash": h_before}
    if not rep["source_unchanged"]["ok"]:
        rep["status"] = "FAIL"
    rep["structure_source"] = structure_source
    rep["seconds"] = round(time.time() - t0, 1)

    trusted = rep["status"] == "PASS"
    doc_dir = os.path.join(out_root, rel_dir, name) if trusted else os.path.join(out_root, "_pending", rel_dir, name)
    os.makedirs(doc_dir, exist_ok=True)
    verdict = "PASS" if trusted else "FAIL — not trusted"
    layout = ("This document's folder → one sub-folder per Section/Schedule → one file per Part. "
              "Names show clause range and pages; a clause ID gives its Part (D2D13 → Part D2, S5C11 → Specification 5)."
              + (f" Italic terms are defined in '{defs_dir}'." if defs_dir else ""))

    # Every file is self-sufficient: what it is, whether it is in force, how to cite it and
    # how to find the rest. This replaces any README/catalog/index file.
    for c, fn, body in zip(chunks, files, bodies):
        p0, p1 = c.pages
        cl = [e.clause_id for e in chunk_clauses(c) if e.clause_id]
        nflag = body.count("⚠️[formula/symbols not readable")
        fm = ["---",
              f"document: {_yaml_str(name + ' — ' + meta['title'] if meta['title'] and meta['title'] != name else name)}",
              f"status: {_yaml_str(status)}",
              f"chapter: {_yaml_str(c.title)}",
              f"pages: \"{p0}–{p1}\"" if p0 != p1 else f"pages: \"{p0}\"",
              f"clauses: [{', '.join(cl)}]" if len(cl) <= 120 else f"clauses: \"{cl[0]} … {cl[-1]} ({len(cl)})\"",
              f"cite_as: {_yaml_str(name + ', <clause ID>, p.<N> — N is the page in the nearest unit marker (src: p.N) above the text')}",
              f"source: {_yaml_str(src_display + ' (content_hash ' + h_before[:12] + ')')}",
              f"verified: {_yaml_str(verdict + (f'; {nflag} formula(s) in this file marked ⚠️ are not readable — check the source page' if nflag else ''))}",
              f"layout: {_yaml_str(layout)}",
              "---", ""]
        banner = ""
        if status.startswith("DRAFT"):
            banner = f"> **{status.upper()}.** Do not cite this as the current NCC requirement.\n\n"
        fp = longpath(os.path.join(doc_dir, *fn.split("/")))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(fm) + banner + body)

    with open(os.path.join(cache_dir, h_before + ".report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    sizes = [len(b) for b in bodies]
    return {"name": name, "rel_path": rel_path, "source": src_display, "status": status,
            "verdict": rep["status"], "pages": len(pages), "files": len(files),
            "max_file_chars": max(sizes), "total_chars": sum(sizes),
            "content_hash": h_before, "out_dir": os.path.relpath(doc_dir, out_root), "report": rep}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-prefix", default="")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--only", default=None)
    a = ap.parse_args(argv)
    cache = a.cache or os.path.join(a.out, "..", "cache")
    os.makedirs(cache, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    results = []
    for root, _, fns in os.walk(a.src):
        for fn in sorted(fns):
            if not fn.lower().endswith(".pdf"):
                continue
            if a.only and a.only not in fn:
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, a.src)
            print(f"[distill] {rel}", flush=True)
            r = distill_pdf(p, rel, a.out, a.source_prefix, cache, log=lambda m: print(m, flush=True))
            rep = r["report"]
            print(f"  -> {r['verdict']} files={r['files']} max_file={r['max_file_chars']} chars "
                  f"recall={rep['chars']['recall']} numbers={rep['numbers']['recall']} "
                  f"headings_unmatched={rep['headings']['unmatched']} pages_ok={rep['pages']['ok']} "
                  f"agree={rep.get('agreement', {}).get('recall')}", flush=True)
            results.append(r)
    with open(os.path.join(cache, "last_run.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
