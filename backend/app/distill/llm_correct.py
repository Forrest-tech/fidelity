# -*- coding: utf-8 -*-
"""Constrained local correction model (spec F-14 layer 4, Phase 6 — runs on the Mac mini).

Where two OCR engines still disagree on a word after the rule and glossary layers, a local model
(Ollama) is asked to pick the reading that fits the sentence. The model is constrained by code, not by
trust:
  - it only sees spans where the engines disagree (word for word);
  - its answer must be EXACTLY one of the engines' readings (or a glossary word for that span),
    anything else is discarded;
  - spans containing digits are never decided by the model (numbers must be 100 % right: review);
  - every choice is logged; nothing happens unless FIDELITY_LLM_URL is set.

    FIDELITY_LLM_URL=http://127.0.0.1:11434  FIDELITY_LLM_MODEL=qwen2.5:7b-instruct
"""
from __future__ import annotations

import difflib
import json
import os
import re
import urllib.request

from . import glossary

URL = os.environ.get("FIDELITY_LLM_URL", "")
MODEL = os.environ.get("FIDELITY_LLM_MODEL", "qwen2.5:7b-instruct")
CONTEXT_WORDS = 8
_TOKEN = re.compile(r"\S+")

PROMPT = """You are checking an OCR transcription of a building-code document. Two OCR engines read one word
differently. Choose which reading is correct in this sentence. You must answer with one of the candidates
exactly as written, and nothing else.

Sentence: {context}
Candidates: {candidates}

Answer as JSON: {{"choice": "<one candidate exactly>"}}"""


def enabled() -> bool:
    return bool(URL)


def ask_ollama(prompt: str, url: str = None, model: str = None, timeout: int = 60) -> str:
    body = json.dumps({"model": model or MODEL, "prompt": prompt, "stream": False, "format": "json",
                       "options": {"temperature": 0}}).encode("utf-8")
    req = urllib.request.Request((url or URL).rstrip("/") + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("response", "")


def _choice(raw: str) -> str:
    try:
        return str(json.loads(raw).get("choice", "")).strip()
    except (ValueError, AttributeError):
        return raw.strip().strip('"')


def _replace(text, spans):
    out, last = [], 0
    for (s, e), new in sorted(spans.items()):
        out += [text[last:s], new]
        last = e
    return "".join(out + [text[last:]])


def resolve(a: str, b: str, names=("a", "b"), ask=None, known=None):
    """Return (a2, b2, log). `ask(prompt) -> raw answer` defaults to the local Ollama model."""
    ask = ask or ask_ollama
    known = known if known is not None else glossary.load()
    ma, mb = list(_TOKEN.finditer(a)), list(_TOKEN.finditer(b))
    wa, wb = [m.group() for m in ma], [m.group() for m in mb]
    sa, sb, log = {}, {}, []
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "replace" or i2 - i1 != j2 - j1:
            continue
        for x, y in zip(range(i1, i2), range(j1, j2)):
            ta, tb = wa[x], wb[y]
            if ta == tb or any(ch.isdigit() for ch in ta + tb):        # numbers: never decided by a model
                continue
            cands = [ta, tb] + [w for w in known if w not in (ta, tb) and
                                difflib.SequenceMatcher(None, glossary.core(ta), w).ratio() >= 0.7][:3]
            ctx = " ".join(wa[max(0, x - CONTEXT_WORDS):x] + ["[" + " / ".join(cands) + "]"] + wa[x + 1:x + 1 + CONTEXT_WORDS])
            try:
                pick = _choice(ask(PROMPT.format(context=ctx, candidates=json.dumps(cands))))
            except Exception as e:                       # model down: leave the span for review
                log.append({"rule": "llm", "skipped": str(e)[:80], "from": ta, "to": tb})
                continue
            if pick not in cands:                        # the constraint: only a value an engine or the glossary gave
                log.append({"rule": "llm", "rejected": pick[:40], "from": ta, "to": tb})
                continue
            if pick != ta:
                sa[ma[x].span()] = pick
            if pick != tb:
                sb[mb[y].span()] = pick
            log.append({"rule": "llm", "engine": names[0] if pick != ta else names[1], "from": tb if pick == ta else ta,
                        "to": pick, "model": MODEL})
    return _replace(a, sa), _replace(b, sb), log
