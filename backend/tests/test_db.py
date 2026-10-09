"""Database tables and helpers on a temporary SQLite file."""

import json
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from ctxpack.schemas.document import Document
from ctxpack.schemas.enums import EventType, Mode, Requester, RunStage, RunStatus
from ctxpack.schemas.pack import ContextPack

EXAMPLE = Path(__file__).parent / "fixtures" / "example_pack.json"


def _pack() -> ContextPack:
    return ContextPack.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))


def test_create_run_and_stage(temp_db):
    run = temp_db.create_run("Gen Z and meal prep", mode=Mode.standard, requester=Requester.cli)
    assert run.id.startswith("run_") and run.status is RunStatus.created
    temp_db.set_status(run.id, RunStatus.running)
    temp_db.set_stage(run.id, RunStage.collecting)
    stored = temp_db.get_run(run.id)
    assert stored.status is RunStatus.running and stored.stage is RunStage.collecting
    events = temp_db.get_events(run.id)
    assert [(e.seq, e.type, e.payload) for e in events] == [(1, EventType.stage, {"stage": "collecting"})]


def test_events_are_numbered_and_resumable(temp_db):
    run = temp_db.create_run("x brief")
    for i in range(3):
        assert temp_db.append_event(run.id, EventType.counters, {"kept": i}) == i + 1
    assert [e.seq for e in temp_db.get_events(run.id, after_seq=1)] == [2, 3]


def test_save_and_read_documents(temp_db):
    run = temp_db.create_run("x brief")
    doc = Document(id="d1", run_id=run.id, platform="reddit", source_unit="reddit:r/x",
                   url="https://example.com/1", text="hello there friends", author_hash="a" * 64,
                   engagement_raw={"score": 3}, research_question_ids=["RQ-01"], is_relevant=True)
    assert temp_db.save_documents([doc]) == 1
    rows = temp_db.get_documents(run.id, relevant_only=True)
    assert rows[0].engagement_raw == {"score": 3} and rows[0].expires_at is not None


def test_expired_documents_are_deleted(temp_db):
    run = temp_db.create_run("x brief")
    old = Document(id="old", run_id=run.id, platform="reddit", source_unit="reddit:r/x",
                   url="https://example.com/2", text="old post", expires_at=temp_db.utcnow() - timedelta(days=1))
    new = Document(id="new", run_id=run.id, platform="reddit", source_unit="reddit:r/x",
                   url="https://example.com/3", text="new post")
    temp_db.save_documents([old, new])
    assert temp_db.delete_expired_documents() == 1
    assert [d.id for d in temp_db.get_documents(run.id)] == ["new"]


def test_save_pack_links_run(temp_db):
    run = temp_db.create_run("x brief")
    pack_id = temp_db.save_pack(_pack(), run_id=run.id)
    assert temp_db.get_run(run.id).pack_id == pack_id
    assert ContextPack.model_validate(temp_db.get_pack(pack_id)) == _pack()
    assert temp_db.get_pack("missing") is None


def test_add_spend_updates_day_and_run(temp_db):
    run = temp_db.create_run("x brief")
    temp_db.add_spend(apify_usd=0.5, llm_usd=0.25, run_id=run.id)
    temp_db.add_spend(llm_usd=0.25)
    assert temp_db.spend_today() == 1.0
    stored = temp_db.get_run(run.id)
    assert (stored.cost_apify_usd, stored.cost_llm_usd) == (0.5, 0.25)


def test_load_featured_inserts_once(temp_db, tmp_path):
    folder = tmp_path / "featured"
    folder.mkdir()
    shutil.copy(EXAMPLE, folder / "example.json")
    assert temp_db.load_featured(folder) == 1
    assert temp_db.load_featured(folder) == 0
    assert [p.id for p in temp_db.list_featured_packs()] == [json.loads(EXAMPLE.read_text())["pack_id"]]


def test_stale_running_run_is_interrupted(temp_db):
    stale = temp_db.create_run("stale")
    fresh = temp_db.create_run("fresh")
    now = temp_db.utcnow()
    temp_db.set_status(stale.id, RunStatus.running, heartbeat_at=now - timedelta(minutes=5))
    temp_db.set_status(fresh.id, RunStatus.running, heartbeat_at=now)
    assert temp_db.mark_stale_runs_interrupted() == [stale.id]
    assert temp_db.get_run(fresh.id).status is RunStatus.running


def test_startup_runs_cleanly(temp_db):
    result = temp_db.startup()
    assert set(result) == {"migrated", "featured_added", "documents_deleted", "runs_interrupted"}


def test_new_columns_are_added_to_an_existing_table(tmp_path):
    """An old documents table (made before Step 1.5) gains the new nullable columns."""
    from sqlalchemy import MetaData, Table, create_engine, inspect, text

    from ctxpack import db

    new = {"market_match", "is_promotional", "relevance_reason"}
    url = f"sqlite:///{tmp_path / 'old.db'}"
    old = create_engine(url)
    Table("documents", MetaData(),
          *[c._copy() for c in db.DocumentRow.__table__.columns if c.name not in new]).create(old)
    with old.begin() as conn:
        conn.execute(text("INSERT INTO documents (id, run_id, platform, source_unit, url, text, date_precision,"
                          " engagement_raw, research_question_ids, redacted, short_form) VALUES"
                          " ('DOC-1', 'RUN-1', 'reddit', 'reddit:r/x', 'u', 'kept', 'unknown', '{}', '[]', 0, 0)"))
    old.dispose()

    db.init_engine(url)
    try:
        db.create_tables()
        cols = {c["name"] for c in inspect(db.get_engine()).get_columns("documents")}
        assert new <= cols
        with db.get_engine().connect() as conn:  # existing data untouched
            assert conn.execute(text("SELECT text FROM documents WHERE id='DOC-1'")).scalar_one() == "kept"
        assert db.add_missing_columns(db.get_engine()) == []  # second run: nothing to do
    finally:
        db.get_engine().dispose()
        db._engine = None


def test_featured_packs_are_added_and_updated_from_their_files(temp_db, tmp_path):
    import json
    from pathlib import Path

    fixture = json.loads((Path(__file__).parent / "fixtures" / "example_pack.json").read_text(encoding="utf-8"))
    (tmp_path / f"{fixture['pack_id']}.json").write_text(json.dumps(fixture), encoding="utf-8")
    assert temp_db.load_featured(tmp_path) == 1
    assert temp_db.load_featured(tmp_path) == 0                       # unchanged file: nothing to do
    fixture["digest"] = "A cleaned digest."
    (tmp_path / f"{fixture['pack_id']}.json").write_text(json.dumps(fixture), encoding="utf-8")
    assert temp_db.load_featured(tmp_path) == 1                       # changed file: the database follows it
    assert temp_db.get_pack(fixture["pack_id"])["digest"] == "A cleaned digest."


def test_featured_pack_without_a_file_is_unfeatured(temp_db, tmp_path):
    import json
    from pathlib import Path

    fixture = json.loads((Path(__file__).parent / "fixtures" / "example_pack.json").read_text(encoding="utf-8"))
    path = tmp_path / f"{fixture['pack_id']}.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    assert temp_db.load_featured(tmp_path) == 1
    path.unlink()                                                     # replaced by a rebuilt pack
    assert temp_db.load_featured(tmp_path) == 1 and temp_db.list_featured_packs() == []
    assert temp_db.get_pack(fixture["pack_id"]) is not None           # still readable by id


def test_new_enum_labels_are_found_and_only_added():
    """Seen live (2026-10-09): the Postgres platform type lacked "x", so every X search failed to save."""
    from ctxpack.db import missing_enum_values, wanted_enum_values

    assert "x" in wanted_enum_values()["platform"]
    existing = {"platform": ["reddit", "tiktok"], "other_type": ["a"]}
    wanted = {"platform": ["reddit", "tiktok", "x"], "not_in_db": ["b"]}
    assert missing_enum_values(existing, wanted) == {"platform": ["x"]}   # never removes; unknown types left alone
    assert missing_enum_values({"platform": ["reddit", "x"]}, {"platform": ["reddit", "x"]}) == {}


def test_concurrent_spend_writes_are_never_lost(temp_db):
    """Data audit 1: add_spend read, added in Python and wrote back; parallel writers lost updates, so the daily
    and run caps under-counted. Database-side increments keep every cent."""
    from concurrent.futures import ThreadPoolExecutor

    run = temp_db.create_run("snacks")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: temp_db.add_spend(apify_usd=0.01, llm_usd=0.02, run_id=run.id, analysis=True),
                      range(200)))
        list(pool.map(lambda _: temp_db.add_ask("pk_x1234567", 0.001), range(50)))
    assert temp_db.spend_today() == pytest.approx(200 * 0.03)
    r = temp_db.get_run(run.id)
    assert (r.cost_apify_usd, r.cost_llm_usd, r.cost_analysis_llm_usd) == pytest.approx((2.0, 4.0, 4.0))
    assert temp_db.asks_today("pk_x1234567") == 50


def test_schema_problems_are_found_read_only_and_migrate_fixes_them_once(tmp_path, monkeypatch):
    """Data audit 3: schema changes were implicit at app start; the live database lacked a new column and every
    CLI command with newer code failed. Now: a read-only check, an explicit recorded migrate."""
    from sqlalchemy import text

    from ctxpack import db

    db.init_engine(f"sqlite:///{tmp_path / 'old.db'}")
    try:
        db.create_tables()
        with db.get_engine().begin() as conn:
            conn.execute(text("ALTER TABLE documents DROP COLUMN found_by"))
        assert "column documents.found_by" in db.schema_problems()
        calls = []
        monkeypatch.setattr(db, "MIGRATIONS", [("001_example", lambda engine: calls.append(1))])
        assert "step 001_example" in db.schema_problems()
        applied = db.migrate()
        assert "column documents.found_by" in applied and "step 001_example" in applied
        assert db.schema_problems() == [] and db.SCHEMA_READY.is_set()
        assert db.migrate() == [] and calls == [1]                  # recorded: never run twice
    finally:
        db.get_engine().dispose()
        db._engine = None


def test_retention_also_clears_old_drafts_clusters_and_cache_files(temp_db, tmp_path, monkeypatch):
    """Data audit 6: posts expired after 30 days, but run drafts (excerpts, translations) and cache files stayed."""
    import os
    import time

    from ctxpack.config import get_settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        old, recent = temp_db.create_run("snacks"), temp_db.create_run("chips")
        long_ago = temp_db.utcnow() - timedelta(days=60)
        for run in (old, recent):
            temp_db.update_run(run.id, status=RunStatus.complete, draft={"verified": {"evidence": [{"text": "x"}]}})
        temp_db.update_run(old.id, created_at=long_ago)
        temp_db.save_clusters(old.id, [temp_db.ClusterRow(run_id=old.id, id="CL-01", kind="theme", label="l")])
        cache = tmp_path / "cache"
        cache.mkdir()
        (stale := cache / "old.json").write_text("{}")
        (fresh := cache / "new.json").write_text("{}")
        os.utime(stale, (time.time() - 48 * 3600,) * 2)
        temp_db.delete_expired_documents()
        assert temp_db.get_run(old.id).draft is None and temp_db.get_clusters(old.id) == []
        assert temp_db.get_run(recent.id).draft is not None                  # within retention: kept
        assert not stale.exists() and fresh.exists()
    finally:
        get_settings.cache_clear()
