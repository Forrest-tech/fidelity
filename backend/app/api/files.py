# -*- coding: utf-8 -*-
"""文件列表、对比任务、任务状态"""
import os
from fastapi import APIRouter, HTTPException

from .. import config, db
from ..domain import trust
from ..jobs.queue import queue

router = APIRouter()

# ---------- 文件列表 ----------
@router.get("/files")
def list_files(sid: str = "n2", status: str = "", limit: int = 3000):
    """列该数据源下已转 .md 的文件，附可信度状态。

    badge 走批量查询（badges_bulk），避免 N+1：上千文件只打 2 次 SQL。
    """
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    md_root = src["md_root"]
    rels = []
    for dp, dn, fn in os.walk(md_root):
        if "_kb" in dp or "_review" in dp:
            continue
        for name in fn:
            if not name.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dp, name), md_root).replace("\\", "/")[:-3]
            rels.append(rel)
    rels.sort()
    total = len(rels)
    if len(rels) > limit:
        rels = rels[:limit]
    badges = trust.badges_bulk(rels)
    out = [badges[r] for r in rels]
    if status:
        out = [f for f in out if f["state"] == status]
    return {"count": len(out), "total": total, "truncated": total > limit, "files": out}


# ---------- 对比（自动评测 + 分页 diff） ----------
@router.post("/compare")
def enqueue_compare(rel: str, sid: str = "n2"):
    jid = queue.submit("compare:" + sid, rel, "queued")
    return {"job_id": jid}


@router.post("/batch")
def enqueue_batch(sid: str = "n2", force: bool = False, mode: str = "",
                  defer_mb: float = 0, defer_sec: float = 0):
    """批量评测。

    mode: all(增量，默认) | force(全量重跑) | defer(只补跑被延后的文件)
    defer_mb / defer_sec: 覆盖默认延后阈值；0 表示沿用模式默认值。
    """
    if not mode:
        mode = "force" if force else "all"
    if mode not in ("all", "force", "defer"):
        raise HTTPException(400, "mode must be all|force|defer")
    spec = "%s|%s|%s" % (mode, defer_mb or "", defer_sec or "")
    jid = queue.submit("batch:" + sid, spec, "queued")
    return {"job_id": jid}


@router.get("/deferred")
def list_deferred(sid: str = "n2", limit: int = 200):
    """列出被延后的文件（大文件 / 慢文件），供后续人工决定何时回来补跑。"""
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    con = db.trust_rw()
    try:
        rows = con.execute(
            "SELECT rel, fail_reasons, engine_b, evaluated_at FROM file_eval "
            "WHERE status='deferred' ORDER BY rel LIMIT ?", (limit,)).fetchall()
    finally:
        con.close()
    # 附带体积信息，便于判断哪些值得单独攻坚
    out = []
    for r in rows:
        rel = r["rel"]
        sp = os.path.join(src["src_root"], rel)
        try:
            mb = round(os.path.getsize(sp) / 1048576.0, 1) if os.path.exists(sp) else None
        except OSError:
            mb = None
        out.append({"rel": rel, "mb": mb, "reason": r["fail_reasons"],
                    "at": r["evaluated_at"]})
    return {"count": len(out), "items": out}



@router.get("/job/{jid}")
def job_status(jid: str):
    j = queue.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    return j
