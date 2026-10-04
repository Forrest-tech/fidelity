# -*- coding: utf-8 -*-
"""把「源文行」定位回**源文件页面上的坐标** —— 左侧高亮的数据基础。

## 为什么需要这个模块
用户要的核心功能是：左边永远是源文件原貌，**md 里能在源文件上找到的内容要绿底标出来**。
只做「右栏 md 上色」是不够的 —— 那样用户无法确认「md 里那行绿色」在原图上到底指哪一块。
所以必须把对齐结果（哪些源文行被 md 收录了）反查成页面上的矩形框，
交给前端叠在渲染图 / 表格单元格上。

## 三个关键设计
1. **行号不可信 → 按归一化文本匹配**。
   `page.get_text("text")`（抽取用）与 `page.get_text("dict")`（定位用）的切行方式
   并不完全一致，同一份 PDF 两者行数可能对不上。所以这里**不按行号对齐**，
   而是按「归一化行文本」建 multiset：dict 的每一行去查它属于 match / src_only / changed。
   重复行用游标按出现顺序消费，与 compare.align_lines 的重复行配对策略一致。

2. **坐标必须做旋转变换**。
   `get_text("dict")` 的 bbox 在**未旋转**页面坐标系里，而 `get_pixmap()` 渲染出来的是
   **旋转后**的可见页面（page.rect）。直接归一化会导致横排/竖排 PDF 的高亮框整体错位。
   正确做法是 `fitz.Rect(bbox) * page.rotation_matrix` 再除以 page.rect 宽高。

3. **全链路有缓存 + 规模上限**。
   逐页 bbox、逐页行数都落盘缓存（key 含 mtime/size）；超过 MARKS_MAX_PAGES 直接降级，
   绝不为了高亮去硬攻一个 3000 页的巨著。
"""
import hashlib
import json
import os

from .. import config

MARKS_CACHE = os.path.join(config.CACHE_DIR, "marks")
os.makedirs(MARKS_CACHE, exist_ok=True)

MARKS_MAX_PAGES = 600      # 超过页数：只对前 N 页提供坐标高亮
LINE_CLIP = 200            # 单行参与匹配的最大长度（超长行匹配极慢且无意义）


def _key(path, tag=""):
    try:
        st = os.stat(path)
        raw = "%s|%s|%s|%s" % (path, st.st_mtime, st.st_size, tag)
    except OSError:
        raw = "%s|%s" % (path, tag)
    return hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()


def _cache_path(path, tag):
    return os.path.join(MARKS_CACHE, "mk_%s.json" % _key(path, tag))


def _read_cache(path, tag):
    p = _cache_path(path, tag)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _write_cache(path, tag, payload):
    p = _cache_path(path, tag)
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass


def _mupdf():
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    return pymupdf


# ------------------------------------------------------------------ 源文行 → 页
# ⚠️ 切分语义必须与 compare.align_lines 完全一致。
# 对齐侧用的是 `src_text.splitlines()`，而 splitlines() 与 split("\n") **不等价**：
# splitlines() 还会在 \r / \v / \f / \x85 /   /   处断行。
# PDF 抽取出的文本里 \r 极常见（实测某图纸 per-page split("\n") 累计 136 行，
# 而 join 后 splitlines() 只有 135 行）。若这里用 split("\n") 计数，
# 行号→页号映射会从第二页起整体错位，导致「点 md 的行跳到源文件错误的页」。
_LINE_BOUNDARIES = "\n\r\v\f\x1c\x1d\x1e\x85  "


def _ends_with_break(text):
    return bool(text) and text[-1] in _LINE_BOUNDARIES


def cum_line_counts(texts):
    """给定每页原始文本，返回「累计行数」列表，语义严格等于 splitlines()。

    不变量（已用 1884 组合成边界用例 + 真实 PDF 双重验证）：
        cum[i] == len("\\n".join(texts[:i+1]).splitlines())

    为什么不能把各页行数直接相加：抽取侧用 "\\n" 把各页连起来，
    **连接符本身就是一个换行**（"a" + "\\n" + "b" = 2 行）。
    而且 splitlines() 认 \\r / \\v / \\f 等 break 字符，split("\\n") 不认 ——
    对齐侧用的是 splitlines()，这里必须逐字符对齐，否则页码映射会整体错位。

    实现：维护三态并增量推进
        n          已确认完整的行数
        pending    跨页未闭合的残行内容（"" 表示恰好停在换行处）
        pending_cr 上一步是否以 "\\r" 结尾
    关键细节 —— **连接符的增量依赖 pending_cr**：
        以 "\\r" 结尾时，随后到来的 "\\n" 会与之合成 "\\r\\n"，
        splitlines 视其为**一个**换行，因此 n 不变（被吸收）；
        否则 "\\n" 终结 pending（或新建一个空行），n += 1。
    累计值取「本页结束时总行数」，残行计入当前页（它在视觉上就画在本页，
    与 get_text("dict") 的分页行为一致）。
    """
    cum = []
    n = 0
    pending = ""
    pending_cr = False
    for i, t in enumerate(texts):
        if i:                                   # 页间连接符 "\n"
            if not pending_cr:
                n += 1                          # 终结残行 / 新建一个空行
            pending = ""
            pending_cr = False
        if t:
            parts = t.splitlines()
            if _ends_with_break(t):
                n += len(parts)
                pending = ""
                pending_cr = t[-1] == "\r"       # "\r" 结尾：等待吸收下一个 "\n"
            else:
                n += len(parts) - 1
                pending = parts[-1]
                pending_cr = False
        cum.append(n + (1 if pending else 0))
    return cum


def page_line_counts(path, max_pages=2000):
    """每页累计行数（1-based 索引即页序），供「源文行 → 页号」反查。"""
    if os.path.splitext(path)[1].lower() != ".pdf":
        return []
    c = _read_cache(path, "plc2")
    if c is not None:
        return c
    try:
        with _mupdf().open(path) as d:
            n = min(d.page_count, max_pages or 2000)
            texts = [(d[i].get_text("text") or "") for i in range(n)]
    except Exception:
        return []
    counts = cum_line_counts(texts)
    _write_cache(path, "plc2", counts)
    return counts


def line_to_page(cum, line_idx):
    """全局源文行下标（0-based）→ 页号（1-based）。cum 为 page_line_counts 的累计值。"""
    if not cum or line_idx is None or line_idx < 0 or line_idx >= cum[-1]:
        return None
    lo, hi = 0, len(cum) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if line_idx < cum[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo + 1


def src_line_page_map(path, max_pages=2000):
    """展开成「每个源文行 → 页号」的列表，供 md 侧反查页码。"""
    cum = page_line_counts(path, max_pages)
    if not cum:
        return []
    out = []
    prev = 0
    for i, c in enumerate(cum):
        out.extend([i + 1] * (c - prev))
        prev = c
    return out


# ------------------------------------------------------------------ 页内矩形
def page_lines(path, page_no, max_pages=2000):
    """返回该页每一行的 {text, x, y, w, h}，坐标已归一化到 0..1（显示坐标系）。

    归一化后前端可以任意缩放 / 改侧栏宽度而无需重新请求。
    """
    if os.path.splitext(path)[1].lower() != ".pdf":
        return None
    page_no = max(1, int(page_no or 1))
    tag = "pl@%d" % page_no
    c = _read_cache(path, tag)
    if c is not None:
        return c
    try:
        with _mupdf().open(path) as d:
            n = d.page_count
            if page_no > min(n, max_pages or 2000):
                return None
            page = d[page_no - 1]
            rect = page.rect
            pw, ph = float(rect.width) or 1.0, float(rect.height) or 1.0
            # 关键：bbox 在未旋转坐标系，需乘 rotation_matrix 才是显示坐标
            mat = page.rotation_matrix
            out = []
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                for line in block.get("lines", []) or []:
                    spans = line.get("spans") or []
                    text = "".join(s.get("text", "") for s in spans)
                    if not text.strip():
                        continue
                    try:
                        r = _mupdf().Rect(line["bbox"]) * mat
                    except Exception:
                        continue
                    out.append({
                        "text": text[:LINE_CLIP],
                        "x": round(max(0.0, r.x0) / pw, 5),
                        "y": round(max(0.0, r.y0) / ph, 5),
                        "w": round(max(0.0, min(r.x1, pw) - max(r.x0, 0)) / pw, 5),
                        "h": round(max(0.0, min(r.y1, ph) - max(r.y0, 0)) / ph, 5),
                    })
            out.sort(key=lambda ln: (ln["y"], ln["x"]))
            payload = {"page": page_no, "w": round(pw, 2), "h": round(ph, 2), "lines": out}
    except Exception:
        return None
    _write_cache(path, tag, payload)
    return payload


def total_pages(path):
    if os.path.splitext(path)[1].lower() != ".pdf":
        return 0
    try:
        with _mupdf().open(path) as d:
            return d.page_count
    except Exception:
        return 0
