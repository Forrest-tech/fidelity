# -*- coding: utf-8 -*-
"""API 路由聚合层：各领域路由在同目录模块中，这里只负责拼装。"""
from fastapi import APIRouter

from . import (sources, files, decisions, reviewers, tree, align, preview,
               review, stats, ingest, distill, overview, dropbox_sync, storage, rooms)
from .align import ALIGN_MAX_LINES, MAX_SEG_CHARS  # noqa: F401  (re-export, used by scripts)

router = APIRouter()
for _m in (sources, files, decisions, reviewers, tree, align, preview, review, stats, ingest, distill, overview,
           dropbox_sync, storage, rooms):
    router.include_router(_m.router)
