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


def is_path(src: str) -> bool:
    """A source may be a shared-folder link or a path in the account itself (F-1)."""
    return src.startswith("/")


def parse_link(raw: str):
    """Understand what people paste (found in testing):
      - a folder path:                         /AS 3500                       -> ("path", "/AS 3500")
      - the Dropbox website's address bar:     https://www.dropbox.com/home/AS%203500?di=...  -> ("path", "/AS 3500")
      - a shared folder link:                  https://www.dropbox.com/scl/fo/<id>/<key>?rlkey=..  -> ("link", base, "")
      - the same link after clicking into a sub-folder on the website:
                                               https://www.dropbox.com/scl/fo/<id>/<key>/AS%203500?rlkey=..&subfolder_nav_tracking=1
                                               -> ("link", "https://www.dropbox.com/scl/fo/<id>/<key>/AS%203500?rlkey=..", "/AS 3500")
    A link keeps only the rlkey parameter, which is what the Dropbox API accepts, and keeps its sub-folder path: that
    whole address is itself a link to the sub-folder. The <key> part changes as one clicks into sub-folders, so the
    parent link cannot be rebuilt from it (found 2026-11-25 with a "gas regulation" sub-folder of a folder someone
    else shared)."""
    from urllib.parse import parse_qs, unquote, urlencode, urlparse
    s = (raw or "").strip()
    if s.startswith("/"):
        return ("path", s.rstrip("/") or "/")
    u = urlparse(s)
    if u.netloc.lower() not in ("www.dropbox.com", "dropbox.com"):
        return ("link", s, "")
    parts = [unquote(p) for p in u.path.split("/") if p]
    if parts[:1] == ["home"]:
        return ("path", "/" + "/".join(parts[1:]) if len(parts) > 1 else "/")
    if parts[:2] == ["scl", "fo"] and len(parts) >= 4:
        from urllib.parse import quote
        q = parse_qs(u.query)
        query = urlencode({"rlkey": q["rlkey"][0]}) if "rlkey" in q else ""
        sub = "/" + "/".join(parts[4:]) if len(parts) > 4 else ""
        link = f"https://www.dropbox.com/scl/fo/{parts[2]}/{parts[3]}" + quote(sub) + (f"?{query}" if query else "")
        return ("link", link, sub)
    return ("link", s, "")


def canonical(dbx, raw: str) -> str:
    """A form every function here accepts: an account path, or a shared link without sub-folder."""
    kind, *rest = parse_link(raw)
    if kind == "path":
        return rest[0]
    link, sub = rest
    if not sub:
        return link
    md = dbx.sharing_get_shared_link_metadata(link)   # the sub-folder's own address works as a link
    if md.path_lower:                                 # the shared folder is in this account: use the exact path
        return md.path_lower.rstrip("/")
    return link                                       # someone else's folder: read it through the link


def display_name(dbx, root: str) -> str:
    """The folder's name with the letter case the person gave it. Paths here are kept lower-case for comparing,
    but the output mirrors the source, so its folder must read "AS 3500", not "as 3500"."""
    fallback = root.rstrip("/").split("/")[-1]
    try:
        md = dbx.files_get_metadata(root)
    except Exception:                                       # noqa: BLE001 - the lower-case name still works
        return fallback
    name = getattr(md, "name", "") or ""
    return name if name.lower() == fallback.lower() else fallback


def link_root(dbx, url):
    """Path in the user's Dropbox that a shared link points to ('' if not theirs); a path is returned as is."""
    if is_path(url):
        return _norm(url)
    md = dbx.sharing_get_shared_link_metadata(url)
    return md.path_lower or ""


# ------------------------------------------------------------------ reading

def list_shared_folder(dbx, url, rel=""):
    """Recursively list files behind a shared folder link (shared-link listing is
    not recursive, so walk subfolders). Yields dicts with rel path + identity."""
    import dropbox
    if is_path(url):                                   # read-only listing in the account itself
        res = dbx.files_list_folder(path=url.rstrip("/") + rel)
    else:
        res = dbx.files_list_folder(path=rel, shared_link=dropbox.files.SharedLink(url=url))
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
    if is_path(url):
        md = dbx.files_get_metadata(url.rstrip("/") + rel)
    else:
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
    if is_path(url):
        md, resp = dbx.files_download(url.rstrip("/") + rel)
    else:
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

    def upload_many(self, items: dict, workers: int = 6):
        """Upload many files the way Dropbox recommends for bulk writes: each file's bytes go up in its own upload
        session, several at once, and all of them are committed in one batch (one write lock instead of one per
        file). A dropped connection is retried for that one file, not for the whole document. Measured 2026-11-23:
        one request per file took ~10 s per file on this VM's flaky TLS link, and one drop restarted a document."""
        import concurrent.futures as cf

        from dropbox.files import CommitInfo, UploadSessionCursor, UploadSessionFinishArg, WriteMode

        from .sync import _retry
        for p in items:
            self.check(p)

        def start(item):
            path, data = item
            sid = _retry(lambda: self.dbx.files_upload_session_start(data, close=True).session_id, f"upload {path}")
            return UploadSessionFinishArg(UploadSessionCursor(sid, len(data)), CommitInfo(path, mode=WriteMode.overwrite, mute=True))

        with cf.ThreadPoolExecutor(max(1, min(workers, len(items)))) as ex:
            entries = list(ex.map(start, items.items()))
        for i in range(0, len(entries), 1000):
            part = entries[i:i + 1000]
            res = _retry(lambda: self.dbx.files_upload_session_finish_batch_v2(part), "commit")
            bad = [(e.commit.path, r.get_failure()) for e, r in zip(part, res.entries)
                   if r.is_failure() and not self._has(e.commit.path, e.cursor.offset)]
            # A batch commit can refuse files for a passing reason (another write holding the lock: seen 2026-11-24,
            # 28 files of one document at once). Send each of those again on its own before giving up.
            still = []
            for path, why in bad:
                try:
                    _retry(lambda p=path: self.dbx.files_upload(items[p], p, mode=WriteMode.overwrite, mute=True),
                           f"upload {path}")
                except Exception as e:             # noqa: BLE001
                    still.append((path, f"{why} / {type(e).__name__}: {e}"))
            if still:
                raise RuntimeError(f"Dropbox did not take {len(still)} file(s), e.g. {still[0][0]} ({str(still[0][1])[:200]})")
        self.written += list(items)

    def _has(self, path, size) -> bool:
        """The file is there with this size (a retried commit whose first answer was lost)."""
        try:
            return getattr(self.dbx.files_get_metadata(path), "size", -1) == size
        except Exception:                          # noqa: BLE001
            return False

    def restore(self, path, rev):
        """Bring back one deleted file at the revision it had (Dropbox keeps deleted files): inside output roots only."""
        self.check(path)
        self.dbx.files_restore(path, rev)

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
    save_role(role, app_key, res.refresh_token, res.scope)
    print(f"Saved {role} credentials to {AUTH_PATH}")


def load_auth() -> dict:
    try:
        with open(AUTH_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_auth(data: dict):
    os.makedirs(os.path.dirname(AUTH_PATH), exist_ok=True)
    tmp = AUTH_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, AUTH_PATH)
    try:
        os.chmod(AUTH_PATH, 0o600)          # credentials: owner only (no effect on Windows ACLs)
    except OSError:
        pass


def save_role(role: str, app_key: str, refresh_token: str, scopes) -> None:
    """Store one role's Dropbox credentials (used by the command line and the web settings page)."""
    data = load_auth()
    data[role] = {"app_key": app_key, "refresh_token": refresh_token, "scopes": scopes}
    _write_auth(data)


def remove_role(role: str) -> bool:
    data = load_auth()
    if role not in data:
        return False
    del data[role]
    _write_auth(data)
    return True


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

    def upload_many(self, items: dict):
        self.w.upload_many(items)

    def move(self, src, dst):
        self.w.move(src, dst)

    def delete(self, path):
        self.w.delete(path)

    def revisions(self, path):
        """[[path, rev], …] for every file under `path`: what rollback needs to bring them back after a delete."""
        import dropbox
        try:
            res = self.w.dbx.files_list_folder(path, recursive=True)
        except dropbox.exceptions.ApiError:
            try:
                md = self.w.dbx.files_get_metadata(path)
                return [[md.path_display, md.rev]] if isinstance(md, dropbox.files.FileMetadata) else []
            except dropbox.exceptions.ApiError:
                return []
        out = []
        while True:
            out += [[e.path_display, e.rev] for e in res.entries if isinstance(e, dropbox.files.FileMetadata)]
            if not res.has_more:
                return out
            res = self.w.dbx.files_list_folder_continue(res.cursor)

    def restore(self, tokens):
        for path, rev in tokens:
            self.w.restore(path, rev)

    def drop_empty(self, path):
        """Delete a folder that holds no files any more (a published run's staging); a missing one is fine."""
        import dropbox
        if self.list(path):
            return False
        try:
            self.w.delete(path)
            return True
        except dropbox.exceptions.ApiError:
            return False

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
