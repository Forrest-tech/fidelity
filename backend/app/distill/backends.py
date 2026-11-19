# -*- coding: utf-8 -*-
"""Where sources come from and where output goes: Dropbox or Google Drive, in any combination.

A *source* lists, downloads and re-checks files (read-only connection). A *destination* gives the
guarded store the Publisher writes through, plus its _staging / _archive siblings. The provider is
chosen from the link: a Google Drive folder link (or gdrive:<id>) is Google Drive; anything else is
Dropbox (a shared link or a /path in the connected account).
"""
from __future__ import annotations

import os

from . import dropbox_io as D
from . import gdrive_io as G
from . import run as R


class DropboxSource:
    provider = "dropbox"

    def __init__(self, link: str):
        self.link = link
        self.dbx = D.client("reader")
        self.root = D.link_root(self.dbx, link)            # e.g. /2025 ('' for a link outside the account)
        self.label = self.root or link                      # ledger key, shown in logs
        self.name = self.root.rstrip("/").split("/")[-1] if self.root else "source"

    def snapshot(self) -> dict:
        return D.snapshot(self.dbx, self.link)

    def download(self, rel, entry, local_path):
        D.download(self.dbx, self.link, rel, local_path)

    def local_matches(self, local_path, entry) -> bool:
        return os.path.exists(local_path) and R.dropbox_content_hash(local_path) == entry["content_hash"]

    def verify_local(self, local_path, entry) -> bool:
        return R.dropbox_content_hash(local_path) == entry["content_hash"]

    def identity(self, rel, entry) -> dict:
        return D.file_identity(self.dbx, self.link, rel)


class GDriveSource:
    provider = "gdrive"

    def __init__(self, link: str):
        self.link = link
        self.svc = G.service("reader")
        self.fid = G.folder_id(link)
        meta = self.svc.files().get(fileId=self.fid, fields="id, name", supportsAllDrives=True).execute()
        self.name = meta["name"].replace("/", "_")
        self.root = ""
        self.label = "gdrive:" + self.fid

    def snapshot(self) -> dict:
        return G.snapshot(self.svc, self.fid)

    def download(self, rel, entry, local_path):
        G.download(self.svc, entry, local_path)

    def local_matches(self, local_path, entry) -> bool:
        return G.local_matches(local_path, entry)

    def verify_local(self, local_path, entry) -> bool:
        # ordinary files: md5 must match Drive's; Google Docs/Sheets/Slides are exports (no stored hash)
        return entry["content_hash"].startswith("rev:") or G.md5_file(local_path) == entry["content_hash"]

    def identity(self, rel, entry) -> dict:
        return G.identity(self.svc, entry)


class DropboxDest:
    provider = "dropbox"

    def __init__(self, link: str, source):
        writer = D.client("writer")
        self.root = D.link_root(writer, link)                # e.g. /transfer_md
        if not self.root:
            raise SystemExit("The output link must be a folder in your own Dropbox")
        self.stage_root, self.archive_root = self.root.rstrip("/") + "_staging", self.root.rstrip("/") + "_archive"
        protect = [source.root] if source.provider == "dropbox" else []
        guard = D.SafeWriter(writer, self.root, protect, extra_roots=[self.stage_root, self.archive_root])  # raises on overlap
        self.store = D.DropboxStore(guard)


class GDriveDest:
    provider = "gdrive"

    def __init__(self, link: str, source):
        svc = G.service("writer")
        protect = [source.fid] if source.provider == "gdrive" else []
        name, dest_id, stage_id, archive_id = G.output_roots(svc, G.folder_id(link), protect)  # raises on overlap
        self.root = "/" + name
        self.stage_root, self.archive_root = self.root + "_staging", self.root + "_archive"
        self.store = G.GDriveStore(svc, {self.root: dest_id, self.stage_root: stage_id, self.archive_root: archive_id})


def open_source(link: str):
    return GDriveSource(link) if G.is_gdrive(link) else DropboxSource(link)


def open_dest(link: str, source):
    return GDriveDest(link, source) if G.is_gdrive(link) else DropboxDest(link, source)
