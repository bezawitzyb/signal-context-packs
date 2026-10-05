"""Database tables and helpers on a temporary SQLite file."""

import json
import shutil
from datetime import timedelta
from pathlib import Path

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
    assert set(result) == {"featured_added", "documents_deleted", "runs_interrupted"}


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
