"""The distilled library as an AI tool sees it: Markdown files with front matter, cut into page units, and a BM25 search
over them (an AI tool searches by words and file names, then reads the file)."""
from __future__ import annotations

import collections
import math
import os
import re
from dataclasses import dataclass

from ..adapters.facts import front_matter

UNIT = re.compile(r"<!-- unit: p\d+ \| src: p\.(\d+)[^>]*-->(.*?)(?=<!-- unit:|<!-- /unit -->|\Z)", re.S)
_TOKEN = re.compile(r"[a-z]+|\d+(?:\.\d+)*")
_DESIG = re.compile(r"\b3500\.(\d)\b")
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")


@dataclass
class Unit:
    path: str
    file: str
    document: str
    source_filename: str
    std_id: str
    year: str
    edition_status: str
    chapter: str
    clauses: str
    page: int
    text: str

    def header(self) -> str:
        return (f"file: {self.file} | document: {self.document} | edition_status: {self.edition_status or 'unknown'}"
                f" | page: p.{self.page} | chapter: {self.chapter} | clauses: {self.clauses}")


def _lp(p: str) -> str:
    p = os.path.abspath(p)
    return "\\\\?\\" + p if os.name == "nt" and not p.startswith("\\\\") else p


def load(root: str) -> list[Unit]:
    units = []
    for d, _, files in os.walk(_lp(root)):
        for f in sorted(files):
            if not f.endswith(".md") or "/_pending" in d.replace("\\", "/"):
                continue
            path = os.path.join(d, f)
            fm = front_matter(path)
            with open(path, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            end = body.find("\n---", 3) if body.startswith("---") else -1
            body = body[end + 4:] if end > 0 else body
            year = fm.get("std_year") or (m.group(1) if (m := _YEAR.search(fm.get("document", ""))) else "")
            for m in UNIT.finditer(body):
                units.append(Unit(path, f, fm.get("document", f), fm.get("source_filename", ""), fm.get("std_id", ""),
                                  year, fm.get("edition_status", ""), fm.get("chapter", ""), fm.get("clauses", ""),
                                  int(m.group(1)), m.group(2).strip()))
    return units


def tokens(s: str) -> list[str]:
    return _TOKEN.findall(s.lower())


class Search:
    """BM25 over page units; the file name, chapter and clause list count as part of each unit, as a file-name search
    would find them. A designation in the question ("3500.2", "2021") steers to that document and edition."""

    def __init__(self, units: list[Unit], k1: float = 1.4, b: float = 0.75):
        self.units = units
        self.docs = [collections.Counter(tokens(f"{u.file} {u.chapter} {u.clauses} {u.text}")) for u in units]
        self.len = [sum(c.values()) for c in self.docs]
        self.avg = sum(self.len) / max(1, len(self.len))
        df = collections.Counter(t for c in self.docs for t in c)
        n = len(units)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def top(self, question: str, k: int = 8) -> list[Unit]:
        q = [t for t in tokens(question) if t in self.idf]
        part = _DESIG.findall(question)
        years = _YEAR.findall(question)
        scored = []
        for i, c in enumerate(self.docs):
            s = 0.0
            for t in q:
                f = c.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            u = self.units[i]
            name = f"{u.document} {u.file}"
            if part:
                s *= 1.6 if any(f"3500.{p}" in name for p in part) else 0.35
            if years:
                s *= 1.4 if u.year in years else 0.6
            scored.append((s, i))
        scored.sort(reverse=True)
        return [self.units[i] for s, i in scored[:k] if s > 0]
