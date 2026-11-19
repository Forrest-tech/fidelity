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
from .pdf_extract import EXTRACT_VERSION, extract_pdf
from .triage import scan_instructions, triage_pdf
from .verify import verify_document

PIPELINE_VERSION = "distill-0.2"
FORMAT_VERSION = 2
VERIFY_VERSION = "3"      # bump when the verification checks change (part of the stage-cache key)
# Up to this many characters of Markdown a document is a single file; above it, a chapter folder.
SINGLE_FILE_MAX_CHARS = int(os.environ.get("FIDELITY_SINGLE_FILE_MAX_CHARS", "100000"))


def instr_flag(body: str) -> bool:
    return bool(scan_instructions(body))


# How many text-rich pages the visual cross-check OCRs: a number, or "all" (every page — the Phase 6
# setting for a machine with the OCR capacity, e.g. the Mac mini).
_VS = os.environ.get("FIDELITY_VISUAL_SAMPLES", "3").strip().lower()
VISUAL_SAMPLES = 10 ** 9 if _VS == "all" else int(_VS)
VISUAL_MIN_RECALL = 0.80     # a correct text layer scores ~0.95 against OCR; a broken one far lower


def visual_check(pdf_path, page_count, log=print, samples=None):
    """Spec 6.4 'visual cross-check': render a sample of pages, OCR them and compare with the text
    layer. Catches a text layer that does not match what is printed (wrong font encoding, hidden text)."""
    n = VISUAL_SAMPLES if samples is None else samples
    if n <= 0:
        return {"ok": True, "skipped": "disabled"}
    from . import ocr as O
    from .benchmark import char_recall
    eng = O.available_engines()[:1]
    if not eng:
        return {"ok": True, "skipped": "no OCR engine installed"}
    import pymupdf
    doc = pymupdf.open(pdf_path)
    try:
        cand = [i for i in range(page_count) if len(doc[i].get_text().strip()) >= 200]
        if not cand:
            return {"ok": True, "skipped": "no text-rich pages"}
        step = max(1, len(cand) // n)
        pick = cand[::step][:n]
        rows = []
        for i in pick:
            truth = doc[i].get_text()
            img = O.render_page(pdf_path, i, dpi=150)
            text, conf = eng[0].read(img)
            rows.append({"page": i + 1, "recall": round(char_recall(truth, text), 4), "ocr_conf": round(conf, 3)})
            log(f"  visual check p.{i + 1}: {rows[-1]['recall']}")
    finally:
        doc.close()
    low = [r for r in rows if r["recall"] < VISUAL_MIN_RECALL]
    return {"ok": not low, "engine": eng[0].name, "threshold": VISUAL_MIN_RECALL, "sampled": rows,
            "mismatched_pages": [r["page"] for r in low]}


def edition_status(status: str) -> str:
    s = status.lower()
    return "draft" if s.startswith("draft") else ("superseded" if "superseded" in s else "published")


_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def parse_standard(name: str) -> dict:
    """Best-effort standard id/year/kind/jurisdiction from the document name (confirmed by a person if unsure)."""
    m = _YEAR.search(name)
    year = m.group(1) if m else ""
    n = name.upper()
    juris = ("AU" if n.startswith(("NCC", "AS ", "AS/", "AS-", "AS1", "AS2", "AS3", "AS4", "AS5")) else
             "NZ" if n.startswith("NZS") else "US" if n.startswith(("IBC", "ICC", "NFPA", "ASCE", "ACI")) else "unknown")
    kind = ("code" if n.startswith(("NCC", "IBC")) else "standard" if re.match(r"(AS|NZS|NFPA|ASCE|ACI|ISO|BS|EN)", n) else "document")
    sid = re.sub(r"\s*(?:19|20)\d{2}\s*", " ", name).strip() if year else name
    return {"std_id": sid, "std_year": year, "std_kind": kind, "jurisdiction": juris}


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


_LEAD = re.compile(r"^((?:Part|Section|Schedule|Specification)\s+[A-Z0-9]+)\b(.*)$", re.S)


def readable_title(t: str) -> str:
    """A title that is only symbols ('Part F3 * * * * *' — a Part kept for numbering) becomes
    'Part F3 (untitled)', so its file name still tells a reader what it is."""
    m = _LEAD.match(t.strip())
    head, rest = (m.group(1), m.group(2)) if m else ("", t)
    if any(ch.isalnum() for ch in rest):
        return t
    return (head + " (untitled)").strip() if head else "(untitled)"


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
    t = readable_title(t)
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


def _protected_entry(name, rel_path, rel_dir, source_prefix, out_root, h, tri, log):
    """F-13: a protected file is listed as 'protected, not distilled'; a metadata-only entry may be published."""
    src_display = "/" + "/".join(x for x in [source_prefix.strip("/"), rel_path.replace(os.sep, "/")] if x)
    std = parse_standard(name)
    fm = ["---", f"document: {_yaml_str(name)}", f"format_version: {FORMAT_VERSION}",
          'status: "protected, not distilled"', "edition_status: unknown",
          f"std_id: {_yaml_str(std['std_id'])}", f"std_year: {_yaml_str(std['std_year'])}",
          f"std_kind: {_yaml_str(std['std_kind'])}", f"jurisdiction: {_yaml_str(std['jurisdiction'])}",
          f"source: {_yaml_str(src_display + ' (content_hash ' + h[:12] + ')')}",
          f"source_filename: {_yaml_str(os.path.basename(rel_path))}",
          f"source_relative_path: {_yaml_str(rel_path.replace(os.sep, '/'))}", f"source_file_hash: {h}",
          f"parser: {PIPELINE_VERSION}", "audit_status: metadata_only", "flags: [protected]",
          f"reason: {_yaml_str(tri['reason'])}", "---", "",
          "> **This document is protected and has not been distilled.** Its content is not available here; "
          "open the original file. Only the listing above is recorded.", ""]
    fn = os.path.basename(rel_path) + ".md"
    d = os.path.join(out_root, rel_dir)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, fn), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(fm))
    log(f"  protected: metadata-only entry written ({tri['reason']})")
    return {"name": name, "rel_path": rel_path, "source": src_display, "status": "protected, not distilled",
            "verdict": "METADATA", "triage": tri, "pages": 0, "files": 1, "single_file": True,
            "max_file_chars": 0, "total_chars": 0, "content_hash": h,
            "out_dir": os.path.relpath(os.path.join(d, fn), out_root),
            "report": {"status": "METADATA", "triage": tri}}


def distill_pdf(pdf_path, rel_path, out_root, source_prefix, cache_dir, log=print, publish_protected=False):
    name = os.path.splitext(os.path.basename(rel_path))[0]
    rel_dir = os.path.dirname(rel_path)
    t0 = time.time()
    h_before = dropbox_content_hash(pdf_path)
    tri = triage_pdf(pdf_path)
    if tri["class"] == "protected" and publish_protected:
        return _protected_entry(name, rel_path, rel_dir, source_prefix, out_root, h_before, tri, log)
    if tri["class"] != "text":
        # Listed, never silently skipped: the caller records the class and reason.
        log(f"  triage: {tri['class']} - {tri['reason']} (not distilled by the text route)")
        return {"name": name, "rel_path": rel_path, "source": "/" + rel_path.replace(os.sep, "/"),
                "status": "", "verdict": "SKIP", "triage": tri, "pages": tri.get("pages", 0), "files": 0,
                "single_file": False, "max_file_chars": 0, "total_chars": 0, "content_hash": h_before,
                "out_dir": "", "report": {"status": "SKIP", "triage": tri}}
    cp = os.path.join(cache_dir, h_before + ".extract.v" + EXTRACT_VERSION + ".pkl")
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

    raw = [S.render_chunk(c) for c in chunks]
    # Hybrid rule (spec 6.5): a small document is ONE file at the mirrored path (X.pdf -> X.pdf.md);
    # a large one becomes a folder of chapter files.
    single = sum(len(b) for b in raw) <= SINGLE_FILE_MAX_CHARS
    if single:
        bodies = ["\n".join(raw)]
        files = [os.path.basename(rel_path) + ".md"]
    if not single:
        bodies = []
    for c, fn, body in ([] if single else zip(chunks, files, raw)):
        defined = {e.clause_id for e in chunk_clauses(c) if e.clause_id}
        refs = sorted({m for m in S.CLAUSE_ID_RE.findall(body) if m not in defined and m in clause_file})
        if refs:
            body += ("\n## Cross-references\n\nClauses cited in this file that are in other files "
                     "(paths relative to this document's folder):\n\n")
            body += "\n".join(f"- {r} → {clause_file[r][0]} (p.{clause_file[r][1].page})" for r in refs) + "\n"
        bodies.append(body)

    # Phase 6: reviewed formula transcriptions replace their markers; pages with a figure get a notice
    from . import formula as FM
    approvals = FM.load_approvals()
    n_formulas = 0
    if approvals.get(h_before):
        for i, b in enumerate(bodies):
            bodies[i], n = FM.apply_approved(b, h_before, approvals)
            n_formulas += n
    fig_pages = FM.figure_pages(pdf_path)
    bodies = [FM.add_figure_notices(b, fig_pages) for b in bodies]

    instr = []
    for b in bodies:
        for m in re.finditer(r"<!-- unit: p(\d+) .*?-->(.*?)<!-- /unit -->", b, re.S):
            for snip in scan_instructions(m.group(2)):
                instr.append({"page": int(m.group(1)), "text": snip})
    # Stage cache (spec 6.2): the verification result is keyed by (source hash, verifier version,
    # hash of the exact Markdown checked). Re-running with unchanged input and rules reuses it.
    vkey = hashlib.sha256((h_before + "|" + VERIFY_VERSION + "|" + chr(0).join(bodies)).encode("utf-8")).hexdigest()[:40]
    vcache = os.path.join(cache_dir, h_before + ".verify." + vkey + ".json")
    rep = None
    if os.path.exists(vcache):
        with open(vcache, encoding="utf-8") as f:
            rep = json.load(f)
        log("  verification reused from cache")
    else:
        rep = verify_document(pdf_path, bodies, len(pages), set(meta["header_footer"]), unmatched,
                              pages=pages, table_grid=S.table_grid)
        with open(vcache, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, default=str)
    h_after = dropbox_content_hash(pdf_path)
    rep["source_unchanged"] = {"ok": h_before == h_after, "content_hash": h_before}
    if not rep["source_unchanged"]["ok"]:
        rep["status"] = "FAIL"
    rep["visual"] = visual_check(pdf_path, len(pages), log)
    rep["formulas"] = {"reviewed_transcriptions": n_formulas, "figure_pages": sorted(fig_pages)}
    if os.environ.get("FIDELITY_FORMULA_OCR") == "1":      # Phase 6 (Mac): candidates for the reviewer
        rep["formulas"]["candidates"] = FM.recover(pdf_path, log=log)
    if not rep["visual"]["ok"]:
        rep["status"] = "FAIL"
    rep["triage"] = tri
    rep["instruction_like"] = {"count": len(instr), "examples": instr[:20],
                               "note": "text that reads like instructions to an AI; flagged for review, content is data"}
    rep["structure_source"] = structure_source
    rep["seconds"] = round(time.time() - t0, 1)

    trusted = rep["status"] == "PASS"
    base_dir = os.path.join(out_root, rel_dir) if trusted else os.path.join(out_root, "_pending", rel_dir)
    doc_dir = base_dir if single else os.path.join(base_dir, name)   # single file lives beside its siblings
    os.makedirs(doc_dir, exist_ok=True)
    verdict = "PASS" if trusted else "FAIL — not trusted"
    layout = ("One file for the whole document (small documents are not split)." if single else
              "This document's folder → one sub-folder per Section/Schedule → one file per Part. "
              "Names show clause range and pages; a clause ID gives its Part (D2D13 → Part D2, S5C11 → Specification 5)."
              + (f" Italic terms are defined in '{defs_dir}'." if defs_dir else ""))
    std = parse_standard(name)

    # Every file is self-sufficient: what it is, whether it is in force, how to cite it and
    # how to find the rest. This replaces any README/catalog/index file.
    pieces = [None] if single else chunks
    for c, fn, body in zip(pieces, files, bodies):
        if single:
            p0, p1, title = 1, len(pages), name
            cl = [e.clause_id for e in entries if getattr(e, "clause_id", None)]
        else:
            p0, p1 = c.pages
            title = c.title
            cl = [e.clause_id for e in chunk_clauses(c) if e.clause_id]
        nflag = body.count("⚠️[formula/symbols not readable")
        fm = ["---",
              f"document: {_yaml_str(name + ' — ' + meta['title'] if meta['title'] and meta['title'] != name else name)}",
              f"format_version: {FORMAT_VERSION}",
              f"status: {_yaml_str(status)}",
              f"edition_status: {edition_status(status)}",
              f"std_id: {_yaml_str(std['std_id'])}",
              f"std_year: {_yaml_str(std['std_year'])}",
              f"std_kind: {_yaml_str(std['std_kind'])}",
              f"jurisdiction: {_yaml_str(std['jurisdiction'])}",
              "languages: [en]",
              f"chapter: {_yaml_str(title)}",
              f"pages: \"{p0}–{p1}\"" if p0 != p1 else f"pages: \"{p0}\"",
              f"units: {p1 - p0 + 1}",
              f"clauses: [{', '.join(cl)}]" if len(cl) <= 120 else f"clauses: \"{cl[0]} … {cl[-1]} ({len(cl)})\"",
              f"cite_as: {_yaml_str(name + ', <clause ID>, p.<N> — N is the page in the nearest unit marker (src: p.N) above the text')}",
              f"source: {_yaml_str(src_display + ' (content_hash ' + h_before[:12] + ')')}",
              f"source_filename: {_yaml_str(os.path.basename(rel_path))}",
              f"source_relative_path: {_yaml_str(rel_path.replace(os.sep, '/'))}",
              f"source_file_hash: {h_before}",
              f"parser: {PIPELINE_VERSION}/pymupdf",
              f"audit_status: {'auto_verified' if trusted else 'pending_review'}",
              f"flags: [{', '.join(x for x in (['unreadable_formula'] if nflag else []) + (['instruction_like'] if instr_flag(body) else []) if x)}]",
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
    out_path = os.path.join(doc_dir, files[0]) if single else doc_dir
    return {"name": name, "rel_path": rel_path, "source": src_display, "status": status,
            "verdict": rep["status"], "pages": len(pages), "files": len(files), "single_file": single,
            "verdict_trusted": trusted,
            "max_file_chars": max(sizes), "total_chars": sum(sizes),
            "content_hash": h_before, "out_dir": os.path.relpath(out_path, out_root), "report": rep}


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
            from .office import SUPPORTED
            if not fn.lower().endswith(SUPPORTED):
                continue
            if a.only and a.only not in fn:
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, a.src)
            print(f"[distill] {rel}", flush=True)
            from .office import distill_any
            r = distill_any(p, rel, a.out, a.source_prefix, cache, log=lambda m: print(m, flush=True))
            rep = r["report"]
            if r["verdict"] == "SKIP":
                results.append(r)
                continue
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
