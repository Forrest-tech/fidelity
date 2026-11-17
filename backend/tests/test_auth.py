"""Auth and role enforcement on /api/v1 (spec section 8, Phase 1 done-when)."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.auth.models import Role, User
from app.auth.schemas import UserCreate
from app.auth.users import UserManager
from app.main import app
from app.migrate import upgrade
from app.orm import SessionLocal
from fastapi_users.db import SQLAlchemyUserDatabase

PW = "correct-horse-battery"


async def _mk(email, role):
    async with SessionLocal() as s:
        await UserManager(SQLAlchemyUserDatabase(s, User)).create(
            UserCreate(email=email, password=PW, role=role, is_verified=True))


@pytest.fixture(scope="module")
def users():
    upgrade()
    for r in Role:
        asyncio.run(_mk("%s@example.com" % r.value, r))


def client():
    # no `with`: do not run the app's startup (instance lock, worker threads)
    return TestClient(app)


def login(role):
    c = client()
    r = c.post("/api/v1/auth/login", data={"username": "%s@example.com" % role, "password": PW})
    assert r.status_code in (200, 204), r.text
    return c


def test_unauthenticated_requests_refused(users):
    c = client()
    for path in ("/api/v1/sources", "/api/v1/files", "/api/v1/stats", "/api/v1/me", "/api/v1/users/me"):
        assert c.get(path).status_code == 401, path


def test_legacy_unversioned_api_is_off_by_default(users):
    assert client().get("/api/sources").status_code in (404, 405)


def test_wrong_password_refused(users):
    r = client().post("/api/v1/auth/login", data={"username": "admin@example.com", "password": "nope-nope-nope"})
    assert r.status_code == 400


def test_login_sets_httponly_cookie(users):
    r = client().post("/api/v1/auth/login", data={"username": "viewer@example.com", "password": PW})
    assert "httponly" in r.headers["set-cookie"].lower()


def test_me_returns_role(users):
    assert login("reviewer").get("/api/v1/me").json()["role"] == "reviewer"


def test_viewer_can_read_but_not_mutate(users):
    c = login("viewer")
    assert c.get("/api/v1/sources").status_code == 200
    assert c.post("/api/v1/sources", json={}).status_code == 403
    assert c.delete("/api/v1/sources/x").status_code == 403


def test_reviewer_passes_role_gate(users):
    # an invalid body yields 422 (validation), i.e. the role gate was passed
    assert login("reviewer").post("/api/v1/sources", json={}).status_code != 403


def test_user_management_is_admin_only(users):
    body = {"email": "new@example.com", "password": PW, "role": "viewer"}
    assert login("reviewer").post("/api/v1/users/register", json=body).status_code == 403
    assert login("admin").post("/api/v1/users/register", json=body).status_code == 201


def test_weak_password_rejected(users):
    body = {"email": "weak@example.com", "password": "short", "role": "viewer"}
    assert login("admin").post("/api/v1/users/register", json=body).status_code == 400
