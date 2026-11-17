"""Distillation as a job: handler behaviour and API access control."""
import asyncio
import os

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth.models import Role, User
from app.auth.schemas import UserCreate
from app.auth.users import UserManager
from app.jobs import distill_job as DJ
from app.main import app
from app.migrate import upgrade
from app.orm import SessionLocal
from fastapi_users.db import SQLAlchemyUserDatabase

PW = "correct-horse-battery"


def make_pdf(path, pages=4):
    doc = pymupdf.open()
    for i in range(1, pages + 1):
        pg = doc.new_page()
        pg.insert_text((72, 90), "Section %d Scope" % i, fontsize=16, fontname="hebo")
        pg.insert_text((72, 130), "The maximum height is 2400 mm.", fontsize=11)
    doc.set_toc([[1, "Section 1 Scope", 1]])
    doc.save(path)


@pytest.fixture()
def source(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    (root / "sub").mkdir(parents=True)
    make_pdf(str(root / "sub" / "Std 2025.pdf"))
    (root / "notes.txt").write_text("x")
    monkeypatch.setattr(config, "get_source", lambda sid: {"id": sid, "src_root": str(root), "md_root": str(tmp_path / "md")} if sid == "t" else None)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "CACHE_DIR", str(tmp_path / "cache"))
    return root


def test_handler_distills_and_writes_result(source, tmp_path):
    seen = []
    out = DJ.handle_distill({"id": "job1", "kind": "distill:t", "rel": "sub/Std 2025.pdf"}, lambda p, m="": seen.append(p))
    assert out["verdict"] == "PASS" and out["checks"]["tables"] is not None
    assert os.path.isfile(DJ.report_path("t", "job1"))
    assert os.path.isfile(os.path.join(DJ.out_root("t"), "sub", "Std 2025.pdf.md"))
    assert seen


def test_handler_refuses_paths_outside_the_source(source):
    with pytest.raises(RuntimeError, match="escapes"):
        DJ.handle_distill({"id": "j", "kind": "distill:t", "rel": "../../etc/passwd.pdf"}, lambda *a: None)


def test_handler_rejects_unknown_format_and_missing_file(source):
    with pytest.raises(RuntimeError, match="not found"):
        DJ.handle_distill({"id": "j", "kind": "distill:t", "rel": "nope.pdf"}, lambda *a: None)
    with pytest.raises(RuntimeError, match="not handled"):
        DJ.handle_distill({"id": "j", "kind": "distill:t", "rel": "notes.txt"}, lambda *a: None)


def test_batch_listing_is_confined_to_the_source(source):
    assert DJ.list_source_pdfs("t") == ["sub/Std 2025.pdf"]
    assert DJ.list_source_pdfs("t", "..") is None
    assert DJ.list_source_pdfs("nope") is None


async def _mk(email, role):
    async with SessionLocal() as s:
        try:
            await UserManager(SQLAlchemyUserDatabase(s, User)).create(UserCreate(email=email, password=PW, role=role, is_verified=True))
        except Exception:
            pass


@pytest.fixture()
def api(monkeypatch):
    upgrade()
    for r in Role:
        asyncio.run(_mk("dj-%s@example.com" % r.value, r))
    submitted = []
    from app.api import distill as api_mod
    monkeypatch.setattr(api_mod.queue, "submit", lambda kind, rel="", message="": submitted.append((kind, rel)) or "jid%d" % len(submitted))

    def login(role):
        c = TestClient(app)
        assert c.post("/api/v1/auth/login", data={"username": "dj-%s@example.com" % role, "password": PW}).status_code in (200, 204)
        return c
    return login, submitted


def test_distill_endpoints_need_login_and_reviewer_role(api, source):
    login, submitted = api
    assert TestClient(app).post("/api/v1/distill", json={"rel": "a.pdf"}).status_code == 401
    assert login("viewer").post("/api/v1/distill", json={"rel": "a.pdf"}).status_code == 403
    assert submitted == []
    r = login("reviewer").post("/api/v1/distill", json={"rel": "sub/Std 2025.pdf", "sid": "t"})
    assert r.status_code == 200 and submitted == [("distill:t", "sub/Std 2025.pdf")]


def test_batch_endpoint_submits_one_job_per_pdf_and_rejects_bad_folder(api, source):
    login, submitted = api
    c = login("reviewer")
    r = c.post("/api/v1/distill/batch", json={"sid": "t"})
    assert r.json()["files"] == 1 and submitted[-1] == ("distill:t", "sub/Std 2025.pdf")
    assert c.post("/api/v1/distill/batch", json={"sid": "t", "folder": ".."}).status_code == 404
    assert c.post("/api/v1/distill", json={"rel": "x.docx"}).status_code == 415
