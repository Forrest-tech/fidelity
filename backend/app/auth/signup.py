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

PENDING = "pending"            # waits for an administrator
UNVERIFIED = "unverified"      # waits for its owner to click the link in the confirmation e-mail
CONFIRM_HOURS = 24
RESET_MINUTES = 60
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
    from ..ops import mail
    by_email = mail.configured()
    if not exists:
        user = await user_manager.create(UserCreate(email=email, password=body.password, role=Role.viewer,
                                                    is_active=False, is_verified=False))
        state = PENDING
        if by_email:
            try:
                _send_confirmation(user, request)
                state = UNVERIFIED
            except mail.MailError as e:                 # mail is down: an administrator approves instead
                await guard.audit(user.id, "signup_mail_failed", str(e)[:200])
        await user_manager.user_db.update(user, {"approval": state})
        await guard.audit(user.id, "signup_requested", ip)
    else:
        await guard.audit(None, "signup_existing_address", ip)
        if by_email:                                   # tell the owner, as other sites do; say nothing to the asker
            try:
                _send_existing(email, request)
            except mail.MailError:
                pass
    # the same answer either way: nobody learns which addresses have accounts
    return {"status": "verify_email" if by_email else PENDING}


def _token(user, user_manager_cls=None) -> str:
    from fastapi_users.jwt import generate_jwt
    from .users import UserManager
    return generate_jwt({"sub": str(user.id), "email": user.email, "aud": UserManager.verification_token_audience},
                        UserManager.verification_token_secret, CONFIRM_HOURS * 3600)


def _send_confirmation(user, request):
    from urllib.parse import quote
    from ..ops import mail
    link = f"{mail.site_url(request)}/verify-email?token={quote(_token(user))}"
    subject, text, html = mail.confirm_message(link, CONFIRM_HOURS)
    mail.send(user.email, subject, text, html)


def _send_existing(email, request):
    from ..ops import mail
    base = mail.site_url(request)
    text = ("Someone asked for a Fidelity account with this address, which already has one. If it was you, sign in at "
            f"{base}/login or reset your password at {base}/forgot-password. Otherwise ignore this message.\n\n"
            "有人用这个邮箱申请 Fidelity 账号，但这个邮箱已经有账号了。如果是你，请登录或重置密码；否则请忽略。")
    mail.send(email, "Your Fidelity account / 你的 Fidelity 账号", text)


def _send_still_pending(email, request):
    from ..ops import mail
    base = mail.site_url(request)
    text = ("Someone asked to reset the password of the Fidelity account with this address. The account is still "
            "waiting for an administrator's approval, so its password cannot be reset yet. Once it is approved you can "
            f"sign in at {base}/login, or reset the password at {base}/forgot-password. If it was not you, ignore this "
            "message.\n\n"
            "有人申请重置这个邮箱对应的 Fidelity 账号的密码。这个账号还在等管理员批准，暂时不能重置密码。批准后即可登录，"
            "或再重置密码。如果不是你，请忽略此邮件。")
    mail.send(email, "Your Fidelity account is waiting for approval / 你的 Fidelity 账号正在等待批准", text)


async def _after_confirm(user_manager, user):
    """The address is proven. Who still needs an administrator: Settings → Email → approval."""
    from ..ops import mail
    from .oauth import allowed_domains
    policy = mail.load()["approval"]
    in_domain = user.email.rsplit("@", 1)[-1].lower() in allowed_domains()
    if policy == "none" or (policy == "domains" and in_domain):
        await user_manager.user_db.update(user, {"approval": None, "is_active": True})
        return "active"
    await user_manager.user_db.update(user, {"approval": PENDING})
    return PENDING


class TokenIn(BaseModel):
    token: str


class EmailIn(BaseModel):
    email: EmailStr
    altcha: str | None = None


class ResetIn(BaseModel):
    token: str
    password: str


@router.post("/auth/verify-email", tags=["auth"])
async def verify_email(body: TokenIn, request: Request, user_manager=Depends(get_user_manager)):
    from fastapi_users import exceptions
    try:
        user = await user_manager.verify(body.token[:4000], request)
    except exceptions.UserAlreadyVerified:
        raise HTTPException(status_code=409, detail="ALREADY_CONFIRMED")
    except (exceptions.InvalidVerifyToken, Exception):
        raise HTTPException(status_code=400, detail="LINK_INVALID")
    if user.approval != UNVERIFIED:
        return {"status": "active" if user.is_active else PENDING}
    state = await _after_confirm(user_manager, user)
    await guard.audit(user.id, "email_confirmed", state)
    return {"status": state}


@router.post("/auth/verify-email/resend", tags=["auth"])
async def resend_confirmation(body: EmailIn, request: Request, user_manager=Depends(get_user_manager)):
    from fastapi_users import exceptions
    from ..ops import mail
    if (wait := guard.signup_blocked(guard.client_ip(request))):
        return guard.too_many(wait)
    if (reason := captcha.verify(body.altcha)):
        raise HTTPException(status_code=400, detail=reason)
    try:
        user = await user_manager.get_by_email(body.email.strip().lower())
        if user.approval == UNVERIFIED and mail.configured():
            _send_confirmation(user, request)
    except (exceptions.UserNotExists, mail.MailError):
        pass
    return {"status": "sent_if_waiting"}                # the same answer for every address


@router.post("/auth/forgot-password", tags=["auth"])
async def forgot_password(body: EmailIn, request: Request, user_manager=Depends(get_user_manager)):
    from fastapi_users import exceptions
    from ..ops import mail
    if not mail.configured():
        raise HTTPException(status_code=404, detail="EMAIL_OFF")
    if (wait := guard.signup_blocked(guard.client_ip(request))):
        return guard.too_many(wait)
    if (reason := captcha.verify(body.altcha)):
        raise HTTPException(status_code=400, detail=reason)
    try:
        user = await user_manager.get_by_email(body.email.strip().lower())
        if user.approval == UNVERIFIED:            # not confirmed yet: the confirmation link is what they need
            _send_confirmation(user, request)
        elif user.approval == PENDING:             # cannot sign in or reset before approval: say so, not silence
            _send_still_pending(user.email, request)
        else:
            await user_manager.forgot_password(user, request)  # -> UserManager.on_after_forgot_password sends it
        await guard.audit(user.id, "password_reset_requested", guard.client_ip(request))
    except (exceptions.UserNotExists, exceptions.UserInactive, mail.MailError):
        pass
    return {"status": "sent_if_account"}               # the same answer for every address


@router.post("/auth/reset-password", tags=["auth"])
async def reset_password(body: ResetIn, request: Request, user_manager=Depends(get_user_manager)):
    from fastapi_users import exceptions
    try:
        user = await user_manager.reset_password(body.token[:4000], body.password, request)
    except exceptions.InvalidPasswordException as e:
        raise HTTPException(status_code=422, detail="INVALID_PASSWORD: " + str(e.reason))
    except (exceptions.InvalidResetPasswordToken, exceptions.UserInactive, exceptions.UserNotExists):
        raise HTTPException(status_code=400, detail="LINK_INVALID")
    guard.login_succeeded(guard.client_ip(request), user.email)       # a fresh start for its sign-in limits
    await guard.audit(user.id, "password_reset", guard.client_ip(request))
    return {"status": "reset"}


@router.get("/admin/signups", dependencies=[Depends(require_role())], tags=["users"])
async def pending_signups():
    async with SessionLocal() as s:
        rows = (await s.execute(select(User).where(User.approval.in_((PENDING, UNVERIFIED))).order_by(User.email))).scalars().all()
    # "unverified": the owner has not clicked the e-mail link yet; an administrator who knows them may still approve
    return {"pending": [{"id": str(u.id), "email": u.email, "role": u.role.value, "state": u.approval} for u in rows]}


async def _pending_user(user_manager, user_id):
    from fastapi_users import exceptions
    try:
        user = await user_manager.get(user_id)
    except exceptions.UserNotExists:
        raise HTTPException(status_code=404, detail="user not found")
    if user.approval not in (PENDING, UNVERIFIED):
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


# ------------------------------------------------------------------ mail server settings (administrators)
class MailIn(BaseModel):
    host: str | None = None
    port: int | None = None
    security: str | None = None
    username: str | None = None
    password: str | None = None           # write-only; "" removes it
    from_address: str | None = None
    from_name: str | None = None
    site_url: str | None = None
    approval: str | None = None


@router.get("/admin/email", dependencies=[Depends(require_role())], tags=["settings"])
async def get_mail():
    from ..ops import mail
    return mail.public()


@router.put("/admin/email", tags=["settings"])
async def put_mail(body: MailIn, admin: User = Depends(require_role())):
    from ..ops import mail
    try:
        out = mail.save(body.model_dump(exclude_unset=True))
    except (mail.MailError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    await guard.audit(admin.id, "email_settings_changed", out["host"])
    return out


@router.post("/admin/email/test", tags=["settings"])
async def test_mail(admin: User = Depends(require_role())):
    from ..ops import mail
    try:
        mail.send(admin.email, "Fidelity test message / 测试邮件",
                  "This message shows that Fidelity can send e-mail. 这封邮件说明 Fidelity 可以正常发信。")
    except mail.MailError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"sent_to": admin.email}
