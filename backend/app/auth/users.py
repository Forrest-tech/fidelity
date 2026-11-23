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
from .models import OAuthAccount, Role, User

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
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET
    reset_password_token_lifetime_seconds = 3600

    async def on_after_forgot_password(self, user, token, request=None):
        """The reset link goes to the address on the account (app/auth/signup.py: /auth/forgot-password)."""
        from urllib.parse import quote
        from ..ops import mail
        link = f"{mail.site_url(request)}/reset-password?token={quote(token)}"
        subject, text, html = mail.reset_message(link, self.reset_password_token_lifetime_seconds // 60)
        mail.send(user.email, subject, text, html)

    async def validate_password(self, password, user):
        if len(password) < 10:
            raise InvalidPasswordException(reason="password must be at least 10 characters")

    async def update(self, user_update, user, safe=False, request=None):
        """User changes by an administrator: never leave the installation without an active administrator
        (demoting or switching off the last one would lock everybody out of user management)."""
        from sqlalchemy import func, select
        losing_admin = user.role == Role.admin and user.is_active and (
            (getattr(user_update, "role", None) not in (None, Role.admin))
            or getattr(user_update, "is_active", None) is False)
        if losing_admin:
            session = self.user_db.session
            n = (await session.execute(select(func.count()).select_from(User).where(
                User.role == Role.admin, User.is_active.is_(True)))).scalar_one()
            if n <= 1:
                raise HTTPException(status_code=409, detail="LAST_ADMIN")
        return await super().update(user_update, user, safe=safe, request=request)

    async def oauth_callback(self, oauth_name, access_token, account_id, account_email, expires_at=None,
                             refresh_token=None, request=None, *, associate_by_email=False,
                             is_verified_by_default=False):
        """Sign-in with Google/Microsoft/GitHub/company SSO: only for people who already have a user
        (matched by e-mail) or whose domain is allowed. New accounts from an allowed domain are viewers.
        The provider's tokens are not kept (identity only)."""
        from fastapi_users import exceptions
        from .oauth import OAuthRefused, allowed_domains
        try:
            await self.get_by_oauth_account(oauth_name, account_id)
        except exceptions.UserNotExists:
            try:
                await self.get_by_email(account_email)
            except exceptions.UserNotExists:
                if account_email.rsplit("@", 1)[-1].lower() not in allowed_domains():
                    from .signup import PENDING, enabled
                    if not enabled():
                        raise OAuthRefused("oauth_no_account")
                    # sign-up through the provider: the address is proven; an administrator still approves it
                    user = await super().oauth_callback(oauth_name, "-", account_id, account_email, None, None, request,
                                                        associate_by_email=associate_by_email,
                                                        is_verified_by_default=is_verified_by_default)
                    return await self.user_db.update(user, {"is_active": False, "approval": PENDING})
        return await super().oauth_callback(oauth_name, "-", account_id, account_email, None, None, request,
                                            associate_by_email=associate_by_email,
                                            is_verified_by_default=is_verified_by_default)


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
