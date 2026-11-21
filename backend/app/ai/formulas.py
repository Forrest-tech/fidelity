# -*- coding: utf-8 -*-
"""Formulas the text layer cannot decode, for one file of a room: where they are, their image, and approving a
transcription.

The source PDF is the copy the run downloaded (data/work/src/...); it is only read. An approved transcription is saved
with the other formula approvals (distill/formula.py), so every later distillation of the same file uses it too, and it
is put into the current result at once: the ⚠️ marker becomes the formula, labelled as transcribed and reviewed.
"""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os

from ..distill import dropbox_io as D
from ..distill import formula as FM
from ..jobs import corrections as CO
from . import config as CF

WORK = os.path.join(D.DATA_DIR, "work")
DPI = 300
_hash_cache: dict = {}
_locate_cache: dict = {}


def _file_hash(path: str) -> str:
    from ..distill.run import dropbox_content_hash
    st = os.stat(path)
    k = (path, st.st_mtime, st.st_size)
    if k not in _hash_cache:
        _hash_cache[k] = dropbox_content_hash(path)
    return _hash_cache[k]


def source_pdf(rel: str, content_hash: str | None) -> str | None:
    """The downloaded copy of this source file, if it is still on this machine and unchanged."""
    if not rel.lower().endswith(".pdf"):
        return None
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    for path in glob.glob(os.path.join(glob.escape(WORK), "src", "*", *[glob.escape(p) for p in parts])):
        if os.path.isfile(path) and (not content_hash or _file_hash(path) == content_hash):
            return path
    return None


def boxes(pdf: str, content_hash: str) -> dict:
    """{page: [{k, bbox}]} for the undecodable formulas of a source PDF (worked out once per file version)."""
    if content_hash not in _locate_cache:
        by_page: dict = {}
        for it in FM.locate(pdf):
            by_page.setdefault(it["page"], []).append({"k": it["k"], "bbox": it["bbox"]})
        _locate_cache[content_hash] = by_page
    return _locate_cache[content_hash]


def crop(pdf: str, page: int, bbox) -> bytes:
    import pymupdf
    x0, y0, x1, y1 = bbox
    with pymupdf.open(pdf) as doc:
        pix = doc[page - 1].get_pixmap(dpi=DPI, clip=pymupdf.Rect(x0 - 4, y0 - 6, x1 + 4, y1 + 6))
        return pix.tobytes("png")


def ocr_text(png: bytes) -> str | None:
    """What the local OCR reads in the crop (None when no OCR engine is installed: numbers cannot be checked)."""
    from PIL import Image
    from ..distill import ocr as O
    engines = O.available_engines()
    if not engines:
        return None
    img = Image.open(io.BytesIO(png)).convert("L")
    texts = []
    for e in engines:
        try:
            texts.append(e.read(img)[0])
        except Exception:                                   # noqa: BLE001 - one engine failing leaves the others
            continue
    return " ".join(texts) if texts else None


def find(row, page: int, k: int) -> tuple[str, dict]:
    pdf = source_pdf(row["rel"], row["content_hash"])
    if not pdf:
        raise CF.ConfigError(409, "the source file is no longer on this machine; run the room again")
    box = next((b for b in boxes(pdf, row["content_hash"]).get(page, []) if b["k"] == k), None)
    if not box:
        raise CF.ConfigError(404, "no such formula on that page")
    return pdf, box


def image(row, page: int, k: int) -> bytes:
    pdf, box = find(row, page, k)
    return crop(pdf, page, box["bbox"])


def image_sha(png: bytes) -> str:
    return hashlib.sha256(png).hexdigest()


def approved(content_hash: str) -> dict:
    return FM.load_approvals().get(content_hash) or {}


def approve(room_id: str, row, page: int, k: int, latex: str, user: str) -> dict:
    """A person approved a transcription: keep it for every later run, and put it into the current result now."""
    latex = (latex or "").strip().strip("$").strip()
    if not latex or len(latex) > 600 or "\n\n" in latex:
        raise CF.ConfigError(422, "enter the formula as one LaTeX expression")
    find(row, page, k)
    FM.approve(row["content_hash"], page, k, latex, user)
    raw = CO._ensure_raw(room_id, row["out_dir"])
    n = 0
    if raw:
        for inner in CO._md_files(raw):
            text = CO._read(raw, inner)
            new, c = FM.apply_approved(text, row["content_hash"])
            if c:
                CO._write(raw, inner, new)
                n += c
    CO.reapply(room_id, row["rel"])
    return {"applied": n, "approved": approved(row["content_hash"]).get(f"p.{page}#{k}")}


def summary(row) -> dict:
    """For the review list: which pages have formulas that can be looked at, and which are approved already."""
    pdf = source_pdf(row["rel"], row["content_hash"]) if row["content_hash"] else None
    if not pdf:
        return {"available": False, "pages": {}}
    ok = approved(row["content_hash"])
    pages = {p: [{"k": b["k"], "approved": (ok.get(f"p.{p}#{b['k']}") or {}).get("latex")} for b in bs]
             for p, bs in boxes(pdf, row["content_hash"]).items()}
    return {"available": True, "pages": pages}


def logged_input(page: int, k: int, sha: str) -> str:
    return json.dumps({"page": page, "k": k, "image_sha": sha})
