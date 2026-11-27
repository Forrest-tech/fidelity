# -*- coding: utf-8 -*-
"""Page-by-page comparison for one file of a room: the source page as a picture beside the distilled text of the same
page, with each place the check found marked on both.

Why (the owner, 2026-11-26): "复核 · 对比" showed the whole result as one green block ("new file") and a list of
findings such as "missing: 2, 0, 5", so nobody could tell where a difference was or what it was. Here every finding is
tied to its page; the numbers it names are boxed on the picture of the source page, and the page's distilled text says
whether each one is in it. A person then confirms the place ("the source says so") or fixes it.

The source PDF is only read: the run's downloaded copy when it is still on this machine and unchanged, otherwise it is
downloaded again (read access) into the same cache and checked against the content hash of the version distilled.
"""
from __future__ import annotations

import json
import os
import re
import threading

from ..distill import dropbox_io as D
from ..distill.run import longpath
from . import corrections as CO
from . import rooms as R

WORK = os.path.join(D.DATA_DIR, "work")
_UNIT = re.compile(r"<!-- unit: p\d+ \| src: p\.(\d+)[^>]*-->")
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_locks: dict = {}


class PageError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _row(room_id: str, rel: str) -> dict:
    r = next((x for x in R._files(room_id) if x["rel"] == rel), None)
    if r is None:
        raise PageError(404, "no such file in this room")
    if r["outcome"] != "result" or not r["out_dir"]:
        raise PageError(409, "this file has no distilled result to compare")
    return r


def source_copy(room: dict, row) -> str | None:
    """A local copy of the source file exactly as it was distilled, or None when it cannot be had."""
    from ..ai import formulas as FX
    rel = row["rel"]
    p = FX.source_pdf(rel, row["content_hash"])
    if p:
        return p
    if not room.get("source") or (room["source"].get("kind") or "dropbox") != "dropbox":
        return None
    local = os.path.join(WORK, "src", "review-" + room["id"], *rel.strip("/").split("/"))
    lock = _locks.setdefault(local, threading.Lock())
    with lock:
        if not os.path.isfile(longpath(local)):
            try:
                D.download(D.client("reader"), R.target(room["source"]), "/" + rel.strip("/"), longpath(local))
            except Exception:                                  # noqa: BLE001 - not connected, link gone, offline
                return None
    return FX.source_pdf(rel, row["content_hash"])


def _distilled(room_id: str, out_dir: str) -> str:
    _, out = CO._paths(room_id, out_dir)
    if not os.path.exists(longpath(out)):
        raise PageError(409, "the distilled result is no longer on this machine; run the room again")
    from ..distill.rules import split_front
    return "\n".join(split_front(CO._read(out, inner))[1] for inner in CO._md_files(out))


def page_text(text: str, page: int) -> str:
    """The distilled text of one source page: every unit whose marker names that page. A unit that runs over several
    pages counts for the page it starts on, so a page inside it shows the unit it is part of."""
    marks = list(_UNIT.finditer(text))
    if not marks:
        return ""
    parts, last_before = [], None
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(text)
        p = int(m.group(1))
        body = text[m.end():end].replace("<!-- /unit -->", "").strip()
        if p == page:
            parts.append(body)
        elif p < page:
            last_before = body
    if not parts and last_before is not None:
        return last_before
    return "\n\n".join(parts)


def _values(f: dict) -> list:
    """The exact strings a finding is about (numbers that went missing, the two OCR readings)."""
    if f.get("kind") == "reading":
        return [v for v in (f.get("a"), f.get("b")) if v]
    m = re.match(r"missing: (.+)$", f.get("detail") or "")
    if m:
        return [v.strip() for v in m.group(1).split(",") if v.strip()]
    return []


def _boxes(pg, value: str, limit: int = 12) -> list:
    """Where `value` is printed on the source page, as fractions of the page (0..1), whole words only."""
    import pymupdf
    w, h = pg.rect.width or 1, pg.rect.height or 1
    out = []
    for x0, y0, x1, y1, word, *_ in pg.get_text("words"):
        core = word.strip("()[],;:")
        if core == value or (_NUM.fullmatch(value) and value in _NUM.findall(core)):
            r = pymupdf.Rect(x0, y0, x1, y1)
            out.append([round(r.x0 / w, 4), round(r.y0 / h, 4), round(r.x1 / w, 4), round(r.y1 / h, 4)])
            if len(out) >= limit:
                break
    return out


def page(room_id: str, rel: str, n: int) -> dict:
    room = R.get_room(room_id)
    row = _row(room_id, rel)
    findings = json.loads(row["findings"]) if row["findings"] else []
    try:
        known = set(json.loads(R._get(row, "known") or "[]"))
    except (TypeError, ValueError):
        known = set()
    text = _distilled(room_id, row["out_dir"])
    pages = row["pages"] or 0
    mine = page_text(text, n)
    mine_nums = set(_NUM.findall(mine))
    pdf = source_copy(room, row) if rel.lower().endswith(".pdf") else None
    src_text, doc, pg = "", None, None
    if pdf:
        import pymupdf
        doc = pymupdf.open(pdf)
        pages = doc.page_count
        if 1 <= n <= pages:
            pg = doc[n - 1]
            src_text = pg.get_text().strip()
    try:
        items = []
        for i, f in enumerate(findings):
            if f.get("page") != n:
                continue
            vals = []
            for v in _values(f):
                in_result = (v in mine_nums) if _NUM.fullmatch(v) else (v in mine)
                vals.append({"value": v, "in_result": in_result, "boxes": _boxes(pg, v) if pg is not None else []})
            items.append({"i": i, "kind": f.get("kind"), "detail": f.get("detail"), "known": i in known, "values": vals})
    finally:
        if doc is not None:
            doc.close()
    return {"rel": rel, "page": n, "pages": pages, "has_source": bool(pdf), "distilled": mine, "source_text": src_text,
            "items": items, "pages_with_findings": sorted({f.get("page") for f in findings if isinstance(f.get("page"), int)})}


def image(room_id: str, rel: str, n: int, dpi: int = 110) -> bytes:
    room = R.get_room(room_id)
    row = _row(room_id, rel)
    pdf = source_copy(room, row) if rel.lower().endswith(".pdf") else None
    if not pdf:
        raise PageError(404, "the source file is not available (Dropbox not connected, or the file changed since it was distilled)")
    import pymupdf
    with pymupdf.open(pdf) as doc:
        if not 1 <= n <= doc.page_count:
            raise PageError(404, "no such page")
        return doc[n - 1].get_pixmap(dpi=max(60, min(200, dpi))).tobytes("png")
