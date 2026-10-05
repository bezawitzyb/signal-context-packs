"""API skeleton: /ping, /health, placeholder page. No real database or paid API."""

from fastapi.testclient import TestClient

from ctxpack import db
from ctxpack.api.main import app

# No "with": the startup tasks (which would use DATABASE_URL) do not run.
client = TestClient(app)


def test_ping_never_touches_the_database(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("/ping must not touch the database")

    monkeypatch.setattr(db, "get_engine", boom)
    monkeypatch.setattr(db, "init_engine", boom)
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.text == "ok"


def test_health_ok_with_database(temp_db):
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["database"] is True
    assert body["version"]


def test_health_reports_unreachable_database(monkeypatch):
    def broken():
        raise RuntimeError("no database")

    monkeypatch.setattr(db, "get_engine", broken)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database"] is False
    assert response.json()["ok"] is False


def test_home_placeholder(tmp_path, monkeypatch):
    from ctxpack.api import main

    monkeypatch.setattr(main, "DIST", tmp_path / "no-build")  # without a frontend build: the placeholder
    response = client.get("/")
    assert response.status_code == 200
    assert "SIGNAL - Context Packs" in response.text
    assert "Coming soon." in response.text


# --- the web app (Step 4.1): frontend/dist with an index.html fallback ---------------------

def test_web_app_files_and_fallback(tmp_path, monkeypatch):
    from ctxpack.api import main

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("nope", encoding="utf-8")
    monkeypatch.setattr(main, "DIST", tmp_path)

    assert "id=root" in client.get("/").text
    page = client.get("/packs/pk_anything")                     # an app route: index.html
    assert page.status_code == 200 and "id=root" in page.text and page.headers["cache-control"] == "no-cache"
    asset = client.get("/assets/app.js")
    assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
    assert "nope" not in client.get("/../secret.txt").text      # never a file outside dist
    assert "nope" not in client.get("/%2e%2e/secret.txt").text
    assert client.get("/api/v1/does-not-exist").status_code == 404   # the API never falls back to the app
    assert client.get("/ping").text == "ok"


def test_placeholder_page_without_a_build(tmp_path, monkeypatch):
    from ctxpack.api import main

    monkeypatch.setattr(main, "DIST", tmp_path / "missing")
    assert "SIGNAL" in client.get("/").text
    assert client.get("/packs/x").status_code == 404
