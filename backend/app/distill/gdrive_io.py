# -*- coding: utf-8 -*-
"""Google Drive as a source and as an output (spec F-1), with Google's official client libraries
(google-api-python-client, google-auth). Same rules as Dropbox:

- two connections: `reader` (scope drive.readonly — cannot change anything) for sources and `writer`
  (scope drive) used only for output folders;
- the writer is guarded: it accepts only paths under the output folder and its _staging / _archive
  siblings, and refuses an output folder that is inside (or contains) the source folder;
- deleting moves to the Drive trash (recoverable), never a permanent delete.

Folders are given as a Drive folder link (https://drive.google.com/drive/folders/<id>) or `gdrive:<id>`.
Google Docs / Sheets / Slides are exported to .docx / .xlsx / .pptx and distilled like Office files.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import posixpath
import re

from .dropbox_io import IronRuleViolation

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
AUTH_PATH = os.environ.get("FIDELITY_GOOGLE_AUTH") or os.path.join(_REPO, "data", "google_auth.json")
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = {"reader": ["https://www.googleapis.com/auth/drive.readonly"],
          "writer": ["https://www.googleapis.com/auth/drive"]}
FOLDER = "application/vnd.google-apps.folder"
EXPORT = {  # Google-native type -> (export MIME type, extension)
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}
_FIELDS = "nextPageToken, files(id, name, mimeType, md5Checksum, size, version, modifiedTime, parents)"
_LINK = [re.compile(r"^https://drive\.google\.com/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]{10,})"),
         re.compile(r"^https://drive\.google\.com/(?:open|folderview)\?(?:.*&)?id=([A-Za-z0-9_-]{10,})"),
         re.compile(r"^gdrive:([A-Za-z0-9_-]{10,})$")]


# ------------------------------------------------------------------ links and credentials
def is_gdrive(link: str) -> bool:
    return any(rx.match((link or "").strip()) for rx in _LINK)


def folder_id(link: str) -> str:
    for rx in _LINK:
        m = rx.match((link or "").strip())
        if m:
            return m.group(1)
    raise ValueError("not a Google Drive folder link: " + str(link)[:80])


def load_auth() -> dict:
    try:
        with open(AUTH_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_auth(data: dict) -> None:
    os.makedirs(os.path.dirname(AUTH_PATH), exist_ok=True)
    tmp = AUTH_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, AUTH_PATH)
    try:
        os.chmod(AUTH_PATH, 0o600)
    except OSError:
        pass


def service(role: str):
    """Drive API v3 client for exactly this role (never falls back to the other role)."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    data = load_auth()
    c, r = data.get("client") or {}, data.get(role) or {}
    if not (c.get("client_id") and r.get("refresh_token")):
        raise RuntimeError(f"Google Drive {role} access is not connected (Settings → Cloud storage)")
    creds = Credentials(None, refresh_token=r["refresh_token"], client_id=c["client_id"],
                        client_secret=c.get("client_secret"), token_uri=TOKEN_URI, scopes=SCOPES[role])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ------------------------------------------------------------------ reading
def _children(svc, fid):
    page = None
    while True:
        res = svc.files().list(q=f"'{fid}' in parents and trashed = false", fields=_FIELDS, pageSize=1000,
                               pageToken=page, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        yield from res.get("files", [])
        page = res.get("nextPageToken")
        if not page:
            return


def snapshot(svc, root_id: str) -> dict:
    """{relative path: {id, rev, size, content_hash, mime}} for every file under the folder (read-only).
    content_hash is Drive's md5 for ordinary files and the revision number for Google Docs/Sheets/Slides."""
    out = {}

    def walk(fid, prefix):
        for f in _children(svc, fid):
            name = f["name"].replace("/", "_")
            if f["mimeType"] == FOLDER:
                walk(f["id"], prefix + "/" + name)
                continue
            ext = EXPORT.get(f["mimeType"], (None, ""))[1]
            if f["mimeType"].startswith("application/vnd.google-apps.") and not ext:
                continue                      # forms, drawings, shortcuts: nothing to distil
            rel = prefix + "/" + name + (ext if ext and not name.lower().endswith(ext) else "")
            out[rel] = {"rel": rel, "id": f["id"], "rev": f.get("version"), "size": int(f.get("size") or 0),
                        "content_hash": f.get("md5Checksum") or "rev:" + str(f.get("version")), "mime": f["mimeType"]}
    walk(root_id, "")
    return out


def identity(svc, entry: dict) -> dict:
    f = svc.files().get(fileId=entry["id"], fields="id, version, size", supportsAllDrives=True).execute()
    return {"id": f["id"], "rev": f.get("version"), "size": int(f.get("size") or 0)}


def download(svc, entry: dict, local_path: str):
    from googleapiclient.http import MediaIoBaseDownload
    exp = EXPORT.get(entry["mime"])
    req = (svc.files().export_media(fileId=entry["id"], mimeType=exp[0]) if exp
           else svc.files().get_media(fileId=entry["id"], supportsAllDrives=True))
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    tmp = local_path + ".part"
    with open(tmp, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=8 << 20)
        done = False
        while not done:
            _, done = dl.next_chunk()
    os.replace(tmp, local_path)


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def local_matches(path: str, entry: dict) -> bool:
    """A local copy is the same as the Drive file (md5 for ordinary files; exports are re-downloaded)."""
    if entry["content_hash"].startswith("rev:") or not os.path.exists(path):
        return False
    return md5_file(path) == entry["content_hash"]


def ancestors(svc, fid: str) -> list:
    """Folder ids from fid up to the top of its drive (fid included)."""
    chain, cur = [], fid
    for _ in range(64):
        chain.append(cur)
        f = svc.files().get(fileId=cur, fields="id, parents", supportsAllDrives=True).execute()
        parents = f.get("parents") or []
        if not parents:
            return chain
        cur = parents[0]
    return chain


# ------------------------------------------------------------------ writing (guarded)
class GDriveStore:
    """Publisher storage interface (upload / move / delete / list) on Google Drive, addressed by paths
    whose first segment is one of the registered roots, e.g. "/Out/a/b.md" with roots {"/Out": <id>}.
    Anything outside those roots is refused."""

    def __init__(self, svc, roots: dict):
        self.svc = svc
        self.roots = {r.rstrip("/"): fid for r, fid in roots.items()}
        self._ids = {}

    def _split(self, path):
        p = "/" + path.strip("/")
        for root, fid in self.roots.items():
            if p == root or p.startswith(root + "/"):
                return fid, [x for x in p[len(root):].split("/") if x]
        raise IronRuleViolation(f"refusing to write outside the output folders: {path}")

    def _find(self, parent, name, folder=None):
        q = f"'{parent}' in parents and trashed = false and name = '{name.replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))}'"
        if folder is True:
            q += f" and mimeType = '{FOLDER}'"
        res = self.svc.files().list(q=q, fields="files(id, mimeType)", supportsAllDrives=True,
                                    includeItemsFromAllDrives=True).execute().get("files", [])
        return res[0] if res else None

    def _folder(self, parent, parts, create):
        for name in parts:
            key = (parent, name)
            if key not in self._ids:
                f = self._find(parent, name, folder=True)
                if not f and not create:
                    return None
                if not f:
                    f = self.svc.files().create(body={"name": name, "mimeType": FOLDER, "parents": [parent]},
                                                fields="id", supportsAllDrives=True).execute()
                self._ids[key] = f["id"]
            parent = self._ids[key]
        return parent

    def _locate(self, path):
        root, parts = self._split(path)
        if not parts:
            return root, None, root
        parent = self._folder(root, parts[:-1], create=False)
        f = self._find(parent, parts[-1]) if parent else None
        return parent, f, (f or {}).get("id")

    def upload(self, path, data: bytes):
        from googleapiclient.http import MediaIoBaseUpload
        root, parts = self._split(path)
        parent = self._folder(root, parts[:-1], create=True)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype="text/markdown", resumable=False)
        f = self._find(parent, parts[-1])
        if f:
            self.svc.files().update(fileId=f["id"], media_body=media, supportsAllDrives=True).execute()
        else:
            self.svc.files().create(body={"name": parts[-1], "parents": [parent]}, media_body=media,
                                    fields="id", supportsAllDrives=True).execute()

    def move(self, src, dst):
        src_parent, f, _ = self._locate(src)
        if not f:
            raise FileNotFoundError(src)
        droot, dparts = self._split(dst)
        dparent = self._folder(droot, dparts[:-1], create=True)
        if self._find(dparent, dparts[-1]):
            raise FileExistsError(dst)
        self.svc.files().update(fileId=f["id"], addParents=dparent, removeParents=src_parent,
                                body={"name": dparts[-1]}, fields="id", supportsAllDrives=True).execute()
        self._ids = {k: v for k, v in self._ids.items() if v != f["id"]}

    def delete(self, path):
        _, f, _ = self._locate(path)
        if f:                                             # to the Drive trash: recoverable
            self.svc.files().update(fileId=f["id"], body={"trashed": True}, supportsAllDrives=True).execute()
            self._ids = {k: v for k, v in self._ids.items() if v != f["id"]}

    def revisions(self, path):
        """The id of what a delete puts in the Drive trash (a folder takes its contents with it)."""
        _, f, _ = self._locate(path)
        return [f["id"]] if f else []

    def restore(self, tokens):
        for fid in tokens:
            self.svc.files().update(fileId=fid, body={"trashed": False}, supportsAllDrives=True).execute()
        self._ids = {}

    def list(self, path):
        _, f, fid = self._locate(path)
        if fid is None:
            return {}
        if f and f.get("mimeType") != FOLDER:
            return {"/" + path.strip("/"): 0}
        out = {}

        def walk(folder, prefix):
            for c in _children(self.svc, folder):
                p = prefix + "/" + c["name"]
                if c["mimeType"] == FOLDER:
                    walk(c["id"], p)
                else:
                    out[p] = int(c.get("size") or 0)
        walk(fid, "/" + path.strip("/"))
        return out


def output_roots(svc, dest_id: str, source_ids=()):
    """Name and ids of the output folder and its _staging / _archive siblings (created if missing).
    Refuses an output folder inside the source folder, or a source inside the output folder."""
    up = set(ancestors(svc, dest_id))
    for sid in source_ids:
        if sid in up or dest_id in set(ancestors(svc, sid)):
            raise IronRuleViolation("the output folder and the source folder overlap — choose another output folder")
    d = svc.files().get(fileId=dest_id, fields="id, name, parents", supportsAllDrives=True).execute()
    parents = d.get("parents") or []
    if not parents:
        raise IronRuleViolation("the output folder must be a folder inside your Drive, not a drive's top level")
    name = d["name"].replace("/", "_")
    store = GDriveStore(svc, {"/" + name: dest_id})
    sib = {}
    for suffix in ("_staging", "_archive"):
        f = store._find(parents[0], name + suffix, folder=True) or svc.files().create(
            body={"name": name + suffix, "mimeType": FOLDER, "parents": [parents[0]]},
            fields="id", supportsAllDrives=True).execute()
        sib[suffix] = f["id"]
    return name, dest_id, sib["_staging"], sib["_archive"]


def norm_rel(p: str) -> str:
    return posixpath.normpath("/" + p).lstrip("/")
