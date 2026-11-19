"""Cloud storage settings page (Dropbox connect from the web) and first-run administrator setup."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.api import storage as ST
from app.auth.models import Role, User
from app.auth.schemas import UserCreate
from app.auth.users import UserManager
from app.distill import dropbox_io as D
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
def auth_file(tmp_path, monkeypatch):
    p = tmp_path / "dropbox_auth.json"
    monkeypatch.setattr(D, "AUTH_PATH", str(p))
    monkeypatch.setattr(ST, "_account", lambda role: {"name": "Test Account", "email": "t@example.com"})
    return p


@pytest.fixture()
def login():
    upgrade()
    for r in Role:
        asyncio.run(_mk("st-%s@example.com" % r.value, r))

    def do(role):
        c = TestClient(app)
        assert c.post("/api/v1/auth/login", data={"username": "st-%s@example.com" % role, "password": PW}).status_code in (200, 204)
        return c
    return do


class FakeFlow:
    def __init__(self, key, **kw):
        self.key, self.kw = key, kw

    def start(self):
        return "https://www.dropbox.com/oauth2/authorize?client_id=" + self.key

    def finish(self, code):
        if code != "GOOD":
            raise ValueError("bad code")
        return type("R", (), {"refresh_token": "RT-" + self.key, "scope": " ".join(self.kw["scope"])})()


def test_only_admins_reach_storage_settings(login, auth_file):
    assert login("reviewer").get("/api/v1/storage/dropbox").status_code == 403
    assert login("viewer").get("/api/v1/storage/dropbox").status_code == 403
    assert login("admin").get("/api/v1/storage/dropbox").status_code == 200


def test_connect_reader_from_the_web_and_tokens_never_leave_the_server(login, auth_file, monkeypatch):
    import dropbox
    monkeypatch.setattr(dropbox, "DropboxOAuth2FlowNoRedirect", FakeFlow)
    c = login("admin")
    r = c.post("/api/v1/storage/dropbox/start", json={"role": "reader", "app_key": "testappkey00001"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://www.dropbox.com/oauth2/authorize")
    assert c.post("/api/v1/storage/dropbox/finish", json={"role": "reader", "code": "BAD"}).status_code == 422
    c.post("/api/v1/storage/dropbox/start", json={"role": "reader", "app_key": "testappkey00001"})
    r = c.post("/api/v1/storage/dropbox/finish", json={"role": "reader", "code": "GOOD"})
    assert r.status_code == 200 and r.json()["account"]["name"] == "Test Account"
    saved = json.loads(auth_file.read_text(encoding="utf-8"))["reader"]
    assert saved["refresh_token"] == "RT-testappkey00001" and "files.content.write" not in saved["scopes"]  # read-only
    st = c.get("/api/v1/storage/dropbox").text
    assert "RT-" not in st and '"connected":true' in st.replace(" ", "")


def test_writer_gets_write_scope_and_finish_without_start_is_refused(login, auth_file, monkeypatch):
    import dropbox
    monkeypatch.setattr(dropbox, "DropboxOAuth2FlowNoRedirect", FakeFlow)
    c = login("admin")
    assert c.post("/api/v1/storage/dropbox/finish", json={"role": "writer", "code": "GOOD"}).status_code == 409
    c.post("/api/v1/storage/dropbox/start", json={"role": "writer", "app_key": "testappkey00002"})
    c.post("/api/v1/storage/dropbox/finish", json={"role": "writer", "code": "GOOD"})
    assert "files.content.write" in json.loads(auth_file.read_text(encoding="utf-8"))["writer"]["scopes"]


def test_bad_app_key_and_role_are_rejected(login, auth_file):
    c = login("admin")
    assert c.post("/api/v1/storage/dropbox/start", json={"role": "reader", "app_key": "not a key!"}).status_code == 422
    assert c.post("/api/v1/storage/dropbox/start", json={"role": "owner", "app_key": "testappkey00001"}).status_code == 422


def test_disconnect_removes_only_that_role(login, auth_file):
    auth_file.write_text(json.dumps({"reader": {"app_key": "k1", "refresh_token": "r1"},
                                     "writer": {"app_key": "k2", "refresh_token": "w1"}}), encoding="utf-8")
    c = login("admin")
    import unittest.mock as m
    with m.patch.object(ST, "_exact_client", lambda role: None):
        assert c.delete("/api/v1/storage/dropbox/reader").json() == {"removed": True}
    data = json.loads(auth_file.read_text(encoding="utf-8"))
    assert "reader" not in data and data["writer"]["refresh_token"] == "w1"


def test_exact_client_never_falls_back_to_the_other_role(auth_file):
    auth_file.write_text(json.dumps({"writer": {"app_key": "k2", "refresh_token": "w1"}}), encoding="utf-8")
    assert ST._exact_client("reader") is None


def test_first_run_setup_only_while_no_user_exists(login, monkeypatch):
    c = TestClient(app)
    assert c.get("/api/v1/setup").json() == {"needs_setup": False}          # users exist (fixture)
    assert c.post("/api/v1/setup", json={"email": "x@example.com", "password": "long-enough-pw"}).status_code == 409
    from app.auth import routes as AR

    async def zero():
        return 0
    monkeypatch.setattr(AR, "_user_count", zero)
    assert c.get("/api/v1/setup").json() == {"needs_setup": True}
    assert c.post("/api/v1/setup", json={"email": "first@example.com", "password": "short"}).status_code == 422
    r = c.post("/api/v1/setup", json={"email": "first-admin@example.com", "password": "long-enough-pw"})
    assert r.status_code == 201 and r.json()["role"] == "admin"
    assert c.post("/api/v1/auth/login", data={"username": "first-admin@example.com", "password": "long-enough-pw"}).status_code in (200, 204)
