from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.spa import SPAStaticFiles


def make(tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "a.js").write_text("console.log(1)")
    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=str(tmp_path), html=True))
    return TestClient(app)


def test_client_side_route_returns_the_app(tmp_path):
    r = make(tmp_path).get("/documents")
    assert r.status_code == 200 and "app" in r.text


def test_real_asset_is_served_and_api_404_stays_404(tmp_path):
    c = make(tmp_path)
    assert c.get("/a.js").text.startswith("console")
    assert c.get("/api/v1/nope").status_code == 404
