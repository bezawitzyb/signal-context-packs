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
