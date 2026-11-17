# -*- coding: utf-8 -*-
"""人工决定队列与重转"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..domain import trust
from ..jobs.queue import queue

router = APIRouter()
from .reviewers import _check_reviewer  # noqa: E402

# ---------- 人工决定队列（无法自动比对的文件：入不入库用户拍板） ----------
@router.get("/decisions")
def list_decisions(sid: str = "n2", decision: str = "", limit: int = 600):
    """decision 为空 = 待决定队列；include/exclude = 已决定清单。"""
    items = trust.list_decisions(sid, decision or None, limit)
    return {"count": len(items), "items": items}


class DecisionIn(BaseModel):
    decision: str  # include / exclude / "" (撤销)
    reviewer: str = "local"
    note: str = ""


@router.post("/decision/{rel:path}")
def set_decision_rel(rel: str, body: DecisionIn):
    d = body.decision if body.decision else None
    if d not in (None, "include", "exclude"):
        raise HTTPException(400, "decision must be include|exclude|''")
    res = trust.set_decision(rel, d, _check_reviewer(body.reviewer), body.note)
    return res


@router.get("/salvage")
def list_salvage(limit: int = 600):
    """原转换产物是「二进制字符串打捞」的文件清单 → 重新转换候选。"""
    items = trust.salvage_list(limit)
    return {"count": len(items), "items": items}


class ReconvertIn(BaseModel):
    rels: list = []
    sid: str = "n2"
    backup: bool = True


@router.post("/reconvert")
def reconvert(body: ReconvertIn):
    """把「二进制打捞」的无效 .md 用真实提取结果重写。

    ⚠ 只处理显式传入的文件；写盘前自动备份为 .md.salvage.bak。
    重写后立刻重评，让用户马上看到新的转化率。
    """
    from ..ingest import reconvert as rc
    from ..jobs import handlers
    rels = [r for r in (body.rels or []) if r]
    if not rels:
        raise HTTPException(400, "rels is empty")
    if len(rels) > 500:
        raise HTTPException(400, "一次最多 500 个，避免长时间阻塞")
    ok, fail = [], []
    for rel in rels:
        try:
            good, msg = rc.reconvert_one(rel, body.sid, body.backup)
            # 重写后重评：清掉旧缓存，强制用新 MD 打分
            try:
                handlers.eval_one(rel, body.sid)
            except Exception:
                pass
            (ok if good else fail).append({"rel": rel, "msg": msg})
        except Exception as e:
            fail.append({"rel": rel, "msg": str(e)[:200]})
    return {"ok": len(ok), "failed": len(fail), "items": ok + fail}


@router.post("/reconvert/all")
def reconvert_all(sid: str = "n2"):
    """全量重新转换：扫描全部「二进制打捞」产物并用真实提取结果重写（后台任务）。

    写盘前自动备份为 .md.salvage.bak，可回滚；重写后逐个重评。
    """
    jid = queue.submit("reconvert:" + sid, "all", "queued")
    return {"job_id": jid}
