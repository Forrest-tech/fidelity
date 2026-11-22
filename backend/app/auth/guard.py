"""Sign-in rate limiting and audit logging (spec section 8).

Rate limits use `limits` (MIT; the library behind slowapi and Flask-Limiter) with moving windows:
  * failed password sign-ins: 5 per client address per 5 minutes, and 10 per account per 15 minutes
    (stops both one machine guessing many accounts and many machines guessing one account);
  * the other sign-in endpoints (captcha challenge, first-run setup, Google/Microsoft/GitHub sign-in):
    60 requests per client address per minute.
A blocked request gets HTTP 429 with a Retry-After header.
"""
import math
import time
import uuid

import jwt
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..orm import SessionLocal
from .models import AuditLog
from .users import SECRET

LOGIN_PATH = "/api/v1/auth/login"
MAX_FAILURES = 5
WINDOW_SECONDS = 300
FAILS_PER_IP = parse("%d/%d seconds" % (MAX_FAILURES, WINDOW_SECONDS))
FAILS_PER_ACCOUNT = parse("10/15 minutes")
AUTH_CALLS_PER_IP = parse("60/minute")

_storage = MemoryStorage()
_limiter = MovingWindowRateLimiter(_storage)


def reset():
    _storage.reset()


def client_ip(request) -> str:
    return request.client.host if request.client else "?"


def _retry_after(item, *keys) -> int:
    reset_at, _remaining = _limiter.get_window_stats(item, *keys)
    return max(1, math.ceil(reset_at - time.time()))


def login_blocked(ip: str, account: str) -> int:
    """Seconds to wait when this address or account has too many recent failures, else 0."""
    if not _limiter.test(FAILS_PER_IP, "ip", ip):
        return _retry_after(FAILS_PER_IP, "ip", ip)
    if account and not _limiter.test(FAILS_PER_ACCOUNT, "acct", account):
        return _retry_after(FAILS_PER_ACCOUNT, "acct", account)
    return 0


def login_failed(ip: str, account: str):
    _limiter.hit(FAILS_PER_IP, "ip", ip)
    if account:
        _limiter.hit(FAILS_PER_ACCOUNT, "acct", account)


def login_succeeded(ip: str, account: str):
    _limiter.clear(FAILS_PER_IP, "ip", ip)
    if account:
        _limiter.clear(FAILS_PER_ACCOUNT, "acct", account)


def too_many(retry_after: int) -> JSONResponse:
    return JSONResponse({"detail": "too many failed logins; try again later"}, status_code=429,
                        headers={"Retry-After": str(retry_after)})


def _user_id(request):
    tok = request.cookies.get("fidelity_session")
    if not tok:
        return None
    try:
        sub = jwt.decode(tok, SECRET, algorithms=["HS256"], audience=["fastapi-users:auth"])["sub"]
        return uuid.UUID(sub)
    except Exception:
        return None


async def audit(user_id, action, target):
    async with SessionLocal() as s:
        s.add(AuditLog(user_id=user_id, action=action[:100], target=target[:500]))
        await s.commit()


_audit = audit  # older name


def _throttled_auth_path(path: str, method: str) -> bool:
    if path == LOGIN_PATH:
        return False                                   # has its own failure-based limit
    if path == "/api/v1/setup":
        return method == "POST"
    return path.startswith("/api/v1/auth/") and method in ("GET", "POST")


class GuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path, method = request.url.path, request.method
        if _throttled_auth_path(path, method):
            ip = client_ip(request)
            if not _limiter.hit(AUTH_CALLS_PER_IP, "auth", ip):
                return JSONResponse({"detail": "too many requests; try again later"}, status_code=429,
                                    headers={"Retry-After": str(_retry_after(AUTH_CALLS_PER_IP, "auth", ip))})
        resp = await call_next(request)
        # sign-in is audited by its own route (it knows who signed in); everything else that changes data here
        if path.startswith("/api/") and method not in ("GET", "HEAD", "OPTIONS") and path != LOGIN_PATH:
            await audit(_user_id(request), "%s %d" % (method, resp.status_code), path)
        return resp
