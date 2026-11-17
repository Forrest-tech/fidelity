# -*- coding: utf-8 -*-
"""新文件上传"""
import os
from fastapi import APIRouter, HTTPException, UploadFile, File

from .. import config

router = APIRouter()

# ---------- 新文件上传（入库入口） ----------
MAX_UPLOAD_BYTES = int(os.environ.get("FIDELITY_MAX_UPLOAD_MB", "100")) * 1024 * 1024
BLOCKED_EXT = {".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".js", ".msi", ".sh", ".bin"}


def safe_name(raw):
    """Final path component only (handles / and \), no hidden/empty names."""
    name = os.path.basename((raw or "").replace("\\", "/")).strip()
    if not name or name.startswith(".") or chr(0) in name:
        raise HTTPException(400, "invalid file name")
    if os.path.splitext(name)[1].lower() in BLOCKED_EXT:
        raise HTTPException(415, "file type not allowed")
    return name


@router.post("/ingest/upload")
async def upload(file: UploadFile = File(...), sid: str = "n2"):
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    name = safe_name(file.filename)
    dest = os.path.join(src["src_root"], name)
    if os.path.exists(dest):
        raise HTTPException(409, "file already exists; uploads never overwrite")
    size = 0
    try:
        with open(dest, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "file too large")
                f.write(chunk)
    except BaseException:
        if os.path.exists(dest):
            os.remove(dest)
        raise
    return {"ok": True, "rel": name, "bytes": size,
            "note": "已放入源根目录，等待转换流程生成 .md"}
