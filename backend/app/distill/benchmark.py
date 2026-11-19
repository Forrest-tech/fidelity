# -*- coding: utf-8 -*-
"""Synthetic-scan benchmark (spec section 9, Phase 4).

Text-layer pages are rendered to images and degraded (skew, blur, noise, low resolution), so the
exact ground truth is known. Each OCR engine and the two-engine vote are scored:
  character accuracy = 1 - Levenshtein distance / ground-truth length (whitespace normalised)
  number recall      = share of numbers in the ground truth found in the OCR text
  routed to review   = pages the vote sends to a human (should catch the bad pages)
"""
from __future__ import annotations

import random
import re
from collections import Counter

from rapidfuzz.distance import Levenshtein

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")

DEGRADATIONS = {
    "clean": {},
    "skew": {"angle": 1.5},
    "blur": {"blur": 1.2},
    "noise": {"noise": 18},
    "low_res": {"dpi": 150},
    "combined": {"angle": 1.0, "blur": 0.8, "noise": 12, "dpi": 200},
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def char_accuracy(truth: str, got: str) -> float:
    t, g = norm(truth), norm(got)
    if not t:
        return 1.0 if not g else 0.0
    return max(0.0, 1.0 - Levenshtein.distance(t, g) / len(t))


def char_recall(truth: str, got: str) -> float:
    """Order-insensitive: share of the ground truth's letters/digits present in the OCR text.
    Separates *lost* characters from reading-order differences, which char_accuracy also penalises."""
    t = Counter(ch for ch in truth.lower() if ch.isalnum())
    g = Counter(ch for ch in got.lower() if ch.isalnum())
    tot = sum(t.values())
    return 1.0 if not tot else sum(min(c, g.get(k, 0)) for k, c in t.items()) / tot


def number_recall(truth: str, got: str) -> float:
    tn, gn = Counter(NUM_RE.findall(truth)), Counter(NUM_RE.findall(got))
    tot = sum(tn.values())
    return 1.0 if not tot else sum(min(c, gn.get(k, 0)) for k, c in tn.items()) / tot


def degrade(img, angle=0.0, blur=0.0, noise=0, dpi_scale=1.0, seed=7):
    from PIL import Image, ImageFilter
    rnd = random.Random(seed)
    im = img.convert("L")
    if dpi_scale != 1.0:
        im = im.resize((int(im.width * dpi_scale), int(im.height * dpi_scale)), Image.BILINEAR)
    if angle:
        im = im.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        import numpy as np
        a = np.asarray(im).astype("int16")
        rng = np.random.default_rng(rnd.randint(0, 10_000))
        a = np.clip(a + rng.normal(0, noise, a.shape), 0, 255).astype("uint8")
        im = Image.fromarray(a)
    return im


def page_truth(pdf_path: str, index: int) -> str:
    import pymupdf
    doc = pymupdf.open(pdf_path)
    try:
        return doc[index].get_text()
    finally:
        doc.close()


def run(pdf_path: str, pages, engines=None, degradations=None, log=print) -> dict:
    from . import ocr as O
    engines = engines if engines is not None else O.all_engines()
    degradations = degradations or DEGRADATIONS
    rows = []
    for idx in pages:
        truth = page_truth(pdf_path, idx)
        base_dpi = 300
        for dname, d in degradations.items():
            dpi = d.get("dpi", base_dpi)
            img = O.render_page(pdf_path, idx, dpi=base_dpi)
            img = degrade(img, d.get("angle", 0), d.get("blur", 0), d.get("noise", 0), dpi / base_dpi, seed=idx)
            res = O.ocr_image(img, idx + 1, engines)
            row = {"page": idx + 1, "degradation": dname, "status": res.status, "agreement": res.agreement,
                   "engines": {}}
            for name, r in res.engines.items():
                row["engines"][name] = {"char_acc": round(char_accuracy(truth, r["text_corrected"]), 5),
                                        "char_recall": round(char_recall(truth, r["text_corrected"]), 5),
                                        "num_recall": round(number_recall(truth, r["text_corrected"]), 5),
                                        "conf": r["conf"]}
            row["published_char_acc"] = round(char_accuracy(truth, res.text), 5)
            rows.append(row)
            log(f"  p{idx + 1} {dname}: {row['engines']} -> {res.status}")
    models = {e.name: getattr(e, "model", None) or "default" for e in engines}
    return {"pdf": pdf_path, "engines": [e.name for e in engines], "models": models, "rows": rows,
            "summary": summarize(rows)}


def summarize(rows) -> dict:
    out = {}
    for d in sorted({r["degradation"] for r in rows}):
        rs = [r for r in rows if r["degradation"] == d]
        e = {}
        for name in rs[0]["engines"] if rs else []:
            e[name] = {"char_acc": round(sum(r["engines"][name]["char_acc"] for r in rs) / len(rs), 5),
                       "char_recall": round(sum(r["engines"][name]["char_recall"] for r in rs) / len(rs), 5),
                       "num_recall": round(sum(r["engines"][name]["num_recall"] for r in rs) / len(rs), 5)}
        auto = [r for r in rs if r["status"] == "ok"]
        out[d] = {"pages": len(rs), "engines": e, "auto_accepted": len(auto),
                  "auto_accepted_min_char_acc": min((r["published_char_acc"] for r in auto), default=None)}
    return out


def to_markdown(result: dict) -> str:
    lines = ["# OCR synthetic-scan benchmark", "",
             f"Engines: {', '.join(e + ' (' + result.get('models', {}).get(e, 'default') + ' model)' for e in result['engines']) or 'none'}. Ground truth: text layer of `{result['pdf'].split('/')[-1].split(chr(92))[-1]}`.",
             "", "| Degradation | Pages | " + " | ".join(f"{e}: accuracy / recall / numbers" for e in result["engines"])
             + " | Auto-accepted | Worst accepted page |", "|---|---|" + "---|" * len(result["engines"]) + "---|---|"]
    for d, s in result["summary"].items():
        cells = [f"{s['engines'][e]['char_acc'] * 100:.1f}% / {s['engines'][e]['char_recall'] * 100:.1f}% / "
                 f"{s['engines'][e]['num_recall'] * 100:.1f}%" for e in result["engines"]]
        worst = s["auto_accepted_min_char_acc"]
        lines.append(f"| {d} | {s['pages']} | " + " | ".join(cells) + f" | {s['auto_accepted']} | "
                     + (f"{worst * 100:.2f}%" if worst is not None else "-") + " |")
    lines += ["", "Accuracy = 1 - edit distance / length (reading order counts). Recall = share of the ground truth's",
              "letters and digits found anywhere on the page (order ignored). Numbers = share of numbers found.",
              "Auto-accepted pages are published without review; all others go to the review queue."]
    return "\n".join(lines) + "\n"


def select(result: dict, path: str = None) -> dict:
    """Rank engines by mean accuracy over all degradations and record the best two as the engines the
    pipeline uses (spec Phase 6: engines chosen by benchmark). The first one's text is published."""
    import datetime as _dt
    import json as _json
    import os as _os
    score = {}
    for d in result["summary"].values():
        for name, m in d["engines"].items():
            score.setdefault(name, []).append(m["char_acc"])
    ranked = sorted(score, key=lambda n: -sum(score[n]) / len(score[n]))
    sel = {"engines": ranked[:2], "mean_char_acc": {n: round(sum(score[n]) / len(score[n]), 5) for n in ranked},
           "benchmark": _os.path.basename(result.get("pdf", "")), "selected": _dt.date.today().isoformat()}
    path = path or O.SELECTION_FILE
    _os.makedirs(_os.path.dirname(_os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(sel, f, indent=1)
    return sel
