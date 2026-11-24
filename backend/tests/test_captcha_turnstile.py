"""Cloudflare Turnstile as the human check (owner 2026-11-23), with ALTCHA standing in while Cloudflare is unreachable."""
import pytest
from fastapi.testclient import TestClient

from app.auth import captcha, guard
from app.main import app

ADMIN_PW = "correct-horse-battery"


@pytest.fixture()
def turnstile(tmp_path, monkeypatch):
    monkeypatch.setattr(captcha, "_settings_path", lambda: str(tmp_path / "captcha_settings.json"))
    monkeypatch.setenv("FIDELITY_CAPTCHA", "on")
    monkeypatch.setenv("FIDELITY_CAPTCHA_COST", "10")
    monkeypatch.setenv("FIDELITY_CAPTCHA_MAX", "50")
    secrets = {}
    from app.ai import config as CF
    monkeypatch.setattr(CF, "key_for", lambda k: secrets.get(k))
    monkeypatch.setattr(CF, "_store_key", lambda k, v: secrets.__setitem__(k, v) if v else secrets.pop(k, None))
    monkeypatch.setattr(captcha, "_cf_down_until", 0.0)
    monkeypatch.setattr(captcha, "_cf_up_until", 0.0)
    guard.reset()
    captcha.reset()
    yield secrets
    guard.reset()
    captcha.reset()


def test_turnstile_is_off_until_both_keys_are_there(turnstile):
    assert captcha.provider() == "altcha"
    captcha.save({"provider": "turnstile", "site_key": "1x00000000000000000000AA"})
    assert captcha.provider() == "altcha" and captcha.public()["secret_set"] is False
    captcha.save({"secret_key": "1x0000000000000000000000000000000AA"})
    assert captcha.provider() == "turnstile"
    o = TestClient(app).get("/api/v1/auth/options").json()
    assert o["captcha_provider"] == "turnstile" and o["turnstile_site_key"] == "1x00000000000000000000AA"
    assert "secret" not in str(captcha.public()).replace("secret_set", "")


def test_a_turnstile_token_is_checked_with_cloudflare(turnstile, monkeypatch):
    captcha.save({"provider": "turnstile", "site_key": "site", "secret_key": "secret"})
    seen = []

    def fake(token, ip):
        seen.append(token)
        return {"success": token == "good"} if token != "used" else {"success": False, "error-codes": ["timeout-or-duplicate"]}
    monkeypatch.setattr(captcha, "_siteverify", fake)
    assert captcha.verify("turnstile:good") is None
    assert captcha.verify("turnstile:bad") == "CAPTCHA_INVALID"
    assert captcha.verify("turnstile:used") == "CAPTCHA_EXPIRED"
    assert seen == ["good", "bad", "used"]


def test_altcha_is_refused_while_cloudflare_answers_and_accepted_when_it_cannot(turnstile, monkeypatch):
    captcha.save({"provider": "turnstile", "site_key": "site", "secret_key": "secret"})
    c = TestClient(app)
    altcha_proof = captcha.solve_for_tests(c.get("/api/v1/auth/challenge").json())
    monkeypatch.setattr(captcha, "cloudflare_down", lambda: False)
    assert captcha.verify(altcha_proof) == "CAPTCHA_REQUIRED"
    monkeypatch.setattr(captcha, "cloudflare_down", lambda: True)
    assert captcha.verify(altcha_proof) is None


def test_a_turnstile_token_is_refused_when_turnstile_is_not_set_up(turnstile):
    assert captcha.verify("turnstile:anything") == "CAPTCHA_INVALID"


def test_cloudflare_unreachable_is_reported_not_crashed(turnstile, monkeypatch):
    import urllib.request
    captcha.save({"provider": "turnstile", "site_key": "site", "secret_key": "secret"})

    def boom(*a, **k):
        raise OSError("no route")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert captcha.verify("turnstile:x") == "CAPTCHA_UNAVAILABLE"
    assert captcha.cloudflare_down() is True
