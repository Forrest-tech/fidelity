# -*- coding: utf-8 -*-
"""Dropbox input/output for the distiller.

Iron rule: the SOURCE folder is never modified. Enforced three ways:
  1. Source files are read only through shared-link endpoints (list + download),
     which cannot change anything. A separate read-only app/token may be used.
  2. All writes go through SafeWriter: the destination path must lie under the
     output root and must not lie under any source root — otherwise it raises.
     Only uploads are implemented; there is no delete/move code at all.
  3. A snapshot (id, rev, content_hash, size) of every source file is taken
     before and after the run; any difference fails the run loudly.

One-time authorisation (run by the user in a terminal; the token never leaves
this machine and is stored in data/dropbox_auth.json, which is git-ignored):
    python -m app.distill.dropbox_io auth --app-key <APP_KEY>
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
AUTH_PATH = os.path.abspath(os.path.join(DATA_DIR, "dropbox_auth.json"))
READ_SCOPES = ["files.metadata.read", "files.content.read", "sharing.read", "account_info.read"]  # account_info.read: needed by rclone (get current account); read-only
WRITE_SCOPES = READ_SCOPES + ["files.content.write"]


class IronRuleViolation(RuntimeError):
    pass


def _norm(p: str) -> str:
    p = posixpath.normpath("/" + p.strip().replace("\\", "/").lstrip("/")).lower()
    p = "/" + p.lstrip("/")                      # normpath keeps a leading '//' — collapse it
    return "/" if p == "/" else p.rstrip("/")


def is_under(path: str, root: str) -> bool:
    path, root = _norm(path), _norm(root)
    return root == "/" or path == root or path.startswith(root + "/")


def client(role="writer"):
    import dropbox
    with open(AUTH_PATH, encoding="utf-8") as f:
        auth = json.load(f)
    a = auth.get(role) or auth.get("writer") or auth.get("reader")
    if not a:
        raise RuntimeError(f"No Dropbox credentials in {AUTH_PATH}; run the 'auth' command first")
    return dropbox.Dropbox(oauth2_refresh_token=a["refresh_token"], app_key=a["app_key"])


def link_root(dbx, url):
    """Path in the user's Dropbox that a shared link points to ('' if not theirs)."""
    md = dbx.sharing_get_shared_link_metadata(url)
    return md.path_lower or ""


# ------------------------------------------------------------------ reading

def list_shared_folder(dbx, url, rel=""):
    """Recursively list files behind a shared folder link (shared-link listing is
    not recursive, so walk subfolders). Yields dicts with rel path + identity."""
    import dropbox
    link = dropbox.files.SharedLink(url=url)
    res = dbx.files_list_folder(path=rel, shared_link=link)
    while True:
        for e in res.entries:
            child = f"{rel}/{e.name}"
            if isinstance(e, dropbox.files.FolderMetadata):
                yield from list_shared_folder(dbx, url, child)
            elif isinstance(e, dropbox.files.FileMetadata):
                yield {"rel": child, "id": e.id, "rev": e.rev, "content_hash": e.content_hash,
                       "size": e.size, "server_modified": e.server_modified.isoformat()}
        if not res.has_more:
            break
        res = dbx.files_list_folder_continue(res.cursor)


def snapshot(dbx, url):
    return {f["rel"]: f for f in list_shared_folder(dbx, url)}


def list_tree(dbx, path):
    """Normalised paths of all files under a folder in the user's Dropbox (read-only)."""
    import dropbox
    out = set()
    try:
        res = dbx.files_list_folder(path, recursive=True)
    except dropbox.exceptions.ApiError:
        return out
    while True:
        out.update(_norm(e.path_lower) for e in res.entries if isinstance(e, dropbox.files.FileMetadata))
        if not res.has_more:
            return out
        res = dbx.files_list_folder_continue(res.cursor)


def file_identity(dbx, url, rel):
    """Current id/rev/size of one file behind a shared folder link (read-only call)."""
    md = dbx.sharing_get_shared_link_metadata(url, path=rel)
    return {"id": md.id, "rev": getattr(md, "rev", None), "size": getattr(md, "size", None)}


def compare_snapshots(before, after):
    diffs = []
    for rel in sorted(set(before) | set(after)):
        a, b = before.get(rel), after.get(rel)
        if a is None:
            diffs.append(f"ADDED {rel}")
        elif b is None:
            diffs.append(f"REMOVED {rel}")
        else:
            for k in ("id", "rev", "content_hash", "size"):
                if a[k] != b[k]:
                    diffs.append(f"CHANGED {rel} ({k})")
    return diffs


def download(dbx, url, rel, local_path):
    md, resp = dbx.sharing_get_shared_link_file(url=url, path=rel)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    tmp = local_path + ".part"
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(1 << 20):
            f.write(chunk)
    os.replace(tmp, local_path)
    return md


# ------------------------------------------------------------------ writing

class SafeWriter:
    def __init__(self, dbx, dest_root, forbidden_roots, extra_roots=()):
        """dest_root is the live knowledge-base folder; extra_roots (staging, archive) are further
        OUTPUT-side folders. Every output root must stay clear of every source root."""
        roots = [dest_root] + [r for r in extra_roots if r]
        for r in roots:
            if not r or _norm(r) == "/":
                raise IronRuleViolation("refusing to write to the Dropbox root")
            for fr in forbidden_roots:
                if fr and (is_under(r, fr) or is_under(fr, r)):
                    raise IronRuleViolation(f"output root {r} overlaps source root {fr}")
        self.dbx, self.dest_root, self.forbidden = dbx, _norm(dest_root), [f for f in forbidden_roots if f]
        self.roots = [_norm(r) for r in roots]
        self.written = []

    def check(self, path):
        if not any(is_under(path, r) and _norm(path) != r for r in self.roots):
            raise IronRuleViolation(f"write outside output root: {path}")
        for fr in self.forbidden:
            if is_under(path, fr):
                raise IronRuleViolation(f"write inside SOURCE folder refused: {path}")

    def upload(self, path, data: bytes):
        import dropbox
        self.check(path)
        self.dbx.files_upload(data, path, mode=dropbox.files.WriteMode.overwrite, mute=True)
        self.written.append(path)

    def move(self, src, dst):
        """Server-side move of a file or folder; both ends must be inside output roots."""
        self.check(src)
        self.check(dst)
        self.dbx.files_move_v2(src, dst, autorename=False, allow_ownership_transfer=False)

    def delete(self, path):
        """Delete one file inside the OUTPUT root (same guard as upload; goes to Dropbox
        'Deleted files', recoverable). Can never reach the source folder."""
        self.check(path)
        self.dbx.files_delete_v2(path)

    def upload_tree(self, local_root, dest_prefix=None, log=print):
        prefix = dest_prefix or self.dest_root
        n = 0
        local_root = os.path.abspath(local_root)
        if os.name == "nt" and not local_root.startswith("\\\\?\\"):
            local_root = "\\\\?\\" + local_root          # extended-length path (no 260-char limit)
        for root, _, files in os.walk(local_root):
            for fn in sorted(files):
                lp = os.path.join(root, fn)
                rel = os.path.relpath(lp, local_root).replace(os.sep, "/")
                with open(lp, "rb") as f:
                    self.upload(f"{prefix}/{rel}", f.read())
                n += 1
                if n % 25 == 0:
                    log(f"  uploaded {n} files")
        return n


# ------------------------------------------------------------------ auth CLI

def auth(app_key, role, write):
    import re
    import dropbox
    import requests
    app_key = app_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{8,32}", app_key):
        raise SystemExit(f"'{app_key}' does not look like a Dropbox App key (letters/digits only, "
                         "about 15 characters). Copy it from the Settings tab of your app at "
                         "https://www.dropbox.com/developers/apps and run the command again.")
    flow = dropbox.DropboxOAuth2FlowNoRedirect(app_key, use_pkce=True, token_access_type="offline",
                                               scope=WRITE_SCOPES if write else READ_SCOPES)
    print("1. Open this URL, sign in to Dropbox and click Allow:\n\n   " + flow.start() + "\n")
    code = input("2. Paste the authorisation code here: ").strip()
    try:
        res = flow.finish(code)
    except requests.exceptions.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("error_description", "")
        except Exception:
            pass
        raise SystemExit("Dropbox refused the code (" + (detail or str(e)) + ").\n"
                         "Check: the App key is correct; the 4 permissions were ticked AND submitted "
                         "before authorising; the code was pasted within a few minutes and only once. "
                         "Then run the command again (each run makes a new URL and code).")
    data = {}
    if os.path.exists(AUTH_PATH):
        with open(AUTH_PATH, encoding="utf-8") as f:
            data = json.load(f)
    data[role] = {"app_key": app_key, "refresh_token": res.refresh_token, "scopes": res.scope}
    os.makedirs(os.path.dirname(AUTH_PATH), exist_ok=True)
    with open(AUTH_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    print(f"Saved {role} credentials to {AUTH_PATH}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth")
    a.add_argument("--app-key", required=True)
    a.add_argument("--role", choices=["reader", "writer"], default="writer")
    a.add_argument("--read-only", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "auth":
        auth(a.app_key, a.role, write=not a.read_only and a.role == "writer")
    return 0


if __name__ == "__main__":
    sys.exit(main())


class DropboxStore:
    """Storage interface used by publish.Publisher, on top of the guarded writer."""

    def __init__(self, writer: SafeWriter):
        self.w = writer

    def upload(self, path, data):
        self.w.upload(path, data)

    def move(self, src, dst):
        self.w.move(src, dst)

    def delete(self, path):
        self.w.delete(path)

    def list(self, path):
        import dropbox
        out = {}
        try:
            res = self.w.dbx.files_list_folder(path, recursive=True)
        except dropbox.exceptions.ApiError:
            # a single file (or nothing) rather than a folder
            try:
                md = self.w.dbx.files_get_metadata(path)
                return {md.path_display: getattr(md, "size", 0)}
            except dropbox.exceptions.ApiError:
                return {}
        while True:
            for e in res.entries:
                if isinstance(e, dropbox.files.FileMetadata):
                    out[e.path_display] = e.size
            if not res.has_more:
                break
            res = self.w.dbx.files_list_folder_continue(res.cursor)
        return out
