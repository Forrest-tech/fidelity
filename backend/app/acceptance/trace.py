"""Requirements v3 R-3: every citation in an answer can be followed back, link by link —
library version -> library file -> page in that file -> source PDF (same bytes) -> that page of the PDF.

    python -m app.acceptance trace --run RUN.json --library DIR --sources DIR --publish DIR --releases DIR --out OUT.md

No model is involved: each link is checked by a fixed rule, so anyone re-running it gets the same table. A chain
that breaks says where it broke."""
from __future__ import annotations

import glob
import json
import os
import re

from .grade import _quote_on_page
from .library import Unit
from .text import norm, numbers

_NUM = re.compile(r"3500\.(\d)")
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
_WORD = re.compile(r"[a-z]{3,}")
LONG = "\\\\?\\"                     # Windows long-path prefix the library loader adds



def designation(doc: str, edition: str = "") -> tuple[str, str]:
    """("3500.1", "2021") from what an answer wrote: "AS/NZS 3500.1:2021", "AS NZS 3500.1-2021 · 007 … p28-38.md"."""
    num = _NUM.search(doc) or _NUM.search(edition)
    year = _YEAR.search(doc) or _YEAR.search(edition)
    return (f"3500.{num.group(1)}" if num else "", year.group(1) if year else "")


def _unit_matches(u: Unit, num: str, year: str) -> bool:
    name = f"{u.source_filename} {u.document} {u.file}".replace(" ", "")
    return bool(num) and num in name and (not year or year in name or u.year == year)


def in_text(text: str, quote: str) -> bool:
    """The quote is in the library page: word for word, or (a table row, re-ordered cells) every figure and 95 % of
    the words."""
    t, q = norm(text), norm(quote)
    if q and q in t:
        return True
    words = _WORD.findall(q)
    tw, tn = set(_WORD.findall(t)), set(numbers(text))
    return len(words) >= 3 and all(n in tn for n in numbers(quote)) and sum(w in tw for w in words) >= 0.95 * len(words)


def _content_hash(path: str, cache: dict) -> str:
    """Dropbox's content hash of the file: what the library file's `source_file_hash` records."""
    if path not in cache:
        from ..distill.run import dropbox_content_hash
        cache[path] = dropbox_content_hash(path)
    return cache[path]


def versions(publish_dir: str, releases_dir: str) -> list[dict]:
    """Every publish run with the files it put in the library, newest first, and its release number if it has one."""
    rel = {}
    for p in glob.glob(os.path.join(releases_dir, "*.json")):
        r = json.load(open(p, encoding="utf-8"))
        rel[r["run"]] = r["release"]
    out = []
    for p in glob.glob(os.path.join(publish_dir, "publish-*.json")):
        r = json.load(open(p, encoding="utf-8"))
        files = {f"{k}/{f}" for k, d in (r.get("docs") or {}).items() for f in (d.get("files") or {})}
        out.append({"run": r["run"], "release": rel.get(r["run"]), "files": files})
    return sorted(out, key=lambda v: v["run"], reverse=True)


def library_key(path: str, library: str) -> str:
    """"AS 3500/2021/AS NZS 3500.3-2021/07 Section 6 …/file.md": the path below the library folder, as the publish
    records write it (`library` is the folder of one collection, e.g. …/Md_Library/AS 3500)."""
    def strip(p: str) -> str:
        p = p[4:] if p.startswith(LONG) else p
        return os.path.abspath(p).replace(os.sep, "/")
    return os.path.relpath(strip(path), os.path.dirname(strip(library).rstrip("/"))).replace("\\", "/")


def trace(cite: dict, edition: str, units: list[Unit], sources: dict[str, str], vers: list[dict],
          front: dict, cache: dict, library: str = "") -> dict:
    """One citation -> its chain. `front` maps a library file path to its front matter."""
    page, quote = int(cite.get("page") or 0), cite.get("quote") or ""
    num, year = designation(cite.get("document") or "", edition)
    out = {"document": cite.get("document"), "page": page, "designation": f"{num}:{year}".strip(":"), "ok": False}
    cands = [u for u in units if _unit_matches(u, num, year)]
    if not cands:
        return {**out, "broken_at": "library file: no document in the library matches the citation"}
    hit = next((u for d in (0, 1) for u in cands if abs(u.page - page) == d and in_text(u.text, quote)), None)
    if not hit:
        return {**out, "broken_at": "library page: the quote is not on that page of any matching library file"}
    fm = front[hit.path]
    out.update(library_file=hit.file, library_page=hit.page)
    key = library_key(hit.path, library)
    ver = next((v for v in vers if key in v["files"]), None)
    out["version"] = (f"release {ver['release']}" if ver and ver["release"] else f"publish run {ver['run']}") if ver else ""
    if not ver:
        return {**out, "broken_at": "library version: no publish record lists this file"}
    src = sources.get(fm.get("source_filename", ""))
    out["source_pdf"] = fm.get("source_relative_path") or fm.get("source_filename")
    if not src:
        return {**out, "broken_at": "source PDF: not found"}
    if _content_hash(src, cache) != fm.get("source_file_hash"):
        return {**out, "broken_at": "source PDF: its bytes differ from the ones the library file was made from"}
    pdf_page = next((p for p in (hit.page, hit.page - 1, hit.page + 1) if _quote_on_page(src, p, quote, "E")
                     and (p == hit.page or not _quote_on_page(src, hit.page, quote, "E"))), None)
    if not pdf_page:
        return {**out, "broken_at": "source page: the quote is not on that page of the PDF"}
    return {**out, "pdf_page": pdf_page, "ok": True, "broken_at": ""}


def run(answers: list[dict], library: str, sources: dict[str, str], publish_dir: str, releases_dir: str) -> list[dict]:
    from ..adapters.facts import front_matter
    from .library import load
    units = load(library)
    front = {p: front_matter(p) for p in {u.path for u in units}}
    vers, cache, rows = versions(publish_dir, releases_dir), {}, []
    for a in answers:
        cites = a.get("citations") or []
        if isinstance(cites, dict):
            cites = [cites]
        for c in cites[:1]:                     # the citation the answer rests on (the first one)
            rows.append({"id": a["id"], "model": a.get("model", ""),
                         **trace(c, a.get("edition_used") or "", units, sources, vers, front, cache, library)})
    return rows


def write(path: str, rows: list[dict], title: str):
    ok = sum(r["ok"] for r in rows)
    lines = [f"# {title}", "", f"**{ok}/{len(rows)}** citations traced end to end "
             "(library version → library file → page → source PDF with the same bytes → source page).", "",
             "| Q | Cited | Version | Library file | p. | Source PDF | PDF p. | Result |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['designation']} p.{r['page']} | {r.get('version', '')} | {r.get('library_file', '')} "
                     f"| {r.get('library_page', '')} | {r.get('source_pdf', '')} | {r.get('pdf_page', '')} "
                     f"| {'✅' if r['ok'] else '❌ ' + r['broken_at']} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
