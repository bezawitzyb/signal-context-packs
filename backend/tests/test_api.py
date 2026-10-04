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


def test_home_placeholder():
    response = client.get("/")
    assert response.status_code == 200
    assert "SIGNAL - Context Packs" in response.text
    assert "Coming soon." in response.text
