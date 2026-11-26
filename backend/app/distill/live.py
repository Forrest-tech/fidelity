# -*- coding: utf-8 -*-
"""The live copy of a document in the output folder, read so a new result can be compared with it before it is
accepted, and the output account's folders, listed so people can pick a folder instead of typing a path.

Read-only: only the reader connection is used and nothing here writes anything.
"""
from __future__ import annotations

import difflib
import os

from . import dropbox_io as D
from . import run as R

ACCEPT_KEYS = ("accepted_by", "accepted_at", "accuracy")   # written when a file is accepted; not a content change
MAX_DIFF_LINES = 800                                         # per file; the rest is summarised
MAX_FILES = 40                                               # files compared inside one multi-file result
MAX_BYTES = 8_000_000                                        # larger files are compared by size only


class LiveError(Exception):
    def __init__(self, status: int, message: str, code: str = ""):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code   # code: the page shows it in its language


# ------------------------------------------------------------------ the output folder (Dropbox)
class DropboxLive:
    """The output folder of a room, read through the reader connection."""

    def __init__(self, link: str):
        try:
            self.dbx = D.client("reader")
        except (OSError, ValueError, RuntimeError) as e:
            raise LiveError(409, "Dropbox is not connected; connect it in Settings") from e
        self.root = D.link_root(self.dbx, D.canonical(self.dbx, link)).rstrip("/")
        if not self.root:
            raise LiveError(422, "the output must be a folder in your own Dropbox")

    def _path(self, key: str) -> str:
        return self.root + "/" + key.strip("/")

    def listing(self, key: str) -> dict:
        """{path inside the document: size}; "" is the document itself when it is a single file; {} = not there."""
        import dropbox
        path = self._path(key)
        try:
            md = self.dbx.files_get_metadata(path)
        except dropbox.exceptions.ApiError:
            return {}
        if isinstance(md, dropbox.files.FileMetadata):
            return {"": md.size}
        out = {}
        res = self.dbx.files_list_folder(path, recursive=True)
        base = md.path_lower.rstrip("/") + "/"
        while True:
            for e in res.entries:
                if isinstance(e, dropbox.files.FileMetadata):
                    out[e.path_lower[len(base):] if e.path_lower.startswith(base) else e.name] = e.size
            if not res.has_more:
                return out
            res = self.dbx.files_list_folder_continue(res.cursor)

    def read(self, key: str, inner: str = "") -> bytes:
        _, resp = self.dbx.files_download(self._path(key) + ("/" + inner if inner else ""))
        return resp.content

    def existing(self) -> set:
        """Lower-case paths, relative to the output folder, of every file in it (one listing)."""
        n = len(D._norm(self.root)) + 1
        return {p[n:] for p in D.list_tree(self.dbx, self.root)}


def open_live(link: str):
    from . import gdrive_io as G
    if G.is_gdrive(link):
        raise LiveError(422, "comparing with a Google Drive output folder is not available yet")
    return DropboxLive(link)


# ------------------------------------------------------------------ comparing
def _strip_accept(text: str) -> str:
    """Drop the lines that only record an acceptance, so they do not show as changes."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    head = [ln for ln in text[4:end].split("\n") if (ln.split(":", 1)[0].strip() if ":" in ln else "") not in ACCEPT_KEYS]
    return "---\n" + "\n".join(head) + text[end:]


def _text(data: bytes) -> list:
    return _strip_accept(data.decode("utf-8", "replace").replace("\r\n", "\n")).split("\n")


def diff_lines(old: list, new: list) -> tuple[list, int, int, bool]:
    """Unified diff as [{op, text}] with op one of ' ', '+', '-', '@'; plus lines added, removed, truncated."""
    out, added, removed = [], 0, 0
    for ln in difflib.unified_diff(old, new, lineterm="", n=2):
        if ln.startswith(("---", "+++")):
            continue
        op = "@" if ln.startswith("@@") else ln[:1]
        if op == "+":
            added += 1
        elif op == "-":
            removed += 1
        if len(out) < MAX_DIFF_LINES:
            out.append({"op": op, "text": ln if op == "@" else ln[1:]})
    return out, added, removed, len(out) >= MAX_DIFF_LINES and added + removed > 0


def _local_files(base: str) -> dict:
    lp = R.longpath(base)
    if os.path.isfile(lp):
        return {"": base}
    out = {}
    for root, _, names in os.walk(lp):
        for fn in sorted(names):
            full = os.path.join(root, fn)
            out[os.path.relpath(full, lp).replace(os.sep, "/").lower()] = full
    return out


def compare(local_base: str, key: str, live) -> dict:
    """Compare one document's new result (a file or a folder on this machine) with its live copy.

    status: "new" (not in the output folder yet), "same" (only the acceptance lines differ) or "changed"."""
    local = _local_files(local_base)
    if not local:
        raise LiveError(409, "the distilled result is no longer on this machine; run the room again")
    remote = live.listing(key)
    files, added, removed = [], 0, 0
    for inner in sorted(set(local) | set(remote))[:MAX_FILES]:
        name = inner or key.rsplit("/", 1)[-1]
        if inner not in remote:
            st = "new"
        elif inner not in local:
            st = "removed"
        else:
            st = None
        entry = {"path": name, "status": st, "lines": [], "added": 0, "removed": 0, "truncated": False}
        is_text = name.lower().endswith((".md", ".txt", ".csv", ".json", ".yaml", ".yml"))
        new = old = None
        if inner in local and os.path.getsize(R.longpath(local[inner])) <= MAX_BYTES:
            with open(R.longpath(local[inner]), "rb") as f:
                new = f.read()
        if inner in remote and remote[inner] <= MAX_BYTES and (is_text or new is not None):
            old = live.read(key, inner)
        if st is None:
            if new is None or old is None:
                st = "same" if remote[inner] == os.path.getsize(R.longpath(local[inner])) else "changed"
            elif is_text:
                st = "same" if _text(old) == _text(new) else "changed"
            else:
                st = "same" if old == new else "changed"
            entry["status"] = st
        if is_text and st != "same":
            lines, a, r, cut = diff_lines(_text(old) if old is not None else [], _text(new) if new is not None else [])
            entry.update(lines=lines, added=a, removed=r, truncated=cut)
            added, removed = added + a, removed + r
        files.append(entry)
    status = "new" if not remote else "same" if all(f["status"] == "same" for f in files) else "changed"
    return {"status": status, "key": key, "files": files, "added": added, "removed": removed,
            "more_files": max(0, len(set(local) | set(remote)) - MAX_FILES)}


def impact(keys: list, live) -> dict:
    """How many of these documents are new to the output folder and how many replace a live copy."""
    have = live.existing()
    folders = set()
    for p in have:
        parts = p.split("/")
        for i in range(1, len(parts)):
            folders.add("/".join(parts[:i]))
    new = replaces = 0
    for k in keys:
        k = k.strip("/").lower()
        if k in have or k in folders:
            replaces += 1
        else:
            new += 1
    return {"new": new, "replaces": replaces}


# ------------------------------------------------------------------ picking a folder
def subfolders(path: str = "", dbx=None) -> dict:
    """The folders directly inside `path` of the connected Dropbox account ("" or "/" = the top)."""
    import dropbox
    if dbx is None:
        try:
            dbx = D.client("reader")
        except (OSError, ValueError, RuntimeError) as e:
            raise LiveError(409, "Dropbox is not connected; connect it in Settings") from e
    p = (path or "").strip()
    if ".." in p.split("/"):
        raise LiveError(422, "not a folder path")
    p = "" if p in ("", "/") else "/" + p.strip("/")
    try:
        res = dbx.files_list_folder(p)
    except dropbox.exceptions.ApiError as e:
        raise LiveError(404, "that folder does not exist or cannot be read") from e
    folders = []
    while True:
        folders += [{"name": e.name, "path": e.path_display} for e in res.entries if isinstance(e, dropbox.files.FolderMetadata)]
        if not res.has_more:
            break
        res = dbx.files_list_folder_continue(res.cursor)
    folders.sort(key=lambda f: f["name"].lower())
    display = p or "/"
    if p:
        try:
            display = dbx.files_get_metadata(p).path_display
        except dropbox.exceptions.ApiError:
            pass
    return {"path": display, "folders": folders}


def inspect_link(raw: str, dbx=None, limit: int = 5000) -> dict:
    """A Dropbox shared link someone else gave us, read before it becomes a room's input (read-only calls only).

    Reports what a run would read: the folder's name, how many files, how many of a kind the distiller handles, and
    the total size. A link to a folder in the connected account itself is reported with its path, which runs use
    instead (requirements v3 S-4). The output folder is never a link: it must be a folder in the connected account."""
    import time

    from .office import SUPPORTED
    from urllib.parse import urlparse
    kind, *_ = D.parse_link(raw or "")
    u = urlparse((raw or "").strip())
    if kind != "link" or u.netloc.lower() not in ("www.dropbox.com", "dropbox.com"):
        raise LiveError(422, "paste a Dropbox shared link (https://www.dropbox.com/scl/fo/…)", "not_link")
    if u.path.startswith(("/scl/fi/", "/s/")):              # what people paste most often by mistake (2026-11-25)
        raise LiveError(422, "this is a link to one file; share the folder that holds the files instead", "file_link")
    if u.path.startswith("/scl/fo/") and "rlkey=" not in u.query:
        raise LiveError(422, "the link is incomplete (no rlkey=…); copy it again with Share > Copy link", "no_rlkey")
    if dbx is None:
        try:
            dbx = D.client("reader")
        except (OSError, ValueError, RuntimeError) as e:
            raise LiveError(409, "Dropbox is not connected; connect it in Settings", "not_connected") from e
    try:
        link = D.canonical(dbx, raw)
        root = D.link_root(dbx, link)
        name = getattr(dbx.sharing_get_shared_link_metadata(link), "name", "") or "shared folder"
    except SystemExit as e:                                  # a sub-folder link of a folder shared with us
        raise LiveError(422, str(e)) from e
    except Exception as e:                                   # noqa: BLE001 - removed, expired or not a folder link
        raise LiveError(404, code="gone", message="Dropbox cannot open this link: it may have been removed, expired or need a "
                             f"password ({type(e).__name__})") from e
    files = supported = size = 0
    started, complete = time.time(), True
    try:
        for f in D.list_shared_folder(dbx, link):
            files += 1
            size += f.get("size") or 0
            supported += f["rel"].lower().endswith(SUPPORTED)
            if files >= limit or time.time() - started > 12:
                complete = False
                break
    except Exception as e:                                   # noqa: BLE001
        raise LiveError(404, f"Dropbox cannot list this link's files ({type(e).__name__})", "list_failed") from e
    return {"link": link, "name": name, "in_account": bool(root), "path": root or None, "files": files,
            "supported": supported, "size_mb": round(size / 1e6, 1), "complete": complete}
