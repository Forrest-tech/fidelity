# -*- coding: utf-8 -*-
"""前端渲染契约测试：核对 UI 实际依赖的每个 API 字段是否齐备、类型正确。

为什么需要这个：浏览器截图在本机沙箱里连不上本地端口（ERR_CONNECTION_REFUSED），
无法做像素级验收。改用「契约测试」——把 App.tsx / SourcePreview.tsx 里读到的
每一个字段都在真实 API 响应里核对一遍。字段缺失会让界面空白或报 undefined，
这正是 UI bug 的主要来源。

用法：python scripts/ui_contract_check.py
"""
import io
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config  # noqa: E402

BASE = "http://127.0.0.1:8000/api"
FAILS = []
CHECKS = [0]


def get(path, **params):
    q = urllib.parse.urlencode(params)
    url = "%s/%s%s" % (BASE, path, ("?" + q) if q else "")
    with urllib.request.urlopen(url, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def need(cond, label, extra=""):
    CHECKS[0] += 1
    if not cond:
        FAILS.append("%s %s" % (label, extra))
        print("  FAIL  %s %s" % (label, extra))
    else:
        print("  ok    %s" % label)


def pick_sample(sid, exts, want_flags=None):
    """从库里挑一个真实文件（按扩展名）。"""
    src = config.get_source(sid)
    root = src["src_root"]
    for r, d, fs in os.walk(root):
        for f in fs:
            if os.path.splitext(f)[1].lower() in exts:
                return os.path.relpath(os.path.join(r, f), root).replace("\\", "/")
    return None


def main():
    sid = "n2"
    print("== 1. /stats（顶栏总览）==")
    st = get("stats", sid=sid)
    for k in ("total", "evaluated", "avg_score", "reviewed", "deferred"):
        need(k in st, "stats.%s" % k)
    need(isinstance(st.get("by_state"), dict), "stats.by_state 是对象")
    need(isinstance(st.get("decisions"), dict), "stats.decisions 是对象")
    for k in ("pending", "include", "exclude"):
        need(k in (st.get("decisions") or {}), "stats.decisions.%s" % k)
    t = st.get("totals") or {}
    for k in ("files", "src_chars", "md_chars", "src_words", "md_words",
              "char_ratio", "word_ratio"):
        need(k in t, "stats.totals.%s" % k)
    print("  totals: 源 %s 字 → md %s 字（保留 %s%%）"
          % (t.get("src_chars"), t.get("md_chars"), t.get("char_ratio")))

    print("== 2. /files（侧边栏列表 Badge 字段）==")
    fl = get("files", sid=sid, status="")
    files = fl["files"]
    need(len(files) > 0, "files 非空", "(%d)" % len(files))
    b = files[0]
    for k in ("rel", "state", "label", "badge", "auto_score", "trust_state", "reviewer"):
        need(k in b, "Badge.%s" % k)
    # 字数字段：对**已评测**的文件必须存在且为整数。
    # （未评测的文件 auto_score/src_chars 本来就是 null，属正常状态，
    #   不能拿列表第一行当断言对象 —— 它恰好可能是未评测的。）
    need(any("src_chars" in x for x in files), "Badge 含 src_chars 字段")
    scored = [x for x in files if x.get("auto_score") is not None]
    need(len(scored) > 0, "存在已评测文件（auto_score 非空）", "(%d)" % len(scored))
    bad = [x["rel"] for x in scored
           if not isinstance(x.get("src_chars"), int)
           or not isinstance(x.get("md_chars"), int)]
    need(not bad, "已评测文件的字数字段均为整数",
         "异常 %d 个，例：%s" % (len(bad), bad[0][-40:] if bad else ""))


    print("== 3. /md（右栏 md 原文 MdResp 字段）==")
    rel_pdf = pick_sample(sid, {".pdf"})
    md = get("md", sid=sid, rel=rel_pdf)
    for k in ("rel", "text", "missing", "chars", "words"):
        need(k in md, "MdResp.%s" % k)
    need("salvage" in md, "MdResp.salvage")
    need(md["chars"] >= 0 and md["words"] >= 0, "MdResp 字数非负")
    print("  样本 %s：%d 字 / %d 词" % (rel_pdf.split("/")[-1][:36], md["chars"], md["words"]))

    print("== 4. /diff（逐行比对 DiffResp 字段）==")
    df = get("diff", sid=sid, rel=rel_pdf, page=1, per_page=5, only_diff="false")
    for k in ("rel", "not_applicable", "segments", "total", "page", "pages",
              "src_chars", "md_chars", "src_words", "md_words", "by_status", "verdict"):
        need(k in df, "DiffResp.%s" % k)
    seg = (df.get("segments") or [{}])[0]
    for k in ("status", "src", "md", "src_no", "md_no"):
        need(k in seg, "Segment.%s" % k)
    need(seg.get("status") in ("match", "src_only", "md_only", "changed"),
         "Segment.status 合法", "= %r" % seg.get("status"))
    # 行长度上限（防浏览器崩）
    longest = max((len(s.get("src") or "") for s in df.get("segments") or []), default=0)
    need(longest <= 20100, "单行已截断保护", "(max=%d)" % longest)

    print("== 5. /preview/meta（SourcePreview 能力探测）==")
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

    print("== 6. /preview（内容 kind 合法性）==")
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

    print("== 7. 边界：文件不存在 / 非法 sid ==")
    c = get("preview", sid=sid, rel="__not_exist__/x.pdf")
    need(c.get("kind") in ("missing", "unsupported"), "不存在文件不报错",
         "kind=%s" % c.get("kind"))
    m = get("md", sid=sid, rel="__not_exist__/x.pdf")
    need(m.get("missing") is True, "不存在文件 md.missing=True")

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
