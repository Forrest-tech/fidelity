# -*- coding: utf-8 -*-
"""Accepting a distilled file into the knowledge base ("入库").

A result below the threshold carries `audit_status: pending_review` in its front matter. When a person accepts it,
the published copy says so: who accepted it, when, and the accuracy it had, so nobody reading the knowledge base
mistakes it for a file the system verified on its own.
"""
from __future__ import annotations

import re

_FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _yaml(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def accept_markdown(text: str, who: str, when: str, accuracy, forced: bool, edition: dict | None = None) -> str:
    """Return `text` with its front matter updated for a human acceptance.

    forced=True: the file did not pass on its own (it was below the room's threshold), so audit_status becomes
    human_accepted and `verified` says who accepted it. forced=False: the file qualified by its accuracy and keeps
    its status; the acceptance is only recorded. Text without front matter is returned unchanged.

    edition: the file's edition in the library (distill/editions.py). Its lines replace any earlier ones, and a
    superseded edition gets a one-line notice at the top of the body, so an answer drawn from it says so."""
    from . import editions as ED
    stamp = ED.stamp_lines(edition)
    stamp_keys = {ln.split(":", 1)[0] for ln in stamp}
    m = _FM.match(text)
    if not m:
        return text
    lines = m.group(1).split("\n")
    out, seen = [], set()
    for ln in lines:
        key = ln.split(":", 1)[0].strip() if ":" in ln else ""
        if key in ("accepted_by", "accepted_at", "accuracy") or key in stamp_keys or \
                (stamp and key in ("edition", "amends", "amendment", "superseded_by")):
            continue                                            # replaced below
        if forced and key == "audit_status":
            ln = "audit_status: human_accepted"
        elif forced and key == "verified":
            ln = "verified: " + _yaml(f"accepted by {who} on {when} at {accuracy}% accuracy (did not pass the automatic checks)")
        out.append(ln)
        seen.add(key)
    out += [f"accuracy: {accuracy}" if accuracy is not None else "accuracy: null",
            f"accepted_by: {_yaml(who)}", f"accepted_at: {_yaml(when)}"] + stamp
    body = text[m.end():]
    if body.startswith(ED.BANNER_MARK):                         # an earlier notice: replaced (or dropped) below
        body = body.split("\n", 2)[2] if body.count("\n") >= 2 else ""
    if stamp:
        body = ED.banner(edition) + body
    return "---\n" + "\n".join(out) + "\n---\n" + body


def live_key(out_dir: str, top: str | None = None) -> str:
    """Where a document belongs in the output folder: its output path without the local `_pending` marker.

    `top` is the source folder's name as the person sees it ("AS 3500"). Results distilled before the name kept
    its letter case were filed under the lower-case form ("as 3500"); the output mirrors the source, so the first
    folder is written the way the source spells it."""
    k = out_dir.replace("\\", "/").strip("/")
    k = k[len("_pending/"):] if k.startswith("_pending/") else k
    if top:
        head, sep, rest = k.partition("/")
        if head.lower() == top.lower():
            k = top + sep + rest
    return k
