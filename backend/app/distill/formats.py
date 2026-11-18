# -*- coding: utf-8 -*-
"""Extractor plug-ins for non-PDF sources (spec F-3, Phase 4): Word, Excel, PowerPoint,
HTML / Markdown web snapshots and Outlook .msg (attachments processed recursively).

Each extractor returns a list of Units (the library's unit of citation: a section, sheet,
slide or attachment page). Each format also has an *independent* reader that takes the raw
text straight from the file's XML/markup, used by `verify_units` as the second opinion:
characters recall >= 99.5 % and every number present, otherwise the document is not trusted.
New formats are added by registering a function in EXTRACTORS (plug-ins).
"""
from __future__ import annotations

import html as _html
import os
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass
class Unit:
    src: str                    # human-readable location: 'sheet "Rates"', 'slide 3', 'section 2'
    text: str                   # Markdown content
    flags: list = field(default_factory=list)


# ------------------------------------------------------------------ helpers
def _cell(v) -> str:
    s = "" if v is None else str(v)
    return s.replace("|", "\\|").replace("\n", " ").strip()


def md_table(rows) -> str:
    rows = [[_cell(c) for c in r] for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _xml_text(xml: str, tag_re: str) -> str:
    return "\n".join(_html.unescape(m) for m in re.findall(tag_re, xml, re.S))


# ------------------------------------------------------------------ Word
def extract_docx(path: str) -> list:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(path)
    units, cur, title, n = [], [], "Start", 0

    def flush():
        nonlocal cur
        if any(x.strip() for x in cur):
            units.append(Unit(f"section {len(units) + 1}: {title[:60]}", "\n\n".join(cur).strip()))
        cur = []

    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            t = p.text.strip()
            if not t:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            m = re.match(r"heading (\d)", style)
            if m and int(m.group(1)) <= 2:
                flush()
                title = t
                n += 1
                cur.append("#" * (int(m.group(1)) + 1) + " " + t)
            elif m or style == "title":
                cur.append("#" * min(6, int(m.group(1)) + 1 if m else 2) + " " + t)
            else:
                cur.append(t)
        elif tag == "tbl":
            tb = Table(child, d)
            rows = []
            for r in tb.rows:
                cells, seen = [], set()
                for c in r.cells:              # merged cells repeat the same object: keep once
                    if id(c._tc) in seen:
                        continue
                    seen.add(id(c._tc))
                    cells.append(c.text)
                rows.append(cells)
            t = md_table(rows)
            if t:
                cur.append(t)
    flush()
    # headers and footers are content too (document numbers, revision)
    hf = []
    for s in d.sections:
        for part in (s.header, s.footer):
            txt = "\n".join(p.text for p in part.paragraphs if p.text.strip())
            if txt and txt not in hf:
                hf.append(txt)
    if hf:
        units.append(Unit("headers and footers", "\n\n".join(hf)))
    return units


def raw_docx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        parts = [n for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*)\.xml$", n)]
        xml = "\n".join(z.read(n).decode("utf-8", "replace") for n in parts)
    xml = re.sub(r"</w:p>", "\n", xml)
    return _xml_text(xml, r"<w:t(?:\s[^>]*)?>(.*?)</w:t>")


# ------------------------------------------------------------------ Excel
def extract_xlsx(path: str) -> list:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    units = []
    try:
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            t = md_table(rows)
            units.append(Unit(f'sheet "{ws.title}"', t if t else "*(empty sheet)*", [] if t else ["empty"]))
    finally:
        wb.close()
    return units


def raw_xlsx(path: str) -> str:
    """Values straight from the XML: shared strings + cached cell values + inline strings."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            sx = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            for si in re.findall(r"<si>(.*?)</si>", sx, re.S):
                shared.append("".join(_html.unescape(x) for x in re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", si, re.S)))
        out = []
        date_styles = _date_styles(z)
        for n in sorted(x for x in names if re.match(r"xl/worksheets/sheet\d+\.xml$", x)):
            sx = z.read(n).decode("utf-8", "replace")
            for c in re.finditer(r"<c\b([^>]*)>(.*?)</c>", sx, re.S):
                attrs, body = c.group(1), c.group(2)
                v = re.search(r"<v>(.*?)</v>", body, re.S)
                if 't="s"' in attrs and v:
                    out.append(shared[int(v.group(1))])
                elif 't="inlineStr"' in attrs:
                    out.append("".join(_html.unescape(x) for x in re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", body, re.S)))
                elif v:
                    val = _html.unescape(v.group(1))
                    sm = re.search(r'\bs="(\d+)"', attrs)
                    if sm and int(sm.group(1)) in date_styles:
                        val = _excel_date(val)
                    out.append(val)
    return "\n".join(out)


_BUILTIN_DATE_FMTS = set(range(14, 23)) | {45, 46, 47}


def _date_styles(z) -> set:
    """Indexes of cell styles whose number format is a date/time (cached values are serial numbers)."""
    try:
        sx = z.read("xl/styles.xml").decode("utf-8", "replace")
    except KeyError:
        return set()
    custom = {int(i): f for i, f in re.findall(r'<numFmt numFmtId="(\d+)" formatCode="([^"]*)"', sx)}
    is_date = lambda fid: fid in _BUILTIN_DATE_FMTS or (
        fid in custom and re.search(r"[dmyhs]", re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom[fid]), re.I))
    xfs = re.search(r"<cellXfs[^>]*>(.*?)</cellXfs>", sx, re.S)
    out = set()
    for i, xf in enumerate(re.findall(r"<xf\b[^>]*>", xfs.group(1) if xfs else "")):
        m = re.search(r'numFmtId="(\d+)"', xf)
        if m and is_date(int(m.group(1))):
            out.add(i)
    return out


def _excel_date(serial: str) -> str:
    from openpyxl.utils.datetime import from_excel
    try:
        d = from_excel(float(serial))
        return str(d)
    except (ValueError, TypeError, OverflowError):
        return serial


# ------------------------------------------------------------------ PowerPoint
def extract_pptx(path: str) -> list:
    from pptx import Presentation

    prs = Presentation(path)
    units = []
    for i, slide in enumerate(prs.slides, 1):
        parts = []

        def walk(shapes):
            for sh in shapes:
                if getattr(sh, "shape_type", None) == 6 and hasattr(sh, "shapes"):   # group
                    walk(sh.shapes)
                elif getattr(sh, "has_table", False) and sh.has_table:
                    parts.append(md_table([[c.text for c in r.cells] for r in sh.table.rows]))
                elif getattr(sh, "has_text_frame", False) and sh.has_text_frame and sh.text_frame.text.strip():
                    parts.append(sh.text_frame.text.strip())

        walk(slide.shapes)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            parts.append("**Speaker notes:** " + slide.notes_slide.notes_text_frame.text.strip())
        units.append(Unit(f"slide {i}", "\n\n".join(parts) if parts else "*(no text on this slide)*",
                          [] if parts else ["no_text"]))
    return units


def raw_pptx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        parts = sorted(n for n in z.namelist() if re.match(r"ppt/(slides/slide|notesSlides/notesSlide)\d+\.xml$", n))
        xml = "\n".join(z.read(n).decode("utf-8", "replace") for n in parts)
    # slide numbers in notes placeholders are generated, not authored text
    xml = re.sub(r'<a:fld [^>]*type="slidenum".*?</a:fld>', "", xml, flags=re.S)
    return _xml_text(xml, r"<a:t>(.*?)</a:t>")


# ------------------------------------------------------------------ HTML / Markdown web snapshots
class _HtmlToMd(HTMLParser):
    BLOCK = {"p", "div", "li", "tr", "br", "section", "article", "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.prefix = [], 0, ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
            if re.match(r"h[1-6]$", tag):
                self.out.append("#" * int(tag[1]) + " ")
            elif tag == "li":
                self.out.append("- ")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _read(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _split_headings(md: str, level=2) -> list:
    units, cur, title = [], [], "Start"
    for line in md.split("\n"):
        m = re.match(r"(#{1,%d})\s+(.*)" % level, line)
        if m and any(x.strip() for x in cur):
            units.append(Unit(f"section {len(units) + 1}: {title[:60]}", "\n".join(cur).strip()))
            cur = []
        if m:
            title = m.group(2).strip()
        cur.append(line)
    if any(x.strip() for x in cur):
        units.append(Unit(f"section {len(units) + 1}: {title[:60]}", "\n".join(cur).strip()))
    return units


def extract_html(path: str) -> list:
    p = _HtmlToMd()
    p.feed(_read(path))
    md = re.sub(r"[ \t]+", " ", "".join(p.out))
    md = re.sub(r"\n\s*\n+", "\n\n", md).strip()
    return _split_headings(md)


def raw_html(path: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", _read(path))
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    return _html.unescape(re.sub(r"<[^>]+>", " ", t))


def extract_md(path: str) -> list:
    return _split_headings(_read(path))


def raw_md(path: str) -> str:
    return _read(path)


# ------------------------------------------------------------------ Outlook .msg (recursive)
def extract_msg(path: str, depth=0) -> list:
    import extract_msg as em

    m = em.Message(path)
    try:
        head = []
        for label, attr in (("Subject", "subject"), ("From", "sender"), ("To", "to"), ("Cc", "cc"), ("Date", "date")):
            v = getattr(m, attr, None)
            if v not in (None, "") and str(v).strip().lower() not in ("none", "null"):
                head.append(f"**{label}:** {str(v).strip()}")
        units = [Unit("message", "\n\n".join(head + ["", (m.body or "").strip()]).strip())]
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            for a in m.attachments:
                name = getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or "attachment"
                data = getattr(a, "data", None)
                if not isinstance(data, (bytes, bytearray)):
                    units.append(Unit(f'attachment "{name}"', "*(embedded item not extracted)*", ["attachment_not_extracted"]))
                    continue
                ap = os.path.join(td, os.path.basename(name))
                with open(ap, "wb") as f:
                    f.write(data)
                sub = extract_any(ap, depth + 1) if depth < 3 else None
                if sub is None:
                    units.append(Unit(f'attachment "{name}"', "*(format not handled yet: listed, not distilled)*",
                                      ["unsupported_attachment"]))
                for u in sub or []:
                    units.append(Unit(f'attachment "{name}" {u.src}', u.text, u.flags))
        return units
    finally:
        m.close()


def raw_msg(path: str) -> str:
    """Independent read: message headers/body via the MAPI properties, plus each attachment's raw text."""
    import extract_msg as em
    import tempfile

    m = em.Message(path)
    try:
        parts = [str(getattr(m, a, "") or "") for a in ("subject", "sender", "to", "cc", "date")]
        parts.append(m.body or "")
        with tempfile.TemporaryDirectory() as td:
            for a in m.attachments:
                data = getattr(a, "data", None)
                name = getattr(a, "longFilename", None) or "attachment"
                parts.append(name)
                if isinstance(data, (bytes, bytearray)):
                    ap = os.path.join(td, os.path.basename(name))
                    with open(ap, "wb") as f:
                        f.write(data)
                    r = raw_any(ap)
                    if r:
                        parts.append(r)
        return "\n".join(parts)
    finally:
        m.close()


# ------------------------------------------------------------------ PDF attachments (simple text route)
def extract_pdf_text(path: str) -> list:
    import pymupdf
    doc = pymupdf.open(path)
    try:
        return [Unit(f"p.{i}", pg.get_text().strip() or "*(no text on this page)*", [] if pg.get_text().strip() else ["no_text"])
                for i, pg in enumerate(doc, 1)]
    finally:
        doc.close()


def raw_pdf_text(path: str) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)


# ------------------------------------------------------------------ registry
EXTRACTORS = {
    ".docx": (extract_docx, raw_docx),
    ".xlsx": (extract_xlsx, raw_xlsx),
    ".xlsm": (extract_xlsx, raw_xlsx),
    ".pptx": (extract_pptx, raw_pptx),
    ".html": (extract_html, raw_html),
    ".htm": (extract_html, raw_html),
    ".md": (extract_md, raw_md),
    ".msg": (extract_msg, raw_msg),
}
ATTACHMENT_ONLY = {".pdf": (extract_pdf_text, raw_pdf_text)}


def supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in EXTRACTORS


def extract_any(path, depth=0):
    ext = os.path.splitext(path)[1].lower()
    fn = (EXTRACTORS.get(ext) or ATTACHMENT_ONLY.get(ext) or (None, None))[0]
    if fn is None:
        return None
    return fn(path, depth) if fn is extract_msg else fn(path)


def raw_any(path) -> str:
    ext = os.path.splitext(path)[1].lower()
    fn = (EXTRACTORS.get(ext) or ATTACHMENT_ONLY.get(ext) or (None, None))[1]
    try:
        return fn(path) if fn else ""
    except Exception:
        return ""


# ------------------------------------------------------------------ verification
def _alnum(s: str) -> Counter:
    return Counter(ch for ch in s.lower() if ch.isalnum())


def _nums(s: str) -> Counter:
    return Counter(NUM_RE.findall(s))


def verify_units(units: list, raw: str) -> dict:
    """Second-reader check: every character and number of the raw file text is in the Markdown."""
    md = "\n".join(u.src + "\n" + u.text for u in units)   # unit locations (sheet, attachment names) are published too
    md_plain = md.replace("\\|", "|")
    src, got = _alnum(raw), _alnum(md_plain)
    tot = sum(src.values())
    hit = sum(min(c, got.get(k, 0)) for k, c in src.items())
    sn, mn = _nums(raw), _nums(md_plain)
    missing_nums = [k for k, c in sn.items() if mn.get(k, 0) < c]
    rec = hit / tot if tot else 1.0
    rep = {"chars": {"recall": round(rec, 6), "source_chars": tot, "ok": rec >= 0.995},
           "numbers": {"missing": missing_nums[:20], "ok": not missing_nums},
           "units": len(units)}
    rep["status"] = "PASS" if rep["chars"]["ok"] and rep["numbers"]["ok"] and units else "FAIL"
    return rep
