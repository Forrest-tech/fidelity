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


# ------------------------------------------------------------------ Google Drive connection
from app.distill import gdrive_io as G  # noqa: E402

CID = "123456789012-testclientid.apps.googleusercontent.com"


@pytest.fixture()
def gauth(tmp_path, monkeypatch):
    p = tmp_path / "google_auth.json"
    monkeypatch.setattr(G, "AUTH_PATH", str(p))
    monkeypatch.setattr(ST, "_google_account", lambda role: {"name": "G User", "email": "g@example.com"})
    return p


def test_google_client_is_validated_and_secret_never_returned(login, gauth):
    c = login("admin")
    assert c.put("/api/v1/storage/google/client", json={"client_id": "nope", "client_secret": "x" * 20}).status_code == 422
    assert c.put("/api/v1/storage/google/client", json={"client_id": CID, "client_secret": "fake-secret-for-tests"}).status_code == 200
    st = c.get("/api/v1/storage/google")
    j = st.json()
    assert j["client_configured"] and j["client_id"] == CID and "fake-secret-for-tests" not in st.text
    assert j["redirect_uri"].endswith("/api/v1/storage/google/callback")
    assert login("reviewer").get("/api/v1/storage/google").status_code == 403


def test_google_connect_uses_the_read_only_scope_and_saves_the_token(login, gauth, monkeypatch):
    c = login("admin")
    c.put("/api/v1/storage/google/client", json={"client_id": CID, "client_secret": "fake-secret-for-tests"})
    url = c.post("/api/v1/storage/google/start", json={"role": "reader"}).json()["url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/auth") and "drive.readonly" in url and "access_type=offline" in url
    import urllib.parse as up
    state = up.parse_qs(up.urlparse(url).query)["state"][0]
    from google_auth_oauthlib.flow import Flow

    def fake_fetch(self, code=None, **kw):
        assert code == "AUTHCODE"
        self.oauth2session.token = {"access_token": "a", "refresh_token": "fake-refresh-for-tests",
                                    "scope": G.SCOPES["reader"], "token_type": "Bearer", "expires_at": 4102444800}
        return self.oauth2session.token
    monkeypatch.setattr(Flow, "fetch_token", fake_fetch)
    r = c.get(f"/api/v1/storage/google/callback?state={state}&code=AUTHCODE", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings?google=connected&role=reader"
    assert json.loads(gauth.read_text(encoding="utf-8"))["reader"]["refresh_token"] == "fake-refresh-for-tests"
    st = c.get("/api/v1/storage/google")
    assert st.json()["reader"]["connected"] and "fake-refresh-for-tests" not in st.text
    # the same state cannot be used twice
    r = c.get(f"/api/v1/storage/google/callback?state={state}&code=AUTHCODE", follow_redirects=False)
    assert "google=error" in r.headers["location"]


def test_google_disconnect_removes_only_that_role(login, gauth, monkeypatch):
    gauth.write_text(json.dumps({"client": {"client_id": CID, "client_secret": "s" * 12},
                                 "reader": {"refresh_token": "r"}, "writer": {"refresh_token": "w"}}), encoding="utf-8")
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: None)      # no network in tests
    c = login("admin")
    assert c.delete("/api/v1/storage/google/writer").json() == {"removed": True}
    data = json.loads(gauth.read_text(encoding="utf-8"))
    assert "writer" not in data and data["reader"]["refresh_token"] == "r"


# ------------------------------------------------------------------ one click (browser goes to Dropbox and back)
class FakeWebFlow:
    """dropbox.DropboxOAuth2Flow stand-in: start() stores a CSRF token in the session; finish() checks it."""
    n = 0

    def __init__(self, key, redirect_uri, session, csrf_key, **kw):
        self.key, self.redirect, self.session, self.csrf_key, self.kw = key, redirect_uri, session, csrf_key, kw

    def start(self):
        FakeWebFlow.n += 1
        self.session[self.csrf_key] = f"csrf{FakeWebFlow.n}"
        return f"https://www.dropbox.com/oauth2/authorize?state={self.session[self.csrf_key]}&redirect_uri={self.redirect}"

    def finish(self, q):
        if q["state"] != self.session[self.csrf_key] or q["code"] != "GOOD":
            raise ValueError("bad state or code")
        return type("R", (), {"refresh_token": f"RT-{self.session[self.csrf_key]}", "scope": " ".join(self.kw["scope"])})()


def _state(url):
    return url.split("state=")[1].split("&")[0]


def _local(role="admin"):
    """The Mac opens the app at http://127.0.0.1:8000: the one address (with localhost and https) Dropbox returns to."""
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    assert c.post("/api/v1/auth/login", data={"username": f"st-{role}@example.com", "password": PW}).status_code in (200, 204)
    return c


def test_one_click_connects_read_then_write_and_comes_back(login, auth_file, monkeypatch):
    import dropbox
    monkeypatch.setattr(dropbox, "DropboxOAuth2Flow", FakeWebFlow)
    monkeypatch.setattr(ST, "_pending_key", {})
    login("admin")
    c = _local()
    r = c.get("/api/v1/storage/dropbox/connect?role=both")
    assert r.status_code == 428                                         # a new server asks for the app key once
    assert c.get("/api/v1/storage/dropbox/connect?role=both&key=bad!").status_code == 422
    r = c.get("/api/v1/storage/dropbox/connect?role=both&key=companyappkey01")
    assert r.status_code == 200 and r.json()["redirect_uri"].endswith("/api/v1/storage/dropbox/callback")
    s1 = _state(r.json()["url"])
    r = c.get(f"/api/v1/storage/dropbox/callback?state={s1}&code=GOOD", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"].startswith("https://www.dropbox.com/oauth2/")  # on to write
    s2 = _state(r.headers["location"])
    r = c.get(f"/api/v1/storage/dropbox/callback?state={s2}&code=GOOD", follow_redirects=False)
    assert r.headers["location"] == "/settings/storage?dropbox=connected"
    saved = json.loads(auth_file.read_text(encoding="utf-8"))
    assert "files.content.write" not in saved["reader"]["scopes"] and "files.content.write" in saved["writer"]["scopes"]
    assert saved["reader"]["app_key"] == saved["writer"]["app_key"] == "companyappkey01"
    monkeypatch.setattr(ST, "_pending_key", {})
    assert c.get("/api/v1/storage/dropbox/connect?role=both").status_code == 200   # then never again: it is saved


def test_one_click_cancel_replay_and_unknown_state_change_nothing(login, auth_file, monkeypatch):
    import dropbox
    monkeypatch.setattr(dropbox, "DropboxOAuth2Flow", FakeWebFlow)
    monkeypatch.setenv("FIDELITY_DROPBOX_APP_KEY", "envappkey000001")
    login("admin")
    c = _local()
    s = _state(c.get("/api/v1/storage/dropbox/connect?role=reader").json()["url"])
    r = c.get(f"/api/v1/storage/dropbox/callback?state={s}&error=access_denied", follow_redirects=False)
    assert r.headers["location"].endswith("dropbox=cancelled")
    r = c.get(f"/api/v1/storage/dropbox/callback?state={s}&code=GOOD", follow_redirects=False)   # used once only
    assert r.headers["location"].endswith("dropbox=expired")
    r = c.get("/api/v1/storage/dropbox/callback?state=forged&code=GOOD", follow_redirects=False)
    assert r.headers["location"].endswith("dropbox=expired")
    assert not auth_file.exists() or "reader" not in json.loads(auth_file.read_text(encoding="utf-8"))
    assert _local("reviewer").get("/api/v1/storage/dropbox/connect").status_code == 403


def test_one_click_needs_localhost_or_https(login, auth_file):
    c = TestClient(app, base_url="http://10.0.0.5:8000")
    assert c.post("/api/v1/auth/login", data={"username": "st-admin@example.com", "password": PW}).status_code in (200, 204)
    r = c.get("/api/v1/storage/dropbox/connect")
    assert r.status_code == 409 and "127.0.0.1" in r.json()["detail"]
