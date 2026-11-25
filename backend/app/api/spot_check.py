# -*- coding: utf-8 -*-
"""Weekly spot check of the published library (requirements v3 H-3). Reading needs a login; giving a verdict needs a
reviewer or administrator (enforced for the whole API in main.py)."""
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth.users import current_user
from ..ops import spot_check as SC

router = APIRouter()
_WEEK = re.compile(r"^\d{4}-W\d{2}$")


def _guard(fn, *a):
    try:
        return fn(*a)
    except SC.SpotError as e:
        raise HTTPException(e.status, e.message)
    except (RuntimeError, OSError) as e:          # Dropbox not set up or out of reach
        raise HTTPException(503, f"the library cannot be read right now: {str(e)[:160]}")


@router.get("/spot-check")
def spot_check(week: str | None = None):
    week = week or SC.week_of()
    if not _WEEK.match(week):
        raise HTTPException(422, "week looks like 2026-W48")
    return {"week": week, "current": SC.week_of(), "items": _guard(SC.draw, week), "summary": SC.summary()}


class VerdictIn(BaseModel):
    verdict: str
    note: str = ""


@router.post("/spot-check/{item_id}")
def spot_verdict(item_id: int, body: VerdictIn, user=Depends(current_user)):
    return _guard(SC.record, item_id, body.verdict, body.note, getattr(user, "email", "") or "")


@router.get("/spot-check/{item_id}/page.png")
def spot_page(item_id: int):
    return Response(_guard(SC.page_image, item_id), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})
