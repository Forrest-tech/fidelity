# -*- coding: utf-8 -*-
"""API 路由层。"""
import os
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from .. import config, db
from ..domain import compare as cmp
from ..domain import trust
from ..ingest import parsers
from ..jobs.queue import queue

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
    res = trust.set_decision(rel, d, body.reviewer, body.note)
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


@router.get("/job/{jid}")
def job_status(jid: str):
    j = queue.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    return j


MAX_SEG_CHARS = 20000  # 单行展示上限（超出截断并标注）


def _explain(cs, cm, src_text, md_text=""):
    """给低分/异常文件一句人话结论，避免用户看到 0 分或 200% 却不知道原因。

    典型场景：
      * 图纸照片 / 尺寸标注图 —— 图上本来就没多少文字，覆盖率 0 是**真实结果**，
        不是系统出错，必须说清楚，否则会被误判成「转换质量差」；
      * 原转换把表格单元格重复拼接 —— md 字数虚高到源文 2 倍。
    """
    sc, mc = cs["chars"], cm["chars"]
    if sc == 0 and mc == 0:
        return "两侧都没有可抽取的文本（可能是纯图形/图纸线条）"
    if sc < 60:
        return ("源文件本身几乎没有文字（仅 %d 字，多为图纸尺寸标注），"
                "自动比对不适用 —— 请切到「源文件预览」人工核对" % sc)
    if mc == 0:
        return "入库 .md 没有正文内容 —— 建议用「需重新转换」重写"
    ratio = mc * 100.0 / sc
    if ratio < 20:
        return ("md 字数仅为源文的 %d%%，转换很可能大量丢内容，请逐行核对" % ratio)
    if ratio > 180:
        d = cmp.dup_ratio(md_text) if md_text else 0.0
        extra = ("，其中 %.1f%% 的行存在内容重复（疑似原转换重复展开），"
                 "建议用「需重新转换」重写" % (d * 100)) if d > 0.01 else ""
        return ("md 字数是源文的 %.1f 倍，疑似重复内容或混入管线元数据%s"
                % (ratio / 100.0, extra))
    return ""


@router.get("/diff")
def diff(rel: str, page: int = 1, per_page: int = 50, only_diff: bool = False, sid: str = "n2"):
    """同步分页返回左右对齐 diff（绿/红）。数据来自已评测结果或实时算。"""
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    src_path = os.path.join(src["src_root"], rel)
    md_path = parsers.md_path_for(src["md_root"], rel)
    src_text = parsers.extract_source_text_guarded(src_path, config.CACHE_DIR)
    if src_text == parsers.TIMEOUT_SENTINEL:
        return {"rel": rel, "not_applicable": True,
                "reason": "源文件过大，抽取超时（需人工抽检）",
                "segments": [], "total": 0, "page": 1, "pages": 1}
    md_text = cmp.strip_md_artifacts(parsers.read_md_text(md_path)) if os.path.exists(md_path) else ""
    if not src_text.strip():
        return {"rel": rel, "not_applicable": True,
                "reason": "源文无文本层/格式不适用", "segments": [], "total": 0, "page": 1, "pages": 1}
    segments = cmp.align_lines_cached(src_text, md_text, rel=rel)
    segs, total, pages = cmp.page(segments, page, per_page, only_diff)
    cs, cm = cmp.count_text(src_text), cmp.count_text(md_text)
    stats_of_diff = {}
    for s in segments:
        stats_of_diff[s["status"]] = stats_of_diff.get(s["status"], 0) + 1
    # 单行可能极长（畸形文件 / 无换行的二进制打捞文本），序列化前截断保护：
    # 不截的话单条 segment 能到几十 MB，浏览器会直接崩掉。
    segs = [_clip_segment(s) for s in segs]
    return {"rel": rel, "not_applicable": False, "segments": segs,
            "total": total, "page": page, "pages": pages,
            "src_chars": cs["chars"], "md_chars": cm["chars"],
            "src_words": cs["words"], "md_words": cm["words"],
            "by_status": stats_of_diff,
            "verdict": _explain(cs, cm, src_text, md_text)}


def _clip_segment(s):
    """截断超长行，保证响应体可控（不截会让浏览器卡死/崩溃）。"""
    out = dict(s)
    for k in ("src", "md"):
        v = out.get(k)
        if isinstance(v, str) and len(v) > MAX_SEG_CHARS:
            out[k] = v[:MAX_SEG_CHARS] + " …（本行过长已截断，原长 %d 字符）" % len(v)
    return out



@router.get("/md")
def get_md(rel: str, sid: str = "n2"):
    """入库 .md 正文（已剥离管线伪影），供右栏「原文」视图使用。"""
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    md_path = parsers.md_path_for(src["md_root"], rel)
    if not os.path.exists(md_path):
        return {"rel": rel, "text": "", "missing": True}
    raw = parsers.read_md_text(md_path)
    text = cmp.strip_md_artifacts(raw)
    c = cmp.count_text(text)
    # md 也可能是畸形超长文本（无换行打捞产物），限制单行长度避免浏览器崩
    text = "\n".join(
        (t[:MAX_SEG_CHARS] + " …（本行过长已截断，原长 %d 字符）" % len(t))
        if len(t) > MAX_SEG_CHARS else t
        for t in text.split("\n"))
    return {"rel": rel, "text": text, "missing": False,
            "salvage": cmp.md_is_salvage(raw),
            "chars": c["chars"], "words": c["words"]}


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


# ---------- 人工裁决 ----------
class VerdictIn(BaseModel):
    verdict: str  # ok / diff_big / rejected / "" (重置未审)
    reviewer: str = "local"
    note: str = ""


@router.post("/review/{rel:path}")
def review(rel: str, body: VerdictIn):
    v = body.verdict if body.verdict else None
    if v not in (None, "ok", "diff_big", "rejected"):
        raise HTTPException(400, "bad verdict")
    res = trust.set_verdict(rel, v, body.reviewer, body.note)
    return {**res, "badge": trust.trust_badge(rel)}


@router.get("/review/{rel:path}")
def get_review(rel: str):
    return trust.trust_badge(rel)


@router.get("/eval/{rel:path}")
def get_eval(rel: str):
    """自动评测明细（供界面展示覆盖率/数字保真率/引擎）。"""
    return trust.get_eval(rel) or {}


@router.get("/stats")
def stats(sid: str = "n2"):
    """总览：各状态文件数 + 平均自动分 + 已审比例。"""
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    md_root = src["md_root"]
    rels = []
    for dp, dn, fn in os.walk(md_root):
        if "_kb" in dp or "_review" in dp:
            continue
        for name in fn:
            if name.endswith(".md"):
                rels.append(os.path.relpath(os.path.join(dp, name), md_root).replace("\\", "/")[:-3])
    badges = trust.badges_bulk(rels)
    by_state = {}
    scores = []
    reviewed = 0
    for b in badges.values():
        by_state[b["state"]] = by_state.get(b["state"], 0) + 1
        if b["auto_score"] is not None:
            scores.append(b["auto_score"])
        if b["trust_state"]:
            reviewed += 1
    n = len(badges) or 1
    # 延后（大文件/慢文件）单独计数：不算失败，是待办
    deferred = 0
    try:
        con = db.trust_rw()
        try:
            deferred = con.execute(
                "SELECT count(*) FROM file_eval WHERE status='deferred'").fetchone()[0]
        finally:
            con.close()
    except Exception:
        pass
    # 人工决定队列（无法自动比对：待决定/已入库/已排除）
    try:
        dec = trust.decision_stats()
    except Exception:
        dec = {"pending": 0, "include": 0, "exclude": 0}
    return {
        "total": len(badges),
        "by_state": by_state,
        "deferred": deferred,
        "decisions": dec,
        "salvage": len(trust.salvage_list(2000)),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "evaluated": len(scores),
        "reviewed": reviewed,
        "reviewed_pct": round(100.0 * reviewed / n, 1),
        # 字数总量：源文 vs 入库 .md（用户 2026-10-04 需求，直观的体量指标）
        "totals": trust.totals(),
    }


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
