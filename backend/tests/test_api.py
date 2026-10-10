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


def test_health_says_when_the_daily_cap_stops_runs(temp_db, monkeypatch):
    from ctxpack.config import get_settings

    assert client.get("/health").json()["accepting_runs"] is True
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "0.01")           # the cap test (guide Step 5.5)
    get_settings.cache_clear()
    temp_db.add_spend(llm_usd=0.02)
    body = client.get("/health").json()
    get_settings.cache_clear()
    assert body["accepting_runs"] is False and "usd" not in str(body).lower()


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


def test_a_pack_link_previews_with_its_own_title_and_escapes_it(tmp_path, monkeypatch):
    from ctxpack.api import main, service

    (tmp_path / "index.html").write_text('<html><head><meta name="description" content="x" /><title>SIGNAL</title>'
                                         '</head><body><div id=root></div></body></html>', encoding="utf-8")
    monkeypatch.setattr(main, "DIST", tmp_path)
    pack = {"brief": {"text": 'Snacks <script>alert(1)</script> in NL', "interpreted": {"topic": "snacks",
            "audience": "Dutch snackers"}}, "coverage": {"counts": {"relevant": 71}}}
    monkeypatch.setattr(service, "pack", lambda pack_id: pack if pack_id == "pk_known123" else 1 / 0)
    page = client.get("/packs/pk_known123")
    assert "<title>Snacks &lt;script&gt;" in page.text and 'property="og:title"' in page.text
    assert "<script>alert" not in page.text and "71 public posts" in page.text and "id=root" in page.text
    plain = client.get("/packs/pk_unknown99")                   # unknown pack: the plain page, never an error
    assert plain.status_code == 200 and "og:title" not in plain.text


def test_placeholder_page_without_a_build(tmp_path, monkeypatch):
    from ctxpack.api import main

    monkeypatch.setattr(main, "DIST", tmp_path / "missing")
    assert "SIGNAL" in client.get("/").text
    assert client.get("/packs/x").status_code == 404


def test_unexpected_errors_are_friendly(monkeypatch):
    from ctxpack.api import routes

    def boom():
        raise RuntimeError("internal detail that must not leak")

    monkeypatch.setattr(routes.service, "featured", boom)
    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/packs")
    assert response.status_code == 500
    assert "try again" in response.json()["detail"] and "internal detail" not in response.text
    assert "Traceback" not in response.text
