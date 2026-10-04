# -*- coding: utf-8 -*-
"""可配置多数据源 + 全局路径。

不写死任何 Library 路径：数据源来自 config.json，用户可在界面里增删/选文件夹。
"""
import os, json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # fidelity/
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
TRUST_DB = os.path.join(DATA_DIR, "trust.db")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

# 后端监听端口。与前端 dev / 启动脚本共用一处，避免各处写死 8000 走偏。
SERVER_PORT = int(os.environ.get("QA_SERVER_PORT", "8000"))
SERVER_HOST = os.environ.get("QA_SERVER_HOST", "127.0.0.1")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

DEFAULT_SOURCES = [
    {
        "id": "n2",
        "name": "N2 合规库",
        "src_root": r"C:\Users\Forrest Lin\WorkBuddy\Library",
        "md_root": r"C:\Users\Forrest Lin\WorkBuddy\Md_Library",
        "enabled": True,
    }
]


def _load():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    data = {"sources": DEFAULT_SOURCES}
    _save(data)
    return data


def _save(data):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def get_sources():
    return _load().get("sources", [])


def get_source(sid):
    for s in get_sources():
        if s["id"] == sid:
            return s
    return None


def upsert_source(src: dict):
    data = _load()
    srcs = data.setdefault("sources", [])
    for i, s in enumerate(srcs):
        if s["id"] == src.get("id"):
            srcs[i] = src
            break
    else:
        srcs.append(src)
    _save(data)
    return src


def delete_source(sid):
    data = _load()
    data["sources"] = [s for s in data.get("sources", []) if s["id"] != sid]
    _save(data)


# ---------- 审核人配置 ----------
# 为什么要「配置」而不是让用户在裁决栏自由输入（用户 2026-10-05 明确要求）：
#   自由输入会产生拼写变体（Forrest / forrest / Forrest Lin / F. Lin），
#   同一���在审计日志里被拆成好几个人，统计与追溯全部失真 —— 这在
#   受监管行业（审核人 + 时间戳要可审计）是不能接受的。
#   改为：名单在配置里集中维护，裁决时只能从名单里选，身份唯一且可统计。
DEFAULT_REVIEWERS = [
    {"id": "forrest", "name": "Forrest", "role": "审核人", "enabled": True},
]


def get_reviewers():
    """返回审核人列表。首次访问时写入默认名单，保证 id 稳定。"""
    data = _load()
    rv = data.get("reviewers")
    if not rv:
        rv = [dict(r) for r in DEFAULT_REVIEWERS]
        data["reviewers"] = rv
        _save(data)
    return rv


def active_reviewers():
    return [r for r in get_reviewers() if r.get("enabled", True)]


def resolve_reviewer_id(rid):
    """按 id 或姓名找审核人；找不到返回 None（调用方决定是否拒绝）。"""
    if not rid:
        return None
    rid = str(rid).strip()
    for r in get_reviewers():
        if r.get("id") == rid or r.get("name") == rid:
            return r
    return None


def upsert_reviewer(r):
    """新增或更新审核人。id 缺省时按姓名生成稳定 id。"""
    name = (r.get("name") or "").strip()
    if not name:
        raise ValueError("审核人姓名不能为空")
    data = _load()
    rv = data.setdefault("reviewers", [])
    rid = (r.get("id") or "").strip() or _slug(name)
    for i, x in enumerate(rv):
        if x.get("id") == rid or x.get("name") == name:
            rv[i] = {"id": rid, "name": name,
                     "role": (r.get("role") or x.get("role") or "审核人"),
                     "enabled": bool(r.get("enabled", x.get("enabled", True)))}
            _save(data)
            return rv[i]
    item = {"id": rid, "name": name,
            "role": (r.get("role") or "审核人"),
            "enabled": bool(r.get("enabled", True))}
    rv.append(item)
    _save(data)
    return item


def delete_reviewer(rid):
    """删除审核人。至少保留一位（否则裁决无处可选，等于把功能锁死）。"""
    data = _load()
    rv = data.get("reviewers", [])
    left = [x for x in rv if x.get("id") != rid]
    if len(left) == len(rv):
        return False
    if not left:
        raise ValueError("至少需要保留一位审核人")
    data["reviewers"] = left
    _save(data)
    return True


def _slug(name):
    import re as _re
    s = _re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.strip().lower()).strip("-")
    return s or "reviewer"

