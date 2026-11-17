# -*- coding: utf-8 -*-
"""人工裁决与批量审核"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..domain import trust

router = APIRouter()
from .reviewers import _check_reviewer  # noqa: E402

# ---------- 人工裁决 ----------
class VerdictIn(BaseModel):
    verdict: str  # ok / diff_big / rejected / "" (重置未审)
    reviewer: str = "local"
    note: str = ""


# ---------- 批量人工审核（按正确率阈值） ----------
# ⚠️ 必须声明在 `/review/{rel:path}` **之前**：FastAPI 按声明顺序匹配路由，
# 若放在后面，字面量路径 "batch" 会被 {rel:path} 抢先捕获，导致 422。
class BatchReviewIn(BaseModel):
    """按阈值批量打「人工审核通过」标签。

    语义边界（重要）：
      * 只处理 **自动评测已完成**（有 auto_score）的文件；
        没有任何自动分的文件一律跳过 —— 拿「没测过」的文件去凑通过率是错的。
      * 阈值由前端传入，默认 90；只有 score >= threshold 才写入 ok。
      * 全部写入审计日志（file_trust_log），审核人 = 当前选中的人，可追溯。
      * 已经人工裁决过的文件**不覆盖**，避免抹掉历史判断。
    """

    rels: list[str]
    threshold: float = 90.0
    reviewer: str = ""
    note: str = ""


@router.post("/review/batch")
def review_batch(body: BatchReviewIn):
    # 先校验参数再看有没有文件：否则空列表会走 early-return，
    # 让非法阈值静默通过，前端拿到「成功」却什么也没做。
    if not (0 <= body.threshold <= 100):
        raise HTTPException(400, "阈值需在 0-100 之间")
    if not body.rels:
        return {"ok": 0, "skipped": 0, "already": 0, "no_score": 0, "items": []}
    name = _check_reviewer(body.reviewer)

    ok = skipped = already = no_score = 0
    items = []
    # 上限保护：一次最多处理 5000 个，避免误传超大列表把服务打满
    for rel in body.rels[:5000]:
        badge = trust.trust_badge(rel)
        if badge.get("reviewer") and badge.get("trust_state"):
            already += 1
            continue
        score = badge.get("auto_score")
        if score is None:
            no_score += 1
            continue
        if score >= body.threshold:
            trust.set_verdict(rel, "ok", name, body.note or "批量按阈值通过")
            ok += 1
        else:
            skipped += 1
        items.append({"rel": rel, "auto_score": score})

    return {
        "ok": ok,
        "skipped": skipped,
        "already": already,
        "no_score": no_score,
        "items": items[:200],
    }


@router.post("/review/{rel:path}")
def review(rel: str, body: VerdictIn):
    v = body.verdict if body.verdict else None
    if v not in (None, "ok", "diff_big", "rejected"):
        raise HTTPException(400, "bad verdict")
    name = _check_reviewer(body.reviewer)
    res = trust.set_verdict(rel, v, name, body.note)
    return {**res, "badge": trust.trust_badge(rel)}


@router.get("/review/{rel:path}")
def get_review(rel: str):
    return trust.trust_badge(rel)


@router.get("/eval/{rel:path}")
def get_eval(rel: str):
    """自动评测明细（供界面展示覆盖率/数字保真率/引擎）。"""
    return trust.get_eval(rel) or {}
