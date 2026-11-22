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
"""
import os
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


def verify(payload: str | None) -> str | None:
    """None when the payload is a fresh valid solution, otherwise a short reason code."""
    if not enabled():
        return None
    if not payload or len(payload) > 8000:
        return "CAPTCHA_REQUIRED"
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
