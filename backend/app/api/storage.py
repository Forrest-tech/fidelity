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
        out[r] = {"connected": ok, "app_key": (a or {}).get("app_key", ""),
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
