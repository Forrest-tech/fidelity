"""Login rate limiting and audit logging (spec section 8)."""
import time
import uuid
from collections import defaultdict, deque

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..orm import SessionLocal
from .models import AuditLog
from .users import SECRET

LOGIN_PATH = "/api/v1/auth/login"
MAX_FAILURES = 5
WINDOW_SECONDS = 300
_failures = defaultdict(deque)  # client ip -> timestamps of recent failed logins


def reset():
    _failures.clear()


def _user_id(request):
    tok = request.cookies.get("fidelity_session")
    if not tok:
        return None
    try:
        sub = jwt.decode(tok, SECRET, algorithms=["HS256"], audience=["fastapi-users:auth"])["sub"]
        return uuid.UUID(sub)
    except Exception:
        return None


async def _audit(user_id, action, target):
    async with SessionLocal() as s:
        s.add(AuditLog(user_id=user_id, action=action[:100], target=target[:500]))
        await s.commit()


class GuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path, ip = request.url.path, (request.client.host if request.client else "?")
        if path == LOGIN_PATH and request.method == "POST":
            q = _failures[ip]
            now = time.time()
            while q and now - q[0] > WINDOW_SECONDS:
                q.popleft()
            if len(q) >= MAX_FAILURES:
                return JSONResponse({"detail": "too many failed logins; try again later"}, status_code=429,
                                    headers={"Retry-After": str(WINDOW_SECONDS)})
            resp = await call_next(request)
            if resp.status_code >= 400:
                q.append(now)
                await _audit(None, "login_failed", ip)
            else:
                _failures.pop(ip, None)
                await _audit(None, "login", ip)
            return resp
        resp = await call_next(request)
        if path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            await _audit(_user_id(request), "%s %d" % (request.method, resp.status_code), path)
        return resp
