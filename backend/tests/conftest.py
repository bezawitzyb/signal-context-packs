"""Shared test setup: a throwaway database per test (SQLite; Postgres when TEST_DATABASE_URL is set, as in CI's
postgres job - data audit 7). Tests never spend money."""

import os

import pytest
from sqlalchemy import text

from ctxpack import db


@pytest.fixture
def temp_db(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    db.init_engine(url or f"sqlite:///{tmp_path / 'test.db'}")
    if url:  # a clean schema for every test: tables AND enum types go
        with db.get_engine().begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    db.migrate()
    yield db
    db.get_engine().dispose()
    db._engine = None


@pytest.fixture(autouse=True)
def no_recorded_transcripts(monkeypatch, tmp_path_factory, request):
    """Fake mode uses the plan-driven stand-in agent unless a test asks for the recorded
    transcripts (tests/fixtures/transcripts) with @pytest.mark.transcripts."""
    if request.node.get_closest_marker("transcripts"):
        return
    from ctxpack.collect import loop
    monkeypatch.setattr(loop, "TRANSCRIPT_DIR", tmp_path_factory.mktemp("no_transcripts"))
