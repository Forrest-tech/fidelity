"""Sign in with Google, Microsoft, GitHub or a company OpenID Connect provider.

The protocol work is done by mature libraries: httpx-oauth (the OAuth 2 / OpenID Connect clients used by
FastAPI Users) talks to the provider, FastAPI Users links the provider account to a Fidelity user and
issues the normal session cookie. This module only wires them into a browser redirect flow:

  GET /api/v1/auth/oauth/{provider}/authorize?next=/distill
      -> 302 to the provider (state = signed JWT, CSRF cookie, PKCE S256 verifier in an httpOnly cookie)
  GET /api/v1/auth/oauth/{provider}/callback?code=...&state=...
      -> 302 to `next` with the session cookie, or to /login?error=<code> when sign-in is refused.

Who may sign in: only people who already have a Fidelity user with the same e-mail address (an
administrator adds them on the Users page), unless their e-mail domain is listed in
FIDELITY_OAUTH_ALLOWED_DOMAINS, in which case a viewer account is created on first sign-in. The provider
must report the address as verified. Provider access tokens are not stored: the sign-in is used only to
prove who the person is.

A provider is offered when its credentials are set (environment):
  FIDELITY_OAUTH_GOOGLE_CLIENT_ID / _SECRET
  FIDELITY_OAUTH_MICROSOFT_CLIENT_ID / _SECRET  (+ FIDELITY_OAUTH_MICROSOFT_TENANT, default "common")
  FIDELITY_OAUTH_GITHUB_CLIENT_ID / _SECRET
  FIDELITY_OAUTH_OIDC_CLIENT_ID / _SECRET / _DISCOVERY_URL (+ FIDELITY_OAUTH_OIDC_LABEL, e.g. "Okta")
Register this redirect address with the provider: <site>/api/v1/auth/oauth/<provider>/callback
(provider = google, microsoft, github or oidc). Set FIDELITY_PUBLIC_URL when the site is reached through
a proxy so that the address is built correctly.
"""
import base64
import hashlib
import os
import secrets
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi_users.jwt import decode_jwt, generate_jwt
from httpx_oauth.clients.github import GitHubOAuth2
from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.clients.microsoft import MicrosoftGraphOAuth2
from httpx_oauth.clients.openid import OpenID
from httpx_oauth.oauth2 import BaseOAuth2

from . import guard
from .users import SECRET, backend, get_jwt_strategy, get_user_manager

STATE_AUDIENCE = "fidelity:oauth-state"
STATE_COOKIE = "fidelity_oauth"
STATE_SECONDS = 600
HTTPS = os.environ.get("FIDELITY_HTTPS") == "1"


class OAuthRefused(Exception):
    """Sign-in with a provider account that may not use Fidelity; `code` goes to the login page."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class VerifiedGitHub(GitHubOAuth2):
    """GitHub may return an unverified primary address: accept only a verified one."""

    async def get_id_email(self, token):
        profile = await self.get_profile(token)
        emails = await self.get_emails(token)
        verified = [e for e in emails if e.get("verified")]
        chosen = next((e["email"] for e in verified if e.get("primary")), verified[0]["email"] if verified else None)
        return str(profile["id"]), chosen


class VerifiedOpenID(OpenID):
    """A company identity provider: refuse an address the provider says is not verified."""

    async def get_id_email(self, token):
        profile = await self.get_profile(token)
        if profile.get("email_verified") is False:
            return str(profile["sub"]), None
        return str(profile["sub"]), profile.get("email")


def _env(name):
    return os.environ.get("FIDELITY_OAUTH_" + name, "").strip()


def configured() -> dict[str, tuple[BaseOAuth2, str]]:
    """provider key -> (client, label shown on the button). Read on each call so settings apply at once."""
    out: dict[str, tuple[BaseOAuth2, str]] = {}
    if _env("GOOGLE_CLIENT_ID") and _env("GOOGLE_CLIENT_SECRET"):
        out["google"] = (GoogleOAuth2(_env("GOOGLE_CLIENT_ID"), _env("GOOGLE_CLIENT_SECRET")), "Google")
    if _env("MICROSOFT_CLIENT_ID") and _env("MICROSOFT_CLIENT_SECRET"):
        out["microsoft"] = (MicrosoftGraphOAuth2(_env("MICROSOFT_CLIENT_ID"), _env("MICROSOFT_CLIENT_SECRET"),
                                                 tenant=_env("MICROSOFT_TENANT") or "common"), "Microsoft")
    if _env("GITHUB_CLIENT_ID") and _env("GITHUB_CLIENT_SECRET"):
        out["github"] = (VerifiedGitHub(_env("GITHUB_CLIENT_ID"), _env("GITHUB_CLIENT_SECRET")), "GitHub")
    if _env("OIDC_CLIENT_ID") and _env("OIDC_CLIENT_SECRET") and _env("OIDC_DISCOVERY_URL"):
        try:
            out["oidc"] = (_oidc_client(), _env("OIDC_LABEL") or "SSO")
        except Exception:                      # discovery document unreachable: do not offer the button
            pass
    return out


_OIDC_CACHE: dict[tuple, OpenID] = {}
_OIDC_FAILED: dict[tuple, float] = {}
OIDC_RETRY_SECONDS = 60


def _oidc_client() -> OpenID:
    # OpenID() downloads the discovery document when made: keep one per setting, and after a failure do
    # not try again for a minute (the sign-in page must not wait on an unreachable provider each time)
    import time
    key = (_env("OIDC_CLIENT_ID"), _env("OIDC_CLIENT_SECRET"), _env("OIDC_DISCOVERY_URL"))
    if key not in _OIDC_CACHE:
        if time.time() - _OIDC_FAILED.get(key, 0) < OIDC_RETRY_SECONDS:
            raise RuntimeError("identity provider unreachable")
        try:
            _OIDC_CACHE[key] = VerifiedOpenID(key[0], key[1], key[2], name="oidc")
        except Exception:
            _OIDC_FAILED[key] = time.time()
            raise
    return _OIDC_CACHE[key]


def allowed_domains() -> set[str]:
    return {d.strip().lower().lstrip("@") for d in _env("ALLOWED_DOMAINS").split(",") if d.strip()}


def _safe_next(nxt: str | None) -> str:
    """Only a path on this site (no open redirect to another host)."""
    if not nxt or not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt or nxt.startswith("/login"):
        return "/"
    return nxt[:500]


def _callback_url(request: Request, provider: str) -> str:
    base = os.environ.get("FIDELITY_PUBLIC_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
    return "%s/api/v1/auth/oauth/%s/callback" % (base, provider)


def _to_login(code: str) -> RedirectResponse:
    r = RedirectResponse("/login?error=" + quote(code), status_code=302)
    r.delete_cookie(STATE_COOKIE, path="/api/v1/auth/oauth")
    return r


router = APIRouter(prefix="/auth/oauth", tags=["auth"])


@router.get("/{provider}/authorize")
async def authorize(provider: str, request: Request, next: str | None = None):
    clients = configured()
    if provider not in clients:
        raise HTTPException(status_code=404, detail="sign-in provider not configured")
    client, _label = clients[provider]
    csrf = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)                                    # PKCE (RFC 7636)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = generate_jwt({"csrf": csrf, "next": _safe_next(next), "aud": STATE_AUDIENCE}, SECRET, STATE_SECONDS)
    extra = {"prompt": "select_account"} if provider in ("google", "microsoft") else None
    url = await client.get_authorization_url(_callback_url(request, provider), state,
                                             code_challenge=challenge, code_challenge_method="S256",
                                             extras_params=extra)
    resp = RedirectResponse(url, status_code=302)
    cookie = generate_jwt({"csrf": csrf, "pkce": verifier, "aud": STATE_AUDIENCE}, SECRET, STATE_SECONDS)
    resp.set_cookie(STATE_COOKIE, cookie, max_age=STATE_SECONDS, path="/api/v1/auth/oauth",
                    secure=HTTPS, httponly=True, samesite="lax")
    return resp


@router.get("/{provider}/callback")
async def callback(provider: str, request: Request, code: str | None = None, state: str | None = None,
                   error: str | None = None, user_manager=Depends(get_user_manager)):
    clients = configured()
    if provider not in clients:
        return _to_login("oauth_unavailable")
    if error:                                     # the person pressed Cancel at the provider, or it refused
        return _to_login("oauth_cancelled" if error == "access_denied" else "oauth_failed")
    if not code or not state:
        return _to_login("oauth_failed")
    try:
        st = decode_jwt(state, SECRET, [STATE_AUDIENCE])
        ck = decode_jwt(request.cookies.get(STATE_COOKIE, ""), SECRET, [STATE_AUDIENCE])
    except jwt.ExpiredSignatureError:
        return _to_login("oauth_expired")
    except jwt.PyJWTError:
        return _to_login("oauth_failed")
    if not secrets.compare_digest(str(st.get("csrf", "")), str(ck.get("csrf", "-"))):
        return _to_login("oauth_failed")
    client, _label = clients[provider]
    try:
        token = await client.get_access_token(code, _callback_url(request, provider), code_verifier=ck.get("pkce"))
        account_id, email = await client.get_id_email(token["access_token"])
    except Exception:
        return _to_login("oauth_failed")
    if not email:
        return _to_login("oauth_no_email")
    try:
        user = await user_manager.oauth_callback(provider, "-", account_id, email.strip().lower(), None, None, request,
                                                 associate_by_email=True, is_verified_by_default=True)
    except OAuthRefused as e:
        await guard.audit(None, "login_refused_oauth", "%s %s" % (provider, guard.client_ip(request)))
        return _to_login(e.code)
    if not user.is_active:
        return _to_login("oauth_inactive")
    login = await backend.login(get_jwt_strategy(), user)      # the normal session cookie
    await guard.audit(user.id, "login_oauth", "%s %s" % (provider, guard.client_ip(request)))
    resp = RedirectResponse(_safe_next(st.get("next")), status_code=302)
    for k, v in login.headers.items():
        if k.lower() == "set-cookie":
            resp.headers.append("set-cookie", v)
    resp.delete_cookie(STATE_COOKIE, path="/api/v1/auth/oauth")
    return resp


def providers_public() -> list[dict]:
    return [{"id": k, "label": label} for k, (_c, label) in configured().items()]
