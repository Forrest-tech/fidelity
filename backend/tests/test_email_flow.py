"""Sign-up by e-mail and password reset by e-mail, the standard way (requirements v2, U-1): the links are read out
of the actual messages, as a person would click them."""
import asyncio
import email
import email.policy
import glob
import os
import re
from urllib.parse import unquote

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
from app.ops import mail
from app.orm import SessionLocal

PW = "correct-horse-battery"
ADMIN = "mail-admin@example.com"


async def _mk(email_, role):
    async with SessionLocal() as s:
        try:
            await UserManager(SQLAlchemyUserDatabase(s, User)).create(
                UserCreate(email=email_, password=PW, role=role, is_verified=True, is_active=True))
        except Exception:
            pass


async def _user(email_):
    async with SessionLocal() as s:
        return (await s.execute(select(User).where(User.email == email_))).scalar_one_or_none()


@pytest.fixture(scope="module", autouse=True)
def admin():
    from app import db
    db.init_trust()
    upgrade()
    asyncio.run(_mk(ADMIN, Role.admin))


def _join_notices():
    """Sign-up notices go out on a background thread: let them land in this test's outbox, not the next one's."""
    import threading
    for t in threading.enumerate():
        if t.name == "signup-notice":
            t.join(10)


@pytest.fixture()
def outbox(tmp_path, monkeypatch):
    box = tmp_path / "outbox"
    monkeypatch.setenv("FIDELITY_MAIL_OUTBOX", str(box))
    monkeypatch.setenv("FIDELITY_CAPTCHA", "on")
    monkeypatch.setenv("FIDELITY_CAPTCHA_COST", "10")
    monkeypatch.setenv("FIDELITY_CAPTCHA_MAX", "50")
    monkeypatch.setattr(mail, "PATH", str(tmp_path / "email_settings.json"))
    guard.reset()
    captcha.reset()
    yield box
    _join_notices()
    guard.reset()
    captcha.reset()


def client(ip):
    return TestClient(app, client=(ip, 50000), follow_redirects=False)


def proof(c):
    return captcha.solve_for_tests(c.get("/api/v1/auth/challenge").json())


def mails(box, to):
    out = []
    for p in sorted(glob.glob(os.path.join(box, "*.eml"))):
        with open(p, "rb") as f:
            m = email.message_from_binary_file(f, policy=email.policy.default)
        if m["To"] == to:
            out.append((str(m["Subject"]), m.get_body(preferencelist=("plain",)).get_content()))
    return out


def link_token(text, path):
    m = re.search(re.escape(path) + r"\?token=(\S+)", text)
    assert m, text
    return unquote(m.group(1))


def login(c, e, pw=PW):
    return c.post("/api/v1/auth/login", data={"username": e, "password": pw, "altcha": proof(c)})


def test_sign_up_sends_a_confirmation_link_and_the_link_confirms_the_address(outbox):
    c = client("10.1.0.1")
    assert c.get("/api/v1/auth/options").json()["email"] is True
    r = c.post("/api/v1/auth/signup", json={"email": "Mail.User@Example.com", "password": PW, "altcha": proof(c)})
    assert r.status_code == 201 and r.json() == {"status": "verify_email"}
    ((subject, text),) = mails(outbox, "mail.user@example.com")
    assert "Confirm" in subject and "/verify-email?token=" in text
    assert login(c, "mail.user@example.com").json()["detail"] == "EMAIL_NOT_CONFIRMED"
    r = c.post("/api/v1/auth/verify-email", json={"token": link_token(text, "/verify-email")})
    assert r.status_code == 200 and r.json() == {"status": "pending"}         # not a company domain: an admin approves
    u = asyncio.run(_user("mail.user@example.com"))
    assert u.is_verified and u.approval == "pending" and not u.is_active
    assert c.post("/api/v1/auth/verify-email", json={"token": link_token(text, "/verify-email")}).status_code == 409
    assert c.post("/api/v1/auth/verify-email", json={"token": "forged.token.value"}).json()["detail"] == "LINK_INVALID"


def test_a_company_address_can_sign_in_as_soon_as_it_is_confirmed(outbox, monkeypatch):
    monkeypatch.setenv("FIDELITY_OAUTH_ALLOWED_DOMAINS", "company.example")
    c = client("10.1.0.2")
    c.post("/api/v1/auth/signup", json={"email": "staff@company.example", "password": PW, "altcha": proof(c)})
    ((_s, text),) = mails(outbox, "staff@company.example")
    assert c.post("/api/v1/auth/verify-email", json={"token": link_token(text, "/verify-email")}).json() == {"status": "active"}
    assert login(client("10.1.0.3"), "staff@company.example").status_code == 204


def test_everyone_confirmed_can_sign_in_when_approval_is_switched_off(outbox):
    mail.save({"approval": "none"})
    c = client("10.1.0.4")
    c.post("/api/v1/auth/signup", json={"email": "anyone@else.example", "password": PW, "altcha": proof(c)})
    ((_s, text),) = mails(outbox, "anyone@else.example")
    assert c.post("/api/v1/auth/verify-email", json={"token": link_token(text, "/verify-email")}).json() == {"status": "active"}


def test_an_address_that_has_an_account_gets_a_notice_and_the_asker_learns_nothing(outbox):
    c = client("10.1.0.5")
    r = c.post("/api/v1/auth/signup", json={"email": ADMIN, "password": "another-password-9", "altcha": proof(c)})
    assert r.json() == {"status": "verify_email"}
    ((subject, text),) = mails(outbox, ADMIN)
    assert "already has one" in text and "verify-email" not in text
    assert login(client("10.1.0.6"), ADMIN).status_code == 204                 # the account is untouched


def test_the_confirmation_mail_can_be_sent_again(outbox):
    c = client("10.1.0.7")
    c.post("/api/v1/auth/signup", json={"email": "again@example.com", "password": PW, "altcha": proof(c)})
    r = c.post("/api/v1/auth/verify-email/resend", json={"email": "again@example.com", "altcha": proof(c)})
    assert r.json() == {"status": "sent_if_waiting"}
    assert len(mails(outbox, "again@example.com")) == 2
    r = c.post("/api/v1/auth/verify-email/resend", json={"email": "nobody@example.com", "altcha": proof(c)})
    assert r.json() == {"status": "sent_if_waiting"} and not mails(outbox, "nobody@example.com")


def test_a_forgotten_password_is_reset_through_a_link_that_works_once(outbox):
    asyncio.run(_mk("forgetful@example.com", Role.viewer))
    c = client("10.1.0.8")
    r = c.post("/api/v1/auth/forgot-password", json={"email": "forgetful@example.com", "altcha": proof(c)})
    assert r.json() == {"status": "sent_if_account"}
    ((subject, text),) = mails(outbox, "forgetful@example.com")
    token = link_token(text, "/reset-password")
    assert c.post("/api/v1/auth/reset-password", json={"token": token, "password": "short"}).status_code == 422
    assert c.post("/api/v1/auth/reset-password", json={"token": token, "password": "a-brand-new-password"}).json() == {"status": "reset"}
    assert c.post("/api/v1/auth/reset-password", json={"token": token, "password": "yet-another-password"}).json()["detail"] == "LINK_INVALID"
    assert login(client("10.1.0.9"), "forgetful@example.com", "a-brand-new-password").status_code == 204
    assert login(client("10.1.1.0"), "forgetful@example.com").status_code == 400                # the old one no longer works


def test_asking_for_a_reset_reveals_nothing_and_needs_the_human_check(outbox):
    c = client("10.1.1.1")
    assert c.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com", "altcha": proof(c)}).json() == {"status": "sent_if_account"}
    assert not mails(outbox, "ghost@example.com")
    assert c.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"}).json()["detail"] == "CAPTCHA_REQUIRED"


def test_a_reset_asked_before_the_account_is_usable_gets_the_mail_that_helps(outbox):
    c = client("10.1.1.3")
    c.post("/api/v1/auth/signup", json={"email": "early@example.com", "password": PW, "altcha": proof(c)})
    c.post("/api/v1/auth/forgot-password", json={"email": "early@example.com", "altcha": proof(c)})
    first, again = mails(outbox, "early@example.com")
    assert "/verify-email?token=" in again[1]                         # not confirmed yet: the confirmation link again
    c.post("/api/v1/auth/verify-email", json={"token": link_token(again[1], "/verify-email")})
    r = c.post("/api/v1/auth/forgot-password", json={"email": "early@example.com", "altcha": proof(c)})
    assert r.json() == {"status": "sent_if_account"}                  # the same answer as for every address
    subject, text = mails(outbox, "early@example.com")[-1]
    assert "waiting for approval" in subject and "reset-password" not in text


def test_without_a_mail_server_everything_falls_back_to_an_administrator(tmp_path, monkeypatch):
    monkeypatch.delenv("FIDELITY_MAIL_OUTBOX", raising=False)
    monkeypatch.setenv("FIDELITY_CAPTCHA", "off")
    monkeypatch.setattr(mail, "PATH", str(tmp_path / "none.json"))
    guard.reset()
    c = client("10.1.1.2")
    assert c.get("/api/v1/auth/options").json()["email"] is False
    assert c.post("/api/v1/auth/signup", json={"email": "plain@example.com", "password": PW}).json() == {"status": "pending"}
    assert c.post("/api/v1/auth/forgot-password", json={"email": "plain@example.com"}).status_code == 404


def test_administrators_set_up_the_mail_server_and_the_password_is_never_shown(outbox, monkeypatch):
    monkeypatch.setenv("FIDELITY_CAPTCHA", "off")
    a = client("10.1.1.3")
    assert a.post("/api/v1/auth/login", data={"username": ADMIN, "password": PW}).status_code == 204
    r = a.put("/api/v1/admin/email", json={"host": "smtp.example.com", "port": 587, "security": "starttls",
                                            "username": "fidelity", "password": "s3cret-app-password",
                                            "from_address": "fidelity@example.com"})
    assert r.status_code == 200 and r.json()["password_set"] is True and "s3cret" not in r.text
    assert "s3cret" not in a.get("/api/v1/admin/email").text
    assert a.get("/api/v1/admin/email/password").json() == {"password": "s3cret-app-password"}   # only on request
    assert client("10.1.1.5").get("/api/v1/admin/email/password").status_code == 401
    assert a.put("/api/v1/admin/email", json={"port": 0}).status_code == 422
    assert a.post("/api/v1/admin/email/test").json() == {"sent_to": ADMIN}     # the outbox stands in for the server
    assert client("10.1.1.4").get("/api/v1/admin/email").status_code == 401


def test_the_sender_defaults_to_the_username_and_the_page_is_told_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("FIDELITY_MAIL_OUTBOX", raising=False)
    monkeypatch.setattr(mail, "PATH", str(tmp_path / "m.json"))
    assert mail.public()["missing"] == ["host", "from_address"]
    out = mail.save({"host": "smtp.gmail.com", "username": " someone@gmail.com "})
    assert out["from_address"] == "someone@gmail.com" and out["configured"] and out["missing"] == []
    assert mail.save({"from_address": "alias@gmail.com"})["from_address"] == "alias@gmail.com"   # a typed sender stays
    monkeypatch.setattr(mail, "PATH", str(tmp_path / "n.json"))
    out = mail.save({"host": "relay.office.local", "username": "relayuser"})
    assert out["from_address"] == "" and out["missing"] == ["from_address"] and not out["configured"]


def _wait_mail(box, to, n=1, timeout=10):
    import time
    end = time.time() + timeout
    while time.time() < end:
        got = mails(box, to)
        if len(got) >= n:
            return got
        time.sleep(0.1)
    return mails(box, to)


def test_administrators_are_told_at_once_when_someone_confirms_a_sign_up(outbox):
    """Owner 2026-11-23: a new sign-up must reach the administrators by e-mail straight away, not only when the
    five-minute digest happens to see it still waiting."""
    from app.ops import notify_mail
    c = client("10.1.0.20")
    c.post("/api/v1/auth/signup", json={"email": "newcomer@else.example", "password": PW, "altcha": proof(c)})
    ((_s, text),) = mails(outbox, "newcomer@else.example")
    assert c.post("/api/v1/auth/verify-email", json={"token": link_token(text, "/verify-email")}).json() == {"status": "pending"}
    got = [m for m in _wait_mail(outbox, ADMIN) if "newcomer@else.example" in m[0]]
    assert got, {"mails to admin": mails(outbox, ADMIN), "people": asyncio.run(notify_mail._people_async()),
                 "admin wants mail": notify_mail.wants_mail(ADMIN), "mail configured": mail.configured(),
                 "all mails": sorted(os.listdir(outbox)) if os.path.isdir(outbox) else "no outbox"}
    subject, body = got[0]
    assert "waiting for approval" in subject and "/settings/users" in body
    import time
    time.sleep(0.3)
    # the digest does not repeat it as "1 sign-up waits"
    con = notify_mail._con()
    keys = {r[0] for r in con.execute("SELECT nkey FROM notification_mail WHERE user_email=?", (ADMIN,))}
    con.close()
    assert any(k.startswith("signup:") for k in keys)


def test_an_administrator_who_switched_mail_off_gets_no_sign_up_notice(outbox):
    from app.ops import notify_mail
    notify_mail.set_wants_mail(ADMIN, False)
    try:
        c = client("10.1.0.21")
        c.post("/api/v1/auth/signup", json={"email": "quiet@else.example", "password": PW, "altcha": proof(c)})
        ((_s, text),) = mails(outbox, "quiet@else.example")
        c.post("/api/v1/auth/verify-email", json={"token": link_token(text, "/verify-email")})
        import time
        time.sleep(1)
        assert not [m for m in mails(outbox, ADMIN) if "quiet@else.example" in m[0]]
    finally:
        notify_mail.set_wants_mail(ADMIN, True)


def test_an_eight_character_password_is_accepted(outbox):
    c = client("10.1.0.22")
    r = c.post("/api/v1/auth/signup", json={"email": "short.pw@else.example", "password": "abcd1234", "altcha": proof(c)})
    assert r.status_code == 201, r.text
    r = c.post("/api/v1/auth/signup", json={"email": "too.short@else.example", "password": "abc123", "altcha": proof(c)})
    assert r.status_code in (400, 422)


def test_one_address_that_cannot_be_mailed_does_not_stop_the_others(outbox, monkeypatch):
    """Found on macOS CI: with many administrators, an error for one address ended the sender before the rest."""
    from app.ops import notify_mail
    real = mail.send

    def flaky(to, *a, **k):
        if to != ADMIN:
            raise ValueError("bad header")
        return real(to, *a, **k)

    async def admins():
        return [("broken@example.com", "admin"), (ADMIN, "admin")]
    monkeypatch.setattr(mail, "send", flaky)
    monkeypatch.setattr(notify_mail, "_people_async", admins)
    asyncio.run(notify_mail.new_signup("someone@else.example", "active"))
    assert [m for m in _wait_mail(outbox, ADMIN) if "someone@else.example" in m[0]]
