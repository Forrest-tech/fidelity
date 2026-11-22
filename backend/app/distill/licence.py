"""Who a standards PDF is licensed to, read from the vendor's own watermark (requirement IR-5, D-6).

Standards Australia / SAI Global PDFs stamp every page with a line such as
  "Licensed to <person> on 19 July 2011. Personal use licence only. Storage, distribution or use on network prohibited."
  "Accessed by <organisation> on 07 Jun 2017 (Document currency not guaranteed when printed)"
That line is the primary evidence of the licence a copy was sold under. It is read here so that:
  - the licence inventory is produced from the files themselves, not from memory;
  - copies licensed to someone else, or under terms that forbid network storage or AI use, can be held back;
  - the licensee's name (personal data) is not copied into the published Markdown.
"""
from __future__ import annotations

import collections
import re

_LICENSED = re.compile(r"Licensed to\s+(?P<who>.+?)\s+on\s+(?P<date>\d{1,2}\s+\w+\s+\d{4})\.?\s*(?P<terms>[^\n]{0,160})",
                       re.IGNORECASE)
_ACCESSED = re.compile(r"Accessed by\s+(?P<who>.+?)\s+on\s+(?P<date>\d{1,2}\s+\w{3,9}\s+\d{4})", re.IGNORECASE)
_TERMS_END = re.compile(r"(?<=prohibited)|(?<=only)|(?<=\))", re.IGNORECASE)

# what a stamp's own words say about the copy (kinds are ordered from most to least restrictive)
KIND_PERSONAL = "personal"        # "Personal use licence only" / "1 user personal user licence"
KIND_COMMITTEE = "committee"      # "For Committee WS-014 use only"
KIND_ORGANISATION = "organisation"  # "Accessed by <organisation>" (an organisation's subscription)
KIND_OTHER = "other"


def _kind(stamp_type: str, terms: str) -> str:
    t = terms.lower()
    if "personal" in t or "1 user" in t:
        return KIND_PERSONAL
    if "committee" in t:
        return KIND_COMMITTEE
    if stamp_type == "accessed":
        return KIND_ORGANISATION
    return KIND_OTHER


def stamps(text: str) -> list[dict]:
    """Every licence stamp in the text, most frequent first: {type, who, date, terms, kind, network_prohibited, count}."""
    seen: collections.Counter = collections.Counter()
    info: dict = {}
    for m in _LICENSED.finditer(text):
        terms = _TERMS_END.split(m.group("terms"))[0].strip(" .")
        k = ("licensed", m.group("who").strip(), m.group("date"), terms)
        seen[k] += 1
        info[k] = m.group("terms")
    for m in _ACCESSED.finditer(text):
        k = ("accessed", m.group("who").strip(), m.group("date"), "")
        seen[k] += 1
        info[k] = ""
    out = []
    for (typ, who, date, terms), n in seen.most_common():
        out.append({"type": typ, "who": who, "date": date, "terms": terms, "kind": _kind(typ, terms),
                    "network_prohibited": "network prohibited" in info[(typ, who, date, terms)].lower(), "count": n})
    return out


def holder(text: str) -> dict | None:
    """The stamp a document carries on most pages, or None when it has none."""
    s = stamps(text)
    return s[0] if s else None


def redact(text: str) -> str:
    """The text with each stamp's licensee replaced by a placeholder, keeping the rest of the line."""
    text = _LICENSED.sub(lambda m: m.group(0).replace(m.group("who"), "[licensee]", 1), text)
    return _ACCESSED.sub(lambda m: m.group(0).replace(m.group("who"), "[licensee]", 1), text)
