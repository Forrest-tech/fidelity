# -*- coding: utf-8 -*-
"""可配置多数据源 + 全局路径。

不写死任何 Library 路径：数据源来自 config.json，用户可在界面里增删/选文件夹。
"""
import os, json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # qa-platform/
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
