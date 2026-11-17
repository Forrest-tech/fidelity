# -*- coding: utf-8 -*-
"""新文件上传"""
import os
from fastapi import APIRouter, HTTPException, UploadFile, File

from .. import config

router = APIRouter()

# ---------- 新文件上传（入库入口） ----------
@router.post("/ingest/upload")
async def upload(file: UploadFile = File(...), sid: str = "n2"):
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    # 落到源根目录（按原文件名），后续由转换流程处理
    dest = os.path.join(src["src_root"], os.path.basename(file.filename))
    data = await file.read()
    with open(dest, "wb") as f:
        f.write(data)
    return {"ok": True, "rel": os.path.basename(file.filename),
            "note": "已放入源根目录，等待转换流程生成 .md"}
