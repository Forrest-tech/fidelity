# -*- coding: utf-8 -*-
"""审核人配置"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config
from ..domain import trust

router = APIRouter()

# ---------- 审核人配置（受监管场景要求：审核人可审计、身份唯一） ----------
@router.get("/reviewers")
def list_reviewers():
    """审核人名单 + 每人的工作量统计。"""
    stats = trust.reviewer_stats()
    items = []
    for r in config.get_reviewers():
        d = dict(r)
        d.update(stats.get(r["name"], {"verdicts": 0, "ok": 0, "diff_big": 0,
                                       "rejected": 0, "decisions": 0}))
        items.append(d)
    # 已产生裁决但不在名单里的历史审核人（老数据/手工改库），标出来便于补录
    known = {r["name"] for r in items}
    for name, s in stats.items():
        if name not in known:
            items.append({"id": "", "name": name, "role": "未登记",
                          "enabled": False, "orphan": True, **s})
    return {"items": items}


class ReviewerIn(BaseModel):
    id: str = ""
    name: str
    role: str = "审核人"
    enabled: bool = True


@router.post("/reviewers")
def upsert_reviewer(body: ReviewerIn):
    try:
        return config.upsert_reviewer(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/reviewers/{rid}")
def del_reviewer(rid: str):
    try:
        if not config.delete_reviewer(rid):
            raise HTTPException(404, "reviewer not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


def _check_reviewer(rid):
    """裁决/入库决定的审核人必须在名单内 —— 这正是本模块存在的意义：
    自由输入会让同一人的拼写变体在审计日志里裂成多个身份。"""
    r = config.resolve_reviewer_id(rid)
    if not r:
        raise HTTPException(400, "审核人不在名单中，请先在「设置 · 审核人」中添加")
    return r["name"]
