from fastapi import APIRouter, Depends, Form, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users.router.common import ErrorCode

from . import captcha, guard, oauth
from .models import User
from .schemas import UserCreate, UserRead, UserUpdate
from .users import backend, current_user, fastapi_users, get_user_manager, require_role
from .models import Role

router = APIRouter()


# ------------------------------------------------------------------ sign in / out
# The FastAPI Users login route plus bot protection (ALTCHA) and per-address/per-account failure limits.
@router.post("/auth/login", tags=["auth"])
async def login(request: Request, credentials: OAuth2PasswordRequestForm = Depends(),
                altcha: str | None = Form(None), user_manager=Depends(get_user_manager),
                strategy=Depends(backend.get_strategy)):
    from fastapi import HTTPException
    ip = guard.client_ip(request)
    account = credentials.username.strip().lower()[:320]
    wait = guard.login_blocked(ip, account)
    if wait:
        return guard.too_many(wait)
    reason = captcha.verify(altcha)
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    user = await user_manager.authenticate(credentials)
    if user is not None and not user.is_active and getattr(user, "approval", None) in ("pending", "unverified"):
        # the right password for an account that waits: say for what (it reveals nothing to a stranger)
        raise HTTPException(status_code=403, detail="EMAIL_NOT_CONFIRMED" if user.approval == "unverified" else "ACCOUNT_PENDING")
    if user is None or not user.is_active:
        guard.login_failed(ip, account)
        await guard.audit(None, "login_failed", ip)
        raise HTTPException(status_code=400, detail=ErrorCode.LOGIN_BAD_CREDENTIALS)
    guard.login_succeeded(ip, account)
    await guard.audit(user.id, "login", ip)
    response = await backend.login(strategy, user)
    await user_manager.on_after_login(user, request, response)
    return response


_current_user_token = fastapi_users.authenticator.current_user_token(active=True)


@router.post("/auth/logout", tags=["auth"])
async def logout(user_token=Depends(_current_user_token), strategy=Depends(backend.get_strategy)):
    user, token = user_token
    return await backend.logout(strategy, user, token)


@router.get("/auth/challenge", tags=["auth"])
async def challenge():
    """A fresh ALTCHA proof-of-work challenge for the sign-in or first-run form."""
    from fastapi.responses import JSONResponse
    return JSONResponse(captcha.new_challenge(), headers={"Cache-Control": "no-store"})


@router.get("/auth/options", tags=["auth"])
async def auth_options():
    """What the sign-in page offers: the configured providers, whether the captcha is required, and sign-up."""
    from . import signup
    from ..ops import mail
    return {"providers": oauth.providers_public(), "captcha": captcha.enabled(), "signup": signup.enabled(),
            "email": mail.configured()}


router.include_router(oauth.router)
from . import signup as _signup  # noqa: E402
router.include_router(_signup.router)
# User management is admin-only.
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users", tags=["users"], dependencies=[Depends(require_role())],
)
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/users", tags=["users"], dependencies=[Depends(require_role())],
)


@router.get("/me", response_model=UserRead, tags=["auth"])
async def me(user: User = Depends(current_user)):
    return user


# ------------------------------------------------------------------ first-run setup
# While no user exists, the sign-in page offers to create the first administrator. As soon as one
# user exists these endpoints refuse, so they cannot be used to add accounts later.
from fastapi import HTTPException  # noqa: E402
from pydantic import BaseModel, EmailStr  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from ..orm import SessionLocal  # noqa: E402


class SetupIn(BaseModel):
    email: EmailStr
    password: str
    altcha: str | None = None


async def _user_count() -> int:
    async with SessionLocal() as s:
        return (await s.execute(select(func.count()).select_from(User))).scalar_one()


@router.get("/setup", tags=["auth"])
async def setup_status():
    return {"needs_setup": await _user_count() == 0}


@router.post("/setup", status_code=201, tags=["auth"])
async def setup_first_admin(body: SetupIn, request: Request):
    if await _user_count() > 0:
        raise HTTPException(status_code=409, detail="setup is already complete")
    reason = captcha.verify(body.altcha)
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    from fastapi_users.db import SQLAlchemyUserDatabase
    from fastapi_users.exceptions import InvalidPasswordException
    from .users import UserManager
    async with SessionLocal() as s:
        mgr = UserManager(SQLAlchemyUserDatabase(s, User))
        try:
            user = await mgr.create(UserCreate(email=body.email, password=body.password, role=Role.admin, is_verified=True))
        except InvalidPasswordException as e:
            raise HTTPException(status_code=422, detail=str(e.reason))
    # signed in straight away (the one captcha solution is used up by this request)
    from fastapi.responses import JSONResponse
    from .users import get_jwt_strategy
    session = await backend.login(get_jwt_strategy(), user)
    resp = JSONResponse({"created": body.email, "role": "admin"}, status_code=201)
    for k, v in session.headers.items():
        if k.lower() == "set-cookie":
            resp.headers.append("set-cookie", v)
    await guard.audit(user.id, "setup_first_admin", guard.client_ip(request))
    return resp


# ------------------------------------------------------------------ user changes by an administrator
# FastAPI Users' own PATCH /users/{id} needs its "superuser" flag; Fidelity uses roles instead, so the
# same update (role, active, new password) is offered here for the admin role.
import uuid as _uuid  # noqa: E402


@router.patch("/admin/users/{user_id}", response_model=UserRead, tags=["users"])
async def admin_update_user(user_id: _uuid.UUID, body: UserUpdate, request: Request,
                            admin: User = Depends(require_role()), user_manager=Depends(get_user_manager)):
    from fastapi_users import exceptions
    try:
        user = await user_manager.get(user_id)
    except exceptions.UserNotExists:
        raise HTTPException(status_code=404, detail="user not found")
    patch = UserUpdate(**body.model_dump(exclude_unset=True, include={"role", "is_active", "password"}))
    try:
        user = await user_manager.update(patch, user, safe=False, request=request)
    except exceptions.InvalidPasswordException as e:
        raise HTTPException(status_code=400, detail="INVALID_PASSWORD: " + str(e.reason))
    return user
