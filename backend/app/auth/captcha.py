"""Bot protection for the sign-in and first-run forms: ALTCHA proof-of-work (MIT, self-hosted).

ALTCHA was chosen over Cloudflare Turnstile / reCAPTCHA / hCaptcha because it runs entirely on this
server: no third-party script, no tracking cookie, no outside call, and it works on an offline or
office-network installation. The browser fetches a signed challenge from `GET /api/v1/auth/challenge`,
solves it invisibly with the ALTCHA solver (npm `altcha/lib`, key derivation by @noble/hashes so it also
works on plain-HTTP office addresses where WebCrypto is unavailable) and sends the proof with the form as
the field `altcha`. The server checks the signature, the expiry, the solution, and that the same
challenge is not used twice.

Settings (environment):
  FIDELITY_CAPTCHA          "on" (default) or "off" (only for automated tests and scripted set-ups)
  FIDELITY_CAPTCHA_COST     PBKDF2 iterations per attempt (default 100)
  FIDELITY_CAPTCHA_MAX      highest counter the browser may have to search (default 3000)
With the defaults a person's browser needs well under a second; a bot pays that for every attempt, on
top of the rate limits in guard.py.

Cloudflare Turnstile (owner's choice, 2026-11-23) can be switched on in Settings → Human check with the site key
and secret key of a Turnstile widget. The browser then shows Cloudflare's check and sends its token as
"turnstile:<token>"; the server confirms it with Cloudflare's siteverify (each token works once). If Cloudflare
cannot be reached (an office network without internet, an outage), the browser falls back to the ALTCHA box and the
server accepts ALTCHA while Cloudflare is unreachable, so nobody is locked out; otherwise only Turnstile is accepted.
"""
import json
import os
import urllib.parse
import urllib.request
import secrets
import threading
import time

import altcha

from .users import SECRET

ALGORITHM = "PBKDF2/SHA-256"
TTL_SECONDS = 600            # a challenge must be solved and used within 10 minutes

_HMAC = "altcha:" + SECRET   # derived from the app secret, so nothing new to configure
_HMAC_KEY = "altcha-key:" + SECRET
_used: dict[str, float] = {}  # nonce -> expiry: a solved challenge works once
_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("FIDELITY_CAPTCHA", "on").lower() not in ("off", "0", "false", "no")


# ------------------------------------------------------------------ provider settings (Turnstile)
SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
SECRET_ID = "__turnstile__"
PROVIDERS = ("altcha", "turnstile")


def _settings_path() -> str:
    from .. import config
    return os.path.join(config.DATA_DIR, "captcha_settings.json")


def settings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    return {"provider": s.get("provider") if s.get("provider") in PROVIDERS else "altcha",
            "site_key": str(s.get("site_key") or "")}


def _secret() -> str | None:
    from ..ai import config as CF
    return CF.key_for(SECRET_ID)


def provider() -> str:
    """The check people see; Turnstile only once both keys are there."""
    s = settings()
    return "turnstile" if s["provider"] == "turnstile" and s["site_key"] and _secret() else "altcha"


def public() -> dict:
    s = settings()
    return {**s, "secret_set": bool(_secret()), "active": provider()}


def save(changes: dict) -> dict:
    s = settings()
    if changes.get("provider") is not None:
        if changes["provider"] not in PROVIDERS:
            raise ValueError("provider must be altcha or turnstile")
        s["provider"] = changes["provider"]
    if changes.get("site_key") is not None:
        s["site_key"] = str(changes["site_key"]).strip()
    if changes.get("secret_key") is not None:
        from ..ai import config as CF
        CF._store_key(SECRET_ID, str(changes["secret_key"]).strip() or None)       # "" clears it
    tmp = _settings_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, _settings_path())
    return public()


_cf_down_until = 0.0


def _siteverify(token: str, remote_ip: str | None) -> dict:
    """Cloudflare's answer, or {"unreachable": True} when it cannot be asked."""
    global _cf_down_until
    data = {"secret": _secret() or "", "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    req = urllib.request.Request(SITEVERIFY, data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            _cf_down_until = 0.0
            return json.load(r)
    except (OSError, ValueError):
        _cf_down_until = time.time() + 300          # ALTCHA is accepted for the next five minutes
        return {"unreachable": True}


_cf_up_until = 0.0


def cloudflare_down() -> bool:
    """Whether Cloudflare cannot be reached from this server (asked at most once a minute)."""
    global _cf_down_until, _cf_up_until
    now = time.time()
    if now < _cf_down_until:
        return True
    if now < _cf_up_until:
        return False
    try:
        urllib.request.urlopen(urllib.request.Request("https://challenges.cloudflare.com/cdn-cgi/trace"), timeout=4).close()
        _cf_up_until = now + 60
        return False
    except OSError:
        _cf_down_until = now + 300
        return True


def _verify_turnstile(token: str, remote_ip: str | None) -> str | None:
    if not token or len(token) > 4096:
        return "CAPTCHA_REQUIRED"
    res = _siteverify(token, remote_ip)
    if res.get("unreachable"):
        return "CAPTCHA_UNAVAILABLE"
    if res.get("success"):
        return None
    codes = res.get("error-codes") or []
    if "timeout-or-duplicate" in codes:
        return "CAPTCHA_EXPIRED"
    return "CAPTCHA_INVALID"


def _cost() -> int:
    return max(1, int(os.environ.get("FIDELITY_CAPTCHA_COST", "100")))


def _max_counter() -> int:
    return max(1, int(os.environ.get("FIDELITY_CAPTCHA_MAX", "3000")))


def new_challenge() -> dict:
    counter = secrets.randbelow(_max_counter()) + 1
    ch = altcha.create_challenge(
        algorithm=ALGORITHM,
        cost=_cost(),
        counter=counter,                      # deterministic: the work is bounded by FIDELITY_CAPTCHA_MAX
        expires_at=int(time.time()) + TTL_SECONDS,
        hmac_secret=_HMAC,
        hmac_key_secret=_HMAC_KEY,           # fast verification without re-deriving the key
    )
    return ch.to_dict()


def _forget_expired(now: float):
    for k in [k for k, exp in _used.items() if exp < now]:
        _used.pop(k, None)


def verify(payload: str | None, remote_ip: str | None = None) -> str | None:
    """None when the payload is a fresh valid solution, otherwise a short reason code."""
    if not enabled():
        return None
    if not payload or len(payload) > 8000:
        return "CAPTCHA_REQUIRED"
    if payload.startswith("turnstile:"):
        if provider() != "turnstile":
            return "CAPTCHA_INVALID"
        return _verify_turnstile(payload[len("turnstile:"):], remote_ip)
    if provider() == "turnstile" and not cloudflare_down():
        return "CAPTCHA_REQUIRED"                 # ALTCHA only stands in while Cloudflare cannot be reached
    return _verify_altcha(payload)


def _verify_altcha(payload: str) -> str | None:
    try:
        parsed = altcha.Payload.from_base64(payload)
        result = altcha.verify_solution(parsed, _HMAC, hmac_key_secret=_HMAC_KEY)
    except Exception:
        return "CAPTCHA_INVALID"
    if result.expired:
        return "CAPTCHA_EXPIRED"
    if not result.verified:
        return "CAPTCHA_INVALID"
    nonce = parsed.challenge.parameters.nonce
    now = time.time()
    with _lock:
        _forget_expired(now)
        if nonce in _used:
            return "CAPTCHA_REUSED"
        _used[nonce] = now + TTL_SECONDS + 60
    return None


def solve_for_tests(challenge: dict) -> str:
    """Solve a challenge the way the browser widget does (used by tests and the smoke test)."""
    ch = altcha.Challenge.from_dict(challenge)
    sol = altcha.solve_challenge(ch)
    return altcha.Payload(ch, sol).to_base64()


def reset():
    with _lock:
        _used.clear()
