# -*- coding: utf-8 -*-
"""数据源 / 文件夹"""
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config

router = APIRouter()

# ---------- 数据源 / 文件夹 ----------
@router.get("/sources")
def list_sources():
    return config.get_sources()


@router.get("/browse")
def browse(path: str = ""):
    """后端目录浏览（本机部署，供用户选文件夹）。"""
    if not path:
        drives = []
        for d in "CDEFG":
            if os.path.exists("%s:\\" % d):
                drives.append("%s:\\" % d)
        return {"cwd": "", "dirs": drives, "files": []}
    if not os.path.isdir(path):
        raise HTTPException(400, "not a dir")
    dirs, files = [], []
    try:
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                dirs.append(name)
            else:
                files.append(name)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"cwd": path, "dirs": sorted(dirs)[:500], "files": sorted(files)[:200]}


class SourceIn(BaseModel):
    id: str
    name: str
    src_root: str
    md_root: str
    enabled: bool = True


@router.post("/sources")
def upsert_source(s: SourceIn):
    return config.upsert_source(s.model_dump())


@router.delete("/sources/{sid}")
def del_source(sid: str):
    config.delete_source(sid)
    return {"ok": True}
