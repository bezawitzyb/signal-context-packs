"""Shared test setup: a throwaway SQLite database per test. Tests never spend money."""

import pytest

from ctxpack import db


@pytest.fixture
def temp_db(tmp_path):
    db.init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_tables()
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
