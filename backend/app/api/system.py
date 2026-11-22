# -*- coding: utf-8 -*-
"""System health for administrators (requirements v2, S-1, S-5, S-6): figures, alerts, metrics, backups."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from ..auth.users import require_role
from ..ops import backup as BK
from ..ops import health as H

router = APIRouter()


@router.get("/system/health", dependencies=[Depends(require_role())])
def health():
    return H.report()


@router.get("/system/metrics", dependencies=[Depends(require_role())], response_class=PlainTextResponse)
def metrics():
    """Prometheus text format. Scrape with an administrator's session or put it behind the reverse proxy's auth."""
    return H.metrics()


@router.post("/system/backup", dependencies=[Depends(require_role())])
def backup_now():
    """Make and verify a backup now (it also runs by itself once a day)."""
    rec = BK.make()
    if not rec["ok"]:
        raise HTTPException(500, "the backup was written but did not verify: " + "; ".join(rec["problems"][:3]))
    return rec
