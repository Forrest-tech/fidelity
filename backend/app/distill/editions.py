"""Which standard, which edition, which copy (requirements v2, D-1 to D-5).

Files are not the unit people ask about. A library holds the same edition several times (a printed scan, a
searchable copy, an unlocked copy, a protected original), editions replace each other (AS/NZS 3500.1:2018 is
replaced by :2021), and amendments change a base edition. This module works out, for each file of a room:

  identity  — designation such as "AS/NZS 3500.1:2021", read from the document's own title pages first, then
              from its file name, then from its folder (a file named "AS 3500.0 Glossary" in a "2018" folder is,
              by its own title page, the 2003 edition);
  best copy — of several copies of one edition, the one to publish; the others are marked as copies of it;
  status    — current or superseded within this library, and by which edition.

"Current" means the latest edition this library holds. It is not a claim about the publisher's catalogue.
"""
from __future__ import annotations

import collections
import os
import re

_PREFIX = r"(?P<prefix>AS\s*/\s*NZS|AS[\s_-]+NZS|AS|NZS)?"
_NUMBER = r"(?P<number>\d{3,5}(?:\.\d{1,3})?)"
_YEAR = r"(?P<year>(?:19|20)\d{2})"
# in text: "AS/NZS 3500.1:2021", "AS 3500.1—1990"; in names also "AS3500.1 - 1990", "AS-NZS_3500.0-2021", "3500.1-2018"
_IN_TEXT = re.compile(r"\b(?P<prefix>AS\s*/\s*NZS|AS|NZS)\s+" + _NUMBER + r"\s*[:—–]\s*" + _YEAR + r"(?!\d)")
_IN_NAME = re.compile(r"(?:^|[\s_(])" + _PREFIX + r"[\s_-]*" + _NUMBER + r"(?:\s*[-–—:_]\s*" + _YEAR + r")?(?!\d)",
                      re.IGNORECASE)
_AMDT_NAME = re.compile(r"\bAmdt\.?\s*(?P<n>\d+)\s*[-–]\s*(?P<y>(?:19|20)\d{2})", re.IGNORECASE)
_AMDT_TEXT = re.compile(r"Amendment\s+No\.?\s*(?P<n>\d+)\s*(?:\((?P<y>(?:19|20)\d{2})\))?\s+to\s+" + _IN_TEXT.pattern,
                        re.IGNORECASE)
_CONSOLIDATED = re.compile(r"\bamended\b|amendment\s*\d*\s*(?:included|incorporated)", re.IGNORECASE)
_FOLDER_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_UNLOCKED = re.compile(r"已解锁|解锁版|unlocked|decrypted", re.IGNORECASE)
_SCAN_NAME = re.compile(r"\bprinted\b(?!.*converted)", re.IGNORECASE)


def _prefix(p: str | None) -> str:
    p = re.sub(r"[\s_-]+", " ", (p or "").upper()).replace(" / ", "/").replace("AS NZS", "AS/NZS").replace(" ", "")
    return p.replace("AS/NZS", "AS/NZS")


def identify(rel: str, text: str = "") -> dict:
    """{number, prefix, year, designation, amendment, amendment_year, consolidated, basis} for one file.

    `text` is the start of the distilled document (its first pages), when there is a result; `basis` says where the
    year came from: "document" (its own pages), "name", "folder" or "" (unknown)."""
    name = os.path.splitext(rel.rsplit("/", 1)[-1])[0]
    folders = [p for p in rel.strip("/").split("/")[:-1]]
    m = _IN_NAME.search(name)
    number = m.group("number") if m else ""
    prefix = _prefix(m.group("prefix")) if m and m.group("prefix") else ""
    year, basis = (m.group("year"), "name") if m and m.group("year") else ("", "")
    amd = _AMDT_NAME.search(name)
    amendment, amendment_year = (int(amd.group("n")), amd.group("y")) if amd else (None, "")
    if text:
        at = _AMDT_TEXT.search(text)
        if at and (not number or at.group("number") == number):
            amendment = amendment or int(at.group("n"))
            amendment_year = amendment_year or (at.group("y") or "")
            number, prefix = at.group("number"), _prefix(at.group("prefix"))
            year, basis = at.group("year"), "document"
        else:
            seen = collections.Counter((_prefix(x.group("prefix")), x.group("number"), x.group("year"))
                                       for x in _IN_TEXT.finditer(text) if not number or x.group("number") == number)
            if seen:
                (p, n, y), _ = seen.most_common(1)[0]
                number, prefix = n, p or prefix
                if amendment is None:              # an amendment's own pages name the edition it amends
                    year, basis = y, "document"
    if not year:
        fy = next((f for f in reversed(folders) if _FOLDER_YEAR.match(f)), "")
        if fy:
            year, basis = fy, "folder"
    prefix = prefix or ("AS" if number else "")
    designation = f"{prefix} {number}:{year}" if number and year else (f"{prefix} {number}" if number else "")
    return {"number": number, "prefix": prefix, "year": year, "designation": designation.strip(),
            "amendment": amendment, "amendment_year": amendment_year,
            "consolidated": bool(_CONSOLIDATED.search(name)), "basis": basis}


def _rank(row: dict) -> tuple:
    """Higher is a better copy to publish: already published, has a result, more accurate, a searchable copy over a
    printed scan, an unlocked copy over a protected one."""
    name = row["rel"].rsplit("/", 1)[-1]
    return (1 if row.get("confirmed") else 0,
            1 if row.get("outcome") == "result" else 0,
            row.get("accuracy") or 0.0,
            0 if _SCAN_NAME.search(name) else 1,
            1 if _UNLOCKED.search(name) else 0,
            -len(row["rel"]))


def registry(rows: list[dict]) -> list[dict]:
    """Each row gets `edition`: {…identity, key, status, superseded_by, copy_of, copies}.

    key       — one edition (or one amendment, or one consolidated text) of one standard;
    copy_of   — set on every copy except the best one: the rel of the copy that represents the edition;
    status    — "current" or "superseded" within this library ("" when the file names no standard);
    superseded_by — designation of the latest edition this library holds of the same standard."""
    out = [dict(r) for r in rows]
    groups: dict = collections.defaultdict(list)
    latest: dict = {}
    for r in out:
        e = dict(r.get("edition") or {})
        if not e.get("number"):
            r["edition"] = {**e, "key": "", "status": "", "superseded_by": "", "copy_of": None, "copies": 1}
            continue
        kind = (f"amendment {e['amendment']}" if e.get("amendment") is not None
                else "consolidated" if e.get("consolidated") else "edition")
        e["key"] = f"{e['number']}:{e['year']}:{kind}"
        r["edition"] = e
        groups[e["key"]].append(r)
        if e.get("year") and kind != "amendment" and (e["number"] not in latest or e["year"] > latest[e["number"]]["year"]):
            latest[e["number"]] = e
    # a name says "AS 3500.1-2015" where the standard has been joint (AS/NZS) since an earlier edition: take the
    # joint prefix another file of the same standard states outright, in its pages or its name, for that year or earlier
    joint = collections.defaultdict(list)
    for r in out:
        e = r["edition"]
        if e.get("basis") in ("document", "name") and e.get("prefix") == "AS/NZS" and e.get("year"):
            joint[e["number"]].append(e["year"])
    for r in out:
        e = r["edition"]
        if e.get("key") and e.get("basis") != "document" and e.get("prefix") == "AS" and e.get("year")                 and any(y <= e["year"] for y in joint.get(e["number"], [])):
            e["prefix"] = "AS/NZS"
            e["designation"] = f"AS/NZS {e['number']}:{e['year']}"
    for n, top in latest.items():
        latest[n] = next(r["edition"] for r in out if r["edition"].get("key") == top["key"])
    for members in groups.values():
        best = max(members, key=_rank)
        for r in members:
            r["edition"]["copy_of"] = None if r is best else best["rel"]
            r["edition"]["copies"] = len(members)
    for r in out:
        e = r["edition"]
        if not e.get("key"):
            continue
        top = latest.get(e["number"])
        newer = bool(top and e.get("year") and top["year"] > e["year"])
        e["status"] = "superseded" if newer else "current"
        e["superseded_by"] = top["designation"] if newer else ""
    return out


def stamp_lines(edition: dict | None) -> list[str]:
    """Front-matter lines that tell a reader (and the AI) which edition a file is and whether it is in force here."""
    if not edition or not edition.get("designation"):
        return []
    q = lambda s: '"' + str(s).replace('"', '\\"') + '"'       # noqa: E731
    lines = [f"edition: {q(edition['designation'])}"]
    if edition.get("amendment") is not None:
        lines.append(f"amends: {q(edition['designation'])}")
        lines.append(f"amendment: {edition['amendment']}" + (f" ({edition['amendment_year']})" if edition.get("amendment_year") else ""))
    if edition.get("status"):
        lines.append(f"edition_status: {'superseded' if edition['status'] == 'superseded' else 'published'}")
    if edition.get("superseded_by"):
        lines.append(f"superseded_by: {q(edition['superseded_by'])}")
    return lines


BANNER_MARK = "<!-- fidelity:edition -->"


def banner(edition: dict | None) -> str:
    """One line at the top of the body for a superseded edition, so an answer from it says so."""
    if not edition or edition.get("status") != "superseded" or not edition.get("superseded_by"):
        return ""
    what = edition["designation"] + (f" Amendment {edition['amendment']}" if edition.get("amendment") is not None else "")
    return (f"{BANNER_MARK}\n> ⚠️ **Superseded edition.** {what} has been replaced by {edition['superseded_by']} "
            f"(the latest edition in this library). Use it only for work under the older edition.\n")
