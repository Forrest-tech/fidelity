# -*- coding: utf-8 -*-
"""Drawings (spec F-12): title block, text annotations, a reference to the source sheet, and a
notice that spatial relationships must be read from the original. PDF sheets and DXF files.
"""
from __future__ import annotations

import json
import os
import re
import time

from . import run as R
from .structure import UNIT_CLOSE, unit_open

NOTICE = ("> **Drawing.** Only the text on this drawing is reproduced here. Dimensions, positions and other "
          "spatial relationships must be read from the original sheet.")

FIELDS = {
    "drawing_number": r"(?:drawing|dwg)\.?\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/._]{1,30})",
    "revision": r"\brev(?:ision)?\.?\s*[:\-]?\s*([A-Z0-9]{1,4})\b",
    "scale": r"\bscale\s*[:\-]?\s*(1\s*:\s*\d+(?:\s*@\s*A\d)?|NTS|N\.T\.S\.?)",
    "date": r"\bdate\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    "project": r"\bproject\s*(?:name)?\s*[:\-]\s*(.+)",
    "title": r"\b(?:drawing\s+)?title\s*[:\-]\s*(.+)",
}


def parse_title_block(lines) -> dict:
    """Fields found in the title-block text (bottom-right region); missing ones stay empty."""
    text = "\n".join(lines)
    out = {}
    for k, rx in FIELDS.items():
        m = re.search(rx, text, re.I)
        out[k] = m.group(1).strip() if m else ""
    return out


def _pdf_sheets(path):
    import pymupdf
    doc = pymupdf.open(path)
    try:
        for i, pg in enumerate(doc, 1):
            w, h = pg.rect.width, pg.rect.height
            block, notes = [], []
            for b in pg.get_text("dict")["blocks"]:
                for ln in b.get("lines", []):
                    t = " ".join("".join(s["text"] for s in ln["spans"]).split())
                    if not t:
                        continue
                    x0, y0 = ln["bbox"][0], ln["bbox"][1]
                    (block if x0 > w * 0.6 and y0 > h * 0.7 else notes).append(t)
            yield i, block, notes
    finally:
        doc.close()


def _dxf_sheets(path):
    import ezdxf
    doc = ezdxf.readfile(path)
    texts = []
    for e in doc.modelspace():
        t = ""
        if e.dxftype() == "TEXT":
            t = e.dxf.text
        elif e.dxftype() == "MTEXT":
            t = e.plain_text()
        elif e.dxftype() == "INSERT":
            for a in e.attribs:
                texts.append((a.dxf.tag, a.dxf.text))
            continue
        if t and t.strip():
            texts.append(("", " ".join(t.split())))
    block = [f"{tag}: {txt}" for tag, txt in texts if tag]       # block attributes = title block fields
    notes = [txt for tag, txt in texts if not tag]
    yield 1, block, notes


def distill_drawing(path, rel_path, out_root, source_prefix, cache_dir, log=print):
    t0 = time.time()
    name = os.path.splitext(os.path.basename(rel_path))[0]
    rel_dir = os.path.dirname(rel_path)
    h = R.dropbox_content_hash(path)
    src_display = "/" + "/".join(x for x in [source_prefix.strip("/"), rel_path.replace(os.sep, "/")] if x)
    sheets = list(_dxf_sheets(path) if path.lower().endswith(".dxf") else _pdf_sheets(path))
    parts, blocks = [], []
    for n, block, notes in sheets:
        tb = parse_title_block(block + notes)
        blocks.append(tb)
        rows = "\n".join(f"| {k.replace('_', ' ')} | {v or '—'} |" for k, v in tb.items())
        txt = (f"**Title block (sheet {n})**\n\n| Field | Value |\n|---|---|\n{rows}\n\n"
               + ("**Title block text:**\n\n" + "\n".join(f"- {b}" for b in block) + "\n\n" if block else "")
               + ("**Annotations:**\n\n" + "\n".join(f"- {a}" for a in notes) if notes else "*(no annotations)*"))
        flags = "drawing" + ("" if any(tb.values()) else ",title_block_not_found")
        parts.append(unit_open(n, len(txt), flags) + "\n\n" + txt + "\n\n" + UNIT_CLOSE)
    found = blocks[0] if blocks else {}
    missing = [k for k in ("drawing_number", "title", "revision") if not found.get(k)]
    status = "REVIEW" if missing else "PASS"   # uncertain metadata is confirmed by a person (F-9)
    rep = {"route": "drawing", "sheets": len(sheets), "title_block": found, "missing_fields": missing,
           "status": status, "triage": {"class": "drawing", "reason": "drawing route"},
           "source_unchanged": {"ok": R.dropbox_content_hash(path) == h, "content_hash": h},
           "seconds": round(time.time() - t0, 1)}
    if not rep["source_unchanged"]["ok"]:
        rep["status"] = status = "FAIL"
    ok = status == "PASS"
    fm = ["---", f"document: {R._yaml_str(name)}", f"format_version: {R.FORMAT_VERSION}", "std_kind: \"drawing\"",
          f"drawing_number: {R._yaml_str(found.get('drawing_number', ''))}",
          f"drawing_title: {R._yaml_str(found.get('title', ''))}",
          f"revision: {R._yaml_str(found.get('revision', ''))}", f"scale: {R._yaml_str(found.get('scale', ''))}",
          f"drawing_date: {R._yaml_str(found.get('date', ''))}", f"project: {R._yaml_str(found.get('project', ''))}",
          f"units: {len(sheets)}", f"source: {R._yaml_str(src_display + ' (content_hash ' + h[:12] + ')')}",
          f"source_filename: {R._yaml_str(os.path.basename(rel_path))}",
          f"source_relative_path: {R._yaml_str(rel_path.replace(os.sep, '/'))}", f"source_file_hash: {h}",
          f"parser: {R.PIPELINE_VERSION}/drawing", f"audit_status: {'auto_verified' if ok else 'pending_review'}",
          "flags: [drawing]", "---", "", NOTICE, "", ""]
    base = os.path.join(out_root, rel_dir) if ok else os.path.join(out_root, "_pending", rel_dir)
    os.makedirs(base, exist_ok=True)
    fn = os.path.basename(rel_path) + ".md"
    body = "\n\n".join(parts) + "\n"
    with open(R.longpath(os.path.join(base, fn)), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(fm) + body)
    with open(os.path.join(cache_dir, h + ".report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    return {"name": name, "rel_path": rel_path, "source": src_display, "status": "", "verdict": status,
            "pages": len(sheets), "files": 1, "single_file": True, "max_file_chars": len(body),
            "total_chars": len(body), "content_hash": h,
            "out_dir": os.path.relpath(os.path.join(base, fn), out_root), "report": rep}
