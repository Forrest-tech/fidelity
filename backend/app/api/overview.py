# -*- coding: utf-8 -*-
"""Read-only lists for the web application: jobs, distilled documents, overview counts, users."""
import glob
import json
import os
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import config, db
from ..auth.models import User
from ..auth.users import require_role
from ..orm import get_session

router = APIRouter()


def _reports(sid=None):
    """Latest result per document, from the per-job result files written by distill jobs."""
    base = os.path.join(config.DATA_DIR, "distilled_reports")
    pattern = os.path.join(base, sid or "*", "*.json")
    latest = {}
    for p in glob.glob(pattern):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        d["at"] = os.path.getmtime(p)
        d["job"] = os.path.splitext(os.path.basename(p))[0]
        key = (d.get("sid", ""), d.get("rel", ""))
        if key not in latest or d["at"] > latest[key]["at"]:
            latest[key] = d
    return sorted(latest.values(), key=lambda x: -x["at"])


@router.get("/jobs")
def list_jobs(status: str = "", kind: str = "", limit: int = 100):
    limit = min(max(limit, 1), 500)
    q, args = "SELECT id,kind,rel,status,progress,message,created_at,updated_at FROM job WHERE 1=1", []
    if status:
        q += " AND status=?"
        args.append(status)
    if kind:
        q += " AND kind LIKE ?"
        args.append(kind + "%")
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    db.init_trust()      # idempotent; the table may not exist on a fresh install
    con = db.trust_rw()
    try:
        return [dict(r) for r in con.execute(q, args).fetchall()]
    finally:
        con.close()


@router.get("/documents")
def list_documents(sid: str = "", verdict: str = "", limit: int = 500):
    rows = _reports(sid or None)
    if verdict:
        rows = [r for r in rows if r.get("verdict") == verdict]
    return rows[: min(max(limit, 1), 2000)]


@router.get("/overview")
def overview():
    db.init_trust()
    con = db.trust_rw()
    try:
        jobs = Counter(r["status"] for r in con.execute("SELECT status FROM job WHERE kind LIKE 'distill%'").fetchall())
    finally:
        con.close()
    docs = _reports()
    return {
        "sources": len(config.get_sources()),
        "jobs": dict(jobs),
        "documents": dict(Counter(d.get("verdict", "?") for d in docs)),
        "needs_attention": [
            {"rel": d.get("rel"), "sid": d.get("sid"), "verdict": d.get("verdict"),
             "instruction_like": d.get("instruction_like", 0)}
            for d in docs if d.get("verdict") not in ("PASS",) or d.get("instruction_like")
        ][:20],
    }


@router.get("/admin/users", dependencies=[Depends(require_role())])
async def list_users(session: AsyncSession = Depends(get_session)):
    # people waiting for approval are listed apart (GET /admin/signups), not among the accounts
    rows = (await session.execute(select(User).where(User.approval.is_(None)).order_by(User.email))).scalars().all()
    return [{"id": str(u.id), "email": u.email, "role": u.role.value, "is_active": u.is_active,
             # how the person signs in: their password and/or the providers linked to the account
             "sign_in": sorted({a.oauth_name for a in (u.oauth_accounts or [])})} for u in rows]
