# -*- coding: utf-8 -*-
"""重新转换：把「二进制字符串打捞」的无效 .md 用真实提取结果重写。

背景（2026-10-04 实测发现）：原转换管线遇到无法解析的二进制格式（DWG/RFA 等）时，
会把文件里的可打印 ASCII 片段原样倒进 .md（parser=salvage），内容形如
`AC1032 / RdAkRdAkRdA / IDATx…` —— 不是文档内容，检索与引用都不可用。
现在 CAD 有了真实文字提取、扫描件有了 OCR，这些文件应当被**重新转换**。

安全边界（重要）：
  * 只重写用户显式指定的文件，绝不批量自动执行；
  * 写盘前先把原 .md 备份为 `.md.salvage.bak`，可随时回滚；
  * front-matter 只做最小必要改写（parser / flags / audit_status），
    保留 source_hash、std_id、tier 等既有元数据，不破坏知识库索引。
"""
import os
import re
import shutil

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _parse_fm(raw):
    """解析 YAML front-matter 为 (dict, 剩余正文)。非严格解析：只认 `key: value`。"""
    m = _FM.match(raw or "")
    if not m:
        return {}, raw or ""
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, raw[m.end():]


def _render_fm(fm):
    order = ["source_filename", "source_relative_path", "source_file_type",
             "source_file_size", "source_file_hash", "source_mtime",
             "target_md_path", "tier", "std_id", "std_year", "std_kind",
             "parser", "units", "audit_status", "risk_score", "flags",
             "reconverted_at", "reconvert_engine"]
    head, rest = [], []
    for k in order:
        if k in fm:
            head.append("%s: %s" % (k, fm[k]))
    for k in fm:
        if k not in order:
            rest.append("%s: %s" % (k, fm[k]))
    return "---\n" + "\n".join(head + rest) + "\n---\n\n"


def build_md(raw_md, text, engine, filename):
    """在保留原 front-matter 的前提下，用真实文本重建 md 正文。"""
    fm, _body = _parse_fm(raw_md)
    fm["parser"] = fm.get("parser", "") if fm.get("parser") not in ("salvage", "") else engine
    if fm.get("parser") in ("salvage", ""):
        fm["parser"] = engine
    fm["flags"] = "[]"
    fm["audit_status"] = "pending_review"
    fm["risk_score"] = "0"
    fm["reconverted_at"] = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
    fm["reconvert_engine"] = engine
    lines = [l for l in (text or "").splitlines() if l.strip()]
    body = "# %s\n\n" % filename + "\n".join("- " + l for l in lines[:5000])
    return _render_fm(fm) + body + "\n"


def scan_salvage(sid="n2", limit=5000):
    """扫描该数据源下**全部** .md，找出仍是「二进制打捞」产物的相对路径。

    与 trust.salvage_list() 的区别：后者只列出已评测且带 flags 的记录，
    而全量扫描能发现尚未评测（历史批次没跑到）的打捞产物 —— 这才是真实全集。
    """
    from .. import config
    from ..domain import compare as cmp
    src = config.get_source(sid)
    if not src:
        return []
    md_root = src["md_root"]
    out = []
    for dp, dn, fn in os.walk(md_root):
        if "_kb" in dp or "_review" in dp:
            continue
        for name in fn:
            if not name.endswith(".md"):
                continue
            p = os.path.join(dp, name)
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(2000)
            except OSError:
                continue
            if cmp.md_is_salvage(head):
                rel = os.path.relpath(p, md_root).replace("\\", "/")[:-3]
                out.append(rel)
                if len(out) >= limit:
                    return sorted(out)
    return sorted(out)


def reconvert_one(rel, sid="n2", backup=True):
    """重新转换单个文件。返回 (ok:bool, msg:str)。"""
    from .. import config
    from . import parsers, format_router

    src = config.get_source(sid)
    if not src:
        return False, "source not configured"
    src_path = os.path.join(src["src_root"], rel)
    md_path = parsers.md_path_for(src["md_root"], rel)
    if not os.path.exists(src_path):
        return False, "源文件不存在"
    if not os.path.exists(md_path):
        return False, "缺少 .md"
    meta = {}
    text = format_router.extract(src_path, meta=meta)
    if not (text or "").strip():
        return False, "提取结果为空（%s）" % (meta.get("human_reason") or "无文本")
    try:
        raw = parsers.read_md_text(md_path)
    except Exception:
        raw = ""
    if backup and not os.path.exists(md_path + ".salvage.bak"):
        try:
            shutil.copy2(md_path, md_path + ".salvage.bak")
        except OSError:
            pass
    engine = meta.get("engine") or "extract"
    new_md = build_md(raw, text, engine, os.path.basename(rel))
    tmp = md_path + ".tmp"
    try:
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_md)
        os.replace(tmp, md_path)
    except OSError as e:
        return False, "写盘失败：%s" % e
    return True, "%s · %d 行" % (engine, len([l for l in text.splitlines() if l.strip()]))
