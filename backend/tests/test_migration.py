"""Moving a server's state to another machine (the Mac in Docker): export packs it, import checks and restores it."""
import importlib.util
import json
import os
import sqlite3
import zipfile

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "scripts", f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _server(root):
    app, data = root / "backend" / "data", root / "data"
    (app / "work" / "rooms" / "r1" / "out").mkdir(parents=True)
    (data / "work" / "releases").mkdir(parents=True)
    (data / "work" / "src").mkdir(parents=True)
    (app / "secret.key").write_text("sign-in secret")
    con = sqlite3.connect(app / "trust.db")
    con.execute("CREATE TABLE room (id TEXT, name TEXT)")
    con.execute("INSERT INTO room VALUES ('r1', 'AS 3500')")
    con.commit()
    con.close()
    (app / "work" / "rooms" / "r1" / "out" / "a.md").write_text("result")
    (data / "dropbox_auth.json").write_text('{"reader": {"refresh_token": "t"}}')
    (data / "work" / "releases" / "0001-x.json").write_text('{"release": 1}')
    (data / "work" / "src" / "big.pdf").write_text("a cached source, not packed")
    return str(app), str(data)


def test_a_package_carries_the_state_and_restores_it_elsewhere(tmp_path):
    ex, im = _load("migrate_export"), _load("migrate_import")
    ex.APPDATA, ex.DATA = _server(tmp_path / "old")
    pkg = str(tmp_path / "m.zip")
    m = ex.export(pkg)
    names = {f["name"] for f in m["files"]}
    assert {"appdata/secret.key", "appdata/trust.db", "appdata/work/rooms/r1/out/a.md", "data/dropbox_auth.json",
            "data/work/releases/0001-x.json"} <= names
    assert not any("src/" in n for n in names)                         # caches stay behind

    new_app, new_data = tmp_path / "new" / "backend" / "data", tmp_path / "new" / "data"
    new_app.mkdir(parents=True)
    (new_app / "secret.key").write_text("fresh install secret")
    im.ROOTS = {"appdata": str(new_app), "data": str(new_data)}
    r = im.load(pkg)
    assert (new_app / "secret.key").read_text() == "sign-in secret"
    assert sqlite3.connect(new_app / "trust.db").execute("SELECT name FROM room").fetchone() == ("AS 3500",)
    assert (new_app / "work" / "rooms" / "r1" / "out" / "a.md").read_text() == "result"
    with zipfile.ZipFile(r["backup"]) as b:                            # what was replaced can be put back
        assert b.read("appdata/secret.key") == b"fresh install secret"


def test_a_damaged_package_changes_nothing(tmp_path):
    ex, im = _load("migrate_export"), _load("migrate_import")
    ex.APPDATA, ex.DATA = _server(tmp_path / "old")
    pkg = str(tmp_path / "m.zip")
    ex.export(pkg)
    bad = str(tmp_path / "bad.zip")
    with zipfile.ZipFile(pkg) as a, zipfile.ZipFile(bad, "w") as b:
        for i in a.infolist():
            data = a.read(i)
            b.writestr(i, b"tampered" if i.filename == "appdata/secret.key" else data)
    target = tmp_path / "new" / "backend" / "data"
    target.mkdir(parents=True)
    (target / "secret.key").write_text("keep me")
    im.ROOTS = {"appdata": str(target), "data": str(tmp_path / "new" / "data")}
    with pytest.raises(SystemExit):
        im.load(bad)
    assert (target / "secret.key").read_text() == "keep me"


def test_an_entry_outside_the_data_folders_is_refused(tmp_path):
    im = _load("migrate_import")
    im.ROOTS = {"appdata": str(tmp_path / "a"), "data": str(tmp_path / "d")}
    pkg = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("appdata/../../x.txt", "x")
        z.writestr("manifest.json", json.dumps({"files": [{"name": "appdata/../../x.txt", "sha256":
                                                           "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881", "size": 1}]}))
    with pytest.raises(SystemExit):
        im.load(pkg)
    assert not (tmp_path / "x.txt").exists()
