# -*- coding: utf-8 -*-
"""源文件预览"""
import os
from fastapi import APIRouter, HTTPException

from .. import config

router = APIRouter()

# ---------- 源文件预览（左栏显示源文件的真实样貌） ----------
def _src_path(sid, rel):
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    return os.path.join(src["src_root"], rel)


@router.get("/preview")
def preview(rel: str, sid: str = "n2", page: int = 1, sheet: int = 0):
    """返回源文件预览内容：image（PDF 页 / 图片 / CAD 图）| html | text | unsupported。"""
    from ..ingest import preview as pv
    from fastapi.responses import JSONResponse
    p = _src_path(sid, rel)
    if not os.path.exists(p):
        return {"kind": "missing", "note": "源文件不存在：%s" % rel, "pages": 1}
    try:
        data = pv.content(p, page=page, sheet=sheet)
    except Exception as e:
        data = {"kind": "unsupported", "note": "预览失败：%s" % str(e)[:160], "pages": 1}
    data["rel"] = rel
    data["ext"] = os.path.splitext(rel)[1].lower()
    return JSONResponse(data)


@router.get("/preview/img")
def preview_img(rel: str, sid: str = "n2", page: int = 1, dpi: int = 110):
    """图像型预览的二进制流（供 <img src> 直接引用）。"""
    from ..ingest import preview as pv
    from fastapi.responses import Response
    p = _src_path(sid, rel)
    if not os.path.exists(p):
        raise HTTPException(404, "source file not found")
    try:
        data, mime = pv.image_bytes(p, page=page, dpi=dpi)
    except Exception:
        data, mime = b"", "image/png"
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/preview/meta")
def preview_meta(rel: str, sid: str = "n2"):
    """预览能力描述：页数 / 渲染方式 / 是否支持。前端据此决定翻页 UI。"""
    from ..ingest import preview as pv
    p = _src_path(sid, rel)
    if not os.path.exists(p):
        return {"kind": "missing", "pages": 1, "note": "源文件不存在"}
    try:
        d = pv.info(p)
    except Exception as e:
        d = {"kind": "unsupported", "pages": 1, "note": str(e)[:160]}
    d["rel"] = rel
    d["ext"] = os.path.splitext(rel)[1].lower()
    return d
