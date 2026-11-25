"""Requirements v3 H-3: each week, 20 pages of the published library are drawn at random and a person compares each
with the same page of the original PDF. The error rate is judged statistically (Wilson upper bound), not by feel.

The draw is fixed by the week ("2026-W48"), so the same week always gives the same pages and nobody can pick easy
ones. The library page's text is kept with the draw, so what was checked is on record even after the library
changes. The source page is shown from the original PDF, after checking it is the same file (content hash) the
library page was made from."""
from __future__ import annotations

import datetime as dt
import os
import random
import re

from .. import config, db
from ..acceptance.grade import wilson

SIZE = 20
TARGET = 0.01                 # error rate the sample must show to be below (upper 95 % bound)
MAX_READS = 200               # files read to find SIZE usable pages
VERDICTS = ("ok", "wrong")
_UNIT = re.compile(r"<!-- unit: p\d+ \| src: p\.(\d+)[^>]*-->(.*?)(?=<!-- unit:|<!-- /unit -->|\Z)", re.S)
_FM = re.compile(r"^---\n(.*?)\n---\n", re.S)



class SpotError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def week_of(day: dt.date | None = None) -> str:
    y, w, _ = (day or dt.date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def _con():
    return db.trust_rw()


def front_matter(text: str) -> dict:
    m = _FM.match(text.replace("\r\n", "\n"))
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, sep, v = line.partition(":")
        if sep and not line.startswith(" "):
            out[k.strip()] = v.strip().strip('"')
    return out


def pick_page(text: str, rnd: random.Random) -> tuple[int, str] | None:
    """One page of a library file with enough text to compare (a heading alone says little)."""
    units = [(int(m.group(1)), m.group(2).strip()) for m in _UNIT.finditer(text)]
    units = [u for u in units if len(u[1]) >= 200]
    return rnd.choice(units) if units else None


# ------------------------------------------------------------------ the library, as the draw sees it
class DropboxLibrary:
    """The published library in Dropbox (read-only connection): the folders the rooms publish to."""

    def __init__(self, roots: list[str]):
        from ..distill import dropbox_io as D
        self.D, self.dbx, self.roots = D, D.client("reader"), roots

    def files(self) -> list[str]:
        out = set()
        for r in self.roots:
            out |= {p for p in self.D.list_tree(self.dbx, r) if p.endswith(".md")
                    and not any(part.startswith("_") for part in p.split("/"))}
        return sorted(out)

    def read(self, path: str) -> str:
        _, resp = self.dbx.files_download(path)
        return resp.content.decode("utf-8", "replace")

    def source(self, rel: str, want_hash: str) -> str:
        """The original PDF, downloaded once into the work folder; refused when its bytes are not the recorded ones."""
        from ..distill.run import dropbox_content_hash
        local = os.path.join(config.DATA_DIR, "work", "spot-src", *rel.strip("/").split("/"))
        if not (os.path.exists(local) and dropbox_content_hash(local) == want_hash):
            self.D.download(self.dbx, "/" + rel.strip("/"), "", local)
        if dropbox_content_hash(local) != want_hash:
            raise SpotError(409, "the source PDF in Dropbox is no longer the file this library page was made from")
        return local


def library_roots() -> list[str]:
    from ..jobs import rooms as R
    roots = {R.target(R.with_path(r["dest"])) for r in R.list_rooms() if r.get("dest") and r["dest"].get("kind") == "dropbox"}
    return sorted(r for r in roots if r.startswith("/")) or ["/Library_Installation/Md_Library"]


def _library():
    return DropboxLibrary(library_roots())


# ------------------------------------------------------------------ draw, record, summarise
def _read_in_order(lib, paths: list[str], batch: int = 10):
    """Files are read ten at a time (a draw took 55 s one by one) but handed on in the drawn order, so the sample
    does not depend on which download finished first."""
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(batch) as ex:
        for i in range(0, len(paths), batch):
            chunk = paths[i:i + batch]
            yield from zip(chunk, ex.map(lib.read, chunk))


def draw(week: str, lib=None) -> list[dict]:
    """This week's sample, drawn on first use and then kept."""
    con = _con()
    try:
        if not con.execute("SELECT 1 FROM spot_check WHERE week=? LIMIT 1", (week,)).fetchone():
            lib = lib or _library()
            rnd = random.Random(f"fidelity-spot-check {week}")
            files = lib.files()
            rnd.shuffle(files)
            rows, now = [], db.now()
            for path, text in _read_in_order(lib, files[:MAX_READS]):
                fm = front_matter(text)
                if fm.get("audit_status") == "pending_review" or not fm.get("source_relative_path"):
                    continue
                got = pick_page(text, rnd)
                if not got:
                    continue
                rows.append((week, len(rows) + 1, path, got[0], got[1], fm.get("source_relative_path"),
                             fm.get("source_file_hash"), fm.get("document", ""), now))
                if len(rows) == SIZE:
                    break
            con.executemany("INSERT INTO spot_check(week,n,lib_path,page,text,source,source_hash,document,"
                            "created_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT (week, n) DO NOTHING", rows)
            con.commit()
        return [dict(r) for r in con.execute("SELECT * FROM spot_check WHERE week=? ORDER BY n", (week,))]
    finally:
        con.close()


def record(item_id: int, verdict: str, note: str, user: str) -> dict:
    if verdict not in VERDICTS:
        raise SpotError(422, "verdict must be ok or wrong")
    if verdict == "wrong" and not (note or "").strip():
        raise SpotError(422, "say what is wrong (the figure, word or table cell)")
    con = _con()
    try:
        if not con.execute("SELECT 1 FROM spot_check WHERE id=?", (item_id,)).fetchone():
            raise SpotError(404, "no such sample page")
        con.execute("UPDATE spot_check SET verdict=?, note=?, by_user=?, at=? WHERE id=?",
                    (verdict, (note or "").strip()[:500], user, db.now(), item_id))
        con.commit()
        return dict(con.execute("SELECT * FROM spot_check WHERE id=?", (item_id,)).fetchone())
    finally:
        con.close()


def item(item_id: int) -> dict:
    con = _con()
    try:
        r = con.execute("SELECT * FROM spot_check WHERE id=?", (item_id,)).fetchone()
    finally:
        con.close()
    if not r:
        raise SpotError(404, "no such sample page")
    return dict(r)


def page_image(item_id: int, lib=None, dpi: int = 110) -> bytes:
    import pymupdf
    it = item(item_id)
    path = (lib or _library()).source(it["source"], it["source_hash"])
    doc = pymupdf.open(path)
    try:
        if not 1 <= it["page"] <= doc.page_count:
            raise SpotError(404, "that page is not in the source PDF")
        return doc[it["page"] - 1].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()


def summary() -> dict:
    """Per week and over all weeks: pages checked, found wrong, and the upper 95 % bound of the error rate."""
    con = _con()
    try:
        rows = con.execute("SELECT week, COUNT(*) AS n, SUM(CASE WHEN verdict IS NULL THEN 0 ELSE 1 END) AS checked, "
                           "SUM(CASE WHEN verdict='wrong' THEN 1 ELSE 0 END) AS wrong "
                           "FROM spot_check GROUP BY week ORDER BY week DESC").fetchall()
    finally:
        con.close()
    weeks = [{"week": r["week"], "size": r["n"], "checked": r["checked"] or 0, "wrong": r["wrong"] or 0} for r in rows]
    checked, wrong = sum(w["checked"] for w in weeks), sum(w["wrong"] for w in weeks)
    upper = wilson(checked - wrong, checked)[0] if checked else None
    upper_err = round(1 - upper, 4) if upper is not None else None
    return {"weeks": weeks, "checked": checked, "wrong": wrong, "target": TARGET,
            "error_upper95": upper_err,
            "meets_target": upper_err is not None and upper_err <= TARGET,
            # how many more clean pages it takes before the bound can show ≤ 1 %
            "clean_pages_needed": _needed(checked, wrong)}


def _needed(checked: int, wrong: int) -> int:
    n = checked
    while n < checked + 5000 and (1 - wilson(n - wrong, n)[0] if n else 1) > TARGET:
        n += 1
    return n - checked

