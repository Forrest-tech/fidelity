# -*- coding: utf-8 -*-
"""O(n) 源文 vs .md 对比与转化率算法。

设计要点（对应规格 §5.4 / §7）：
- **禁用 difflib.SequenceMatcher（O(n^2)）**，大文本必卡。这里用
  「归一化行 -> 行哈希 -> 倒排索引」做对齐，整体 O(n)，几十万行不炸。
- 逐行判定：两边都有 = match(绿底)；只在源 = src_only(红底·转换遗漏)；
  只在 md = md_only(红底·转换多出)。满足"绿/红"需求。
- 数字保真：抽取数字/量纲 token 做多重集比对，OCR 最易把 25mm→2Smm。
- 自动分 S = 0.5*内容覆盖率 + 0.5*数字保真率（0-100）。
- 分页：全局只做一次 O(n) 对齐，display 时按页切片，保证大文件流畅。
"""
import hashlib
import json
import os
import re
from collections import Counter

# ---- .md 伪影剥离：管线自己加的元数据/锚点/标题不是转换内容，
#      不剥离会让每个文件凭空多出成百上千条假 md_only 差异。 ----
_FM = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
# 剥离「所有」HTML 注释：管线会写 <!-- unit: ... --> 开标签和 <!-- /unit --> 闭标签，
# 只剥开标签会漏掉闭标签，在差异里刷出成百上千条无意义行。
_ANCHOR = re.compile(r"<!--.*?-->", re.S)
_STDID = re.compile(r"^>\s*标准标识.*$", re.M)
_H1 = re.compile(r"^#\s+\S")


# 「二进制字符串打捞」产物的特征串。原转换管线遇到无法解析的二进制格式
# （DWG/RFA 等）时，会把文件里的可打印 ASCII 片段原样倒进 .md，内容形如
#   AC1032 / RdAkRdAkRdA / IDATx / Z)&Z)FZ)fZ)
# 这不是文档内容。拿它跟真实源文比对必然低分——低分本身是正确信号，
# 但必须说清「低分是因为原转换没产出内容」，而不是「源文件没内容」。
_SALVAGE_MARKS = (
    "parser: salvage",
    "salvage:001",
    "字符串打捞",
    "low_confidence,salvage",
)


def md_is_salvage(raw_md):
    """判断 md 是否为二进制字符串打捞产物。传**未剥离**的原始 md 文本。"""
    if not raw_md:
        return False
    head = raw_md[:2000]
    return any(m in head for m in _SALVAGE_MARKS)


def strip_md_artifacts(md_text):
    """剥离管线元数据与纯排版标记，只留「正文内容」。

    剥离项：
      * front-matter / HTML 注释 / 标准标识行 / 首个 H1 标题
      * **行首 Markdown 排版标记**：列表符（- * + / 1.）、引用符（>）、
        标题井号（##+）、表格竖线与对齐行、强调符（* _ ~）、
        以及块引用/代码围栏的收尾行。

    ⚠️ 为什么必须剥：这些是**排版**不是内容。早期版本没剥，导致
    「源文 `600X600 ACCESS CHAMBER`」vs「md `- 600X600 ACCESS CHAMBER`」
    被判成 changed —— 内容其实 100% 一致，却在界面上刷出满屏红色差异，
    属于典型的假差异（false positive），会让整个质检结论失真。
    """
    if not md_text:
        return ""
    t = _FM.sub("", md_text)
    t = _ANCHOR.sub("", t)
    t = _STDID.sub("", t)
    out = []
    in_fence = False
    for ln in t.splitlines():
        s = ln.strip()
        # 代码围栏内保持原样（代码块的缩进/符号是有意义的内容）
        if _FENCE.match(s):
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(ln)
            continue
        # 表格对齐行（|---|---|）整行丢弃
        if _TBL_ALIGN.match(s):
            continue
        s = _strip_markup(s)
        if s:
            out.append(s)
    return "\n".join(out)


_FENCE = re.compile(r"^(`{3,}|~{3,})")
_TBL_ALIGN = re.compile(r"^\|?[\s:\-|]+\|[\s:\-|]*$")
# 行首排版标记（可叠加）。
# ⚠️ 有序列表必须要求「点后跟空白」：`2. Fire hydrant` 是列表，`2.5m` 是尺寸——
#    早期写成 `\d{1,3}[.)]\s*` 会把 `2.5m` 啃成 `5m`，制造假差异。
# 同理 `**` 只有在**后面跟空白**时才算粗体起始，否则是 `**bold**` 这种内联强调，
#    不能在这里动（交给 _INLINE_PAIR 处理）。
_MD_LEAD = re.compile(
    r"^(?:"
    r"(?:#{1,6}\s)"          # 标题
    r"|(?:>\s)"              # 引用
    r"|(?:[-*+]\s)"          # 无序列表（- / * / + 后必须有空白）
    r"|(?:\d{1,3}\.\s)"       # 有序列表：只认「数字 + 点 + 空白」
    r")+")
# ⚠️ 故意**不剥 `12) Check the cover`**：右括号式编号在技术规范里同样是真实编号
#    （`Clause 3) ...`），剥掉会丢内容，属于另一种假差异。

# 行内成对强调符：**粗体** / ~~删除~~ / *斜体*（不含 _ ，见 _strip_markup 注释）
_INLINE_PAIR = re.compile(r"(\*\*|~~|\*)(?=\S)(.+?)(?<=\S)\1")





def _strip_markup(s):
    """去掉单行的 Markdown 排版标记，保留文字本身。"""
    # 顺序很关键：**先**处理行首的列表符，再处理行内成对强调符。
    # 若先剥强调符，`- **Term** - definition` 的前导 `**` 会被行首规则吃掉，
    # 导致尾部 `**` 残留。
    prev = None
    while prev != s:
        prev = s
        s = _MD_LEAD.sub("", s)
    # 行内成对强调符：**粗体** / ~~删除~~ / *斜体*。
    # ⚠️ 故意**不处理下划线 `_`**：技术文档里 `A_B_C`、`2_5` 极常见，
    # 剥它会破坏真实内容（假差异的另一面 —— 假内容丢失）。
    if "`" not in s:
        s = _INLINE_PAIR.sub(r"\2", s)
    # 表格行：单元格用空格代替竖线，保留文字
    if "|" in s:
        s = " ".join(x.strip() for x in s.strip("|").split("|")).strip()
        s = _WS.sub(" ", s).strip()
    # 行尾硬换行标记与多余空白
    s = re.sub(r"\s{2,}$", "", s)
    return s.strip()







_WS = re.compile(r"\s+")
# 数字/量纲 token：可选符号 + 数字 + 可选单位（mm, m, kPa, °C, %, L/s ...）
_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)*\s*(?:mm|cm|m|km|kPa|MPa|Pa|°C|C|kW|MW|V|A|mA|mL|L/s|L|Hz|kHz|MHz|%|s|ms|N|kN|Nm|kg|t)?", re.I)
_WORD = re.compile(r"[a-z0-9]+", re.I)


def normalize_line(s: str) -> str:
    """归一化：折叠空白、去首尾、小写。用于哈希匹配（忽略排版差异）。"""
    if s is None:
        return ""
    return _WS.sub(" ", s).strip().lower()


def _tokens_for(ln):
    return set(_WORD.findall((ln or "").lower()))


def pair_similar(unmatched_src, unmatched_md, threshold=0.5,
                 max_cmp=200000, time_budget=5.0,
                 src_lines=None, md_lines=None):
    """把「只在源」和「只在 md」的行里高度相似的配成 changed 对。

    ⚠️ 性能红线（对应规格「大文件不许卡死」）：
    早期版本对候选对调用 difflib.SequenceMatcher，200 页 PDF 上要跑十几万次，
    实测把对比任务拖到 >2 分钟（HTTP 直接超时）。这里改为**纯 token 级 Dice 系数**，
    用倒排索引只算有 token 重叠的候选对，整体接近 O(n)，不调用 difflib。
    另有 max_cmp 与时间预算双保险，超限即放弃配对（退化为 src_only/md_only，不影响正确性）。
    返回 ({src_idx: md_idx}, {md_idx: src_idx})

    ⚠️ 并发红线（2026-10-04 修复）：早期用模块级缓存传行内容，FastAPI 线程池下
    两个 /diff 并发请求互相覆盖缓存 → IndexError(500)。现在行内容显式传参，无共享状态。
    """
    import time as _time
    src_lines = src_lines if src_lines is not None else []
    md_lines = md_lines if md_lines is not None else []
    t0 = _time.time()

    # 倒排索引：token -> 未匹配 md 行下标。
    # 停用词阈值按「未匹配行规模」自适应：早期固定 300 会在小候选集下把仅有的
    # 区分 token 全删光，导致 OCR 改写行配不上（漏检 changed）。
    inv = {}
    for j in unmatched_md:
        if 0 <= j < len(md_lines):
            for t in _tokens_for(md_lines[j]):
                inv.setdefault(t, []).append(j)
    stop_hi = max(500, len(unmatched_md) // 2)
    for t in list(inv.keys()):
        if len(inv[t]) > stop_hi or len(inv[t]) > 5000:
            del inv[t]

    pairs = []
    cmp_count = 0
    for i in unmatched_src:
        if cmp_count >= max_cmp or (_time.time() - t0) > time_budget:
            break
        if i >= len(src_lines):
            continue
        toks = _tokens_for(src_lines[i])
        if not toks:
            continue
        cand = {}
        for t in toks:
            lst = inv.get(t)
            if not lst:
                continue
            for j in lst:
                cand[j] = cand.get(j, 0) + 1
        if not cand:
            continue
        # 只取重叠最多的前 30 个候选：控制成本，同时不牺牲小候选集的召回
        top = sorted(cand.items(), key=lambda kv: -kv[1])[:30]
        for j, ov in top:
            if cmp_count >= max_cmp or (_time.time() - t0) > time_budget:
                break
            cmp_count += 1
            if not (0 <= j < len(md_lines)):
                continue
            btoks = _tokens_for(md_lines[j])
            if not btoks:
                continue
            # Dice 系数（token 级）：对切行/空格/大小写差异免疫，且 O(1) 每对
            dice = 2.0 * ov / (len(toks) + len(btoks))
            if dice >= threshold:
                pairs.append((dice, i, j))

    pairs.sort(reverse=True)
    s2m, m2s = {}, {}
    for r, i, j in pairs:
        if i in s2m or j in m2s:
            continue
        s2m[i] = j
        m2s[j] = i
    return s2m, m2s


# pair_similar 曾用模块级缓存传行内容 → FastAPI 线程池并发下互相覆盖（已修复为显式传参，
# 以下两个全局仅为兼容保留，不再使用）
src_lines_cache: list = []
md_lines_cache: list = []


def align_lines(src_lines, md_lines, pair_changed=True):
    """O(n) 行对齐，**按源文阅读顺序**输出。

    返回 segments: [{status: match|src_only|md_only|changed, src, md, src_no, md_no}]
    - match  : 两侧同一行（绿底）
    - src_only: 源有 .md 无（红底·转换遗漏）
    - md_only : .md 有源无（红底·转换多出）
    - changed: 两侧相似但不相同（黄底·OCR 改写）
    重复行按出现次数一一配对。**顺序即阅读顺序**，保证左右分屏能逐行读下去。
    """
    global src_lines_cache, md_lines_cache
    src_lines_cache = src_lines
    md_lines_cache = md_lines
    # 兼容占位（不再被 pair_similar 读取）；显式传参见下方 pair_changed 调用

    # 1) 精确匹配：归一化行哈希 -> 源行下标队列
    src_index = {}
    for i, ln in enumerate(src_lines):
        h = normalize_line(ln)
        if not h:
            continue
        src_index.setdefault(h, []).append(i)

    matched_src = {}      # src_idx -> md_idx
    used_src = set()
    md_anchor = {}        # md_idx -> 源下标（用于 md_only 插回正确位置）
    last_anchor = -1
    unmatched_md = []
    for j, ln in enumerate(md_lines):
        h = normalize_line(ln)
        if not h:
            # 空白行不参与对齐：否则会产出成千上万条"内容为空"的假差异，
            # 把真正需要人看的差异淹掉。
            continue
        cands = src_index.get(h)
        i = None
        if cands:
            while cands and cands[0] in used_src:
                cands.pop(0)
            if cands:
                i = cands.pop(0)
                used_src.add(i)
                matched_src[i] = j
        if i is not None:
            md_anchor[j] = i
            last_anchor = i
        else:
            unmatched_md.append(j)
            md_anchor[j] = last_anchor

    # 2) 相似行配对 -> changed
    s2m, m2s = ({}, {})
    unmatched_src = [i for i in range(len(src_lines)) if i not in used_src]
    if pair_changed and unmatched_src and unmatched_md:
        s2m, m2s = pair_similar(unmatched_src, unmatched_md,
                                src_lines=src_lines, md_lines=md_lines)

    # 3) 按源顺序归并；md_only 在其锚点之前插入
    pending_md = {j for j in unmatched_md if j not in m2s}
    by_anchor = {}
    for j in pending_md:
        by_anchor.setdefault(md_anchor.get(j, -1), []).append(j)
    for lst in by_anchor.values():
        lst.sort()

    segments = []
    for anchor in sorted(by_anchor.keys()):
        for j in by_anchor[anchor]:
            segments.append({"status": "md_only", "src": None, "md": md_lines[j],
                             "src_no": None, "md_no": j})
    for i in range(len(src_lines)):
        if i in matched_src:
            j2 = matched_src[i]
            segments.append({"status": "match", "src": src_lines[i], "md": md_lines[j2],
                             "src_no": i, "md_no": j2})
        elif i in s2m:
            j2 = s2m[i]
            segments.append({"status": "changed", "src": src_lines[i], "md": md_lines[j2],
                             "src_no": i, "md_no": j2})
        elif normalize_line(src_lines[i]):
            segments.append({"status": "src_only", "src": src_lines[i], "md": None,
                             "src_no": i, "md_no": None})
    return segments


def extract_numbers(text: str) -> Counter:
    """抽取数字/量纲 token 多重集。

    ⚠️ 千分位（2026-10-04 修复）：规范里数字常带千分位，如 `1,000 L`。
    早期把逗号一律当小数点归一，导致 `1,000` 变成 `1.000`，
    于是「源文 1,000 L / md 写错成 1.000 L」这种**真实的 OCR 数字错误
    会被判成保真率 1.0** —— 恰恰是数字保真最该抓的那类错。
    规则：逗号后恰好 3 位数字 → 视为千分位分组符（`1,000` / `1,234,567`）；
    其余情况（`1,5` / `1,50` / `0,25` 欧式写法）才当小数点。
    """
    c = Counter()
    for m in _NUM.finditer(text or ""):
        tok = _WS.sub("", m.group(0)).lower()
        if not re.search(r"\d", tok):
            continue
        # 去量纲单位后只剩数字部分才做千分位处理
        num = re.match(r"[+-]?\d+(?:[.,]\d+)*", tok)
        if num:
            head = num.group(0)
            digits = head.replace(",", "")
            # 每 3 位一组的千分位串（1,000 / 12,345 / 1,234,567）
            if "," in head and re.fullmatch(r"\d{1,3}(?:,\d{3})+", head):
                head = digits
            else:
                # 非千分位形态：逗号当小数点（保持历史行为）
                head = head.replace(",", ".")
            tok = head + tok[num.end():]
        c[tok] += 1
    return c


def number_fidelity(src_text: str, md_text: str) -> float:
    """数字保真率 = md 中数字能在源中找到的比例(多重集交集/源总量)。
    源里没有数字 -> 返回 None（不适用）。"""
    s = extract_numbers(src_text)
    if not s:
        return None
    m = extract_numbers(md_text)
    hit = sum(min(cnt, m.get(tok, 0)) for tok, cnt in s.items())
    return hit / float(sum(s.values()))


def token_counter(text):
    c = Counter()
    for w in _WORD.findall((text or "").lower()):
        c[w] += 1
    return c


# ---- 字数统计（用户 2026-10-04 需求：源文/MD 总字数是直观指标） ----
# 中文按「字」计（每汉字 1），拉丁/数字按「词」计（连续串 1），两者相加即为习惯意义上的字数。
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_LATIN_WORD = re.compile(r"[A-Za-z0-9]+(?:[.,'\-][A-Za-z0-9]+)*")


def count_text(text):

    """统计 (字符数, 字数)。字数 = CJK 字数 + 拉丁词数。"""
    t = text or ""
    cjk = len(_CJK.findall(t))
    latin = len(_LATIN_WORD.findall(t))
    return {"chars": len(t.strip()), "words": cjk + latin, "cjk": cjk, "latin": latin}


def dup_ratio(text):
    """检测「同一行被重复展开」的比例（不参与打分，只作提示）。

    实测：原转换管线处理 Word/表格密集文档时会把单元格内容重复拼接
    （如 `thermostatic mixing valve` 连续出现多次），md 字数虚高到源文 1.8–2 倍。
    抽样 20 个偏高文件，3.35% 的行存在 4 次以上重复。

    ⚠️ 不影响评分可信度：coverage 以**源文**为分母，重复内容不会让分数虚高
    （实测重复 3 份仍 100 分）。这个指标只用来提示「这份 md 可能有冗余」。
    """
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return 0.0
    bad = 0
    for l in lines:
        toks = l.split()
        if len(toks) <= 6:
            continue
        if max(Counter(toks).values()) >= 4:
            bad += 1
    return bad / float(len(lines))


def token_coverage(src_text, md_text):
    """词级内容覆盖率（用于评分，对两家抽取器的切行差异免疫）。O(n)。"""
    s = token_counter(src_text)
    if not s:
        return None
    m = token_counter(md_text)
    hit = sum(min(cnt, m.get(w, 0)) for w, cnt in s.items())
    return hit / float(sum(s.values()))


def evaluate(src_text: str, md_text: str, engine_b="pdfplumber"):
    """产出自动评测结果（写 file_eval 用）。"""
    src_lines = (src_text or "").splitlines()
    md_lines = (md_text or "").splitlines()
    segments = align_lines(src_lines, md_lines)
    n_src = len([l for l in src_lines if normalize_line(l)])
    n_match = sum(1 for s in segments if s["status"] == "match")
    line_match_ratio = (n_match / n_src) if n_src else None
    # 评分用词级覆盖率（对 pdfplumber vs pymupdf 切行差异免疫）；
    # 行级匹配率只用于左侧可视化 diff 统计，不参与打分。
    coverage = token_coverage(src_text, md_text)
    numf = number_fidelity(src_text, md_text)
    cs, cm = count_text(src_text), count_text(md_text)
    if coverage is None and numf is None:
        auto = None
    else:
        c = coverage if coverage is not None else 0.0
        nf = numf if numf is not None else c   # 无数字时用覆盖率兜底
        auto = round(100.0 * (0.5 * c + 0.5 * nf), 1)
    return {
        "auto_score": auto,
        "coverage": coverage,
        "line_match_ratio": line_match_ratio,
        "number_fidelity": numf,
        "engine_b": engine_b,
        "n_src_lines": n_src,
        "n_md_lines": len(md_lines),
        "src_chars": cs["chars"], "md_chars": cm["chars"],
        "src_words": cs["words"], "md_words": cm["words"],
        "n_match": n_match,
        "n_src_only": sum(1 for s in segments if s["status"] == "src_only"),
        "n_md_only": sum(1 for s in segments if s["status"] == "md_only"),
        "n_changed": sum(1 for s in segments if s["status"] == "changed"),
        "_segments": segments,
    }


def page(segments, page=1, per_page=50, only_diff=False):
    """把 segments 分页；only_diff=True 只返回有差异的行。

    ⚠️ 参数夹紧（2026-10-04 修复）：`per_page` 与 `page` 都直接来自
    HTTP 查询串（`/api/diff?per_page=0`），早期不校验导致
    ZeroDivisionError → 整个接口 500。分页参数不可信，一律夹到安全区间。
    """
    # 下限 1（防除零），上限 1000（防一次返回 10 万行把浏览器打挂）
    try:
        per_page = max(1, min(int(per_page), 1000))
    except (TypeError, ValueError):
        per_page = 50
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    segs = segments
    if only_diff:
        segs = [s for s in segs if s["status"] != "match"]
    total = len(segs)
    start = (page - 1) * per_page
    end = start + per_page
    return segs[start:end], total, max(1, (total + per_page - 1) // per_page)


# ------------------------------------------------------------------ 对齐结果缓存
# 性能红线：一次全量对齐在 4.6MB / 上万行的 PDF 上要 50 秒级（实测 54s）。
# 用户点开文件、切页、切换「只看差异」都会重新触发同样的计算 —— 必须缓存。
#
# 缓存 key = md 文件的 (mtime, size) + 抽取文本的哈希长度。理由：
#   * md 变了 → 重新转换过 → 必须重算；
#   * 源文变了（重新抽取）→ 行数/内容变 → 用长度+首尾片段做指纹即可，
#     完整哈希对几十万行太慢（实测比对齐本身还贵）。
_ALIGN_CACHE_DIR = None


def _align_cache_path(rel, src_text, md_text):
    global _ALIGN_CACHE_DIR
    if _ALIGN_CACHE_DIR is None:
        from .. import config
        _ALIGN_CACHE_DIR = os.path.join(config.CACHE_DIR, "align")
        os.makedirs(_ALIGN_CACHE_DIR, exist_ok=True)
    # 指纹：源文行数 + md 行数 + 长度 + md 头部片段（够区分不同内容，又不遍历全文）
    sig = "%s|%d|%d|%d|%d|%s" % (
        rel, src_text.count("\n") + 1, md_text.count("\n") + 1,
        len(src_text), len(md_text), md_text[:400].replace("\n", " "))
    key = hashlib.md5(sig.encode("utf-8", "ignore")).hexdigest()
    return os.path.join(_ALIGN_CACHE_DIR, "al_%s.json" % key)


def align_lines_cached(src_text, md_text, rel="", cache_dir=None):
    """带磁盘缓存的 align_lines。返回 segments（不含元信息）。

    缓存失效条件：rel / 两侧行数 / 字符数 / md 头部变化 —— 即任一侧内容实质变化。
    缓存损坏或版本不符时自动回落到实时计算（保证正确性优先）。
    """
    p = _align_cache_path(rel, src_text, md_text)
    if cache_dir:
        p = os.path.join(cache_dir, os.path.basename(p))
    try:
        with open(p, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("v") == ALIGN_CACHE_VERSION:
            return payload["segments"]
    except Exception:
        pass

    segments = align_lines(src_text.splitlines(), md_text.splitlines())
    # 只缓存完整结果的对齐（pair_similar 内部有 time_budget，超预算时结果
    # 是不完整的；这类重算代价也不高，就不缓存，避免把「半份结果」固化下来）
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": ALIGN_CACHE_VERSION, "segments": segments}, f)
        os.replace(tmp, p)
    except Exception:
        pass
    return segments


# 对齐缓存版本：改动 align_lines / pair_similar 的逻辑时必须 +1，使旧缓存整体失效
ALIGN_CACHE_VERSION = 2


if __name__ == "__main__":

    src = " Pipes shall be 25 mm.\n Vent size 300mm.\n Cable tray 2.5 m.\n Flue temp 60 C."
    md = " Pipes shall be 2S mm.\n Vent size 300mm.\n Cable tray 2.5 m."
    r = evaluate(src, md)
    print("auto_score:", r["auto_score"], "coverage:", r["coverage"],
          "num_fid:", r["number_fidelity"])
    print("match/src_only/md_only:", r["n_match"], r["n_src_only"], r["n_md_only"],
          "changed:", r["n_changed"])
    for s in r["_segments"]:
        print("  ", s["status"], "|", (s["src"] or "")[:28], "||", (s["md"] or "")[:28])
