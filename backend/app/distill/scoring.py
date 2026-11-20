# -*- coding: utf-8 -*-
"""One accuracy percentage per distilled file, and a clear line between "has a result" and "no result".

The verification report has many separate checks (text recall, numbers, headings, tables ...). A person
needs one number to decide with, plus the list of places that cost accuracy. A file that could not be
read at all has no percentage: it is "unprocessable", with a reason, and is not a quality problem.

    outcome  result          a result exists; `accuracy` is set (0-100)
             unprocessable   no result could be produced; `reason` says why
             skipped         deliberately not distilled (e.g. protected by the vendor)

For a scanned file there is no text layer to compare with, so the percentage is how closely the two OCR
engines agree page by page (`basis` says which). A formula the text layer cannot decode is listed as a finding
but does not count as a number difference: the output already carries an explicit warning marker there.

Whether a result is good enough is decided later, against the user's own threshold, by `decide()`.
Changing the threshold therefore never needs a re-run.
"""
from __future__ import annotations

import re

# Share of each check in the single number. Checks that do not apply to a file type are left out and the
# remaining weights are scaled up, so an image-only file is not punished for having no tables.
WEIGHTS = {"text": 0.40, "numbers": 0.30, "headings": 0.20, "tables": 0.10}

REASONS = {
    "download": "Could not download the file (network or permission).",
    "unreadable": "The file is damaged or cannot be read.",
    "protected": "The file is copy-protected, so its text may not be extracted.",
    "resources": "The machine ran out of memory or disk space.",
    "source_changed": "The source file changed while it was being processed, so the result cannot be trusted.",
    "unsupported": "This file type is not handled yet.",
    "duplicate": "Same content as another file in this folder; it is distilled once.",
    "other": "Processing stopped with an error.",
}

_REASON_PATTERNS = (
    ("source_changed", ("SOURCE CHANGED", "does not match the source file's checksum", "source changed")),
    ("resources", ("No space left", "not enough free disk", "MemoryError", "out of memory", "Cannot allocate memory")),
    ("download", ("download", "SSLError", "ConnectionError", "Timeout", "timed out", "Max retries", "RemoteDisconnected",
                  "shared_link", "403", "429", "5xx")),
    ("unreadable", ("MuPDF", "cannot open", "not a PDF", "broken", "damaged", "EOF marker", "Failed to open", "BadZipFile",
                    "format error", "repair")),
)


def reason_code(error_text: str) -> str:
    """Map an error message from the pipeline to one of REASONS."""
    t = error_text or ""
    for code, needles in _REASON_PATTERNS:
        if any(n.lower() in t.lower() for n in needles):
            return code
    return "other"


def _num(d, key="recall"):
    v = d.get(key) if isinstance(d, dict) else None
    return float(v) if isinstance(v, (int, float)) else None


def parts_from_report(rep: dict) -> dict:
    """The per-check scores (0..1, or None when a check does not apply to this file)."""
    parts = {"text": None, "numbers": None, "headings": None, "tables": None}
    if not isinstance(rep, dict):
        return parts
    if rep.get("route") == "ocr":                       # scanned file: how closely the two OCR engines agree
        pages = rep.get("pages") or []
        if pages:
            parts["text"] = sum(float(p.get("agreement") or 0.0) for p in pages) / len(pages)
        return parts
    chars = _num(rep.get("chars"))
    if chars is not None:
        pc = rep.get("page_count") or 0
        missing = len((rep.get("pages") or {}).get("missing") or []) if isinstance(rep.get("pages"), dict) else 0
        extra = len((rep.get("extra_text") or {}).get("pages") or []) if isinstance(rep.get("extra_text"), dict) else 0
        penalty = (missing + extra) / pc if pc else 0.0       # whole pages lost or duplicated cost more than a missing letter
        parts["text"] = max(0.0, chars - penalty)
    parts["numbers"] = _num(rep.get("numbers"))
    h = rep.get("headings")
    if isinstance(h, dict) and isinstance(h.get("total"), int) and h["total"] > 0:
        parts["headings"] = max(0.0, 1 - (h.get("unmatched") or 0) / h["total"])
    t = rep.get("tables")
    if isinstance(t, dict) and (t.get("cells") or 0) > 0:
        parts["tables"] = max(0.0, 1 - (t.get("mismatches") or 0) / t["cells"])
    return parts


def accuracy(parts: dict, weights: dict | None = None):
    """Weighted accuracy, 0..100 with one decimal, over the checks that apply. None if none applies."""
    w = weights or WEIGHTS
    used = {k: v for k, v in parts.items() if v is not None and w.get(k)}
    if not used:
        return None
    total = sum(w[k] for k in used)
    return round(100 * sum(parts[k] * w[k] for k in used) / total, 1)


def findings(rep: dict, limit: int = 200) -> list:
    """The places that cost accuracy: [{kind, page, detail}] for the review list."""
    out = []
    if not isinstance(rep, dict):
        return out
    for page, items in ((rep.get("numbers") or {}).get("pages_with_missing") or []):
        out.append({"kind": "numbers", "page": page, "detail": "missing: " + ", ".join(map(str, items[:6]))})
    for r, page, lost in ((rep.get("chars") or {}).get("pages_below_99_5") or []):
        out.append({"kind": "text", "page": page, "detail": f"recall {r}, {lost} characters missing"})
    for page, extra in ((rep.get("extra_text") or {}).get("pages") or []):
        out.append({"kind": "text", "page": page, "detail": f"{extra} characters not on the source page"})
    for ex in ((rep.get("headings") or {}).get("examples") or []):
        m = re.match(r"p\.(\d+)\s+(.*)", ex)
        out.append({"kind": "headings", "page": int(m.group(1)) if m else None, "detail": m.group(2) if m else ex})
    for ex in ((rep.get("tables") or {}).get("examples") or []):
        out.append({"kind": "tables", "page": ex.get("page") if isinstance(ex, dict) else None,
                    "detail": ex.get("detail") if isinstance(ex, dict) else str(ex)})
    for page in sorted(set(((rep.get("unreadable") or {}).get("pages") or []))):
        out.append({"kind": "formula", "page": page, "detail": "text layer cannot be decoded"})
    for page in (rep.get("review_pages") or []):
        out.append({"kind": "text", "page": page, "detail": "the two OCR engines disagree"})
    return out[:limit]


def classify(result: dict, error: str | None = None) -> dict:
    """Turn one file's pipeline result (or its error) into an outcome. `result` is what distill_any returns."""
    if error is not None or not result:
        return {"outcome": "unprocessable", "reason": reason_code(error or ""), "accuracy": None, "parts": {},
                "diffs": 0, "number_diffs": 0, "findings": [], "detail": (error or "")[:300]}
    verdict, rep = result.get("verdict"), result.get("report") or {}
    if verdict == "SKIP":
        cls = ((result.get("triage") or {}).get("class")) or ""
        return {"outcome": "skipped" if cls != "protected" else "unprocessable",
                "reason": "protected" if cls == "protected" else "unsupported", "accuracy": None, "parts": {},
                "diffs": 0, "number_diffs": 0, "findings": [],
                "detail": ((result.get("triage") or {}).get("reason")) or ""}
    if isinstance(rep.get("source_unchanged"), dict) and rep["source_unchanged"].get("ok") is False:
        return {"outcome": "unprocessable", "reason": "source_changed", "accuracy": None, "parts": {}, "diffs": 0,
                "number_diffs": 0, "findings": [], "detail": REASONS["source_changed"]}
    parts = parts_from_report(rep)
    acc = accuracy(parts)
    items = findings(rep)
    return {"outcome": "result", "reason": "", "accuracy": acc, "parts": {k: (None if v is None else round(v, 4)) for k, v in parts.items()},
            "diffs": len(items), "number_diffs": sum(1 for f in items if f["kind"] == "numbers"),
            "findings": items, "detail": "",
            "basis": "ocr_agreement" if rep.get("route") == "ocr" else "verification"}


def decide(accuracy_value, number_diffs: int, threshold: float, number_guard: bool = True) -> str:
    """'ok' (meets the threshold) or 'below'. With the guard on, any number difference keeps a file below."""
    if accuracy_value is None:
        return "below"
    if number_guard and number_diffs > 0:
        return "below"
    return "ok" if accuracy_value >= threshold else "below"
