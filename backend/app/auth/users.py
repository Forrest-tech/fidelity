"""Authentication (FastAPI Users) with admin/reviewer/viewer roles. See ADR 0002."""
import os
import secrets
import uuid

from fastapi import Depends, HTTPException, Request
from fastapi_users import BaseUserManager, InvalidPasswordException, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, CookieTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from .. import config
from ..orm import get_session
from .models import Role, User

SESSION_SECONDS = int(os.environ.get("FIDELITY_SESSION_SECONDS", str(8 * 3600)))


def _secret() -> str:
    env = os.environ.get("FIDELITY_SECRET")
    if env:
        return env
    path = os.path.join(config.DATA_DIR, "secret.key")  # data/ is git-ignored
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_urlsafe(48))
    with open(path) as f:
        return f.read().strip()


SECRET = _secret()


async def get_user_db(session: AsyncSession = Depends(get_session)):
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def validate_password(self, password, user):
        if len(password) < 10:
            raise InvalidPasswordException(reason="password must be at least 10 characters")


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


# httpOnly cookie, SameSite=Lax; `secure` is switched on when served over HTTPS.
cookie_transport = CookieTransport(
    cookie_name="fidelity_session",
    cookie_max_age=SESSION_SECONDS,
    cookie_secure=os.environ.get("FIDELITY_HTTPS") == "1",
    cookie_httponly=True,
    cookie_samesite="lax",
)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=SECRET, lifetime_seconds=SESSION_SECONDS)


backend = AuthenticationBackend(name="cookie", transport=cookie_transport, get_strategy=get_jwt_strategy)
fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [backend])

# Every authenticated, active user.
current_user = fastapi_users.current_user(active=True)


def require_role(*roles: Role):
    """Dependency: authenticated and holding one of `roles` (admin always passes)."""
    allowed = set(roles) | {Role.admin}

    async def dep(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return dep
