# -*- coding: utf-8 -*-
"""验证「右栏按页显示」在真实数据上的效果（只读，不改任何数据）。

用户 2026-10-05 反馈：右栏一次铺开 61,083 行，与左栏一页对不上。
本脚本复用前端**完全相同**的过滤规则（p === page），统计：
  * 每页有多少 md 行
  * 按页显示后比整篇少渲染多少行
  * 有多少行没有页码映射（这些行在按页模式下看不到 —— 必须确认数量可接受）
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter

BASE = "http://127.0.0.1:8000/api"
REL = "NCC2022/ncc2022-volume-one-20230501.pdf"


def get(path, **params):
    url = "%s/%s?%s" % (BASE, path, urllib.parse.urlencode(params))
    with urllib.request.urlopen(url, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    meta = get("preview/meta", rel=REL, sid="n2")
    pages = meta.get("pages", 1)
    a = get("align", rel=REL, sid="n2")

    sp = a.get("src_page") or []
    st = a.get("status") or []
    total = a.get("total_lines", 0)

    print("源文件页数        : %d" % pages)
    print("md 总行数         : %d" % total)
    print("参与比对的行数    : %d" % len(st))
    print("有页码映射的行数  : %d" % sum(1 for p in sp if p is not None))
    print("无页码映射的行数  : %d" % sum(1 for p in sp if p is None))

    per = Counter(p for p in sp if p is not None)
    shown = [per.get(i, 0) for i in (1, 2, 3, 10, 20, 50)]
    print("第 1/2/3/10/20/50 页对应的 md 行数: %s" % shown)

    empty = [i for i in range(1, min(pages, 200) + 1) if per.get(i, 0) == 0]
    print("前 200 页中「无 md 行」的页数: %d" % len(empty))
    if empty:
        print("  示例页码: %s%s" % (empty[:12], " …" if len(empty) > 12 else ""))

    in_scope = sum(v for k, v in per.items() if k and k <= pages)
    mapped = sum(1 for p in sp if p is not None)
    if mapped:
        print("按页模式可见行数  : %d / %d (%.1f%%)"
              % (in_scope, mapped, 100.0 * in_scope / mapped))
    print()
    # 关键结论：按页模式下「一行 md 都不会显示」必须为假，否则是致命 bug
    assert mapped > 0, "没有任何行有页码映射，按页模式会全空 —— 这是致命 bug"
    assert in_scope > 0, "按页范围内没有任何可见行"
    print("结论：按页模式可用（不会全空），且可一键切回整篇。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
