"""Lists used by the web application: access control and shapes."""
import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient

from app import config
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
        try:
            await UserManager(SQLAlchemyUserDatabase(s, User)).create(UserCreate(email=email, password=PW, role=role, is_verified=True))
        except Exception:
            pass


@pytest.fixture()
def login(tmp_path, monkeypatch):
    upgrade()
    for r in Role:
        asyncio.run(_mk("ov-%s@example.com" % r.value, r))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    rep = tmp_path / "distilled_reports" / "n2"
    rep.mkdir(parents=True)
    (rep / "j1.json").write_text(json.dumps({"sid": "n2", "rel": "a/Std 2025.pdf", "verdict": "PASS", "files": 3, "pages": 10, "instruction_like": 0}))
    (rep / "j2.json").write_text(json.dumps({"sid": "n2", "rel": "b.pdf", "verdict": "FAIL", "files": 1, "pages": 2, "instruction_like": 0}))

    def do(role):
        c = TestClient(app)
        assert c.post("/api/v1/auth/login", data={"username": "ov-%s@example.com" % role, "password": PW}).status_code in (200, 204)
        return c
    return do


def test_lists_require_login():
    c = TestClient(app)
    for p in ("/api/v1/jobs", "/api/v1/documents", "/api/v1/overview", "/api/v1/admin/users"):
        assert c.get(p).status_code == 401, p


def test_documents_list_and_filter(login):
    c = login("viewer")
    docs = c.get("/api/v1/documents").json()
    assert {d["rel"] for d in docs} == {"a/Std 2025.pdf", "b.pdf"}
    assert [d["rel"] for d in c.get("/api/v1/documents", params={"verdict": "FAIL"}).json()] == ["b.pdf"]


def test_overview_counts_and_attention(login):
    o = login("viewer").get("/api/v1/overview").json()
    assert o["documents"] == {"PASS": 1, "FAIL": 1}
    assert [x["rel"] for x in o["needs_attention"]] == ["b.pdf"]


def test_jobs_list_is_a_list(login):
    r = login("viewer").get("/api/v1/jobs", params={"limit": 5})
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_user_list_is_admin_only(login):
    assert login("reviewer").get("/api/v1/admin/users").status_code == 403
    assert login("viewer").get("/api/v1/admin/users").status_code == 403
    emails = [u["email"] for u in login("admin").get("/api/v1/admin/users").json()]
    assert "ov-admin@example.com" in emails
