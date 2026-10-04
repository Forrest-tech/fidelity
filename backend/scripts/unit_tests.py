# -*- coding: utf-8 -*-
"""核心算法单元测试（compare.py）。

为什么必须有这个文件（用户 2026-10-04 要求）：
此前项目**只有一个** `ui_contract_check.py`，它验证的是「接口字段对不对」，
完全不覆盖评分算法本身。也就是说：评分公式改一行、归一化改一行、
数字正则改一行 —— 74 项契约测试**照样全绿**，而知识库的入库判定已经错了。
这类静默劣化对「零幻觉、可信检索」是致命的。

本文件锁定以下行为的**当前事实**：
  1. 归一化与 .md 伪影剥离（含那些**故意不剥**的例外，它们是假差异的边界）
  2. 行对齐四态 match / src_only / md_only / changed
  3. 数字保真（OCR 最易错的地方：25mm → 2Smm）
  4. 词级覆盖率与自动评分公式
  5. 字数统计（CJK 按字 + 拉丁按词）
  6. 重复内容检测
  7. 分页与极端输入不崩

⚠️ 本文件**不修改任何业务逻辑**。若某条断言失败，先判断：是要修 bug，
还是当初的设计决定被误当成 bug —— 后者应改测试并写清理由，绝不能盲改算法。

运行：  python scripts/unit_tests.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import compare as C  # noqa: E402


# ------------------------------------------------------------------ 迷你测试框架
class Fail(Exception):
    pass


_RESULTS = []


def check(name, cond, detail=""):
    if cond:
        _RESULTS.append((name, True, ""))
    else:
        _RESULTS.append((name, False, detail))


def eq(name, got, want):
    check(name, got == want, "got=%r want=%r" % (got, want))


def near(name, got, want, tol=0.05):
    ok = got is not None and abs(got - want) <= tol
    check(name, ok, "got=%r want=%r±%s" % (got, want, tol))


# ================================================================== 1. 归一化
def test_normalize():
    print("\n== 1. normalize_line 归一化 ==")
    eq("折叠内部空白", C.normalize_line("a   b\t\tc"), "a b c")
    eq("去首尾空白", C.normalize_line("   hello   "), "hello")
    eq("转小写", C.normalize_line("Hello WORLD"), "hello world")
    eq("None 安全", C.normalize_line(None), "")
    eq("空串", C.normalize_line(""), "")


# ============================================================== 2. md 伪影剥离
def test_strip_md():
    print("\n== 2. strip_md_artifacts 伪影剥离 ==")

    # front-matter 必须整体剥掉
    md = "---\ntitle: X\nunit: 22mm\n---\nReal content here"
    out = C.strip_md_artifacts(md)
    check("front-matter 被剥离", "title: X" not in out and "Real content here" in out,
          repr(out))

    # HTML 注释开闭标签都要剥（只剥开标签会漏闭标签）
    md2 = "A\n<!-- unit: 3 -->\nB\n<!-- /unit -->\nC"
    out2 = C.strip_md_artifacts(md2)
    check("HTML 注释开闭标签均被剥离",
          "unit: 3" not in out2 and "/unit" not in out2 and "C" in out2, repr(out2))

    # --- 排版标记应被剥离（假差异的经典来源）---
    cases = [
        ("- 600X600 ACCESS CHAMBER", "600X600 ACCESS CHAMBER"),
        ("* bullet item", "bullet item"),
        ("+ plus item", "plus item"),
        ("> quoted text", "quoted text"),
        ("## Heading two", "Heading two"),
        ("###### Deep heading", "Deep heading"),
        ("1. ordered item", "ordered item"),
        ("**bold text**", "bold text"),
        ("*italic text*", "italic text"),
        ("~~struck text~~", "struck text"),
    ]
    for raw, want in cases:
        got = C.strip_md_artifacts(raw)
        eq("剥离行首/行内标记 %r" % raw, got, want)

    # 叠加：- **Term** - definition
    eq("列表+粗体叠加", C.strip_md_artifacts("- **Term** - definition"), "Term - definition")

    # 表格竖线 → 空格
    eq("表格行转空格", C.strip_md_artifacts("| a | b |"), "a b")

    # 表格对齐行整行丢弃
    out3 = C.strip_md_artifacts("|---|---|\n| x | y |")
    check("表格对齐行被丢弃", "---" not in out3, repr(out3))

    # 代码围栏内保持原样
    fence = "before\n```\n- keep *this*\n```\nafter"
    outf = C.strip_md_artifacts(fence)
    check("代码围栏内容保留", "- keep *this*" in outf, repr(outf))

    # --- 以下是「故意不剥」的例外（剥了会丢真实内容 = 另一种假差异）---
    keeps = [
        "12) Check the cover",          # 右括号编号是技术规范里的真实编号
        "A_B_C valve",                   # 下划线在技术文档极常见
        "2_5 mm",                        # 同上
    ]
    for raw in keeps:
        eq("故意保留 %r" % raw, C.strip_md_artifacts(raw), raw)

    # 尺寸 vs 列表：2.5m 是尺寸不是列表
    eq("2.5m 不被当列表", C.strip_md_artifacts("2.5m clearance"), "2.5m clearance")
    eq("2. item 是列表", C.strip_md_artifacts("2. item"), "item")

    # 空输入
    eq("空串安全", C.strip_md_artifacts(""), "")
    eq("None 安全", C.strip_md_artifacts(None), "")


# ================================================================ 3. 打捞检测
def test_salvage():
    print("\n== 3. md_is_salvage 打捞检测 ==")
    check("识别 parser: salvage", C.md_is_salvage("---\nparser: salvage\n---\nAC1032"))
    check("识别 salvage:001", C.md_is_salvage("salvage:001"))
    check("正常 md 不误判", not C.md_is_salvage("# Title\nReal content"))
    check("空输入不误判", not C.md_is_salvage(""))
    check("None 不误判", not C.md_is_salvage(None))


# ================================================================== 4. 行对齐
def test_align():
    print("\n== 4. align_lines 行对齐 ==")

    # 全等 → 全部 match
    segs = C.align_lines(["a", "b", "c"], ["a", "b", "c"])
    eq("全等 match 数", sum(1 for s in segs if s["status"] == "match"), 3)

    # 源有 md 无 → src_only
    segs = C.align_lines(["a", "MISSING"], ["a"])
    st = [s["status"] for s in segs]
    check("源有 md 无 = src_only", "src_only" in st, st)

    # md 有源无 → md_only
    segs = C.align_lines(["a"], ["a", "EXTRA"])
    st = [s["status"] for s in segs]
    check("md 有源无 = md_only", "md_only" in st, st)

    # 相似但不同 → changed（OCR 改写场景）
    segs = C.align_lines(
        ["Pipes shall be 25 mm diameter"],
        ["Pipes shall be 2S mm diameter"],
    )
    st = [s["status"] for s in segs]
    check("OCR 改写识别为 changed", "changed" in st, st)

    # 大小写/空白差异不应算差异（归一化后应 match）
    segs = C.align_lines(["Fire Hydrant"], ["  fire   HYDRANT  "])
    eq("大小写空白差异=match", segs[0]["status"], "match")

    # 空行不产出假差异
    segs = C.align_lines(["a", "", "b"], ["a", "", "b"])
    eq("空行不产生差异", sum(1 for s in segs if s["status"] != "match"), 0)

    # 重复行按出现次数配对
    segs = C.align_lines(["x", "x"], ["x", "x"])
    eq("重复行一一配对", sum(1 for s in segs if s["status"] == "match"), 2)

    # 极端输入不能崩
    for a, b in [([], []), (["a"], []), ([], ["b"]), (["", ""], ["", ""]),
                 (["a"] * 50, ["b"] * 50)]:
        try:
            C.align_lines(a, b)
            check("极端输入不崩 %r/%r" % (a[:2], b[:2]), True)
        except Exception as e:
            check("极端输入不崩 %r/%r" % (a[:2], b[:2]), False, repr(e))

    # 超长单行不能崩（曾导致响应失稳）
    try:
        r = C.align_lines(["x" * 200000], ["x" * 199000])
        check("超长单行不崩", isinstance(r, list))
    except Exception as e:
        check("超长单行不崩", False, repr(e))

    # 输出必须按源文阅读顺序（分屏逐行可读）
    src = ["l1", "l2", "l3", "l4", "l5"]
    md = ["l1", "l2", "MISSING3", "l4", "l5"]
    segs = C.align_lines(src, md)
    src_nos = [s["src_no"] for s in segs if s["src_no"] is not None]
    eq("按源文顺序输出", src_nos, sorted(src_nos))

    # 每个 segment 必须有合法 status（前端依赖这个枚举）
    segs = C.align_lines(["a", "b"], ["a", "c", "d"])
    ok = {"match", "src_only", "md_only", "changed"}
    check("status 枚举合法", all(s["status"] in ok for s in segs),
          [s["status"] for s in segs])


# ============================================================== 5. 数字保真
def test_numbers():
    print("\n== 5. extract_numbers / number_fidelity ==")

    eq("抽数字+单位", C.extract_numbers("25 mm and 300mm"),
       __import__("collections").Counter({"25mm": 1, "300mm": 1}))
    # 千分位（2026-10-04 修复的真实缺陷）：
    # 早期把逗号一律当小数点，`1,000 L` 归一成 `1.000l`，
    # 于是「md 把 1,000 误写成 1.000」这种数字错误反而被判成保真率 1.0。
    eq("千分位 1,000 → 1000", dict(C.extract_numbers("1,000 mm")), {"1000mm": 1})
    eq("千分位 1,234,567", dict(C.extract_numbers("1,234,567 L")),
       {"1234567l": 1})
    # 非千分位形态：逗号仍当小数点（欧式写法 0,25）
    eq("非千分位逗号=小数点", dict(C.extract_numbers("0,25 mm")), {"0.25mm": 1})
    # 核心回归：千分位被 OCR 改错，必须被抓出来
    near("千分位误写 → 保真率 0",
         C.number_fidelity("Tank capacity 1,000 L", "Tank capacity 1.000 L"), 0.0)
    # 无数字 → 空
    eq("无数字抽空", dict(C.extract_numbers("no digits here")), {})
    # 空输入安全
    eq("空串安全", dict(C.extract_numbers("")), {})
    eq("None 安全", dict(C.extract_numbers(None)), {})

    # 完全保真
    near("完全保真=1.0", C.number_fidelity("25 mm", "25 mm"), 1.0)
    # OCR 典型错误：25mm → 2Smm，数字全错
    f = C.number_fidelity("25 mm and 300 mm", "2S mm and 3OO mm")
    check("OCR 数字全错 → 保真率 0", f == 0.0, "got=%r" % f)
    # 一半对一半错
    f2 = C.number_fidelity("25 mm and 300 mm", "25 mm and 3OO mm")
    check("半错 → 保真率约 0.5", f2 is not None and 0.4 <= f2 <= 0.6, "got=%r" % f2)
    # 源无数字 → None（不适用），这是接口契约
    eq("源无数字返回 None", C.number_fidelity("abc def", "abc def"), None)


# ============================================================ 6. 覆盖率与评分
def test_coverage_score():
    print("\n== 6. token_coverage / evaluate 评分 ==")
    from collections import Counter

    eq("token 计数", C.token_counter("a b a"), Counter({"a": 2, "b": 1}))
    eq("token 计数空", C.token_counter(""), Counter())
    eq("token 计数 None", C.token_counter(None), Counter())

    near("完全覆盖", C.token_coverage("fire hydrant", "fire hydrant"), 1.0)
    near("部分覆盖", C.token_coverage("fire hydrant valve", "fire hydrant"), 2 / 3)
    eq("源无 token 返回 None", C.token_coverage("...", "..."), None)

    # 评分公式：S = 0.5*coverage + 0.5*num_fidelity
    r = C.evaluate("Pipes shall be 25 mm", "Pipes shall be 25 mm")
    eq("全等=100 分", r["auto_score"], 100.0)

    # 数字全错 → 分数应显著低于 100
    r2 = C.evaluate("Pipes shall be 25 mm", "Pipes shall be 2S mm")
    check("数字错 → 分数下降", r2["auto_score"] < 100, r2["auto_score"])

    # 空输入 → auto_score 必须是 None（前端据此显示「无法评分」）
    eq("空输入评分为 None", C.evaluate("", "")["auto_score"], None)
    # 源空 md 有内容
    eq("源空评分为 None", C.evaluate("", "some content")["auto_score"], None)
    # md 为空 → coverage 0 → 0 分（不崩）
    r3 = C.evaluate("content here", "")
    check("md 空 → 0 分不崩", r3["auto_score"] == 0.0, r3["auto_score"])

    # evaluate 返回结构完整性（routes.py 依赖这些键）
    r4 = C.evaluate("a", "a")
    need = ["auto_score", "coverage", "line_match_ratio", "number_fidelity",
            "engine_b", "n_src_lines", "n_md_lines", "src_chars", "md_chars",
            "src_words", "md_words", "n_match", "n_src_only", "n_md_only",
            "n_changed", "_segments"]
    miss = [k for k in need if k not in r4]
    check("evaluate 返回字段完整", not miss, miss)

    # 数字保真为 None 时用 coverage 兜底（不能因 None 而崩）
    r5 = C.evaluate("alpha beta", "alpha beta")
    eq("无数字时覆盖率兜底", r5["auto_score"], 100.0)


# ================================================================ 7. 字数统计
def test_count():
    print("\n== 7. count_text 字数统计 ==")
    r = C.count_text("消防 hydrant 25mm")
    eq("中文字数", r["cjk"], 2)
    eq("拉丁词数", r["latin"], 2)
    eq("总字数=中+拉", r["words"], 4)
    eq("字符数", r["chars"], len("消防 hydrant 25mm"))

    eq("空串", C.count_text("")["words"], 0)
    eq("None 安全", C.count_text(None)["words"], 0)
    eq("纯中文", C.count_text("消防栓")["words"], 3)
    # 英文按**词**计，不按字母计：3 个空格分隔的词 = 3
    eq("英文按词计", C.count_text("fire hydrant valve")["words"], 3)
    # 连字符算一个词
    eq("连字符算一个词", C.count_text("therm-o-matic")["words"], 1)


# ============================================================ 8. 重复内容检测
def test_dup():
    print("\n== 8. dup_ratio 重复内容检测 ==")
    eq("空文本", C.dup_ratio(""), 0.0)
    eq("无重复", C.dup_ratio("line one\nline two\nline three"), 0.0)
    # 需求：某 token 在同一行出现 >=4 次且行长 >6 token 才算重复膨胀
    # （短行如页码、编号反复出现是正常的，不能误报）
    one = "thermostatic mixing valve " * 4          # 12 token，同词 4 次
    check("检测到重复膨胀", C.dup_ratio(one) > 0, C.dup_ratio(one))
    # 同词只出现 2 次 → 正常，不算膨胀
    two = "thermostatic mixing valve thermostatic mixing valve"   # 6 token
    eq("重复 2 次不算膨胀", C.dup_ratio(two), 0.0)
    # 短行（<=6 token）即使重复 4 次也不计入
    eq("短行不计入", C.dup_ratio("ab ab ab ab ab ab"), 0.0)
    # 全篇膨胀 → 比率为 1.0
    eq("整篇膨胀=1.0", C.dup_ratio(one * 5), 1.0)
    eq("None 安全", C.dup_ratio(None), 0.0)


# ================================================================== 9. 分页
def test_page():
    print("\n== 9. page 分页 ==")
    segs = [{"status": "match"}] * 100
    got, total, pages = C.page(segs, page=1, per_page=10)
    eq("第1页条数", len(got), 10)
    eq("总数", total, 100)
    eq("总页数", pages, 10)

    got2, _, _ = C.page(segs, page=10, per_page=10)
    eq("末页条数", len(got2), 10)

    # 越界页不能崩，返回空
    got3, _, _ = C.page(segs, page=999, per_page=10)
    eq("越界页返回空", len(got3), 0)

    # 空 segments
    eq("空输入", C.page([], page=1)[1], 0)

    # only_diff 过滤
    segs2 = [{"status": "match"}, {"status": "src_only"}, {"status": "changed"}]
    got4, total4, _ = C.page(segs2, only_diff=True)
    eq("only_diff 过滤条数", total4, 2)

    # per_page=0 不能死循环/崩
    try:
        C.page(segs, page=1, per_page=0)
        check("per_page=0 不崩", True)
    except Exception as e:
        check("per_page=0 不崩", False, repr(e))


# ============================================================== 10. 性能红线
def test_perf():
    print("\n== 10. 性能红线（大文件不许卡死）===")

    # 5k 行 vs 5k 行（错位全部不同 = 最坏情况）
    a = ["line %d valve specification" % i for i in range(5000)]
    b = ["completely different content %d" % i for i in range(5000)]
    t0 = time.time()
    segs = C.align_lines(a, b)
    dt = time.time() - t0
    check("5k vs 5k 最坏对齐 < 3s", dt < 3.0, "%.2fs" % dt)
    print("   5k vs 5k 耗时 %.2fs，segments=%d" % (dt, len(segs)))

    # 2 万行
    a2 = ["spec line %d" % i for i in range(20000)]
    b2 = list(a2)
    t0 = time.time()
    C.align_lines(a2, b2)
    dt2 = time.time() - t0
    check("20k 全等对齐 < 3s", dt2 < 3.0, "%.2fs" % dt2)
    print("   20k 全等耗时 %.2fs" % dt2)

    # pair_similar 必须有时间预算兜底
    t0 = time.time()
    s2m, m2s = C.pair_similar(list(range(4000)), list(range(4000, 8000)),
                               src_lines=["t %d common token here" % i for i in range(4000)],
                               md_lines=["t %d common token here" % i for i in range(4000, 8000)],
                               time_budget=2.0)
    dt3 = time.time() - t0
    check("pair_similar 遵守时间预算", dt3 < 4.0, "%.2fs" % dt3)


# =========================================================== 11. 并发安全回归
def test_concurrent():
    print("\n== 11. 并发安全（历史 500 缺陷回归）===")
    import threading

    src = ["shared line %d valve" % i for i in range(300)]
    md = ["shared line %d valve" % i for i in range(300)]
    src2 = ["other content %d" % i for i in range(300)]
    errs = []

    def run(s, m):
        try:
            for _ in range(6):
                r = C.align_lines(s, m)
                assert isinstance(r, list)
        except Exception as e:
            errs.append(repr(e))

    ts = [threading.Thread(target=run, args=(src, md)) for _ in range(4)]
    ts += [threading.Thread(target=run, args=(src2, md)) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("8 线程并发对齐无异常", not errs, errs[:3])


# ==================================================================== 主流程
def main():
    print("=" * 62)
    print("核心算法单元测试 —— compare.py")
    print("=" * 62)

    for fn in (test_normalize, test_strip_md, test_salvage, test_align,
               test_numbers, test_coverage_score, test_count, test_dup,
               test_page, test_perf, test_concurrent):
        fn()

    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    failed = [(n, d) for n, ok, d in _RESULTS if not ok]

    print("\n" + "=" * 62)
    if failed:
        print("失败明细：")
        for n, d in failed:
            print("  ✗ %s" % n)
            if d:
                print("      %s" % d)
    print("结果：%d / %d 通过" % (passed, len(_RESULTS)))
    print("=" * 62)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())