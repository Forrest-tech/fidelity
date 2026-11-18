# -*- coding: utf-8 -*-
"""Distillation jobs: submit one file or a whole folder, read results."""
import json
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..jobs import distill_job as DJ
from ..jobs.queue import queue

router = APIRouter()


class DistillIn(BaseModel):
    rel: str
    sid: str = "n2"


class DistillBatchIn(BaseModel):
    sid: str = "n2"
    folder: str = ""
    limit: int = 500


@router.post("/distill")
def distill_one(body: DistillIn):
    if not body.rel.lower().endswith(DJ.SUPPORTED):
        raise HTTPException(415, "format not handled yet")
    jid = queue.submit("distill:" + body.sid, body.rel, "queued")
    return {"job": jid}


@router.post("/distill/batch")
def distill_batch(body: DistillBatchIn):
    rels = DJ.list_source_files(body.sid, body.folder, min(max(body.limit, 1), 2000))
    if rels is None:
        raise HTTPException(404, "source or folder not found")
    return {"jobs": [queue.submit("distill:" + body.sid, r, "queued") for r in rels], "files": len(rels)}


@router.get("/distill/{sid}/{jid}")
def distill_result(sid: str, jid: str):
    if not jid.isalnum() or not sid.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "bad id")
    p = DJ.report_path(sid, jid)
    if not os.path.isfile(p):
        raise HTTPException(404, "no result yet")
    with open(p, encoding="utf-8") as f:
        return json.load(f)
