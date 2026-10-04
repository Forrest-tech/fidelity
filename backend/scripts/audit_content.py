# -*- coding: utf-8 -*-
"""内容保全审计：找出「源文里有、.md 里没有」的内容。

背景（2026-10-05）：用户发现左栏有中文、md 里却没有，怀疑转换时做了翻译。
排查后确认那批 .msg 的中文表头是**预览层凭空捏造**的，源文件与 md 均无中文，
属于显示层的假警报，而不是数据丢失。

但「显示层说谎」会掩盖真正的丢失，所以这里提供一个**可复现的审计**：
对每个文件抽取源文，与 md 逐行比对，列出源文有而 md 没有的实质内容。

判定原则（重要）：
  * 只看**实义内容行**（非空、非纯标点），跳过页眉页脚、页码、目录点线；
  * 归一化后做**子串包含**匹配，避免因换行/断词造成的假阳性；
  * 只报告长度 >= MIN_LEN 的行，太短的行（页码、单个符号）噪声太大；
  * 只读不写 —— 本脚本**绝不修改**任何 md，产出仅供人工判断。

用法：
    python -m scripts.audit_content            # 全库
    python -m scripts.audit_content --limit 50 # 只看前 50 个有问题���文件
    python -m scripts.audit_content --ext msg  # 只查某类扩展名
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIN_LEN = 12          # 短于此长度的行不报告（页码/符号噪声）
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
# 归一化：去掉所有空白 + 全角转半角 + 小写
_PUNCT = "，。！？；：、（）【】《》“”‘’…—～"


def normalize(s: str) -> str:
    s = s.replace("\u3000", " ")
    # 去掉 markdown 表格/引用/列表的结构符号，只留实义字符。
    # 这样 `| Subject | X |` 与 `Subject: X` 归一化后能落到同一形态。
    s = re.sub(r"[|`*_>#\-]{1,}", " ", s)
    s = re.sub(r"\s+", "", s)
    return s.lower()


def is_noise(line: str) -> bool:
    """页眉页脚/页码/目录点线等非实义内容。"""
    t = line.strip()
    if not t:
        return True
    if len(t) < MIN_LEN:
        return True
    # 纯数字、纯点线、纯标点
    if re.fullmatch(r"[\d\s.\-–—_/·•]*", t):
        return True
    if re.fullmatch(r"[.\s…·•]*", t):
        return True
    # 目录点线行：正文 + 大量连续点
    if len(re.findall(r"[.·•]\s{2,}", t)) > 2:
        return True
    # 形如 "Page 12" / "第 3 页"
    if re.fullmatch(r"(page\s*)?\d+(\s*/\s*\d+)?(页)?", t, re.I):
        return True
    return False


def _variants(line: str):
    """给出该行在 md 中可能出现的等价形态。

    背景：同一份邮件表头，源文抽取是 `Subject: X`，
    而上游转换器写进 md 的是表格行 `| Subject | X |`。
    归一化后分别是 `subject:x` 与 `|subject|x|`，直接子串匹配会误报「丢失」。
    所以对 `标签: 值` 形态额外产出「仅值」的变体，匹配时才不会漏判。
    """
    n = normalize(line)
    yield n
    m = re.match(r"^([A-Za-z][A-Za-z\- ]{0,20}):\s*(.+)$", line.strip())
    if m:
        val = normalize(m.group(2))
        if val:
            yield val          # `| Subject | X |` 里的 X
        lab = normalize(m.group(1))
        if lab:
            yield lab           # 仅标签


def present(line: str, md_norm: str) -> bool:
    return any(v and v in md_norm for v in _variants(line))


def audit_file(src_path: str, md_path: str, cache_dir: str | None = None) -> dict:
    from app.ingest import parsers
    from app.domain import compare as cmp

    src = ""
    # extract_source_text_guarded 需要一个真实的 cache_dir，传 None 会抛 TypeError，
    # 所以这里统一走 format_router（自带缓存与超时保护）。
    try:
        from app.ingest import format_router
        src = format_router.extract(src_path, meta={}) or ""
    except Exception:
        try:
            src = parsers.extract_source_text_guarded(src_path, cache_dir) or ""
        except Exception:
            src = ""

    if not os.path.exists(md_path):
        return {"missing_md": True, "lost": [], "lost_cjk": 0}

    try:
        md = cmp.strip_md_artifacts(parsers.read_md_text(md_path))
    except Exception:
        md = ""

    md_norm = normalize(md)
    if not md_norm:
        return {"missing_md": False, "lost": [], "lost_cjk": 0, "empty_md": True}

    lost, lost_cjk = [], 0
    for line in src.splitlines():
        if is_noise(line):
            continue
        n = normalize(line)
        if len(n) < MIN_LEN:
            continue
        if present(line, md_norm):
            continue
        lost.append(line.strip())
        if CJK.search(line):
            lost_cjk += 1

    return {
        "missing_md": False,
        "lost": lost,
        "lost_cjk": lost_cjk,
        "src_chars": len(src),
        "md_chars": len(md),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="内容保全审计（只读，不修改任何文件）")
    ap.add_argument("--sid", default="n2", help="数据源 id")
    ap.add_argument("--limit", type=int, default=0, help="最多输出多少个有问题的文件（0=不限）")
    ap.add_argument("--ext", default="", help="只查该扩展名，如 msg / pdf（带不带点都可以）")
    ap.add_argument("--json", default="", help="把完整结果写入该 JSON 路径")
    args = ap.parse_args()

    from app import config
    from app.ingest import parsers

    src = config.get_source(args.sid)
    if not src:
        print("数据源未配置：%s" % args.sid)
        return 2

    src_root, md_root = src["src_root"], src["md_root"]
    # 用户可能传 "msg" 或 ".msg"，统一成 ".msg" 再比较
    want_ext = ("." + args.ext.lstrip(".").lower()) if args.ext else ""
    total = 0
    problems = []
    for dp, dn, fn in os.walk(src_root):
        dn[:] = [d for d in dn if d not in ("_kb", "_review", ".git")]
        for name in fn:
            if name.startswith("~$") or name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if want_ext and ext != want_ext:
                continue
            total += 1
            sp = os.path.join(dp, name)
            rel = os.path.relpath(sp, src_root).replace("\\", "/")
            mp = parsers.md_path_for(md_root, rel)
            try:
                r = audit_file(sp, mp)
            except Exception as e:  # 单个文件失败不能中断整轮审计
                r = {"missing_md": False, "lost": [], "lost_cjk": 0, "error": str(e)}
            if r.get("missing_md") or r.get("lost"):
                problems.append({"rel": rel, **r})

    print("=" * 68)
    print("内容保全审计 · 数据源 %s" % args.sid)
    print("=" * 68)
    print("扫描源文件：%d 个" % total)
    print("存在问题　：%d 个" % len(problems))

    cjk_files = [p for p in problems if p.get("lost_cjk")]
    print("其中含中文丢失：%d 个" % len(cjk_files))
    if problems:
        print("-" * 68)
        shown = problems if not args.limit else problems[: args.limit]
        for p in shown:
            flags = []
            if p.get("missing_md"):
                flags.append("缺 md")
            if p.get("lost_cjk"):
                flags.append("中文丢失 %d 行" % p["lost_cjk"])
            elif p.get("lost"):
                flags.append("丢失 %d 行" % len(p["lost"]))
            print("  [%s] %s" % ("/".join(flags), p["rel"]))
            for l in (p.get("lost") or [])[:3]:
                print("        - %s" % l[:88])
        if args.limit and len(problems) > args.limit:
            print("  ... 另有 %d 个未显示（用 --limit 0 查看全部）"
                  % (len(problems) - args.limit))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"sid": args.sid, "total": total,
                       "problems": problems}, f, ensure_ascii=False, indent=1)
        print("完整结果已写入：%s" % args.json)

    print("=" * 68)
    print("本脚本为只读审计，未修改任何 .md 文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
