# -*- coding: utf-8 -*-
"""Backups proven by restoring them, health figures and alerts (requirements v2, phase D)."""
import json
import os
import sqlite3
import time
import zipfile

import pytest

from app.ops import backup as BK
from app.ops import health as H


@pytest.fixture()
def site(tmp_path, monkeypatch):
    be, root = tmp_path / "backend-data", tmp_path / "data"
    (be / "work" / "rooms" / "r1" / "out").mkdir(parents=True)
    (root / "work" / "publish").mkdir(parents=True)
    for name, rows in (("trust.db", 3), ("fidelity.db", 1)):
        con = sqlite3.connect(be / name)
        con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        con.executemany("INSERT INTO t (v) VALUES (?)", [(f"row {i}",) for i in range(rows)])
        con.commit()
        con.close()
    (be / "config.json").write_text("{}", encoding="utf-8")
    (be / "secret.key").write_text("k", encoding="utf-8")
    (be / "work" / "rooms" / "r1" / "out" / "a.pdf.md").write_text("# A\n", encoding="utf-8")
    (be / "work" / "rooms" / "r1" / "cache.tmp").write_text("x", encoding="utf-8")
    (root / "dropbox_auth.json").write_text("{}", encoding="utf-8")
    (root / "work" / "publish" / "20261122.json").write_text("{}", encoding="utf-8")
    (root / "work" / "src").mkdir()
    (root / "work" / "src" / "big.pdf").write_bytes(b"0" * 1000)       # a download cache: not kept
    monkeypatch.setattr(BK, "BACKEND_DATA", str(be))
    monkeypatch.setattr(BK, "ROOT_DATA", str(root))
    monkeypatch.setattr(BK, "FILES", ((str(be), BK.FILES[0][1]), (str(root), BK.FILES[1][1])))
    return be, root, tmp_path / "backups"


def test_a_backup_holds_the_databases_settings_and_results_and_restores_to_the_same_rows(site, tmp_path):
    be, root, dest = site
    rec = BK.make(str(dest))
    assert rec["ok"], rec["problems"]
    assert rec["databases"] == ["trust.db", "fidelity.db"]
    names = set(zipfile.ZipFile(rec["path"]).namelist())
    assert {"databases/trust.db", "databases/fidelity.db", "backend-data/config.json", "backend-data/secret.key",
            "backend-data/work/rooms/r1/out/a.pdf.md", "data/dropbox_auth.json", "data/work/publish/20261122.json"} <= names
    assert not any("src/" in n or n.endswith(".tmp") for n in names)    # caches are rebuilt, not kept
    files = BK.restore_to(rec["path"], str(tmp_path / "restored"))
    assert "databases/trust.db" in files
    con = sqlite3.connect(tmp_path / "restored" / "databases" / "trust.db")
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    con.close()
    assert BK.status(str(dest))["path"] == rec["path"]
    with pytest.raises(FileExistsError):
        BK.restore_to(rec["path"], str(tmp_path / "restored"))             # never over existing files


def test_a_backup_taken_while_the_database_is_written_is_still_consistent(site):
    be, root, dest = site
    con = sqlite3.connect(be / "trust.db")
    con.execute("INSERT INTO t (v) VALUES ('uncommitted')")               # an open write transaction
    rec = BK.make(str(dest))
    con.rollback()
    con.close()
    assert rec["ok"], rec["problems"]


def test_a_damaged_backup_is_caught_by_verification(site, tmp_path):
    be, root, dest = site
    rec = BK.make(str(dest))
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(rec["path"]) as zin, zipfile.ZipFile(bad, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "backend-data/config.json":
                data = b'{"changed": true}'
            zout.writestr(item, data)
    r = BK.verify(str(bad))
    assert not r["ok"] and any("config.json" in p for p in r["problems"])


def test_only_the_newest_backups_are_kept(site):
    be, root, dest = site
    for i in range(4):
        BK.make(str(dest), now=time.time() + i * 86400)
    BK.prune(str(dest), keep=2)
    assert len([n for n in os.listdir(dest) if n.endswith(".zip")]) == 2


def _report(**kw):
    r = {"disk": {"free": 20 * 1024 ** 3, "total": 50 * 1024 ** 3}, "memory": {"available": 2 * 1024 ** 3},
         "backup": {"ok": True, "at": time.time() - 3600, "created": "x"},
         "runs": {"total": 10, "failed": 0, "interrupted": 0, "failure_rate": 0.0}}
    for k, v in kw.items():
        r[k] = {**r[k], **v} if isinstance(v, dict) and r.get(k) else v
    return r


def test_alerts_name_what_needs_doing_and_stay_quiet_when_all_is_well():
    assert H.alerts(_report()) == []
    kinds = {a["kind"]: a["level"] for a in H.alerts(_report(disk={"free": 1 * 1024 ** 3}))}
    assert kinds == {"disk": "bad"}
    assert {a["kind"] for a in H.alerts(_report(backup=None))} == {"backup_none"}
    old = H.alerts(_report(backup={"ok": True, "at": time.time() - 40 * 3600, "created": "y"}))
    assert [a["kind"] for a in old] == ["backup_old"]
    failed = H.alerts(_report(backup={"ok": False, "problems": ["trust.db: integrity_check says x"], "at": 1}))
    assert failed[0]["kind"] == "backup_failed" and failed[0]["level"] == "bad"
    runs = H.alerts(_report(runs={"total": 10, "failed": 3, "interrupted": 0, "failure_rate": 0.3}))
    assert [a["kind"] for a in runs] == ["runs_failing"]
    assert H.alerts(_report(runs={"total": 4, "failed": 1, "interrupted": 0, "failure_rate": 0.25})) == []  # too few to tell


def test_metrics_are_in_prometheus_text_format(monkeypatch):
    monkeypatch.setattr(H, "report", lambda: {**_report(), "uptime_s": 5, "alerts": [],
                                               "runs": {"total": 10, "failed": 1, "interrupted": 0, "failure_rate": 0.1,
                                                        "queued": 2, "running": 1}})
    text = H.metrics()
    assert "# TYPE fidelity_disk_free_bytes gauge" in text and "fidelity_jobs_queued 2" in text
    assert "fidelity_backup_verified 1" in text and text.endswith("\n")
