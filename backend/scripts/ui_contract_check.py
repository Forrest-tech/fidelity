# -*- coding: utf-8 -*-
"""前端渲染契约测试：核对 UI 实际依赖的每个 API 字段是否齐备、类型正确。

为什么需要这个：浏览器截图在本机沙箱里连不上本地端口（ERR_CONNECTION_REFUSED），
无法做像素级验收。改用「契约测试」——把 App.tsx / FileTree.tsx / SourcePane.tsx /
MdPane.tsx / ReviewerPanel.tsx 里读到的每一个字段都在真实 API 响应里核对一遍。
字段缺失会让界面空白或报 undefined，这正是 UI bug 的主要来源。

本轮重点（用户 2026-10-05 的 4 条反馈对应的接口）：
  1. /tree       侧栏显示**原目录结构**（不再是扁平列表）
  2. /align      逐行状态，供右栏 md 上色 —— 且**必须与 /md 的 lines 同下标**
  3. /marks      源文件页内归一化坐标，供左栏叠加绿色高亮框
  4. /reviewers  审核人受管名单（取代自由输入）+ 裁决时强制校验

用法：python scripts/ui_contract_check.py
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config  # noqa: E402

BASE = "http://127.0.0.1:8000/api"
FAILS = []
CHECKS = [0]

LINE_STATUS = {"match", "changed", "md_only", "src_only", "unmatched"}


def get(path, **params):
    q = urllib.parse.urlencode(params)
    url = "%s/%s%s" % (BASE, path, ("?" + q) if q else "")
    with urllib.request.urlopen(url, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, body, **params):
    q = urllib.parse.urlencode(params)
    url = "%s/%s%s" % (BASE, path, ("?" + q) if q else "")
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def delete(path):
    req = urllib.request.Request("%s/%s" % (BASE, path), method="DELETE")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def need(cond, label, extra=""):
    CHECKS[0] += 1
    if not cond:
        FAILS.append("%s %s" % (label, extra))
        print("  FAIL  %s %s" % (label, extra))
    else:
        print("  ok    %s" % label)


def pick_sample(sid, exts, skip_encrypted=True):
    """从库里挑一个真实文件（按扩展名）。"""
    src = config.get_source(sid)
    root = src["src_root"]
    for r, d, fs in os.walk(root):
        for f in fs:
            if os.path.splitext(f)[1].lower() in exts:
                rel = os.path.relpath(os.path.join(r, f), root).replace("\\", "/")
                if skip_encrypted and "AS2304-2019 Fire tank" in f:
                    continue          # 已知加密 PDF（第三方加密处理器打不开）
                return rel
    return None


def walk_dirs(node):
    """深度优先遍历目录树节点。"""
    for d in node.get("dirs") or []:
        yield d
        for x in walk_dirs(d):
            yield x


# 源码级防回归用的前端源码目录（backend/scripts → 项目根 → web/src）
WEB_SRC = os.path.normpath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "..", "web", "src"))


def read_src(*parts):
    """读取 web/src 下的前端源码；不存在返回 None（跳过该检查）。"""
    p = os.path.normpath(os.path.join(WEB_SRC, *parts))
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------
# i18n 静态分析：真正解析词表，而不是只 grep「zh/en 是否存在」
# --------------------------------------------------------------------------
def _dict_block(src, lang):
    """截出 DICT 里某个语言的小节文本。"""
    m = re.search(r"\n\s*%s:\s*\{" % re.escape(lang), src)
    if not m:
        return ""
    i = m.end() - 1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    return src[i:]


def _dict_keys(src, lang):
    """取出某语言小节里所有的 "key": "…" 键。"""
    blk = _dict_block(src, lang)
    return set(re.findall(r'"([a-zA-Z][\w.]*)"\s*:', blk))


def _placeholders(src, lang, key):
    """取某个 key 的文案里出现的 {xxx} 占位符集合。"""
    blk = _dict_block(src, lang)
    m = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % re.escape(key), blk)
    if not m:
        return set()
    return set(re.findall(r"\{(\w+)\}", m.group(1)))


def _effect_deps(src, call):
    """找出包含 `call(` 的那个 useEffect 所依赖的变量集合。

    用于守住「翻页不要重跑与页码无关的请求」这类性能不变量：
    依赖数组里出现 page，就意味着每翻一页都会重新请求一次。
    """
    i = src.find(call)
    while i != -1:
        # 从调用处往前找最近的 useEffect(，往后找它的依赖数组
        start = src.rfind("useEffect(", 0, i)
        if start == -1:
            return set()
        tail = src[i:]
        m = re.search(r"\},\s*\[([^\]]*)\]\s*\)", tail)
        if m:
            return set(re.findall(r"[A-Za-z_$][\w$]*", m.group(1)))
        i = src.find(call, i + 1)
    return set()


# ★ 允许保留中文的源码位置：注释与「必须原样呈现」的源文内容
_CJK_OK = re.compile(
    r"(AC1032|RdAkRdAkRdA)"  # 打捞产物样本串，是技术证据不是界面文案
)


def _hardcoded_cjk():
    """扫出仍写死在 JSX/逻辑里的中文界面文案。

    判定方式：逐行找含 CJK 的**字符串字面量**或 JSX 文本节点，并排除
      * 注释行（// 、* 、/* ）
      * import 语句
      * 含 t( / t(" 的行（已国际化）
      * 明确的源文内容常量
    这样才能真正挡住「设置页/弹窗里漏翻译」—— 只查 key 存在是查不出来的。
    """
    hits = []
    # i18n.tsx 本身就是词表 —— 它的中文正是「已国际化」的文案，不是硬编码残留
    files = ["App.tsx"] + [
        "components/%s" % f for f in os.listdir(os.path.join(WEB_SRC, "components"))
        if f.endswith(".tsx")
    ]
    cjk = re.compile(r"[\u4e00-\u9fff]")
    for rel in files:
        src = read_src(rel)
        if not src:
            continue
        for ln_no, raw in enumerate(src.splitlines(), 1):
            line = raw.strip()
            if not cjk.search(line):
                continue
            if line.startswith(("//", "*", "/*", "<!--")) or "*/" in line:
                continue
            if line.startswith("import "):
                continue
            if _CJK_OK.search(line):
                continue
            # 已国际化的行：t("...") / t('...')
            if re.search(r"\bt\(", line) or re.search(r"\bt\(\"", line):
                continue
            # 只保留「字符串字面量里含中文」或「>中文<」的 JSX 文本
            if re.search(r'"[^"]*[\u4e00-\u9fff][^"]*"', line) or \
               re.search(r"'[^']*[\u4e00-\u9fff][^']*'", line) or \
               re.search(r">[^<>{}]*[\u4e00-\u9fff][^<>{}]*<", line):
                hits.append("%s:%d %s" % (rel, ln_no, line[:70]))
    return hits


def all_tree_files(node):
    for f in node.get("files") or []:
        yield f
    for d in walk_dirs(node):
        for f in d.get("files") or []:
            yield f


def main():
    sid = "n2"

    # ============================================================ 1. /stats
    print("== 1. /stats（统计行 · 独立成行的那一条）==")
    st = get("stats", sid=sid)
    for k in ("total", "evaluated", "avg_score", "reviewed", "reviewed_pct",
              "deferred", "salvage"):
        need(k in st, "stats.%s" % k)
    need(isinstance(st.get("by_state"), dict), "stats.by_state 是对象")
    for k in ("trusted", "need_review", "diff_big", "rejected", "unreviewed"):
        need(k in (st.get("by_state") or {}), "stats.by_state.%s（可点击筛选）" % k)
    need(isinstance(st.get("decisions"), dict), "stats.decisions 是对象")
    for k in ("pending", "include", "exclude"):
        need(k in (st.get("decisions") or {}), "stats.decisions.%s" % k)
    t = st.get("totals") or {}
    for k in ("files", "src_chars", "md_chars", "src_words", "md_words",
              "char_ratio", "word_ratio"):
        need(k in t, "stats.totals.%s" % k)
    print("  totals: 源 %s 字 → md %s 字（char_ratio %s%%）"
          % (t.get("src_chars"), t.get("md_chars"), t.get("char_ratio")))

    # ★ 数字必须自洽，否则统计条会误导用户（用户 2026-10-05 第 11 项）
    bs = st.get("by_state") or {}
    need(sum(bs.values()) == st.get("total"),
         "★ by_state 各状态之和 == total（否则统计条对不上）",
         "(sum=%s, total=%s)" % (sum(bs.values()), st.get("total")))
    need(st.get("evaluated", 0) <= st.get("total", 0),
         "★ evaluated <= total")
    need(st.get("reviewed", 0) <= st.get("evaluated", st.get("total", 0)),
         "★ reviewed <= evaluated")
    # char_ratio 必须与两个字数自洽，且允许 >100（md 可能因 front-matter 反而更大）
    if t.get("src_chars"):
        want = round(100.0 * t["md_chars"] / t["src_chars"], 1)
        need(abs(float(t.get("char_ratio") or 0) - want) <= 0.5,
             "★ char_ratio 与 src/md 字数自洽",
             "(reported=%s, computed=%.1f)" % (t.get("char_ratio"), want))
    # ★ 界面措辞：ratio>100 时必须说「膨胀」而不是「保留」——否则是误导
    appx_now = read_src("App.tsx")
    if appx_now is not None:
        need("stat.expand" in appx_now,
             "★ 字数比 >100% 时用「膨胀」措辞，不误写成「保留」")

    # ====================================================== 2. /tree 目录树
    print("== 2. /tree（侧栏原目录结构）==")
    tr = get("tree", sid=sid)
    for k in ("name", "dirs", "files", "counts"):
        need(k in tr, "TreeResp.%s" % k)
    for k in ("all", "trusted", "need_review", "diff_big", "rejected", "unreviewed"):
        need(k in (tr.get("counts") or {}), "TreeCounts.%s" % k)
    need(len(tr.get("dirs") or []) > 0, "根目录下有子目录（层级已保留）",
         "(%d)" % len(tr.get("dirs") or []))
    n_dirs = len(list(walk_dirs(tr)))
    need(n_dirs > 3, "存在多层嵌套目录（不是扁平列表）",
         "(%d 个目录节点)" % n_dirs)

    tf = list(all_tree_files(tr))
    need(len(tf) > 0, "树里有文件", "(%d)" % len(tf))
    for k in ("rel", "name", "ext", "state", "label", "auto_score"):
        need(k in tf[0], "TreeFile.%s" % k)
    need(any("/" in f["rel"] for f in tf), "TreeFile.rel 保留多级路径")

    # 计数自洽：根 counts.all == 递归文件数 == 各子目录之和
    nested = sum(1 for _ in all_tree_files(tr))
    eq_ok = tr["counts"]["all"] == nested
    need(eq_ok, "根 counts.all == 递归文件数",
         "(counts=%d, 递归=%d)" % (tr["counts"]["all"], nested))
    dir_sum = sum(d["counts"]["all"] for d in tr["dirs"])
    need(tr["counts"]["all"] == dir_sum + len(tr["files"]),
         "根 counts = 子目录之和 + 根级文件",
         "(%d vs %d+%d)" % (tr["counts"]["all"], dir_sum, len(tr["files"])))
    for d in walk_dirs(tr):
        sub = sum(x["counts"]["all"] for x in d["dirs"]) + len(d["files"])
        if d["counts"]["all"] != sub:
            need(False, "目录 %s 计数自洽" % d["name"],
                 "(%d vs %d)" % (d["counts"]["all"], sub))
            break
    else:
        need(True, "所有目录节点计数自洽（自底向上汇总正确）")

    # 筛选：按状态
    tr2 = get("tree", sid=sid, status="unreviewed")
    need(tr2["counts"]["all"] <= tr["counts"]["all"], "状态筛选后文件数不增加",
         "(%d ≤ %d)" % (tr2["counts"]["all"], tr["counts"]["all"]))
    need(all(f["state"] == "unreviewed" for f in all_tree_files(tr2)),
         "状态筛选后仅含该状态文件")
    # 搜索
    tr3 = get("tree", sid=sid, q="3500")
    need(tr3["counts"]["all"] < tr["counts"]["all"], "搜索能缩小结果集",
         "(%d < %d)" % (tr3["counts"]["all"], tr["counts"]["all"]))
    need(all("3500" in f["rel"].lower() for f in all_tree_files(tr3)),
         "搜索结果全部命中关键词")
    # 搜索无命中时不报错
    tr4 = get("tree", sid=sid, q="__no_such_keyword__")
    need(tr4["counts"]["all"] == 0, "搜索无命中返回空树而非报错")

    # ==================================================== 3. /files 徽标
    print("== 3. /files（工作区标题栏徽标）==")
    fl = get("files", sid=sid, status="")
    files = fl["files"]
    need("count" in fl and "total" in fl, "files 返回 count/total")
    need(len(files) > 0, "files 非空", "(%d)" % len(files))
    b = files[0]
    for k in ("rel", "state", "label", "badge", "auto_score", "trust_state", "reviewer"):
        need(k in b, "Badge.%s" % k)
    scored = [x for x in files if x.get("auto_score") is not None]
    need(len(scored) > 0, "存在已评测文件", "(%d)" % len(scored))
    bad = [x["rel"] for x in scored
           if not isinstance(x.get("src_chars"), int)
           or not isinstance(x.get("md_chars"), int)]
    need(not bad, "已评测文件的字数字段均为整数",
         "异常 %d 个，例：%s" % (len(bad), bad[0][-40:] if bad else ""))

    # ============================================ 4. /md + /align 下标一致性
    print("== 4. /md 与 /align 的下标一致性（错位就会把绿色标到错误的行上）==")
    rel_pdf = pick_sample(sid, {".pdf"})
    need(rel_pdf is not None, "找到 PDF 样本")
    md = get("md", sid=sid, rel=rel_pdf)
    for k in ("rel", "text", "lines", "missing", "salvage", "chars", "words"):
        need(k in md, "MdResp.%s" % k)
    need(isinstance(md["lines"], list), "MdResp.lines 是数组")
    need(md["chars"] >= 0 and md["words"] >= 0, "MdResp 字数非负")
    need(all(isinstance(x, str) for x in md["lines"]), "MdResp.lines 全是字符串")
    longest = max((len(x) for x in md["lines"]), default=0)
    need(longest <= 20100, "单行已截断保护（防浏览器崩）", "(max=%d)" % longest)

    al = get("align", sid=sid, rel=rel_pdf)
    for k in ("rel", "not_applicable", "status", "src_page", "truncated",
              "total_lines", "by_status", "verdict"):
        need(k in al, "AlignResp.%s" % k)
    need(al["not_applicable"] is False, "PDF 样本可比对")
    need(len(al["status"]) == len(al["src_page"]), "status 与 src_page 等长",
         "(%d / %d)" % (len(al["status"]), len(al["src_page"])))
    # ★ 核心不变量：status 是 md.lines 的**前缀**，且长度 == min(md行数, 上限)。
    #   前缀语义保证 status[i] 一定对应 md.lines[i]（同一下标）；
    #   允许比 md 短（超大文件只比对前 N 行），但前端必须仍能渲染全部 md 行 ——
    #   若前端跟着截断，3 万行的 md 就只剩前 6000 行可见，属于静默丢数据。
    from app.api.routes import ALIGN_MAX_LINES
    want = min(len(md["lines"]), ALIGN_MAX_LINES)
    need(len(al["status"]) == want,
         "★ align.status 长度 == min(md行数, 比对上限)",
         "(align=%d, want=%d, md=%d)" % (len(al["status"]), want, len(md["lines"])))
    need(len(al["status"]) <= len(md["lines"]),
         "★ align.status 是 md.lines 的前缀（绝不长于 md）",
         "(align=%d, md=%d)" % (len(al["status"]), len(md["lines"])))
    need(al["truncated"] == (len(md["lines"]) > want),
         "truncated 标记与实际一致",
         "(truncated=%s, md=%d, status=%d)" % (al["truncated"], len(md["lines"]),
                                               len(al["status"])))
    need(al["total_lines"] == len(md["lines"]),
         "★ align.total_lines == md.lines 长度（前端据此告知未比对行数）",
         "(total=%d, md=%d)" % (al["total_lines"], len(md["lines"])))
    need(all(s in LINE_STATUS for s in al["status"]), "status 取值全部合法",
         str(sorted(set(al["status"]) - LINE_STATUS))[:120])
    need(all(p is None or (isinstance(p, int) and p >= 1) for p in al["src_page"]),
         "src_page 是 1-based 页号或 null")
    # 不返回正文（避免同一份文本传两遍，最大 md 有 2.6MB）
    need("text" not in al, "align 不返回正文（去重，防 2.6MB 双份传输）")
    # 页码覆盖率：有页码的行应占绝大多数（PDF 才有页码）
    paged = sum(1 for p in al["src_page"] if p)
    if al["status"]:
        need(paged / len(al["status"]) > 0.9, "PDF 样本页码覆盖率 > 90%",
             "(%.1f%%)" % (100.0 * paged / len(al["status"])))
    print("  样本 %s" % rel_pdf.split("/")[-1][:40])
    print("  by_status: %s" % al.get("by_status"))
    print("  页码覆盖 %d/%d 行" % (paged, len(al["src_page"])))

    # 逐条抽查：status[i] 与 md.lines[i] 语义相符（match 行两侧都该有内容）
    hits = 0
    for i, s in enumerate(al["status"]):
        if s == "match" and md["lines"][i].strip():
            hits += 1
    need(hits > 0, "存在 match 行且 md 对应行非空（语义自洽）", "(%d 行)" % hits)

    # ================================================ 5. /marks 左栏高亮坐标
    print("== 5. /marks（源文件页内坐标 · 左栏绿色高亮框）==")
    mk = get("marks", sid=sid, rel=rel_pdf, page=1)
    for k in ("rel", "page", "supported", "lines"):
        need(k in mk, "MarksResp.%s" % k)
    need(mk["supported"] is True, "PDF 支持页内坐标")
    need("page_w" in mk and "page_h" in mk, "MarksResp 带页面尺寸")
    need(len(mk["lines"]) > 0, "第 1 页取到行坐标", "(%d 行)" % len(mk["lines"]))
    l0 = mk["lines"][0]
    for k in ("text", "x", "y", "w", "h", "status"):
        need(k in l0, "MarkLine.%s" % k)
    oob = [x for x in mk["lines"]
           if not (0 <= x["x"] <= 1 and 0 <= x["y"] <= 1
                   and 0 < x["w"] <= 1 and 0 < x["h"] <= 1)]
    need(not oob, "所有坐标归一化到 0..1 且宽高为正", "越界 %d 个" % len(oob))
    need(all(x["status"] in LINE_STATUS for x in mk["lines"]),
         "MarkLine.status 全部合法")
    need(any(x["status"] == "match" for x in mk["lines"]),
         "★ 第 1 页存在 match（可上绿底）",
         str(sorted({x["status"] for x in mk["lines"]})))
    need(all(len(x["text"]) <= 200 for x in mk["lines"]), "行文本已截断到 200 字符")
    # 页内坐标数应与抽取行数量级相符（不是 0 也不是天文数字）
    need(3 < len(mk["lines"]) < 400, "第 1 页行数量级合理", "(%d)" % len(mk["lines"]))

    # 越界页码必须优雅降级，不能 500
    mk2 = get("marks", sid=sid, rel=rel_pdf, page=99999)
    need(mk2.get("supported") is False, "越界页码降级为 supported=False")
    need(bool(mk2.get("reason")), "降级时必须给出 reason（前端要如实告知用户）")
    need(mk2.get("lines") == [], "降级时 lines 为空")

    # 非 PDF 必须降级
    rel_doc = pick_sample(sid, {".docx", ".xlsx", ".msg"})
    if rel_doc:
        mk3 = get("marks", sid=sid, rel=rel_doc, page=1)
        need(mk3.get("supported") is False,
             "非 PDF 降级（%s）" % os.path.splitext(rel_doc)[1],
             "kind=%s" % mk3.get("supported"))
    else:
        print("  skip  非 PDF 降级（库里无样本）")

    # ============================== 6. /reviewers 名单 + 裁决强制校验
    print("== 6. /reviewers（审核人受管名单，取代自由输入）==")
    rv = get("reviewers")
    need("items" in rv, "返回 items 数组")
    items = rv["items"]
    need(len(items) > 0, "名单非空（不能没有可选审核人）", "(%d)" % len(items))
    for r in items:
        for k in ("id", "name", "role", "enabled", "verdicts", "ok",
                  "diff_big", "rejected", "decisions"):
            need(k in r, "Reviewer.%s（%s）" % (k, r.get("name", "?")))
    need(all(isinstance(r["verdicts"], int) for r in items), "工作量计数是整数")
    names = [r["name"] for r in items]
    need(len(names) == len(set(names)), "审核人姓名不重复（一人一身份）",
         str(names))

    # 新增 → 校验 → 删除
    tmp = {"name": "__契约测试临时人__", "role": "测试", "enabled": True}
    created = post("reviewers", tmp)
    need(created.get("name") == tmp["name"], "新增审核人成功")
    need(bool(created.get("id")), "新增返回稳定 id", "id=%r" % created.get("id"))
    tmp_id = created["id"]

    after = get("reviewers")["items"]
    need(any(x["id"] == tmp_id for x in after), "新审核人出现在名单里")

    # 改名（upsert 语义）
    post("reviewers", {"id": tmp_id, "name": tmp["name"], "role": "测试改", "enabled": False})
    upd = [x for x in get("reviewers")["items"] if x["id"] == tmp_id]
    need(len(upd) == 1, "按 id 更新不产生重复身份", "(%d 条)" % len(upd))
    need(upd and upd[0]["role"] == "测试改", "角色已更新")
    need(upd and upd[0]["enabled"] is False, "停用状态已生效")

    # ★ 核心：不在名单里的审核人，裁决必须被拒（HTTP 400）
    # 否则「配置」只是装饰品，用户绕过下拉框直接传个陌生名字就写进审计日志了。
    try:
        post("review/%s" % urllib.parse.quote(rel_pdf),
             {"verdict": "ok", "reviewer": "__不在名单里的人__", "note": ""},
             sid=sid)
        need(False, "★ 陌生审核人被拒绝（HTTP 400）", "竟然写进去了")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        need(e.code == 400, "★ 陌生审核人被拒绝（HTTP 400）", "code=%d" % e.code)
        need("审核人" in body, "错误提示指向「审核人配置」", body[:120])

    # 名单内审核人可以通过（用临时人）。
    # ⚠️ 裁决会**真的写进审计日志**，所以先记住原状态，测完必须原样还原 ——
    # 否则每跑一次契约测试，就给真实文件留下一条假裁决 + 一个临时审核人身份。
    before = get("review/%s" % urllib.parse.quote(rel_pdf)) or {}
    prev_state = {k: before.get(k) for k in
                   ("trust_state", "reviewer", "note", "rev_no")}
    ok_resp = post("review/%s" % urllib.parse.quote(rel_pdf),
                   {"verdict": "ok", "reviewer": tmp["name"], "note": "契约测试"},
                   sid=sid)
    need("rev_no" in ok_resp, "名单内审核人裁决成功（含 rev_no 审计号）")
    need(ok_resp.get("reviewer") == tmp["name"], "裁决记录了审核人姓名")

    # 还原裁决（撤销 → 回到未审；若原本有裁决则写回原值）
    post("review/%s" % urllib.parse.quote(rel_pdf),
         {"verdict": "", "reviewer": tmp["name"], "note": ""}, sid=sid)
    after_state = get("review/%s" % urllib.parse.quote(rel_pdf)) or {}
    need(after_state.get("trust_state") == prev_state.get("trust_state"),
         "★ 撤销后回到测试前的状态（不污染真实审计日志）",
         "(before=%r after=%r)" % (prev_state.get("trust_state"),
                                   after_state.get("trust_state")))

    # ★ 撤销裁决必须**同时清空审核人身份**。
    #   只清结论、留姓名 → 产生「审过但无结论」的幽灵记录，
    #   界面上显示未审，却给该审核人记了工作量，审计账目对不上。
    need(not (after_state.get("reviewer") or "").strip(),
         "★ 撤销后审核人身份被清空（不留幽灵记录）",
         "reviewer=%r" % after_state.get("reviewer"))
    need(not any(x["name"] == tmp["name"] and x["verdicts"] > 0
                 for x in get("reviewers")["items"]),
         "★ 撤销不计入该审核人工作量")
    need(not (get("review/%s" % urllib.parse.quote(rel_pdf)) or {}).get("reviewer"),
         "★ 撤销后不留无主空行（file_trust 行已删除）")

    # 若测试前本来就有裁决，写回原值（撤销会清空身份，故用真实审核人还原）
    if prev_state.get("trust_state"):
        restore = get("reviewers")["items"]
        who = prev_state.get("reviewer")
        pick = next((x["name"] for x in restore
                     if x["name"] == who and x["enabled"]), None)
        if pick:
            post("review/%s" % urllib.parse.quote(rel_pdf),
                 {"verdict": prev_state["trust_state"], "reviewer": pick,
                  "note": prev_state.get("note") or ""}, sid=sid)
    final_state = get("review/%s" % urllib.parse.quote(rel_pdf)) or {}
    need(final_state.get("trust_state") == prev_state.get("trust_state"),
         "★ 收尾：裁决状态与测试前完全一致",
         "(before=%r final=%r)" % (prev_state.get("trust_state"),
                                   final_state.get("trust_state")))
    need((final_state.get("reviewer") or "") == (prev_state.get("reviewer") or ""),
         "★ 收尾：审核人与测试前完全一致",
         "(before=%r final=%r)" % (prev_state.get("reviewer"),
                                   final_state.get("reviewer")))

    # 删除临时人
    d = delete("reviewers/%s" % urllib.parse.quote(tmp_id))
    need(d.get("ok") is True, "删除审核人成功")
    need(not any(x["id"] == tmp_id for x in get("reviewers")["items"]),
         "删除后从名单消失")

    # 删除不存在的 → 404
    try:
        delete("reviewers/__nope__")
        need(False, "删除不存在的审核人返回 404")
    except urllib.error.HTTPError as e:
        need(e.code == 404, "删除不存在的审核人返回 404", "code=%d" % e.code)

    # 删除最后一位必须被拒（否则裁决功能被锁死）
    cur = get("reviewers")["items"]
    if len(cur) == 1:
        try:
            delete("reviewers/%s" % urllib.parse.quote(cur[0]["id"]))
            need(False, "★ 拒绝删除最后一位审核人", "竟然删成功了")
        except urllib.error.HTTPError as e:
            need(e.code == 400, "★ 拒绝删除最后一位审核人", "code=%d" % e.code)
    else:
        need(len(cur) >= 1, "名单仍有人可用")

    # 空姓名 → 400
    try:
        post("reviewers", {"name": "   "})
        need(False, "空姓名被拒绝")
    except urllib.error.HTTPError as e:
        need(e.code == 400, "空姓名被拒绝（400）", "code=%d" % e.code)

    # ============ 6b. /review/batch 批量按阈值审核
    print("== 6b. /review/batch（阈值批量审核）==")
    # ★ 路由顺序回归：/review/batch 必须声明在 /review/{rel:path} 之前，
    #   否则字面量 "batch" 会被 {rel:path} 捕获并返回 422（前端完全不可用）。
    try:
        rr = post("review/batch", {"rels": [], "threshold": 90,
                                   "reviewer": (get("reviewers")["items"] or [{}])[0].get("name", "")})
        need(isinstance(rr.get("ok"), int), "★ /review/batch 可达（路由顺序正确，未被 {rel} 吞掉）")
        need(all(k in rr for k in ("ok", "skipped", "already", "no_score")),
             "批量返回四类计数")
    except urllib.error.HTTPError as e:
        need(False, "★ /review/batch 可达（路由顺序正确）", "HTTP %s" % e.code)

    # 非法阈值必须被拒（即使列表为空也要校验，否则前端拿到「成功」却什么都没做）
    try:
        post("review/batch", {"rels": [], "threshold": 150, "reviewer": "x"})
        need(False, "★ 非法阈值被拒绝（>100）")
    except urllib.error.HTTPError as e:
        need(e.code == 400, "★ 非法阈值被拒绝（>100）", "code=%d" % e.code)
    try:
        post("review/batch", {"rels": [], "threshold": -5, "reviewer": "x"})
        need(False, "★ 非法阈值被拒绝（<0）")
    except urllib.error.HTTPError as e:
        need(e.code == 400, "★ 非法阈值被拒绝（<0）", "code=%d" % e.code)

    # 陌生审核人必须被拒（批量审核同样要可审计）
    real_name = (get("reviewers")["items"] or [{}])[0].get("name", "")
    try:
        post("review/batch", {"rels": [rel_pdf], "threshold": 90,
                              "reviewer": "__不在名单里的人__"})
        need(False, "★ 批量审核拒绝陌生审核人")
    except urllib.error.HTTPError as e:
        need(e.code == 400, "★ 批量审核拒绝陌生审核人", "code=%d" % e.code)

    # ★ 绝不能用「没测过」的文件凑通过率：auto_score 为空的一律计入 no_score
    empty = post("review/batch", {"rels": ["__不存在的文件__.pdf"], "threshold": 90,
                                  "reviewer": real_name})
    need(empty.get("no_score", 0) >= 1,
         "★ 无自动分的文件被计入 no_score（不会被误判通过）",
         str(empty)[:120])

    # 阈值 100 时只有满分文件能通过；不存在的文件绝不能被写成 ok
    r100 = post("review/batch", {"rels": ["__不存在的文件2__.pdf"], "threshold": 100,
                                 "reviewer": real_name})
    need(r100.get("ok") == 0, "★ 不存在的文件不会被写成通过", str(r100)[:120])

    # ============ 7. /decision 同样受审核人名单约束（入库决定也要可审计）
    print("== 7. /decision 同样受审核人约束 ==")
    try:
        post("decision/%s" % urllib.parse.quote(rel_pdf),
             {"decision": "include", "reviewer": "__不在名单里的人__", "note": ""},
             sid=sid)
        need(False, "★ 陌生审核人的入库决定被拒绝")
    except urllib.error.HTTPError as e:
        need(e.code == 400, "★ 陌生审核人的入库决定被拒绝（400）", "code=%d" % e.code)

    # ================================================ 8. /preview/meta 能力探测
    print("== 8. /preview/meta（左栏始终显示源文件）==")
    for exts, label in (({".pdf"}, "PDF"), ({".png", ".jpg"}, "图片"),
                        ({".dwg", ".dxf"}, "CAD"), ({".xlsx"}, "表格"),
                        ({".msg"}, "邮件")):
        rel = pick_sample(sid, exts)
        if not rel:
            print("  skip  %s（库里无样本）" % label)
            continue
        info = get("preview/meta", sid=sid, rel=rel)
        need("kind" in info and "pages" in info, "PreviewResp(meta) %s" % label,
             "kind=%s" % info.get("kind"))
        need(info.get("kind") != "missing", "meta %s 未误报 missing" % label)

    # ================================================= 9. /preview 内容合法性
    print("== 9. /preview（左栏渲染内容）==")
    VALID = {"image", "html", "text", "unsupported", "missing", "list"}
    for exts, label in (({".pdf"}, "PDF"), ({".png", ".jpg"}, "图片"),
                        ({".dwg", ".dxf"}, "CAD"), ({".xlsx"}, "表格"),
                        ({".pptx"}, "PPT"), ({".docx"}, "Word"),
                        ({".msg"}, "邮件"), ({".zip"}, "ZIP")):
        rel = pick_sample(sid, exts)
        if not rel:
            print("  skip  %s（库里无样本）" % label)
            continue
        c = get("preview", sid=sid, rel=rel, page=1)
        need(c.get("kind") in VALID, "preview.kind 合法 · %s" % label,
             "= %r" % c.get("kind"))
        if c.get("kind") == "html":
            need(isinstance(c.get("html"), str), "preview.html 是字符串 · %s" % label)
        if c.get("kind") == "text":
            need(isinstance(c.get("text"), str), "preview.text 是字符串 · %s" % label)
        if c.get("kind") == "unsupported":
            need(bool(c.get("note")), "unsupported 必须给 note · %s" % label)
        # 左栏图片渲染地址可用
        if c.get("kind") == "image":
            try:
                with urllib.request.urlopen(
                        "%s/preview/img?%s" % (BASE, urllib.parse.urlencode(
                            {"sid": sid, "rel": rel, "page": 1, "dpi": 110})),
                        timeout=180) as r:
                    need(r.status == 200 and len(r.read()) > 500,
                         "preview/img 出图 · %s" % label)
            except Exception as e:
                need(False, "preview/img 出图 · %s" % label, repr(e)[:100])

    # ======================================================= 10. 边界与降级
    print("== 10. 边界：文件不存在 / 非法 sid ==")
    c = get("preview", sid=sid, rel="__not_exist__/x.pdf")
    need(c.get("kind") in ("missing", "unsupported"), "不存在文件不报错",
         "kind=%s" % c.get("kind"))
    m = get("md", sid=sid, rel="__not_exist__/x.pdf")
    need(m.get("missing") is True, "不存在文件 md.missing=True")
    need(m.get("lines") == [], "不存在文件 md.lines 为空")
    a = get("align", sid=sid, rel="__not_exist__/x.pdf")
    need(a.get("not_applicable") is True, "不存在文件 align 标记不可比对")
    # 不可比对时也必须返回同构的键（status/src_page 为空数组），
    # 否则前端读 align.status 得到 undefined，界面会空白而不是提示「无需比对」。
    need("status" in a and "src_page" in a,
         "不可比对时仍返回 status/src_page 键（契约同构）",
         "keys=%s" % sorted(a.keys()))
    need(a.get("status") == [] and a.get("src_page") == [],
         "不可比对时不返回脏下标")
    need(bool(a.get("reason")), "不可比对时给出人话原因（前端要如实告知）")
    need("lines" not in a, "不可比对时不再用旧的 lines 键（旧设计残留）")
    k = get("marks", sid=sid, rel="__not_exist__/x.pdf", page=1)
    need(k.get("supported") is False, "不存在文件 marks 降级")

    # 非法 sid → 404（不是 500）
    for path, params in (("tree", {"sid": "__nope__"}),
                         ("align", {"sid": "__nope__", "rel": "x.pdf"}),
                         ("marks", {"sid": "__nope__", "rel": "x.pdf"})):
        try:
            get(path, **params)
            need(False, "非法 sid 时 /%s 返回 404" % path)
        except urllib.error.HTTPError as e:
            need(e.code == 404, "非法 sid 时 /%s 返回 404（不是 500）" % path,
                 "code=%d" % e.code)

    # ============================================= 11. 源码级防回归（静默丢数据）
    print("== 11. 源码级防回归 ==")

    mdp = read_src("components", "MdPane.tsx")
    if mdp is None:
        print("  skip  源码检查（未找到 web/src/components/MdPane.tsx）")
    else:
        # ★ 曾经的真实缺陷：n = Math.min(lines.length, status.length || lines.length)
        #   让 3 万行的 md 只渲染前 6000 行，其余静默消失。
        #   必须遍历 md 的全部行，超出比对上限的行标 nocmp（中性灰）。
        need("Math.min(lines.length" not in mdp,
             "★ MdPane 不再按 min(md行, 状态行) 截断（防静默丢数据）")
        need('"nocmp"' in mdp, "★ MdPane 有独立的 nocmp（未比对）中性态")
        need("i < compared" in mdp, "★ MdPane 按下标判断是否已比对（前缀语义）")
        need("not_applicable" in mdp,
             "MdPane 对不可比对有明确提示")
        # ★ 用户 2026-10-05：右栏顶部那条「本次比对 N 行 / 其余未比对」的整幅
        #   黄色横幅太抢眼、挤掉正文高度，要求去掉。但**不能连说明一起删掉** ——
        #   灰色「未比对」行如果没有任何解释，就成了静默的数据缺失。
        #   正确形态：横幅消失，图例里的 nocmp chip 常驻，完整文案降级为 title 悬停。
        # 因此这里守两件事：(1) 横幅不得复活；(2) 文案必须仍然挂在 chip 上。
        # 判定方式：compare.truncated 在整个文件里**只能出现一次**，
        # 且必须出现在 title= 里 —— 出现在 callout 里就是横幅复活了。
        _trunc = "t(\"compare.truncated\""
        _n_trunc = mdp.count(_trunc)
        need(_n_trunc == 1,
             "★ 截断说明只保留一处（横幅已下线，不重复展示）",
             "(出现 %d 次)" % _n_trunc)
        _ti = mdp.find("title={" + _trunc)
        _ci = mdp.find("nocmp-chip")
        need(_ti != -1 and _ci != -1 and _ti > _ci,
             "★ 截断说明降级到 nocmp 图例 chip 的悬停 title（不静默隐藏数据）",
             "(chip@%d, title@%d)" % (_ci, _ti))
        need("callout warn edge" in mdp and "compare.notApplicable" in mdp,
             "不可比对仍保留独立提示（与截断是两件事）")

    appx = read_src("App.tsx")
    if appx is not None:
        need("SourcePane" in appx and "MdPane" in appx,
             "App 同时挂载左栏源文件与右栏 md")
        need("showMarks" in appx, "左栏高亮开关已接入（左栏打绿底）")
        need("statsbar" in appx, "统计信息独立成行（.statsbar）")
        need("FileTree" in appx, "侧栏使用目录树组件")
        need("ReviewerPanel" in appx, "审核人配置面板已接入")
        # 自由输入框不应再直接决定审核人身份
        need("<input" in appx, "App 仍有输入框（搜索/备注等）")

    treex = read_src("components", "FileTree.tsx")
    if treex is not None:
        need("tchildren" in treex or "trow" in treex,
             "FileTree 渲染目录层级（保留原结构）")

    sp = read_src("components", "SourcePane.tsx")
    if sp is not None:
        need("marks" in sp, "SourcePane 调用 /marks（左栏坐标高亮的数据源）")
        need("previewImg" in sp, "SourcePane 渲染源文件图像")
        need("supported" in sp, "SourcePane 处理 marks 不支持的格式")
        # 2026-10-05 新增能力：缩放、滚动翻页联动、相邻页预取
        need("zoom" in sp and "onZoom" in sp, "★ 左栏支持缩放（用户第 8 项）")
        need("onScroll" in sp and "goto(page + 1)" in sp,
             "★ 左栏滚动到底自动翻页（用户第 2 项：左右绑定）")
        need("PREFETCH" in sp and "new Image()" in sp,
             "★ 左栏预取相邻页，翻页不卡（用户第 2 项：预加载）")
        need("pane-path" in sp, "★ 左栏显示完整文件路径（用户第 4 项）")
        need("focusMark" in sp, "★ 左栏支持被右栏反向选中（用户第 9 项）")

    mdp2 = read_src("components", "MdPane.tsx")
    if mdp2 is not None:
        # 虚拟滚动：3 万行 md 若全量渲染会卡死浏览器
        need("OVERSCAN" in mdp2 and "rowRefs" in mdp2.replace("rowRefs", "rowRefs") or "OVERSCAN" in mdp2,
             "★ MdPane 采用虚拟滚动 + 预加载缓冲（用户第 2 项：顺滑不卡）")
        need("firstIndexOfPage" in mdp2,
             "★ MdPane 按源文件页码联动定位（用户第 2 项：绑定翻页）")
        need("userScrolling" in mdp2,
             "★ MdPane 用户主动滚动时不抢滚动条（避免与翻页打架）")
        need("zoom" in mdp2, "★ 右栏支持缩放（用户第 8 项）")
        # ★ 静默丢数据的回归防线：绝不能按 min(lines, status) 截断渲染
        need("Math.min(lines.length" not in mdp2,
             "★ 右栏不按 min(md行,状态行) 截断（防大文件静默丢行）")

    if appx:
        need("useI18n" in appx or "useLang" in appx,
             "★ App 接入 i18n（用户第 1 项：中英切换）")
        need("LangProvider" in (read_src("main.tsx") or ""),
             "★ i18n Provider 已挂载（main.tsx）")
        need("reviewBatch" in appx, "★ App 接入批量审核（用户第 12 项）")
        need("threshold" in appx, "★ 批量审核阈值可配置（用户第 12 项）")

    i18 = read_src("i18n.tsx")
    if i18 is not None:
        need("zh" in i18 and "en" in i18, "★ i18n 同时提供中英文案")
        need("fidelity.lang" in i18, "★ 语言选择被持久化")

        # ★ 中英文案**逐 key 对齐**（用户 2026-10-05：所有涉及语言的地方都要有中英）
        # 之前只检查了「zh/en 都存在」，漏译的 key 照样能通过测试 ——
        # 结果设置页/弹窗里全是中文。这里真正解析出两边的 key 集合做差集。
        zh_keys = _dict_keys(i18, "zh")
        en_keys = _dict_keys(i18, "en")
        need(bool(zh_keys) and bool(en_keys), "★ i18n 词表可解析（zh/en）")
        only_zh = sorted(zh_keys - en_keys)
        only_en = sorted(en_keys - zh_keys)
        need(not only_zh, "★ 每个中文 key 都有英文翻译", "缺英文：%s" % ", ".join(only_zh[:12]))
        need(not only_en, "★ 每个英文 key 都有中文翻译", "缺中文：%s" % ", ".join(only_en[:12]))
        # 占位符必须一致：{n} 与 {total} 混用会让英文界面出现 "{n}" 这种裸露占位符
        bad_ph = [k for k in sorted(zh_keys & en_keys)
                  if set(_placeholders(i18, "zh", k)) != set(_placeholders(i18, "en", k))]
        need(not bad_ph, "★ 中英文占位符一致（不出现裸露 {n}）", "不一致：%s" % ", ".join(bad_ph[:12]))

    # ★ 界面文案不允许残留硬编码中文（用户 2026-10-05 第 5 项）
    # 白名单：注释、文件名/扩展名常量、以及「必须原样呈现」的源文内容。
    untranslated = _hardcoded_cjk()
    need(not untranslated, "★ 前端无硬编码中文界面文案（全部走 i18n）",
         "残留：%s" % " | ".join(untranslated[:8]))

    # ---- 本轮 5 项反馈的针对性回归 ----
    sp3 = read_src("components", "SourcePane.tsx")
    if sp3:
        need("WHEEL_PAGE_THRESHOLD" in sp3 and "wheelAcc" in sp3,
             "★ 滚轮可翻页（不依赖滚动条，图片比视口矮也能翻）")
        # ★ React 18 把 wheel 注册为 passive 监听器，onWheel 里的 preventDefault()
        #   会被浏览器忽略 —— 必须用原生 addEventListener 显式 passive:false。
        need("addEventListener(\"wheel\"" in sp3 and "passive: false" in sp3,
             "★ 滚轮用原生非 passive 监听器（React onWheel 的 preventDefault 会失效）")
        need("onWheel=" not in sp3,
             "★ 未使用 React onWheel 接管滚轮（会静默失效）")
        # ★★ 方向感知（2026-10-05 用户反馈「不能鼠标滚动来上下查看」的根因）。
        # 旧写法 `scrollable && !atBottom && !atTop` 只判断「在不在边缘」，
        # 不看滚动方向 → 位于页面顶部时向下滚也落进 preventDefault 分支被吞掉，
        # 表现为「滚轮完全失灵，只能拖滚动条」。
        # 正确语义：沿当前 deltaY 方向还有空间就必须放行。
        need("roomToScroll" in sp3 and "e.deltaY > 0 ? !atBottom" in sp3
             and "e.deltaY < 0 && !atTop" in sp3,
             "★ 滚轮方向感知：沿滚动方向还有空间时放行原生滚动（顶部下滚/底部上滚）")
        need("if (scrollable && roomToScroll)" in sp3,
             "★ 仅在「该方向无空间」时才接管滚轮")
        # ★ 翻页判定必须在 wheel 处理器内完成。
        # 旧实现把判定放在 onScroll 里，但边缘处已 preventDefault()，
        # scrollTop 不变 → 永远不触发 scroll 事件 → 滚轮翻页是死逻辑。
        # ⚠️ 断言必须匹配语句形态而非子串存在性：只查 "goto(page + 1)" 会被
        #    「onScroll 里也翻页」的写法骗过（那正是要防的死逻辑）。
        need("      if (wheelAcc.current > WHEEL_PAGE_THRESHOLD) {" in sp3
             and "        goto(page + 1);" in sp3
             and "      } else if (wheelAcc.current < -WHEEL_PAGE_THRESHOLD) {" in sp3
             and "        goto(page - 1);" in sp3,
             "★ 滚轮翻页判定在 wheel 处理器内（不依赖必然不触发的 scroll 事件）")
        need("  const onStageScroll = useCallback(() => {\n    wheelAcc.current = 0;\n  }, []);" in sp3,
             "★ 原生滚动仅清零累积量，不承担翻页判定（避免死逻辑）")
        # 翻页后必须清零累积量：否则一次长滑动（deltaY 累积到 3000）会连翻 7 页。
        # 只断言语句形态，不用出现次数 —— 键盘翻页处同样是 8 空格缩进的
        # `goto(page + 1);`，任何计数条件都会误判。
        need("      if (wheelAcc.current > WHEEL_PAGE_THRESHOLD) {\n        wheelAcc.current = 0;" in sp3
             and "      } else if (wheelAcc.current < -WHEEL_PAGE_THRESHOLD) {\n        wheelAcc.current = 0;" in sp3,
             "★ 翻页后清零滚轮累积量（防止一次长滑连翻多页）")
        need("PREFETCH_MARKS" in sp3 and "warmedMarks" in sp3,
             "★ 翻页预取 marks（最慢的接口，提前热好）")
        need("pv-loading" in sp3 and 't("pane.loadingPage")' in sp3,
             "★ 翻页时保留旧页并显示加载角标（不再整块闪白）")
        need("canvasW" in sp3 and "ResizeObserver" in sp3,
             "★ 缩放按实际像素生效（修复放大缩小无效）")
        need("ArrowRight" in sp3 and "PageDown" in sp3,
             "★ 支持键盘翻页（←/→/PageUp/PageDown/Home/End）")
        # meta 必须与 page 解绑，否则每次翻页都重跑 /preview/meta
        # 取 previewMeta 所在的整个 useEffect 体，看它的依赖数组里有没有 page。
        need(_effect_deps(sp3, "previewMeta") == {"rel", "sid"},
             "★ 页数 meta 只随文件变化，不随翻页重复请求",
             "实际依赖：%s" % sorted(_effect_deps(sp3, "previewMeta")))

    mdp3 = read_src("components", "MdPane.tsx")
    if mdp3:
        need("pageScoped" in mdp3 and "scoped" in mdp3,
             "★ 右栏支持按页显示（与左栏一页对一页）")
        need("md.scopeAll" in mdp3 and "md.scopePage" in mdp3,
             "★ 右栏可在「整篇 / 本页」间切换，且默认按页")
        need("md.pageCount" in mdp3,
             "★ 按页时显示「本页 N / 全篇 M」，不会静默隐藏数据")
        need("md.pageEmpty" in mdp3,
             "★ 本页无对应行时给出明确说明（不显示空白误导用户）")
        need("beyondCompareCap" in mdp3 and "md.pageBeyondCap" in mdp3,
             "★ 区分「本页超出比对上限」与「转换漏内容」（两者结论相反，不能混说）")
        need("canScope" in mdp3,
             "★ 无页码映射的格式自动退回整篇（不会变成空白页）")

    css3 = read_src("styles.css")
    if css3:
        need(".tree-file.sel.picked" in css3,
             "★ 修复选中+勾选并存时白字白底（文字不可见）")
        need("justify-content: center" not in css3.split(".pv-stage")[1][:400]
             if ".pv-stage" in css3 else True,
             "★ 缩放容器不再用 justify-content:center（溢出起始边无法滚动）")
        need("margin: auto" in css3, "★ 缩放容器用 margin:auto 居中，两侧都可平移")
        need(".pv-loading" in css3, "★ 翻页加载角标有对应样式")

    if treex:
        need("tree-resizer" in treex, "★ 目录树可左右拖拽调宽（用户第 7 项）")
        need("fidelity.tree.open" in treex, "★ 展开状态持久化（用户第 7 项）")
        need("expandAll" in treex or "act.expandAll" in treex,
             "★ 支持全部展开/折叠（用户第 7 项）")
        need("tcheck" in treex, "★ 目录树支持勾选多选（用户第 12 项）")
        need("useI18n" in treex, "★ FileTree 接入 i18n（含 FileRow 的勾选提示）")

    # ★ 所有弹窗/面板都必须接入 i18n（设置页、决定队列、重新转换、审核人、数据源、目录选择）
    for comp, label in (
        ("DecisionsPanel.tsx", "待决定队列"),
        ("SalvagePanel.tsx", "重新转换"),
        ("ReviewerPanel.tsx", "审核人配置"),
        ("SourceManager.tsx", "数据源管理"),
        ("FolderPicker.tsx", "目录选择"),
    ):
        src = read_src("components", comp)
        if src is not None:
            need("useI18n" in src, "★ %s 接入 i18n" % label)
            need("confirm(" not in src or "t(\"msg." in src or "confirm(t(" in src
                 or "confirm(\n" in src and "t(" in src,
                 "★ %s 的 confirm 文案已国际化" % label)

    # ---- 动态行高（修「md 文字显示不完整」）--------------------------
    # 根因：.tx 是 pre-wrap 会折行，但 JS 把每行 height 写死 → 第 2 行被压掉。
    # 这组断言的作用是**防止有人把它「优化」回固定行高**。
    mdp = read_src("components", "MdPane.tsx") or ""
    css_all = read_src("styles.css") or ""
    if mdp:
        need("minHeight: rowH" in mdp,
             "★ md 行用 min-height 而非 height（折行文字不被压掉）")
        need("height: rowH," not in mdp and "height: rowH\n" not in mdp,
             "★ md 行未写死 height（写死会截断折行文字）")
        need("offsets[abs]" in mdp,
             "★ md 行定位用实测偏移表（折行后不再是 rowH 整数倍）")
        need("top: abs * rowH" not in mdp,
             "★ md 行未用 i*rowH 定位（折行会导致错位叠字）")
        need("offsetHeight" in mdp,
             "★ md 行高由 DOM 实测（offsetHeight）")
        need("Math.abs(prev - h) > 0.5" in mdp,
             "★ 高度回填有收敛保护（防止测量→重渲染→再测量 死循环）")
        need("heights.current.clear()" in mdp and "hKeyRef" in mdp,
             "★ 宽度/缩放变化时高度缓存失效（折行数会变）")
        need("firstAfter" in mdp and "while (lo < hi)" in mdp,
             "★ 视口首行用二分查找（前缀和偏移，O(log n)）")
        # off-by-one 守卫：第 k 行覆盖 [offsets[k], offsets[k+1])，
        # 覆盖 y 的行是 firstAfter(y)-1。写成 firstAfter(y) 会每屏少一行。
        need("offsets[mid] > y" in mdp,
             "★ 二分查找语义正确（找 offsets>y 的首个下标）")
        need("rowAt" in mdp and "firstAfter(y) - 1" in mdp,
             "★ 覆盖 y 的行取 firstAfter(y)-1（否则每屏顶部少一行）")
        need("startIdx = Math.max(0, rowAt(scrollTop) - OVERSCAN)" in mdp,
             "★ 视口首行经 rowAt 换算（未用未修正的下标）")
        # 只看真实代码行（剔除注释），否则会被解释性注释里的文字误伤
        code_only = "\n".join(
            ln for ln in mdp.splitlines()
            if not ln.strip().startswith(("*", "//", "/*"))
        )
        need("scrollTop / rowH" not in code_only,
             "★ 未用 scrollTop/rowH 反推行号（折行时算错）")
        need("heights.current.clear();\n      changed = true" not in mdp
             and "heights.current.clear(); changed = true" not in mdp,
             "★ 高度缓存不整表清空（会永久抖动：清空→重测→再超阈值）")
    if css_all:
        need(".pane-body.virtual .mdline" in css_all
             and "align-items: flex-start" in css_all,
             "★ md 行顶对齐（center 会让折行文字看着是歪的）")
        need("align-items: center" not in
             css_all.split(".pane-body.virtual .mdline")[1].split("}")[0],
             "★ 虚拟滚动行未用 align-items:center（与折行冲突）")
        # .tx 绝不能加省略号/裁剪 —— 用户要看到全文
        tx_rule = ""
        if ".mdline .tx" in css_all:
            tx_rule = css_all.split(".mdline .tx")[1].split("}")[0]
        need("text-overflow" not in tx_rule and "nowrap" not in tx_rule,
             "★ md 正文无省略号/裁剪（折行文字必须完整显示）")

    # ---- 两侧都必须显示源文件完整路径（用户 2026-10-05 反馈右栏缺路径）----
    # 比对场景下「左栏原文」与「右栏 md」必须能确认是同一份文件，
    # 因此两侧要显示**同一个** srcPath（不能各自算，避免不一致）。
    mdp = read_src("components", "MdPane.tsx") or ""
    # ⚠️ read_src 以 web/src 为根，App.tsx 就在根下 —— 传 ".." 会指向
    # web/App.tsx（不存在）→ 返回 None → 下面整块断言被静默跳过。
    app3 = read_src("App.tsx") or ""
    if mdp:
        need('<div className="pane-path truncate" title={srcPath || rel}>' in mdp,
             "★ 右栏 md 显示源文件完整路径（可确认与左栏是同一份文件）")
        need("{t(\"pane.path\")}" in mdp and "<span className=\"mono\">{srcPath || rel}</span>" in mdp,
             "★ 右栏路径复用左栏同一标记与文案（含悬停完整值）")
        need("(srcPath || rel) && (" in mdp,
             "★ 路径两者皆无时不渲染空行（srcPath 缺失回退 rel）")
    if app3:
        # ⚠️ 必须整段匹配：只查 "srcPath={srcPath}" 会被「只删掉这一行、
        #    留下 rel={sel}」的写法骗过（实测破坏测试确实漏过）。
        need("                      srcPath={srcPath}\n                      rel={sel}" in app3,
             "★ App 向 MdPane 同时传入 srcPath 与 rel（与 SourcePane 同一来源）")
    # 两处必须共用 App 里同一个 srcPath 变量，不能各自拼路径
    if app3 and "srcPath={srcPath}" in app3:
        need(app3.count("srcPath={srcPath}") >= 2,
             "★ 左右两栏共用同一 srcPath（各自拼路径会出现两侧不一致）")

    # ---- 侧栏树「全部展开 / 全部折叠」（用户 2026-10-05 指出是死按钮）----
    # 原实现：allOpen || openSet.has(d.name) —— 只短路一级目录，
    # 且用**目录名**当 key（实测 12 组同名目录，SS×13/DWG×12）互相串联。
    ft = read_src("components", "FileTree.tsx") or ""
    # 只看真实代码行：注释里会引用旧写法（allOpen/openSet）作为「之前错在哪」的说明，
    # 全文匹配会误伤自己写的解释。
    ft_code = "\n".join(
        ln for ln in ft.splitlines()
        if not ln.strip().startswith(("*", "//", "/*", "{/*"))
    )
    if ft:
        need("openSet" not in ft_code and "allOpen ||" not in ft_code,
             "★ 树不再用 allOpen 短路 / openSet（死按钮根因）")
        need("type OpenMap" in ft and "dirKey(" in ft,
             "★ 展开状态用 OpenMap + 完整路径 key（同名目录不串联）")
        need('parentKey + "/" + name' in ft or 'p + "/" + n' in ft
             or "return parentKey" in ft,
             "★ 目录 key 由父路径拼成（不是只有目录名）")
        need("const expandAll = useCallback" in ft and "const collapseAll = useCallback" in ft,
             "★ 全部展开/折叠是两个独立可用函数")
        need("for (const k of allDirKeys) next[k] = true;" in ft,
             "★ 全部展开遍历**所有**目录 key（真实全展开）")
        need("setOpenMap({});" in ft,
             "★ 全部折叠清空 map（不是设 false，残留 true 会让再展开失灵）")
        need("collectDirKeys" in ft and "flattenTree" in ft,
             "★ 树已扁平化（配合虚拟滚动支持 2002 行全展开）")
        need("OVERSCAN" in ft and "ROW_H" in ft and "rows.length * ROW_H" in ft,
             "★ 树用虚拟滚动（全展开 2002 行不卡）")
        # 必须是真切片：只断言 OVERSCAN 存在不够，
        # 把 slice 改成 rows（全量渲染）也必须被抓到。
        need("const slice = rows.slice(startIdx, endIdx);" in ft_code,
             "★ 树只渲染视口切片（slice = rows.slice(...)）")
        need("const endIdx = Math.min(rows.length," in ft_code,
             "★ 切片上界按视口高度计算（不是全量）")
        need("if (!q.trim() && !status) return;" in ft,
             "★ 搜索/筛选时自动展开（否则搜到了看不见）")
        need('onClick={expandAll}' in ft and 'onClick={collapseAll}' in ft,
             "★ 两个按钮各自绑定真实处理函数")
        need("paddingLeft: 6 + INDENT * depth" in ft,
             "★ 层级缩进用内联 paddingLeft（扁平化后无嵌套 DOM 可依赖）")
        # 旧版 localStorage 存的是 string[]（目录名），不迁移会让老用户
        # 刷新后展开状态全丢，且旧键可能误展开同名目录。
        # 注意要匹配 `if (Array.isArray(raw))` 整段，不能只查 "Array.isArray"
        # 是否出现 —— 把它改成 if (false) 就能骗过弱断言。
        need("if (Array.isArray(raw)) {" in ft_code,
             "★ 展开状态持久化兼容旧格式（旧 string[] 自动迁移）")
        need('out["/" + nm] = true;' in ft_code,
             "★ 旧目录名迁移为顶层完整路径 key（不误展开同名目录）")
    ft_css = read_src("styles.css") or ""
    if ft_css:
        trow = ""
        if ".trow {" in ft_css:
            trow = ft_css.split(".trow {")[1].split("}")[0]
        need("height: 24px" in trow,
             "★ .trow 行高固定 24px（与 ROW_H 一致，否则虚拟滚动错位）")
        # 同理剔除 CSS 注释（注释里会说明「已移除 xxx」）
        css_code = "\n".join(
            ln for ln in ft_css.splitlines()
            if not ln.strip().startswith(("*", "//", "/*"))
        )
        need(".tchildren" not in css_code,
             "★ 已移除 .tchildren 嵌套缩进（随递归组件废弃）")

    print()
    print("=" * 56)
    if FAILS:
        print("契约检查失败 %d / %d 项：" % (len(FAILS), CHECKS[0]))
        for f in FAILS:
            print("  -", f)
        return 1
    print("契约检查全部通过：%d / %d" % (CHECKS[0], CHECKS[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
