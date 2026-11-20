# -*- coding: utf-8 -*-
"""Per-file events of a sync run, written as one JSON object per line.

The sync prints a human log; this is the same run as data. The web side reads it while the run is going
and keeps one row per file of a distillation room, so the page can show every file's own state.

    listing      the files found in the source folder: {files: [{rel, size, kind}]}
    start        a file is being processed: {rel}
    file         a file reached an outcome: {rel, outcome, reason, accuracy, parts, diffs, number_diffs, findings, pages, scan}
    unchanged    the file did not change since the last run: {rel}
"""
from __future__ import annotations

import json
import os
import time


class Events:
    def __init__(self, path: str | None):
        self.path = path
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def emit(self, type_: str, **fields):
        if not self.path:
            return
        line = json.dumps({"t": time.time(), "type": type_, **fields}, ensure_ascii=False, default=str)
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
            f.flush()


def kind_of(rel: str) -> str:
    return os.path.splitext(rel)[1].lower().lstrip(".")
