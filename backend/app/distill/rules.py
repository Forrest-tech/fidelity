# -*- coding: utf-8 -*-
"""Correction rules: a fix a person confirmed once, applied again wherever the same reading appears.

No learning and no guessing: a rule replaces an exact piece of text.

    text rule     the wrong text, as a whole word or phrase ("Watre" -> "Water"). Applied wherever it appears.
    number rule   the wrong text contains or produces a digit ("l50 mm" -> "150 mm"). Numbers are where a wrong
                  fix does real harm, so a number rule also stores the text right before and after the place it
                  was confirmed, and applies only where that whole context matches exactly.

Scope says where a rule applies: one document, the same standard series (AS 3500.1 in every edition), or all.
Rules apply to the Markdown body only; the front matter is left alone.
"""
from __future__ import annotations

import re

SCOPES = ("document", "series", "all")
MAX_LEN = 200            # a rule fixes a short piece of text, not a paragraph
CONTEXT = 12             # characters of context kept on each side for a number rule
MIN_CONTEXT = 3          # a number rule needs at least this much non-blank context in total


class RuleError(ValueError):
    pass


# ------------------------------------------------------------------ which documents belong together
_STD = re.compile(r"(?<![A-Za-z])(AS\s*[/_-]\s*NZS|AS|NZS|ISO|IEC|EN|BS|ASME|ANSI|NFPA)[\s_-]*(\d{2,5}(?:\.\d+)*)", re.I)
_NCC = re.compile(r"(?<![A-Za-z])(NCC|BCA)(?![A-Za-z])", re.I)


def series_of(rel: str) -> str | None:
    """The standard a file belongs to, without its year: '/2003/AS 3500.1-2003 Water.pdf' -> 'AS 3500.1'.

    AS/NZS and AS are the same series. The file name decides; the folders are used only when it says nothing."""
    parts = [p for p in (rel or "").replace("\\", "/").split("/") if p]
    for text in ([parts[-1]] if parts else []) + list(reversed(parts[:-1])):
        m = _STD.search(text)
        if m:
            fam = re.sub(r"[\s_/-]+", "/", m.group(1).upper())
            return f"{'AS' if fam == 'AS/NZS' else fam} {m.group(2)}"
        m = _NCC.search(text)
        if m:
            return m.group(1).upper()
    return None


def doc_key(rel: str) -> str:
    """A document regardless of which room it is in: its file name."""
    return (rel or "").replace("\\", "/").rsplit("/", 1)[-1].lower()


def applies_to(rule: dict, rel: str) -> bool:
    if rule["scope"] == "all":
        return True
    if rule["scope"] == "series":
        return bool(rule.get("series")) and series_of(rel) == rule["series"]
    return doc_key(rel) == rule.get("doc")


# ------------------------------------------------------------------ the text
def split_front(text: str) -> tuple[str, str]:
    """(front matter including its fences, body)."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[:end + 5], text[end + 5:]
    return "", text


def is_number(find: str, replace: str) -> bool:
    return any(c.isdigit() for c in find + replace)


def _pattern(rule: dict) -> re.Pattern:
    find = re.escape(rule["find"])
    if rule["kind"] == "number":
        return re.compile(re.escape(rule.get("before") or "") + "(" + find + ")" + re.escape(rule.get("after") or ""))
    left = r"(?<!\w)" if re.match(r"\w", rule["find"]) else ""
    right = r"(?!\w)" if re.search(r"\w$", rule["find"]) else ""
    return re.compile(left + "(" + find + ")" + right)


def count(rule: dict, text: str) -> int:
    _, body = split_front(text)
    if rule["find"] not in body:
        return 0
    return len(_pattern(rule).findall(body))


def apply(text: str, rules: list) -> tuple[str, dict]:
    """Apply rules in order. Returns (new text, {rule id: places changed})."""
    front, body = split_front(text)
    done = {}
    for rule in rules:
        if rule["find"] not in body:
            continue
        pat = _pattern(rule)
        n = 0

        def sub(m, rule=rule):
            nonlocal n
            n += 1
            whole = m.group(0)
            s, e = m.start(1) - m.start(0), m.end(1) - m.start(0)
            return whole[:s] + rule["replace"] + whole[e:]

        body = pat.sub(sub, body)
        if n:
            done[rule["id"]] = n
    return front + body, done


def check(find: str, replace: str, scope: str):
    if scope not in SCOPES:
        raise RuleError("scope must be document, series or all")
    if not find or not find.strip():
        raise RuleError("enter the text that is wrong")
    if "\n" in find or "\n" in replace:
        raise RuleError("a rule fixes text within one line")
    if len(find) > MAX_LEN or len(replace) > MAX_LEN:
        raise RuleError(f"a rule fixes at most {MAX_LEN} characters")
    if find == replace:
        raise RuleError("the correct text is the same as the wrong text")


def context(texts: list, find: str) -> tuple[str, str]:
    """For a number rule: the text right before and after `find` in the document it is confirmed in.

    `find` must appear exactly once there, so it is clear which place the person checked."""
    hits = []
    for t in texts:
        _, body = split_front(t)
        start = 0
        while True:
            i = body.find(find, start)
            if i < 0:
                break
            hits.append((body, i))
            start = i + 1
    if not hits:
        raise RuleError("this text does not appear in the document")
    if len(hits) > 1:
        raise RuleError(f"this text appears {len(hits)} times in the document; include a few more characters around "
                        "the place you checked so it appears once")
    body, i = hits[0]
    s, e = max(0, i - CONTEXT), min(len(body), i + len(find) + CONTEXT)
    while s > max(0, i - 2 * CONTEXT) and body[s - 1].isalnum() and body[s].isalnum():
        s -= 1                                    # whole words: do not start or end in the middle of one
    while e < min(len(body), i + len(find) + 2 * CONTEXT) and body[e - 1].isalnum() and body[e].isalnum():
        e += 1
    before = body[s:i].rsplit("\n", 1)[-1]
    after = body[i + len(find):e].split("\n", 1)[0]
    if len((before + after).strip()) < MIN_CONTEXT:
        raise RuleError("a number fix needs some text around it; include a few more characters so it can be "
                        "matched exactly elsewhere")
    return before, after
