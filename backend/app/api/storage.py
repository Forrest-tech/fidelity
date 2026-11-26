# -*- coding: utf-8 -*-
"""Cloud storage settings (administrators): connect Dropbox from the web page instead of a terminal.

Two connections, as in the command line: `reader` (read-only scopes; used for every source) and
`writer` (adds files.content.write; used only for output folders). Dropbox's PKCE code flow is used,
so no app secret and no redirect URL are needed: the page opens Dropbox, the administrator clicks
Allow and pastes the code back. Tokens stay in data/dropbox_auth.json on the server and are never
sent to the browser.
"""
import re
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth.users import require_role
from ..distill import dropbox_io as D

router = APIRouter(dependencies=[Depends(require_role())])          # administrators only
ROLES = ("reader", "writer")
# The Dropbox app key (a public PKCE client id, but kept out of the code): FIDELITY_DROPBOX_APP_KEY, else the key of
# an existing connection (a migration package brings it), else the administrator enters it once on the page.
CALLBACK_DBX = "/api/v1/storage/dropbox/callback"


def app_key() -> str:
    import os
    env = os.environ.get("FIDELITY_DROPBOX_APP_KEY", "").strip()
    if env:
        return env
    if _pending_key.get("key"):
        return _pending_key["key"]
    for r in ROLES:
        a = D.load_auth().get(r)
        if isinstance(a, dict) and a.get("app_key"):
            return a["app_key"]
    return ""
FLOW_TTL = 600                                                        # an authorisation link is valid 10 minutes
_flows: dict = {}
_lock = threading.Lock()


class StartIn(BaseModel):
    role: str
    app_key: str


class FinishIn(BaseModel):
    role: str
    code: str


def _role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(422, "role must be reader or writer")
    return role


def _exact_client(role: str):
    """A client for exactly this role (never falls back to the other role's credentials)."""
    a = D.load_auth().get(role)
    if not (isinstance(a, dict) and a.get("refresh_token")):
        return None
    import dropbox
    return dropbox.Dropbox(oauth2_refresh_token=a["refresh_token"], app_key=a["app_key"])


def _account(role: str):
    """Who the connection belongs to, read live from Dropbox; None if it does not work."""
    try:
        acc = _exact_client(role).users_get_current_account()
        return {"name": acc.name.display_name, "email": acc.email}
    except Exception as e:
        # an older connection may lack account_info.read: it still works, it just cannot show the name
        return {"error": "missing_scope"} if "missing_scope" in str(e) else None


@router.get("/storage/dropbox")
def status(check: bool = True):
    data = D.load_auth()
    out = {}
    for r in ROLES:
        a = data.get(r) if isinstance(data.get(r), dict) else None
        ok = bool(a and a.get("refresh_token"))
        out[r] = {"connected": ok, "app_key": (a or {}).get("app_key", "") or app_key(),
                  "scopes": (a or {}).get("scopes", ""), "account": _account(r) if ok and check else None}
    return out


@router.post("/storage/dropbox/start")
def start(body: StartIn):
    role = _role(body.role)
    key = body.app_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{8,32}", key):
        raise HTTPException(422, "that does not look like a Dropbox App key (letters and digits, about 15 characters)")
    import dropbox
    flow = dropbox.DropboxOAuth2FlowNoRedirect(key, use_pkce=True, token_access_type="offline",
                                               scope=D.WRITE_SCOPES if role == "writer" else D.READ_SCOPES)
    url = flow.start()
    with _lock:
        _flows[role] = (flow, key, time.time())
    return {"url": url, "expires_in": FLOW_TTL}


@router.post("/storage/dropbox/finish")
def finish(body: FinishIn):
    role = _role(body.role)
    with _lock:
        entry = _flows.pop(role, None)
    if not entry or time.time() - entry[2] > FLOW_TTL:
        raise HTTPException(409, "the authorisation link has expired — click Connect again")
    flow, key, _ = entry
    try:
        res = flow.finish(body.code.strip())
    except Exception as e:
        detail = ""
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                detail = resp.json().get("error_description", "")
            except Exception:
                pass
        raise HTTPException(422, "Dropbox refused the code" + (f" ({detail})" if detail else "")
                            + ". Codes work once and only for a few minutes — click Connect again.")
    D.save_role(role, key, res.refresh_token, res.scope)
    return {"connected": True, "account": _account(role)}


# ---- one click: the browser goes to Dropbox and comes back by itself (no code to copy, no app key to type)
from fastapi import Request as _Request  # noqa: E402
from fastapi.responses import RedirectResponse as _Redirect  # noqa: E402

_web_flows: dict = {}
_pending_key: dict = {}                                   # a key typed on the page, used until a connection saves it


def redirect_uri(request) -> str:
    """Where Dropbox sends the browser back. Dropbox accepts http only for localhost / 127.0.0.1; any other address
    must be https (the page then offers the copy-the-code way)."""
    return str(request.base_url).rstrip("/") + CALLBACK_DBX


def can_redirect(request) -> bool:
    u = redirect_uri(request)
    return u.startswith("https://") or u.startswith(("http://127.0.0.1", "http://localhost"))


def _web_flow(role: str, request, session: dict):
    import dropbox
    return dropbox.DropboxOAuth2Flow(app_key(), redirect_uri(request), session, "dropbox-csrf", use_pkce=True,
                                     token_access_type="offline",
                                     scope=D.WRITE_SCOPES if role == "writer" else D.READ_SCOPES)


@router.get("/storage/dropbox/connect")
def connect(request: _Request, role: str = "both", key: str = ""):
    """Start the one-click connection. `both` connects the read-only access first, then the write access: two
    "Allow" clicks on Dropbox, the second without signing in again."""
    if role not in ROLES + ("both",):
        raise HTTPException(422, "role must be reader, writer or both")
    if not can_redirect(request):
        raise HTTPException(409, "one-click connect needs the page opened at http://127.0.0.1 or over https; "
                                 "use the step-by-step way below")
    key = key.strip()
    if key:
        if not re.fullmatch(r"[A-Za-z0-9]{8,32}", key):
            raise HTTPException(422, "that does not look like a Dropbox App key (letters and digits, about 15 characters)")
        _pending_key["key"] = key
    if not app_key():
        raise HTTPException(428, "enter the Dropbox App key once (Dropbox App Console > your app > Settings)")
    first = "reader" if role in ("reader", "both") else "writer"
    session: dict = {}
    url = _web_flow(first, request, session).start()
    with _lock:
        _web_flows[session["dropbox-csrf"]] = (first, role == "both", session, time.time())
    return {"url": url, "redirect_uri": redirect_uri(request)}


@router.get("/storage/dropbox/callback")
def callback(request: _Request, state: str = "", code: str = "", error: str = "", error_description: str = ""):
    """Dropbox sends the browser here after Allow (or Cancel); the page then shows the result."""
    back = "/settings/storage?dropbox="
    csrf = state.split("|", 1)[0]
    with _lock:
        entry = _web_flows.pop(csrf, None)
    if not entry or time.time() - entry[3] > FLOW_TTL:
        return _Redirect(back + "expired")
    role, then_writer, session, _ = entry
    if error:
        return _Redirect(back + ("cancelled" if error == "access_denied" else "failed"))
    try:
        res = _web_flow(role, request, session).finish({"state": state, "code": code})
    except Exception:                                        # noqa: BLE001 - bad state, used code, wrong redirect
        return _Redirect(back + "failed")
    D.save_role(role, app_key(), res.refresh_token, res.scope)
    if then_writer and role == "reader":                     # straight on to the write access
        session2: dict = {}
        url = _web_flow("writer", request, session2).start()
        with _lock:
            _web_flows[session2["dropbox-csrf"]] = ("writer", False, session2, time.time())
        return _Redirect(url)
    return _Redirect(back + "connected")


@router.delete("/storage/dropbox/{role}")
def disconnect(role: str):
    _role(role)
    c = _exact_client(role)
    if c is not None:
        try:                                # tell Dropbox to revoke this role's token too, if it still works
            c.auth_token_revoke()
        except Exception:
            pass
    return {"removed": D.remove_role(role)}


# ------------------------------------------------------------------ Google Drive
# Google's standard OAuth 2.0 web-server flow (google-auth-oauthlib): the administrator registers this
# app's callback URL once in Google Cloud Console, enters the client ID and secret here, then clicks
# Connect for each access. The secret and the tokens stay on the server.
from fastapi import Request  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402

from ..distill import gdrive_io as G  # noqa: E402

CALLBACK = "/api/v1/storage/google/callback"
_gflows: dict = {}


class GoogleClientIn(BaseModel):
    client_id: str
    client_secret: str


class GoogleStartIn(BaseModel):
    role: str


def _redirect_uri(request: Request) -> str:
    return str(request.base_url).rstrip("/") + CALLBACK


def _google_account(role: str):
    try:
        about = G.service(role).about().get(fields="user(displayName,emailAddress)").execute()["user"]
        return {"name": about.get("displayName", ""), "email": about.get("emailAddress", "")}
    except Exception:
        return None


@router.get("/storage/google")
def google_status(request: Request, check: bool = True):
    data = G.load_auth()
    client = data.get("client") or {}
    out = {"client_configured": bool(client.get("client_id") and client.get("client_secret")),
           "client_id": client.get("client_id", ""), "redirect_uri": _redirect_uri(request)}
    for r in ROLES:
        ok = bool((data.get(r) or {}).get("refresh_token"))
        out[r] = {"connected": ok, "account": _google_account(r) if ok and check else None}
    return out


@router.put("/storage/google/client")
def google_client(body: GoogleClientIn):
    cid, secret = body.client_id.strip(), body.client_secret.strip()
    if not re.fullmatch(r"[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com", cid):
        raise HTTPException(422, "that does not look like a Google OAuth client ID (…apps.googleusercontent.com)")
    if len(secret) < 10:
        raise HTTPException(422, "enter the client secret shown next to the client ID")
    data = G.load_auth()
    if (data.get("client") or {}).get("client_id") != cid:      # a different client invalidates old tokens
        data = {}
    data["client"] = {"client_id": cid, "client_secret": secret}
    G.save_auth(data)
    return {"saved": True}


def _flow(role: str, redirect_uri: str, state=None):
    from google_auth_oauthlib.flow import Flow
    c = G.load_auth().get("client") or {}
    if not c.get("client_id"):
        raise HTTPException(409, "enter the Google OAuth client first")
    cfg = {"web": {"client_id": c["client_id"], "client_secret": c["client_secret"],
                   "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": G.TOKEN_URI,
                   "redirect_uris": [redirect_uri]}}
    return Flow.from_client_config(cfg, scopes=G.SCOPES[role], redirect_uri=redirect_uri, state=state)


@router.post("/storage/google/start")
def google_start(body: GoogleStartIn, request: Request):
    role = _role(body.role)
    flow = _flow(role, _redirect_uri(request))
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="false")
    with _lock:
        _gflows[state] = (role, getattr(flow, "code_verifier", None), time.time())
    return {"url": url}


@router.get("/storage/google/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    with _lock:
        entry = _gflows.pop(state, None)
    if error or not entry or time.time() - entry[2] > FLOW_TTL:
        reason = error or "expired"
        return RedirectResponse(f"/settings?google=error&reason={reason[:40]}", status_code=303)
    role, verifier, _ = entry
    flow = _flow(role, _redirect_uri(request), state=state)
    if verifier:
        flow.code_verifier = verifier
    try:
        flow.fetch_token(code=code)
    except Exception:
        return RedirectResponse("/settings?google=error&reason=token", status_code=303)
    creds = flow.credentials
    if not creds.refresh_token:
        return RedirectResponse("/settings?google=error&reason=no_refresh_token", status_code=303)
    data = G.load_auth()
    data[role] = {"refresh_token": creds.refresh_token, "scopes": list(creds.scopes or G.SCOPES[role])}
    G.save_auth(data)
    return RedirectResponse(f"/settings?google=connected&role={role}", status_code=303)


@router.delete("/storage/google/{role}")
def google_disconnect(role: str):
    _role(role)
    data = G.load_auth()
    tok = (data.get(role) or {}).get("refresh_token")
    if tok:
        try:                                    # Google's revocation endpoint; best effort
            import urllib.parse
            import urllib.request
            urllib.request.urlopen(urllib.request.Request(
                "https://oauth2.googleapis.com/revoke", data=urllib.parse.urlencode({"token": tok}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=10)
        except Exception:
            pass
    removed = data.pop(role, None) is not None
    G.save_auth(data)
    return {"removed": removed}
