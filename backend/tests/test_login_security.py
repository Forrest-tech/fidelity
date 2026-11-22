"""Sign-in: bot protection (ALTCHA), rate limits, and Google/Microsoft/GitHub/company SSO sign-in.

Real values, boundaries and bad input: a correct solution, a reused one, a tampered one, an expired one,
an oversized one; the limits at exactly N and N+1; OAuth with a known, unknown, unverified, inactive or
allowed-domain account, a forged state, a cancelled sign-in and an open-redirect attempt.
"""
import asyncio
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import func, select

from app.auth import captcha, guard, oauth
from app.auth.models import AuditLog, OAuthAccount, Role, User
from app.auth.schemas import UserCreate
from app.auth.users import UserManager
from app.main import app
from app.migrate import upgrade
from app.orm import SessionLocal

PW = "correct-horse-battery"


async def _mk(email, role, active=True):
    async with SessionLocal() as s:
        mgr = UserManager(SQLAlchemyUserDatabase(s, User))
        try:
            u = await mgr.create(UserCreate(email=email, password=PW, role=role, is_verified=True, is_active=active))
        except Exception:
            return


@pytest.fixture(scope="module", autouse=True)
def users():
    upgrade()
    asyncio.run(_mk("sec-reviewer@example.com", Role.reviewer))
    asyncio.run(_mk("sec-viewer@example.com", Role.viewer))
    asyncio.run(_mk("sec-off@example.com", Role.viewer, active=False))


@pytest.fixture(autouse=True)
def clean():
    guard.reset()
    captcha.reset()
    yield
    guard.reset()
    captcha.reset()


@pytest.fixture
def captcha_on(monkeypatch):
    monkeypatch.setenv("FIDELITY_CAPTCHA", "on")
    monkeypatch.setenv("FIDELITY_CAPTCHA_COST", "10")
    monkeypatch.setenv("FIDELITY_CAPTCHA_MAX", "50")


def client(ip="testclient"):
    return TestClient(app, client=(ip, 50000), follow_redirects=False)


def solved(c):
    r = c.get("/api/v1/auth/challenge")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    return captcha.solve_for_tests(r.json())


def creds(email="sec-reviewer@example.com", pw=PW, **extra):
    return {"username": email, "password": pw, **extra}


# ------------------------------------------------------------------ bot protection
def test_options_report_captcha_and_no_providers_by_default(captcha_on):
    j = client().get("/api/v1/auth/options").json()
    assert j == {"providers": [], "captcha": True}


def test_login_without_captcha_is_refused_when_on(captcha_on):
    r = client().post("/api/v1/auth/login", data=creds())
    assert r.status_code == 400 and r.json()["detail"] == "CAPTCHA_REQUIRED"


def test_login_with_solved_captcha_works_once(captcha_on):
    c = client()
    p = solved(c)
    assert c.post("/api/v1/auth/login", data=creds(altcha=p)).status_code == 204
    assert c.get("/api/v1/me").json()["email"] == "sec-reviewer@example.com"
    r = client().post("/api/v1/auth/login", data=creds(altcha=p))          # the same solution again
    assert r.status_code == 400 and r.json()["detail"] == "CAPTCHA_REUSED"


@pytest.mark.parametrize("bad", ["", "not-base64!!", "e30=", "x" * 8001])
def test_garbage_captcha_is_refused(captcha_on, bad):
    r = client().post("/api/v1/auth/login", data=creds(altcha=bad))
    assert r.status_code == 400 and r.json()["detail"] in ("CAPTCHA_REQUIRED", "CAPTCHA_INVALID")


def test_tampered_captcha_is_refused(captcha_on):
    import base64
    import json
    c = client()
    d = json.loads(base64.b64decode(solved(c)))
    d["challenge"]["parameters"]["cost"] = 1                                   # make the work easier: signature breaks
    r = c.post("/api/v1/auth/login", data=creds(altcha=base64.b64encode(json.dumps(d).encode()).decode()))
    assert r.status_code == 400 and r.json()["detail"] == "CAPTCHA_INVALID"


def test_wrong_solution_is_refused(captcha_on):
    import base64
    import json
    c = client()
    d = json.loads(base64.b64decode(solved(c)))
    d["solution"]["counter"] += 1
    d["solution"]["derivedKey"] = "00" * 32
    r = c.post("/api/v1/auth/login", data=creds(altcha=base64.b64encode(json.dumps(d).encode()).decode()))
    assert r.status_code == 400 and r.json()["detail"] == "CAPTCHA_INVALID"


def test_expired_captcha_is_refused(captcha_on, monkeypatch):
    c = client()
    p = solved(c)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + captcha.TTL_SECONDS + 5)
    r = c.post("/api/v1/auth/login", data=creds(altcha=p))
    assert r.status_code == 400 and r.json()["detail"] == "CAPTCHA_EXPIRED"


def test_captcha_failure_does_not_count_as_a_wrong_password(captcha_on):
    c = client()
    for _ in range(guard.MAX_FAILURES + 2):
        assert c.post("/api/v1/auth/login", data=creds()).status_code == 400   # no captcha
    assert c.post("/api/v1/auth/login", data=creds(altcha=solved(c))).status_code == 204


def test_first_run_setup_needs_captcha_when_on(captcha_on, monkeypatch):
    from app.auth import routes

    async def none():
        return 0
    monkeypatch.setattr(routes, "_user_count", none)
    r = client().post("/api/v1/setup", json={"email": "first@example.com", "password": "long-enough-pw"})
    assert r.status_code == 400 and r.json()["detail"] == "CAPTCHA_REQUIRED"


def test_first_run_setup_signs_the_new_admin_in(monkeypatch):
    from app.auth import routes

    async def none():
        return 0
    monkeypatch.setattr(routes, "_user_count", none)
    c = client()
    r = c.post("/api/v1/setup", json={"email": "setup-signs-in@example.com", "password": "long-enough-pw"})
    assert r.status_code == 201 and "fidelity_session" in r.headers.get("set-cookie", "")
    assert c.get("/api/v1/me").json()["role"] == "admin"


# ------------------------------------------------------------------ rate limits
def test_five_failures_per_address_then_locked_with_retry_after():
    c = client("10.0.0.1")
    codes = [c.post("/api/v1/auth/login", data=creds(pw="wrong-wrong-wrong")).status_code for _ in range(5)]
    assert codes == [400] * 5
    r = c.post("/api/v1/auth/login", data=creds())                            # right password, still locked
    assert r.status_code == 429 and 1 <= int(r.headers["retry-after"]) <= guard.WINDOW_SECONDS
    assert client("10.0.0.2").post("/api/v1/auth/login", data=creds()).status_code == 204   # other address fine


def test_one_account_guessed_from_many_addresses_is_locked():
    for i in range(10):                                                        # 10 addresses, one failure each
        assert client("10.1.0.%d" % i).post("/api/v1/auth/login", data=creds(pw="nope-nope-nope")).status_code == 400
    r = client("10.1.0.99").post("/api/v1/auth/login", data=creds())
    assert r.status_code == 429
    # another account from the same new address is not affected
    assert client("10.1.0.99").post("/api/v1/auth/login", data=creds("sec-viewer@example.com")).status_code == 204


def test_account_limit_ignores_case_and_spaces():
    for i in range(10):
        client("10.2.0.%d" % i).post("/api/v1/auth/login", data=creds(" SEC-Reviewer@Example.com ", pw="nope-nope-nope"))
    assert client("10.2.0.50").post("/api/v1/auth/login", data=creds()).status_code == 429


def test_success_clears_the_failures():
    c = client("10.3.0.1")
    for _ in range(4):
        c.post("/api/v1/auth/login", data=creds(pw="wrong-wrong-wrong"))
    assert c.post("/api/v1/auth/login", data=creds()).status_code == 204
    for _ in range(4):
        assert c.post("/api/v1/auth/login", data=creds(pw="wrong-wrong-wrong")).status_code == 400


def test_other_sign_in_endpoints_are_throttled_at_60_a_minute():
    c = client("10.4.0.1")
    codes = [c.get("/api/v1/auth/challenge").status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429


def test_inactive_user_cannot_sign_in():
    r = client().post("/api/v1/auth/login", data=creds("sec-off@example.com"))
    assert r.status_code == 400 and r.json()["detail"] == "LOGIN_BAD_CREDENTIALS"


@pytest.mark.parametrize("email", ["", " ", "a" * 400 + "@example.com", "no-at-sign", "' OR 1=1 --", "名字@例子.公司"])
def test_odd_usernames_get_a_plain_refusal(email):
    r = client().post("/api/v1/auth/login", data=creds(email, pw="whatever-it-is"))
    assert r.status_code in (400, 422)


def test_logout_needs_a_session_and_ends_it():
    c = client()
    assert c.post("/api/v1/auth/logout").status_code == 401
    assert c.post("/api/v1/auth/login", data=creds()).status_code == 204
    assert c.post("/api/v1/auth/logout").status_code == 204
    assert c.get("/api/v1/me").status_code == 401


# ------------------------------------------------------------------ sign in with a provider
class FakeProvider:
    """Stands in for httpx-oauth's Google/GitHub/OpenID client (the network part)."""
    name = "oidc"

    def __init__(self, email="sec-reviewer@example.com", account="acc-1"):
        self.email, self.account, self.seen = email, account, {}

    async def get_authorization_url(self, redirect_uri, state, scope=None, code_challenge=None,
                                    code_challenge_method=None, extras_params=None):
        self.seen.update(redirect_uri=redirect_uri, challenge=code_challenge, method=code_challenge_method)
        return "https://idp.example.test/authorize?state=" + state

    async def get_access_token(self, code, redirect_uri, code_verifier=None):
        import base64
        import hashlib
        expect = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
        assert expect == self.seen["challenge"], "PKCE verifier does not match"
        return {"access_token": "provider-secret-token", "refresh_token": "provider-refresh"}

    async def get_id_email(self, token):
        return self.account, self.email


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(oauth, "configured", lambda: {"oidc": (fake, "Company SSO")})
    return fake


def start(c, nxt="/distill"):
    r = c.get("/api/v1/auth/oauth/oidc/authorize", params={"next": nxt})
    assert r.status_code == 302
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    return state


def test_options_list_configured_providers(provider):
    assert client().get("/api/v1/auth/options").json()["providers"] == [{"id": "oidc", "label": "Company SSO"}]


def test_unknown_provider_is_404():
    assert client().get("/api/v1/auth/oauth/myspace/authorize").status_code == 404


def test_authorize_uses_pkce_s256_and_our_callback(provider):
    c = client()
    start(c)
    assert provider.seen["method"] == "S256" and len(provider.seen["challenge"]) == 43
    assert provider.seen["redirect_uri"].endswith("/api/v1/auth/oauth/oidc/callback")
    assert c.cookies.get(oauth.STATE_COOKIE)


def test_known_user_signs_in_and_lands_on_next(provider):
    c = client()
    state = start(c, "/distill")
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": state})
    assert r.status_code == 302 and r.headers["location"] == "/distill"
    assert c.get("/api/v1/me").json()["email"] == "sec-reviewer@example.com"

    async def linked():
        async with SessionLocal() as s:
            return (await s.execute(select(OAuthAccount).where(OAuthAccount.account_id == "acc-1"))).scalars().all()
    rows = asyncio.run(linked())
    assert len(rows) == 1 and rows[0].access_token == "-" and rows[0].refresh_token is None   # no provider secrets kept


def test_second_sign_in_reuses_the_link(provider):
    for _ in range(2):
        c = client()
        assert c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "x", "state": start(c)}).status_code == 302

    async def n():
        async with SessionLocal() as s:
            return (await s.execute(select(func.count()).select_from(OAuthAccount).where(OAuthAccount.account_id == "acc-1"))).scalar()
    assert asyncio.run(n()) == 1


def test_unknown_person_is_refused_with_a_reason(provider):
    provider.email, provider.account = "stranger@elsewhere.test", "acc-stranger"
    c = client()
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": start(c)})
    assert r.headers["location"] == "/login?error=oauth_no_account"
    assert c.get("/api/v1/me").status_code == 401


def test_allowed_domain_creates_a_viewer(provider, monkeypatch):
    monkeypatch.setenv("FIDELITY_OAUTH_ALLOWED_DOMAINS", "@Newco.Example.com, other.example.org")
    provider.email, provider.account = "new.person@newco.example.com", "acc-new"
    c = client()
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": start(c)})
    assert r.status_code == 302 and r.headers["location"] == "/distill"
    assert c.get("/api/v1/me").json()["role"] == "viewer"


def test_inactive_user_is_refused(provider):
    provider.email, provider.account = "sec-off@example.com", "acc-off"
    c = client()
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": start(c)})
    assert r.headers["location"] == "/login?error=oauth_inactive"


def test_no_verified_email_is_refused(provider):
    provider.email = None
    c = client()
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": start(c)})
    assert r.headers["location"] == "/login?error=oauth_no_email"


def test_forged_or_foreign_state_is_refused(provider):
    c = client()
    start(c)
    other = client()
    foreign_state = start(other)                                               # someone else's sign-in
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": foreign_state})
    assert r.headers["location"] == "/login?error=oauth_failed"
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": "garbage"})
    assert r.headers["location"] == "/login?error=oauth_failed"


def test_missing_cookie_is_refused(provider):
    c = client()
    state = start(c)
    c.cookies.clear()
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": state})
    assert r.headers["location"] == "/login?error=oauth_failed"


def test_cancel_at_the_provider(provider):
    r = client().get("/api/v1/auth/oauth/oidc/callback", params={"error": "access_denied", "state": "s"})
    assert r.headers["location"] == "/login?error=oauth_cancelled"


@pytest.mark.parametrize("nxt,landing", [("//evil.example/x", "/"), ("https://evil.example", "/"), ("/\\evil", "/"),
                                         ("/login", "/"), ("", "/"), ("/documents?x=1", "/documents?x=1")])
def test_next_only_goes_to_a_page_of_this_site(provider, nxt, landing):
    c = client()
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": start(c, nxt)})
    assert r.headers["location"] == landing


def test_provider_failure_returns_to_login(provider):
    async def boom(*a, **k):
        raise RuntimeError("network down")
    provider.get_access_token = boom
    c = client()
    r = c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": start(c)})
    assert r.headers["location"] == "/login?error=oauth_failed"


def test_providers_come_from_settings(monkeypatch):
    for k in ("GOOGLE", "MICROSOFT", "GITHUB"):
        monkeypatch.setenv("FIDELITY_OAUTH_%s_CLIENT_ID" % k, "id")
        monkeypatch.setenv("FIDELITY_OAUTH_%s_CLIENT_SECRET" % k, "secret")
    monkeypatch.setenv("FIDELITY_OAUTH_GOOGLE_CLIENT_SECRET", "")              # half-configured: not offered
    got = [p["id"] for p in oauth.providers_public()]
    assert got == ["microsoft", "github"]


def test_github_uses_only_a_verified_address():
    gh = oauth.VerifiedGitHub("id", "secret")

    async def profile(_t):
        return {"id": 7, "email": "public@unverified.test"}

    async def emails(_t):
        return [{"email": "primary@unverified.test", "primary": True, "verified": False},
                {"email": "ok@verified.test", "primary": False, "verified": True}]
    gh.get_profile, gh.get_emails = profile, emails
    assert asyncio.run(gh.get_id_email("t")) == ("7", "ok@verified.test")

    async def none(_t):
        return [{"email": "x@y.test", "primary": True, "verified": False}]
    gh.get_emails = none
    assert asyncio.run(gh.get_id_email("t")) == ("7", None)


def test_oidc_refuses_an_address_marked_unverified():
    oidc = oauth.VerifiedOpenID.__new__(oauth.VerifiedOpenID)

    async def profile(_t):
        return {"sub": "s1", "email": "a@b.test", "email_verified": False}
    oidc.get_profile = profile
    assert asyncio.run(oidc.get_id_email("t")) == ("s1", None)


def test_oauth_sign_ins_are_audited(provider):
    c = client()
    c.get("/api/v1/auth/oauth/oidc/callback", params={"code": "abc", "state": start(c)})

    async def n():
        async with SessionLocal() as s:
            return (await s.execute(select(func.count()).select_from(AuditLog).where(AuditLog.action == "login_oauth"))).scalar()
    assert asyncio.run(n()) >= 1
