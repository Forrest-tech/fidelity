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
    res = trust.set_decision(rel, d, _check_reviewer(body.reviewer), body.note)
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

# 一次 /api/align 返回的最大 md 行数。md 最大可到 2.6MB（约 3 万行），
# 全量吐给浏览器会卡死；超出则只返回前 N 行并明确告知已截断，
# 前端据此提示用户用「只看差异」或搜索定位，而不是假装内容完整。
ALIGN_MAX_LINES = 6000


# ---------- 审核人配置（受监管场景要求：审核人可审计、身份唯一） ----------
@router.get("/reviewers")
def list_reviewers():
    """审核人名单 + 每人的工作量统计。"""
    stats = trust.reviewer_stats()
    items = []
    for r in config.get_reviewers():
        d = dict(r)
        d.update(stats.get(r["name"], {"verdicts": 0, "ok": 0, "diff_big": 0,
                                       "rejected": 0, "decisions": 0}))
        items.append(d)
    # 已产生裁决但不在名单里的历史审核人（老数据/手工改库），标出来便于补录
    known = {r["name"] for r in items}
    for name, s in stats.items():
        if name not in known:
            items.append({"id": "", "name": name, "role": "未登记",
                          "enabled": False, "orphan": True, **s})
    return {"items": items}


class ReviewerIn(BaseModel):
    id: str = ""
    name: str
    role: str = "审核人"
    enabled: bool = True


@router.post("/reviewers")
def upsert_reviewer(body: ReviewerIn):
    try:
        return config.upsert_reviewer(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/reviewers/{rid}")
def del_reviewer(rid: str):
    try:
        if not config.delete_reviewer(rid):
            raise HTTPException(404, "reviewer not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


def _check_reviewer(rid):
    """裁决/入库决定的审核人必须在名单内 —— 这正是本模块存在的意义：
    自由输入会让同一人的拼写变体在审计日志里裂成多个身份。"""
    r = config.resolve_reviewer_id(rid)
    if not r:
        raise HTTPException(400, "审核人不在名单中，请先在「设置 · 审核人」中添加")
    return r["name"]


# ---------- 源目录结构树（用户 2026-10-05：侧栏要显示原目录结构） ----------
@router.get("/tree")
def dir_tree(sid: str = "n2", status: str = "", q: str = ""):
    """按**源目录**结构返回树，每个文件挂可信度状态。

    与 /files 的区别：/files 是扁平列表（按 md 路径），
    这里保留原始目录层级，用户能像用资源管理器一样逐层点进去找文件。
    目录节点带状态计数，便于一眼看出哪个文件夹还没审完。
    """
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    md_root, src_root = src["md_root"], src["src_root"]

    rels = []
    for dp, dn, fn in os.walk(md_root):
        if "_kb" in dp or "_review" in dp:
            continue
        for name in fn:
            if name.endswith(".md"):
                rels.append(os.path.relpath(os.path.join(dp, name), md_root)
                            .replace("\\", "/")[:-3])
    badges = trust.badges_bulk(rels)

    ql = (q or "").strip().lower()
    root = {"name": os.path.basename(src_root.rstrip("\\/")) or src_root,
            "dirs": {}, "files": []}

    def ensure(parts):
        node = root
        for p in parts:
            nxt = node["dirs"].get(p)
            if nxt is None:
                nxt = {"name": p, "dirs": {}, "files": []}
                node["dirs"][p] = nxt
            node = nxt
        return node

    for rel, b in badges.items():
        if status and b["state"] != status:
            continue
        if ql and ql not in rel.lower():
            continue
        parts = rel.split("/")
        parent = ensure(parts[:-1])
        parent["files"].append({
            "rel": rel, "name": parts[-1],
            "ext": os.path.splitext(parts[-1])[1].lower(),
            "state": b["state"], "label": b["label"],
            "auto_score": b["auto_score"],
        })

    def finish(node):
        """把 dirs 字典转成有序数组，并自底向上汇总各状态计数。"""
        counts = {"all": 0, "trusted": 0, "need_review": 0,
                  "diff_big": 0, "rejected": 0, "unreviewed": 0}
        for f in node["files"]:
            counts["all"] += 1
            counts[f["state"]] = counts.get(f["state"], 0) + 1
        node["files"].sort(key=lambda x: x["name"].lower())
        out_dirs = []
        for name in sorted(node["dirs"], key=str.lower):
            d = finish(node["dirs"][name])
            for k, v in d["counts"].items():
                counts[k] = counts.get(k, 0) + v
            out_dirs.append(d)
        node["dirs"] = out_dirs
        node["counts"] = counts
        return node

    tree = finish(root)
    return {"name": tree["name"], "dirs": tree["dirs"],
            "files": tree["files"], "counts": tree["counts"]}


# ---------- 逐行对齐（左右分栏绿色高亮的数据源） ----------
@router.get("/align")
def align(rel: str, sid: str = "n2"):
    """返回 md 每一行的比对状态 + 对应源文行号 + 该源文行所在页。

    这是「左栏源文件打绿底 / 右栏 md 打绿底」的唯一数据源：
      * status=match   → 两侧都有 → 两侧都绿
      * status=md_only → md 多出（源文里没有）→ 红
      * status=changed → 相似但不同（OCR 改写）→ 琥珀
    src_page 让前端在点 md 行时能直接跳到源文件对应页。
    """
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    src_path = os.path.join(src["src_root"], rel)
    md_path = parsers.md_path_for(src["md_root"], rel)
    src_text = parsers.extract_source_text_guarded(src_path, config.CACHE_DIR)
    # 不可比对时**必须**返回与正常路径同构的键（status/src_page 为空数组），
    # 否则前端读 align.status 会拿到 undefined。早期版本这里返回 "lines"，
    # 与契约不符 —— 字段名一漂移，界面就变成空白而不是「本文件无需比对」。
    if src_text == parsers.TIMEOUT_SENTINEL:
        return {"rel": rel, "not_applicable": True,
                "reason": "源文件过大，抽取超时（需人工抽检）",
                "status": [], "src_page": [], "truncated": False,
                "total_lines": 0, "by_status": {}}
    raw_md = parsers.read_md_text(md_path) if os.path.exists(md_path) else ""
    md_text = cmp.strip_md_artifacts(raw_md)
    if not src_text.strip() or not md_text.strip():
        return {"rel": rel, "not_applicable": True,
                "reason": "源文或 md 无可比对文本",
                "status": [], "src_page": [], "truncated": False,
                "total_lines": 0, "by_status": {}}

    segments = cmp.align_lines_cached(src_text, md_text, rel=rel)

    # 源文行 → 页码（仅 PDF 有意义；其他格式返回空表，前端隐藏页码跳转）
    page_map = []
    try:
        from ..ingest import locate
        page_map = locate.src_line_page_map(src_path)
    except Exception:
        page_map = []

    # ⚠️ 只回「状态 + 页码」，不回文本：正文由 /api/md 提供。
    # 这样避免同一份文本在两个响应里各传一次（最大的 md 有 2.6MB），
    # 也从根本上杜绝了「两边切分不一致 → 绿色标到错误的行上」这个隐患：
    # 索引语义由 md_lines() 唯一定义，两端都走它。
    md_lines = md_text.splitlines()
    n = min(len(md_lines), ALIGN_MAX_LINES)
    status = ["unmatched"] * len(md_lines)
    page_of = [None] * len(md_lines)
    for s in segments:
        j = s.get("md_no")
        if j is None or not (0 <= j < len(md_lines)):
            continue
        status[j] = s["status"]
        sn = s.get("src_no")
        if sn is not None and 0 <= sn < len(page_map):
            page_of[j] = page_map[sn]

    by_status = {}
    for s in segments:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
    cs, cm = cmp.count_text(src_text), cmp.count_text(md_text)
    return {
        "rel": rel, "not_applicable": False,
        # 逐行状态：下标 == /api/md 的 lines 下标
        "status": status[:n],
        "src_page": page_of[:n],
        "truncated": len(md_lines) > n,
        "total_lines": len(md_lines),
        "by_status": by_status,
        "src_chars": cs["chars"], "md_chars": cm["chars"],
        "verdict": _explain(cs, cm, src_text, md_text),
    }


def _clip(v):
    if isinstance(v, str) and len(v) > MAX_SEG_CHARS:
        return v[:MAX_SEG_CHARS] + " …（本行过长已截断，原长 %d 字符）" % len(v)
    return v


# ---------- 源文件页面高亮框（把对齐结果落回源文件坐标） ----------
@router.get("/marks")
def marks(rel: str, sid: str = "n2", page: int = 1):
    """返回源文件该页每行的归一化坐标 + 命中状态，供左栏叠加绿/红色块。

    坐标已归一化到 0..1，前端缩放/改宽度都无需重新请求。
    """
    from ..ingest import locate
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    src_path = os.path.join(src["src_root"], rel)
    pl = locate.page_lines(src_path, page)
    if not pl:
        return {"rel": rel, "page": page, "supported": False,
                "reason": "该格式无页面坐标（仅 PDF 可定位到页内具体位置）",
                "lines": []}

    md_path = parsers.md_path_for(src["md_root"], rel)
    src_text = parsers.extract_source_text_guarded(src_path, config.CACHE_DIR)
    md_text = cmp.strip_md_artifacts(
        parsers.read_md_text(md_path)) if os.path.exists(md_path) else ""

    # 建「归一化行文本 → 状态列表」的多重集：dict 的切行与 text 的切行可能不同，
    # 按内容匹配比按行号稳。重复行按出现顺序消费，与 align_lines 策略一致。
    state_of = {}
    for s in cmp.align_lines_cached(src_text, md_text, rel=rel):
        if s.get("src") is None:
            continue
        state_of.setdefault(cmp.normalize_line(s["src"]), []).append(s["status"])
    used = {}
    out = []
    for ln in pl["lines"]:
        key = cmp.normalize_line(ln["text"])
        arr = state_of.get(key)
        idx = used.get(key, 0)
        status = arr[idx] if arr and idx < len(arr) else "unmatched"
        if arr:
            used[key] = idx + 1
        item = dict(ln)
        item["status"] = status
        out.append(item)
    return {"rel": rel, "page": page, "supported": True,
            "page_w": pl["w"], "page_h": pl["h"], "lines": out,
            "src_line_count": len((src_text or "").splitlines())}


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
    """入库 .md 正文（已剥离管线伪影），供右栏逐行上色。

    ⚠️ `lines` 的切分必须与 /api/align 完全一致（都用 splitlines()）——
    前端靠「同一下标」把绿色/红色标到正确的行上。
    早期版本这里用 text.split("\\n")，而对齐侧用 splitlines()，
    遇到含 \\r 的 md 会整体错位一行，颜色标到隔壁行上。
    """
    src = config.get_source(sid)
    if not src:
        raise HTTPException(404, "source not found")
    md_path = parsers.md_path_for(src["md_root"], rel)
    if not os.path.exists(md_path):
        return {"rel": rel, "text": "", "lines": [], "missing": True}
    raw = parsers.read_md_text(md_path)
    text = cmp.strip_md_artifacts(raw)
    c = cmp.count_text(text)
    lines = text.splitlines()
    # md 也可能是畸形超长文本（无换行打捞产物），限制单行长度避免浏览器崩
    lines = [_clip(t) for t in lines]
    return {"rel": rel, "text": "\n".join(lines), "lines": lines,
            "missing": False, "salvage": cmp.md_is_salvage(raw),
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


# ---------- 批量人工审核（按正确率阈值） ----------
# ⚠️ 必须声明在 `/review/{rel:path}` **之前**：FastAPI 按声明顺序匹配路由，
# 若放在后面，字面量路径 "batch" 会被 {rel:path} 抢先捕获，导致 422。
class BatchReviewIn(BaseModel):
    """按阈值批量打「人工审核通过」标签。

    语义边界（重要）：
      * 只处理 **自动评测已完成**（有 auto_score）的文件；
        没有任何自动分的文件一律跳过 —— 拿「没测过」的文件去凑通过率是错的。
      * 阈值由前端传入，默认 90；只有 score >= threshold 才写入 ok。
      * 全部写入审计日志（file_trust_log），审核人 = 当前选中的人，可追溯。
      * 已经人工裁决过的文件**不覆盖**，避免抹掉历史判断。
    """

    rels: list[str]
    threshold: float = 90.0
    reviewer: str = ""
    note: str = ""


@router.post("/review/batch")
def review_batch(body: BatchReviewIn):
    # 先校验参数再看有没有文件：否则空列表会走 early-return，
    # 让非法阈值静默通过，前端拿到「成功」却什么也没做。
    if not (0 <= body.threshold <= 100):
        raise HTTPException(400, "阈值需在 0-100 之间")
    if not body.rels:
        return {"ok": 0, "skipped": 0, "already": 0, "no_score": 0, "items": []}
    name = _check_reviewer(body.reviewer)

    ok = skipped = already = no_score = 0
    items = []
    # 上限保护：一次最多处理 5000 个，避免误传超大列表把服务打满
    for rel in body.rels[:5000]:
        badge = trust.trust_badge(rel)
        if badge.get("reviewer") and badge.get("trust_state"):
            already += 1
            continue
        score = badge.get("auto_score")
        if score is None:
            no_score += 1
            continue
        if score >= body.threshold:
            trust.set_verdict(rel, "ok", name, body.note or "批量按阈值通过")
            ok += 1
        else:
            skipped += 1
        items.append({"rel": rel, "auto_score": score})

    return {
        "ok": ok,
        "skipped": skipped,
        "already": already,
        "no_score": no_score,
        "items": items[:200],
    }


@router.post("/review/{rel:path}")
def review(rel: str, body: VerdictIn):
    v = body.verdict if body.verdict else None
    if v not in (None, "ok", "diff_big", "rejected"):
        raise HTTPException(400, "bad verdict")
    name = _check_reviewer(body.reviewer)
    res = trust.set_verdict(rel, v, name, body.note)
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
    # ⚠️ 必须把 5 个状态**全部**列出（含 0）：前端统计行是 5 个固定卡片，
    # 若某状态当前为 0 就把 key 省掉，对应卡片会整个消失 —— 界面上看起来像
    # 「这个状态不存在」，而不是「0 个」。空态与不存在是两件事。
    by_state = {"trusted": 0, "need_review": 0, "diff_big": 0,
                "rejected": 0, "unreviewed": 0}
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
