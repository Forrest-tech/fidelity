# -*- coding: utf-8 -*-
"""统计"""
import os
from fastapi import APIRouter, HTTPException

from .. import config, db
from ..domain import trust

router = APIRouter()

@router.get("/stats")
def stats(sid: str = "n2"):
    """总览：各状态文件数 + 平均自动分 + 已审比例。"""
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    md_root = src["md_root"]
    rels = []
    for dp, dn, fn in os.walk(md_root):
        if "_kb" in dp or "_review" in dp:
            continue
        for name in fn:
            if name.endswith(".md"):
                rels.append(os.path.relpath(os.path.join(dp, name), md_root).replace("\\", "/")[:-3])
    badges = trust.badges_bulk(rels)
    # ⚠️ 必须把 5 个状态**全部**列出（含 0）：前端统计行是 5 个固定卡片，
    # 若某状态当前为 0 就把 key 省掉，对应卡片会整个消失 —— 界面上看起来像
    # 「这个状态不存在」，而不是「0 个」。空态与不存在是两件事。
    by_state = {"trusted": 0, "need_review": 0, "diff_big": 0,
                "rejected": 0, "unreviewed": 0}
    scores = []
    reviewed = 0
    for b in badges.values():
        by_state[b["state"]] = by_state.get(b["state"], 0) + 1
        if b["auto_score"] is not None:
            scores.append(b["auto_score"])
        if b["trust_state"]:
            reviewed += 1
    n = len(badges) or 1
    # 延后（大文件/慢文件）单独计数：不算失败，是待办
    deferred = 0
    try:
        con = db.trust_rw()
        try:
            deferred = con.execute(
                "SELECT count(*) FROM file_eval WHERE status='deferred'").fetchone()[0]
        finally:
            con.close()
    except Exception:
        pass
    # 人工决定队列（无法自动比对：待决定/已入库/已排除）
    try:
        dec = trust.decision_stats()
    except Exception:
        dec = {"pending": 0, "include": 0, "exclude": 0}
    return {
        "total": len(badges),
        "by_state": by_state,
        "deferred": deferred,
        "decisions": dec,
        "salvage": len(trust.salvage_list(2000)),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "evaluated": len(scores),
        "reviewed": reviewed,
        "reviewed_pct": round(100.0 * reviewed / n, 1),
        # 字数总量：源文 vs 入库 .md（用户 2026-10-04 需求，直观的体量指标）
        "totals": trust.totals(),
    }
