# -*- coding: utf-8 -*-
"""AI settings and keys.

Settings (no secrets) live in data/ai_settings.json. Keys live in data/ai_keys.json, encrypted with a key kept in
data/ai_secret.key (created on first use, readable by the server's account only). The browser only ever sees the
last four characters of a key. Only administrators change any of this (enforced in api/ai.py).
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid

from .. import config as C

SETTINGS_PATH = os.path.join(C.DATA_DIR, "ai_settings.json")
KEYS_PATH = os.path.join(C.DATA_DIR, "ai_keys.json")
SECRET_PATH = os.path.join(C.DATA_DIR, "ai_secret.key")
_lock = threading.Lock()

# kind -> how it is called and what is offered by default
KINDS = {
    "anthropic": {"label": "Anthropic", "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
                  "prices": {"claude-opus-5-5": [4.0, 20.0], "claude-sonnet-5-5": [2.0, 10.0], "claude-haiku-5-5": [0.10, 0.50]}},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "models": []},
    "xai": {"label": "xAI Grok", "base_url": "https://api.x.ai/v1", "models": []},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "models": []},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta", "models": []},
    "custom": {"label": "Custom (OpenAI-compatible)", "models": []},
}

SKILLS = ("arbitrate", "explain")
LEVELS = (0, 1, 2)         # 0 off, 1 when a person asks, 2 asked by default (still only a suggestion)

DEFAULTS = {
    "enabled": False,
    "providers": [],        # [{id, kind, label, base_url, models, prices: {model: [in, out]}, last4}]
    "skills": {s: {"provider": None, "model": None, "level": 1, "budget_usd": 20.0, "monthly_cap": 500} for s in SKILLS},
    "scope": {"allowed_prefixes": [], "block_licensed": True},
    "evals": {},            # "skill|provider|model" -> {score, n, at}
}


class ConfigError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ------------------------------------------------------------------ settings
def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return copy.deepcopy(default)


def _write_json(path: str, data, private: bool = False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    if private:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def load() -> dict:
    s = _read_json(SETTINGS_PATH, DEFAULTS)
    out = copy.deepcopy(DEFAULTS)
    out.update({k: v for k, v in s.items() if k in DEFAULTS})
    for sk in SKILLS:                                      # a skill added later gets its defaults
        out["skills"][sk] = {**DEFAULTS["skills"][sk], **(s.get("skills", {}).get(sk) or {})}
    out["scope"] = {**DEFAULTS["scope"], **(s.get("scope") or {})}
    return out


def save(s: dict):
    with _lock:
        _write_json(SETTINGS_PATH, s)


def provider(s: dict, pid: str | None) -> dict | None:
    return next((p for p in s["providers"] if p["id"] == pid), None)


# ------------------------------------------------------------------ keys (encrypted at rest)
def _fernet():
    from cryptography.fernet import Fernet
    with _lock:
        if not os.path.exists(SECRET_PATH):
            os.makedirs(os.path.dirname(SECRET_PATH), exist_ok=True)
            with open(SECRET_PATH, "wb") as f:
                f.write(Fernet.generate_key())
            try:
                os.chmod(SECRET_PATH, 0o600)
            except OSError:
                pass
        with open(SECRET_PATH, "rb") as f:
            return Fernet(f.read().strip())


def key_for(pid: str) -> str | None:
    enc = _read_json(KEYS_PATH, {}).get(pid)
    if not enc:
        return None
    try:
        return _fernet().decrypt(enc.encode()).decode()
    except Exception:                                      # noqa: BLE001 - a key that cannot be read is no key
        return None


def _store_key(pid: str, key: str | None):
    keys = _read_json(KEYS_PATH, {})
    if key:
        keys[pid] = _fernet().encrypt(key.encode()).decode()
    else:
        keys.pop(pid, None)
    with _lock:
        _write_json(KEYS_PATH, keys, private=True)


# ------------------------------------------------------------------ changes (administrators)
_PRIVATE = re.compile(r"^(localhost|.*\.local|.*\.internal|.*\.lan)$", re.I)


def check_base_url(url: str) -> str:
    """A custom endpoint must be https and must not point into this machine or the local network (SSRF)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse
    u = urlparse((url or "").strip())
    if u.scheme != "https" or not u.hostname:
        raise ConfigError(422, "the address must start with https://")
    host = u.hostname
    if _PRIVATE.match(host):
        raise ConfigError(422, "the address points to this machine or the local network")
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(host, u.port or 443)}
    except OSError:
        raise ConfigError(422, f"cannot find {host}")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ConfigError(422, "the address points to this machine or the local network")
    return url.strip().rstrip("/")


def add_provider(kind: str, key: str, base_url: str | None = None, label: str | None = None) -> dict:
    if kind not in KINDS:
        raise ConfigError(422, "unknown provider")
    key = (key or "").strip()
    if len(key) < 8 or any(c.isspace() for c in key):
        raise ConfigError(422, "that does not look like an API key")
    s = load()
    p = {"id": uuid.uuid4().hex[:8], "kind": kind, "label": (label or KINDS[kind]["label"]).strip()[:60],
         "base_url": check_base_url(base_url) if kind == "custom" else KINDS[kind].get("base_url"),
         "models": list(KINDS[kind]["models"]), "prices": copy.deepcopy(KINDS[kind].get("prices", {})), "last4": key[-4:]}
    if kind == "custom" and not base_url:
        raise ConfigError(422, "a custom provider needs its address")
    _store_key(p["id"], key)
    s["providers"].append(p)
    save(s)
    return p


def update_provider(pid: str, models=None, prices=None, key: str | None = None) -> dict:
    s = load()
    p = provider(s, pid)
    if not p:
        raise ConfigError(404, "no such provider")
    if models is not None:
        p["models"] = [m.strip() for m in models if isinstance(m, str) and m.strip()][:30]
    if prices is not None:
        p["prices"] = {m: [float(v[0]), float(v[1])] for m, v in prices.items() if isinstance(v, (list, tuple)) and len(v) == 2}
    if key:
        key = key.strip()
        if len(key) < 8:
            raise ConfigError(422, "that does not look like an API key")
        _store_key(pid, key)
        p["last4"] = key[-4:]
    save(s)
    return p


def remove_provider(pid: str):
    s = load()
    if not provider(s, pid):
        raise ConfigError(404, "no such provider")
    s["providers"] = [p for p in s["providers"] if p["id"] != pid]
    for sk in s["skills"].values():                       # a skill that used it goes back to "rules + people"
        if sk["provider"] == pid:
            sk["provider"], sk["model"] = None, None
    _store_key(pid, None)
    save(s)


def remove_all_keys():
    s = load()
    for p in s["providers"]:
        _store_key(p["id"], None)
    s["providers"] = []
    for sk in s["skills"].values():
        sk["provider"], sk["model"] = None, None
    s["enabled"] = False
    save(s)


def eval_key(skill: str, pid: str | None, model: str | None) -> str:
    return f"{skill}|{pid}|{model}"


def update(changes: dict, eval_examples: int = 0) -> dict:
    """Master switch, skills (provider, model, level, budget, cap) and send scope.

    Iron rule 10: a skill's model changes only after the new model was tested on the confirmed examples and scored
    at least as well as the current one (once there are enough examples to test on)."""
    s = load()
    if "enabled" in changes:
        s["enabled"] = bool(changes["enabled"])
    for name, sk in (changes.get("skills") or {}).items():
        if name not in SKILLS:
            raise ConfigError(422, f"unknown skill {name}")
        cur = s["skills"][name]
        new = {**cur, **{k: v for k, v in sk.items() if k in cur}}
        if new["provider"] is not None:
            p = provider(s, new["provider"])
            if not p:
                raise ConfigError(422, "choose one of the connected providers")
            if not new["model"]:
                raise ConfigError(422, "choose a model")
        if int(new["level"]) not in LEVELS:
            raise ConfigError(422, "level must be 0, 1 or 2")
        new["level"] = int(new["level"])
        new["budget_usd"] = max(0.0, float(new["budget_usd"] or 0))
        new["monthly_cap"] = max(0, int(new["monthly_cap"] or 0))
        switching = (new["provider"], new["model"]) != (cur["provider"], cur["model"]) and new["provider"] and cur["provider"]
        if switching and eval_examples >= 5:
            cand = s["evals"].get(eval_key(name, new["provider"], new["model"]))
            now = s["evals"].get(eval_key(name, cur["provider"], cur["model"]))
            if not cand:
                raise ConfigError(409, "test the new model on the confirmed examples first")
            if now and cand["score"] < now["score"]:
                raise ConfigError(409, f"the new model scored {cand['score']}% against {now['score']}% for the current one")
        s["skills"][name] = new
    if "scope" in changes:
        sc = changes["scope"] or {}
        prefixes = [str(x).strip() for x in sc.get("allowed_prefixes", s["scope"]["allowed_prefixes"]) if str(x).strip()]
        s["scope"] = {"allowed_prefixes": prefixes[:50], "block_licensed": bool(sc.get("block_licensed", s["scope"]["block_licensed"]))}
    save(s)
    return s


def public(s: dict | None = None) -> dict:
    """What the page may see: everything except keys (only their last four characters)."""
    s = copy.deepcopy(s or load())
    s["kinds"] = {k: {"label": v["label"], "models": v["models"], "custom": k == "custom"} for k, v in KINDS.items()}
    return s
