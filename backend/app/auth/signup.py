"""Sign-up with an administrator's approval (requirements v2, U-1).

Anyone can ask for an account on the sign-in page. The account is made switched off and marked "pending";
it can sign in once an administrator approves it (Settings → Users and roles, or the bell), choosing its
role. Nothing about other people's accounts leaks: asking for an address that already has an account gets
the same answer as a new one.

Why approval and not open sign-up: the knowledge base holds licensed standards for the company's staff. Why
not an e-mail link: that needs a company mail account; an administrator approving does the same job here.
A Google / Microsoft / GitHub / company sign-in proves the address, so one from an allowed domain
(FIDELITY_OAUTH_ALLOWED_DOMAINS) is approved straight away as a viewer; any other becomes a pending request.

FIDELITY_SIGNUP=off hides the sign-up page and refuses requests (invitation only).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select

from ..orm import SessionLocal
from . import captcha, guard
from .models import Role, User
from .users import get_user_manager, require_role

PENDING = "pending"
router = APIRouter()


def enabled() -> bool:
    return os.environ.get("FIDELITY_SIGNUP", "on").lower() not in ("off", "0", "false", "no")


class SignupIn(BaseModel):
    email: EmailStr
    password: str
    altcha: str | None = None


class ApproveIn(BaseModel):
    role: Role = Role.viewer


@router.post("/auth/signup", status_code=201, tags=["auth"])
async def signup(body: SignupIn, request: Request, user_manager=Depends(get_user_manager)):
    if not enabled():
        raise HTTPException(status_code=404, detail="SIGNUP_OFF")
    ip = guard.client_ip(request)
    wait = guard.signup_blocked(ip)
    if wait:
        return guard.too_many(wait)
    reason = captcha.verify(body.altcha)
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    from fastapi_users import exceptions
    from .schemas import UserCreate
    email = body.email.strip().lower()
    try:
        await user_manager.validate_password(body.password, None)
    except exceptions.InvalidPasswordException as e:
        raise HTTPException(status_code=422, detail="INVALID_PASSWORD: " + str(e.reason))
    try:
        await user_manager.get_by_email(email)
        exists = True
    except exceptions.UserNotExists:
        exists = False
    if not exists:
        user = await user_manager.create(UserCreate(email=email, password=body.password, role=Role.viewer,
                                                    is_active=False, is_verified=False))
        await user_manager.user_db.update(user, {"approval": PENDING})
        await guard.audit(user.id, "signup_requested", ip)
    else:
        await guard.audit(None, "signup_existing_address", ip)
    # the same answer either way: nobody learns which addresses have accounts
    return {"status": PENDING}


@router.get("/admin/signups", dependencies=[Depends(require_role())], tags=["users"])
async def pending_signups():
    async with SessionLocal() as s:
        rows = (await s.execute(select(User).where(User.approval == PENDING).order_by(User.email))).scalars().all()
    return {"pending": [{"id": str(u.id), "email": u.email, "role": u.role.value} for u in rows]}


async def _pending_user(user_manager, user_id):
    from fastapi_users import exceptions
    try:
        user = await user_manager.get(user_id)
    except exceptions.UserNotExists:
        raise HTTPException(status_code=404, detail="user not found")
    if user.approval != PENDING:
        raise HTTPException(status_code=409, detail="NOT_PENDING")
    return user


@router.post("/admin/signups/{user_id}/approve", tags=["users"])
async def approve(user_id: str, body: ApproveIn, request: Request, admin: User = Depends(require_role()),
                  user_manager=Depends(get_user_manager)):
    import uuid
    user = await _pending_user(user_manager, uuid.UUID(user_id))
    await user_manager.user_db.update(user, {"approval": None, "is_active": True, "is_verified": True, "role": body.role})
    await guard.audit(admin.id, "signup_approved", f"{user.email} as {body.role.value}")
    return {"id": user_id, "email": user.email, "role": body.role.value}


@router.post("/admin/signups/{user_id}/decline", tags=["users"])
async def decline(user_id: str, request: Request, admin: User = Depends(require_role()),
                  user_manager=Depends(get_user_manager)):
    import uuid
    user = await _pending_user(user_manager, uuid.UUID(user_id))
    email = user.email
    # the audit trail stays; its entries no longer point at the account being removed (PostgreSQL enforces the link)
    from sqlalchemy import update
    from .models import AuditLog
    session = user_manager.user_db.session
    await session.execute(update(AuditLog).where(AuditLog.user_id == user.id)
                          .values(user_id=None, target=AuditLog.target + " (" + email + ")"))
    await session.commit()
    await user_manager.user_db.delete(user)            # the address may ask again later
    await guard.audit(admin.id, "signup_declined", email)
    return {"declined": email}


async def pending_count() -> int:
    async with SessionLocal() as s:
        return (await s.execute(select(func.count()).select_from(User).where(User.approval == PENDING))).scalar_one()
