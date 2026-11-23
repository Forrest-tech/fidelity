"""Sign-up with an administrator's approval (requirements v2, U-1): bot check, rate limit, no account
enumeration, pending accounts cannot work until approved, approve with a role, decline, switch it off."""
import asyncio

import pytest
from fastapi.testclient import TestClient
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import select

from app.auth import captcha, guard
from app.auth.models import Role, User
from app.auth.schemas import UserCreate
from app.auth.users import UserManager
from app.main import app
from app.migrate import upgrade
from app.orm import SessionLocal

PW = "correct-horse-battery"
ADMIN = "signup-admin@example.com"


async def _mk(email, role):
    async with SessionLocal() as s:
        try:
            await UserManager(SQLAlchemyUserDatabase(s, User)).create(
                UserCreate(email=email, password=PW, role=role, is_verified=True, is_active=True))
        except Exception:
            pass


async def _user(email):
    async with SessionLocal() as s:
        return (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def _audit_for(email):
    from app.auth.models import AuditLog
    async with SessionLocal() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.target.contains(email)))).scalars().all()
        return [(r.action, r.user_id) for r in rows]


@pytest.fixture(scope="module", autouse=True)
def admin():
    from app import db
    db.init_trust()
    upgrade()
    asyncio.run(_mk(ADMIN, Role.admin))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("FIDELITY_CAPTCHA", "on")
    monkeypatch.setenv("FIDELITY_CAPTCHA_COST", "10")
    monkeypatch.setenv("FIDELITY_CAPTCHA_MAX", "50")
    guard.reset()
    captcha.reset()
    yield
    guard.reset()
    captcha.reset()


def client(ip="testclient"):
    return TestClient(app, client=(ip, 50000), follow_redirects=False)


def proof(c):
    return captcha.solve_for_tests(c.get("/api/v1/auth/challenge").json())


def signup(c, email, pw=PW, with_proof=True):
    return c.post("/api/v1/auth/signup", json={"email": email, "password": pw, **({"altcha": proof(c)} if with_proof else {})})


def login(c, email, pw=PW):
    return c.post("/api/v1/auth/login", data={"username": email, "password": pw, "altcha": proof(c)})


def as_admin():
    c = client("10.0.0.9")
    assert login(c, ADMIN).status_code == 204
    return c


def test_the_sign_in_page_is_told_that_sign_up_is_open():
    assert client().get("/api/v1/auth/options").json()["signup"] is True


def test_a_new_account_waits_for_approval_and_says_so_when_its_owner_signs_in():
    c = client("10.0.1.1")
    r = signup(c, "New.Person@Example.com")
    assert r.status_code == 201 and r.json() == {"status": "pending"}
    u = asyncio.run(_user("new.person@example.com"))
    assert u.approval == "pending" and u.is_active is False and u.role == Role.viewer
    r = login(c, "new.person@example.com")
    assert r.status_code == 403 and r.json()["detail"] == "ACCOUNT_PENDING"
    assert login(c, "new.person@example.com", "wrong-password-123").json()["detail"] == "LOGIN_BAD_CREDENTIALS"   # a stranger learns nothing


def test_asking_for_an_existing_address_gets_the_same_answer_and_changes_nothing():
    c = client("10.0.1.2")
    r = signup(c, ADMIN, pw="another-password-9")
    assert r.status_code == 201 and r.json() == {"status": "pending"}
    assert login(c, ADMIN).status_code == 204                          # the real account is untouched


def test_sign_up_needs_the_human_check_and_a_long_enough_password():
    c = client("10.0.1.3")
    assert signup(c, "nocheck@example.com", with_proof=False).json()["detail"] == "CAPTCHA_REQUIRED"
    r = signup(c, "short@example.com", pw="short")
    assert r.status_code == 422 and r.json()["detail"].startswith("INVALID_PASSWORD")
    assert asyncio.run(_user("short@example.com")) is None
    assert c.post("/api/v1/auth/signup", json={"email": "not-an-address", "password": PW, "altcha": proof(c)}).status_code == 422


def test_one_address_cannot_ask_for_many_accounts():
    c = client("10.0.1.4")
    for i in range(5):
        assert signup(c, f"bulk{i}@example.com").status_code == 201
    r = signup(c, "bulk5@example.com")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_an_administrator_approves_with_a_role_and_the_person_can_then_sign_in():
    c = client("10.0.1.5")
    signup(c, "approve-me@example.com")
    a = as_admin()
    pending = a.get("/api/v1/admin/signups").json()["pending"]
    me = next(p for p in pending if p["email"] == "approve-me@example.com")
    r = a.post(f"/api/v1/admin/signups/{me['id']}/approve", json={"role": "reviewer"})
    assert r.status_code == 200 and r.json()["role"] == "reviewer"
    assert login(client("10.0.1.6"), "approve-me@example.com").status_code == 204
    assert a.post(f"/api/v1/admin/signups/{me['id']}/approve", json={"role": "viewer"}).status_code == 409   # only once
    items = a.get("/api/v1/notifications").json()["items"]
    assert not any(i["type"] == "signup" and "approve-me" in str(i) for i in items)


def test_a_declined_request_is_removed_and_the_address_may_ask_again():
    c = client("10.0.1.7")
    signup(c, "decline-me@example.com")
    a = as_admin()
    assert any(i["type"] == "signup" for i in a.get("/api/v1/notifications").json()["items"])
    uid = next(p["id"] for p in a.get("/api/v1/admin/signups").json()["pending"] if p["email"] == "decline-me@example.com")
    assert a.post(f"/api/v1/admin/signups/{uid}/decline").status_code == 200
    assert asyncio.run(_user("decline-me@example.com")) is None
    assert asyncio.run(_audit_for("decline-me@example.com"))          # the request stays in the audit trail
    assert signup(client("10.0.1.8"), "decline-me@example.com").status_code == 201


def test_only_administrators_see_and_approve_requests():
    c = client("10.0.1.9")
    signup(c, "nosy@example.com")
    assert c.get("/api/v1/admin/signups").status_code == 401


def test_sign_up_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("FIDELITY_SIGNUP", "off")
    c = client("10.0.2.1")
    assert c.get("/api/v1/auth/options").json()["signup"] is False
    assert signup(c, "closed@example.com").status_code == 404
