# -*- coding: utf-8 -*-
"""逐行对齐 / 页面标注 / diff / md"""
import os
from fastapi import APIRouter, HTTPException

from .. import config
from ..domain import compare as cmp
from ..ingest import parsers

router = APIRouter()

MAX_SEG_CHARS = 20000  # 单行展示上限（超出截断并标注）

# 一次 /api/align 返回的最大 md 行数。md 最大可到 2.6MB（约 3 万行），
# 全量吐给浏览器会卡死；超出则只返回前 N 行并明确告知已截断，
# 前端据此提示用户用「只看差异」或搜索定位，而不是假装内容完整。
ALIGN_MAX_LINES = 6000



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
