# -*- coding: utf-8 -*-
"""Rule-based OCR correction (spec F-14, layer 2): confusable characters in numeric context,
broken hyphenation and ligatures. Spacing and wording are never changed (text is copied, not edited). Every change is returned in a log so it can be
reviewed; nothing is changed outside the narrow patterns below.
"""
from __future__ import annotations

import re

# Typical OCR confusions of digits. A letter is changed ONLY when it is
#   (a) between two digits inside one number ("1O0" -> "100", "12l5" -> "1215"), or
#   (b) at the edge of a number that is directly followed by a unit ("2S mm" -> "25 mm", "l50 kPa").
# Everything else ("3D", "IS0 9001", "Class 2S") is left alone.
_CONFUSABLE = {"O": "0", "o": "0", "l": "1", "I": "1", "S": "5", "B": "8", "Z": "2"}
_C = "OolISBZ"
_UNIT = r"(?:mm|cm|km|kg|kN|kPa|MPa|Pa|kW|Hz|mL|m|N|W|V|L|%)"
_LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}

_INSIDE = re.compile(rf"(?<=\d)[{_C}]+(?=\d)")
_KILO = re.compile(r"(\d\s?)K(N|Pa|g|m|W|Hz|J|V)\b")
_EDGE = re.compile(rf"(?<![A-Za-z\d])([{_C}]?\d[\d.,]*[{_C}]?|[{_C}]\d*)(?=\s?{_UNIT}\b)")


def _fix_token(tok: str) -> str:
    if not any(c.isdigit() for c in tok):
        return tok
    return "".join(_CONFUSABLE.get(c, c) for c in tok)


def correct_text(text: str):
    log = []
    out = text
    for k, v in _LIG.items():
        if k in out:
            log.append({"rule": "ligature", "from": k, "to": v, "count": out.count(k)})
            out = out.replace(k, v)

    def num(m):
        tok = m.group(1)
        fixed = _fix_token(tok)
        if fixed != tok:
            log.append({"rule": "confusable_in_number", "from": tok, "to": fixed})
        return fixed

    def inside(m):
        fixed = "".join(_CONFUSABLE[c] for c in m.group(0))
        log.append({"rule": "confusable_in_number", "from": m.group(0), "to": fixed})
        return fixed

    out = _INSIDE.sub(inside, out)
    out = _EDGE.sub(num, out)

    def kilo(m):
        log.append({"rule": "si_prefix_case", "from": m.group(0), "to": m.group(1) + "k" + m.group(2)})
        return m.group(1) + "k" + m.group(2)

    # SI has no capital-K prefix: "2.7 KN" after a number is always a misread "kN"
    out = _KILO.sub(kilo, out)

    def hyph(m):
        log.append({"rule": "line_break_hyphen", "from": m.group(0).replace("\n", "\\n"), "to": m.group(1) + m.group(2)})
        return m.group(1) + m.group(2)

    # "fire-\nresistance" is a broken word only when both halves are lowercase letters
    out = re.sub(r"([a-z]{2,})-\n([a-z]{2,})", hyph, out)

    return out, log
