# -*- coding: utf-8 -*-
"""源目录结构树"""
import os
from fastapi import APIRouter, HTTPException

from .. import config
from ..domain import trust

router = APIRouter()

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
