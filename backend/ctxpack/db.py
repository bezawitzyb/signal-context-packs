"""Database tables (guide B4) and helpers.

DATABASE_URL picks the database: Neon dev branch locally, Neon main online.
Tests call init_engine("sqlite:///<tmp file>"). JSON columns work on both.

Every pipeline stage saves here; the SSE endpoint reads the events table.
"""

import json
import threading
import logging
import secrets
import datetime as dt
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import DateTime, Engine, UniqueConstraint, delete, func, inspect, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import JSON, Field, Session, SQLModel, create_engine, select

from ctxpack.config import REPO_DIR, get_settings, load_yaml, sqlalchemy_url
from ctxpack.schemas.document import Document
from ctxpack.schemas.enums import EventType, Mode, Requester, RunStage, RunStatus
from ctxpack.schemas.pack import ContextPack

log = logging.getLogger(__name__)

FEATURED_DIR = REPO_DIR / "featured"


TZ = DateTime(timezone=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """Random, URL-safe id (pack ids are the pack's link, so they must be unguessable)."""
    return f"{prefix}_{secrets.token_urlsafe(12)}"


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


class Run(SQLModel, table=True):
    __tablename__ = "runs"

    id: str = Field(default_factory=lambda: new_id("run"), primary_key=True)
    brief_text: str
    mode: Mode = Field(default=Mode.quick)
    status: RunStatus = Field(default=RunStatus.created, index=True)
    stage: RunStage | None = None
    interpretation: dict | None = Field(default=None, sa_type=JSON)
    plan: dict | None = Field(default=None, sa_type=JSON)
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=TZ)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    cost_apify_usd: float = 0.0
    cost_llm_usd: float = 0.0
    cost_analysis_llm_usd: float | None = None  # the part of cost_llm_usd spent after collection (own budget)
    tool_calls: int = 0
    finish_reason: str | None = None
    fallback_used: bool = False
    top_up_used: bool = False
    error: str | None = None
    pack_id: str | None = None
    requester: Requester = Field(default=Requester.web)
    claimed_at: datetime | None = Field(default=None, sa_type=TZ)
    heartbeat_at: datetime | None = Field(default=None, sa_type=TZ)
    resume_count: int = 0
    peak_mem_mb: float | None = None
    queued_at: datetime | None = Field(default=None, sa_type=TZ)          # FIFO order of the queue
    stop_requested_at: datetime | None = Field(default=None, sa_type=TZ)  # Stop button; read by the worker
    # Agent loop record (Step 2.4): decision_log, sources_used, sources_dropped, gaps, summary
    collection: dict | None = Field(default=None, sa_type=JSON)
    # Spend per call type: {"anthropic": {"worker/record_relevance": {calls, usd, tokens...}}, "apify": {actor: ...}}
    cost_breakdown: dict | None = Field(default=None, sa_type=JSON)
    brand_voice: str | None = None    # used ONLY by the playbook call (never in analysis)
    clarifying_question: dict | None = Field(default=None, sa_type=JSON)  # waiting for the user's answer
    clarification: dict | None = Field(default=None, sa_type=JSON)  # {question, answer} (before V3; read only)
    clarifying_questions: list | None = Field(default=None, sa_type=JSON)  # V3: 0-3 questions waiting for answers
    intake: dict | None = Field(default=None, sa_type=JSON)  # V3: what the user told us (brief.intake)
    # Run-level metrics (Step 3.2, code only): platform lens, what performs, competitors, opportunities, coverage
    analysis: dict | None = Field(default=None, sa_type=JSON)
    # Draft pack sections (Step 3.3): generic points, written items, evidence; verified in Step 3.4
    draft: dict | None = Field(default=None, sa_type=JSON)


class EventRow(SQLModel, table=True):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    seq: int
    type: EventType
    payload: dict = Field(default_factory=dict, sa_type=JSON)
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class DocumentRow(Document, table=True):
    __tablename__ = "documents"


class ClusterRow(SQLModel, table=True):
    __tablename__ = "clusters"

    run_id: str = Field(primary_key=True)
    id: str = Field(primary_key=True)  # CL-07, unique within a run
    kind: str
    label: str
    member_ids: list = Field(default_factory=list, sa_type=JSON)
    verified_member_ids: list = Field(default_factory=list, sa_type=JSON)
    # point (what every member expresses) and kind-specific fields; "verified": membership check done
    details: dict | None = Field(default=None, sa_type=JSON)
    metrics: dict | None = Field(default=None, sa_type=JSON)  # counts, strength, emotion mix... (code only)


class PackRow(SQLModel, table=True):
    __tablename__ = "packs"

    id: str = Field(primary_key=True)
    run_id: str | None = Field(default=None, index=True)
    brief_text: str
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    schema_version: str
    pack: dict = Field(sa_type=JSON)
    featured: bool = Field(default=False, index=True)
    coverage_grade: str | None = None


class Spend(SQLModel, table=True):
    __tablename__ = "spend"

    date: dt.date = Field(primary_key=True)
    usd_apify: float = 0.0
    usd_llm: float = 0.0


class AskCount(SQLModel, table=True):
    """Questions asked of one pack per UTC day (change V10): the keyless limit and what they cost."""

    __tablename__ = "ask_counts"

    pack_id: str = Field(primary_key=True)
    date: dt.date = Field(primary_key=True)
    questions: int = 0
    usd: float = 0.0


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------

_engine: Engine | None = None


def init_engine(url: str | None = None) -> Engine:
    """Create the engine. Without a url, DATABASE_URL from .env is used."""
    global _engine
    if url is None:
        settings = get_settings()
        if settings.is_set("DATABASE_URL"):
            url = settings.database_url.get_secret_value()
        elif settings.offline:  # keyless local demo (README): a local SQLite file
            settings.data_path.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{settings.data_path / 'local.db'}"
        else:
            raise RuntimeError("DATABASE_URL is not set - run the doctor command")
    url = sqlalchemy_url(url)
    if _engine is not None:
        _engine.dispose()
    if url.startswith("sqlite"):
        _engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        # Small pool: one uvicorn worker on a 512 MB instance; Neon pooled URL.
        # data audit 11: room for the pipeline thread, its to_thread calls, the API and the heartbeat at once
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300,
                                pool_timeout=20)
    return _engine


def get_engine() -> Engine:
    return _engine if _engine is not None else init_engine()


def session() -> Session:
    return Session(get_engine(), expire_on_commit=False)


def create_tables() -> None:
    """Create missing tables, then add any new nullable columns and enum labels (additive only)."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    add_missing_columns(engine)
    add_missing_enum_values(engine)


# --------------------------------------------------------------------------
# Migrations (data audit 3): explicit, recorded, run before the database is used
# --------------------------------------------------------------------------

class SchemaMigration(SQLModel, table=True):
    """One applied migration step (name + when)."""

    __tablename__ = "schema_migrations"

    name: str = Field(primary_key=True)
    applied_at: datetime = Field(default_factory=lambda: utcnow(), sa_type=DateTime(timezone=True))


# Named steps run once, in order, and are recorded. Additive changes (new tables, nullable columns, enum labels)
# need no step: create_tables() adds them on every migrate. Add a step here for anything else (data fixes,
# renames, NOT NULL columns) - never edit or reorder an applied one.
def _statement_timeout(engine: Engine) -> None:
    """Data audit 11: no query may hang a connection. Set on the role so it holds through Neon's pooled endpoint
    (a per-session SET can land on another server connection). Postgres only; a refusal is logged, not fatal."""
    if engine.dialect.name != "postgresql":
        return
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"ALTER ROLE CURRENT_USER SET statement_timeout = "
                              f"'{int(load_yaml('modes')['worker']['statement_timeout_secs'])}s'"))
    except Exception as exc:  # never the message: it may contain the URL
        log.warning("statement timeout not set (%s)", type(exc).__name__)


MIGRATIONS: list[tuple[str, Callable[[Engine], Any]]] = [
    ("001_statement_timeout", _statement_timeout),
]
SCHEMA_READY = threading.Event()       # set once migrate() has finished in this process


def schema_problems() -> list[str]:
    """Read-only: what the database lacks compared with this code (tables, columns, enum labels, steps)."""
    engine = get_engine()
    insp = inspect(engine)
    out = [f"table {t.name}" for t in SQLModel.metadata.sorted_tables if not insp.has_table(t.name)]
    for t in SQLModel.metadata.sorted_tables:
        if insp.has_table(t.name):
            have = {c["name"] for c in insp.get_columns(t.name)}
            out += [f"column {t.name}.{c.name}" for c in t.columns if c.name not in have]
    if engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            existing: dict[str, list[str]] = {}
            for name, label in conn.execute(text("SELECT t.typname, e.enumlabel FROM pg_type t "
                                                 "JOIN pg_enum e ON e.enumtypid = t.oid")):
                existing.setdefault(name, []).append(label)
        out += [f"enum {n}.{v}" for n, vals in missing_enum_values(existing, wanted_enum_values()).items()
                for v in vals]
    done: set[str] = set()
    if insp.has_table("schema_migrations"):
        with session() as s:
            done = {m.name for m in s.exec(select(SchemaMigration))}
    out += [f"step {name}" for name, _ in MIGRATIONS if name not in done]
    return out


def migrate() -> list[str]:
    """Bring the database up to this code: additive changes, then each named step not applied yet. Returns what
    was applied. Idempotent; the app runs it before serving database routes, owners run cli migrate."""
    before = schema_problems()
    create_tables()
    engine = get_engine()
    applied = [p for p in before if not p.startswith("step ")]
    with session() as s:
        done = {m.name for m in s.exec(select(SchemaMigration))}
    for name, step in MIGRATIONS:
        if name in done:
            continue
        step(engine)
        with session() as s:
            s.add(SchemaMigration(name=name))
            s.commit()
        applied.append(f"step {name}")
        log.info("migration step %s applied", name)
    SCHEMA_READY.set()
    return applied


def add_missing_columns(engine: Engine) -> list[str]:
    """create_all never changes an existing table. This only ADDS nullable columns
    the models gained since the table was made; it never drops or alters data.
    """
    added = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                if not col.nullable:
                    raise RuntimeError(f"{table.name}.{col.name} is new and NOT NULL - needs a manual migration")
                col_type = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'))
                added.append(f"{table.name}.{col.name}")
    for name in added:
        log.info("added column %s", name)
    return added


def wanted_enum_values() -> dict[str, list[str]]:
    """Postgres enum type name -> the labels the models allow (native enums only)."""
    import sqlalchemy as sa

    out: dict[str, list[str]] = {}
    for table in SQLModel.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, sa.Enum) and col.type.native_enum and col.type.name:
                out.setdefault(col.type.name, list(col.type.enums))
    return out


def missing_enum_values(existing: dict[str, list[str]], wanted: dict[str, list[str]]) -> dict[str, list[str]]:
    """Labels a model allows that the database type lacks (types the database does not have are left alone)."""
    return {name: [v for v in labels if v not in existing[name]]
            for name, labels in wanted.items() if name in existing and any(v not in existing[name] for v in labels)}


def add_missing_enum_values(engine: Engine) -> list[str]:
    """create_all never changes an existing Postgres enum type. This only ADDS the labels the models gained since
    the type was made (e.g. platform "x", 2026-10-07); it never removes or renames one. No-op outside Postgres."""
    if engine.dialect.name != "postgresql":
        return []
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT t.typname, e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid"))
        existing: dict[str, list[str]] = {}
        for name, label in rows:
            existing.setdefault(name, []).append(label)
    added = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for name, labels in missing_enum_values(existing, wanted_enum_values()).items():
            for label in labels:
                conn.execute(text(f'ALTER TYPE "{name}" ADD VALUE IF NOT EXISTS \'{label}\''))
                added.append(f"{name}.{label}")
    for name in added:
        log.info("added enum value %s", name)
    return added


# --------------------------------------------------------------------------
# Runs and events
# --------------------------------------------------------------------------


def create_run(brief_text: str, mode: Mode = Mode.quick, requester: Requester = Requester.web) -> Run:
    run = Run(brief_text=brief_text, mode=mode, requester=requester)
    with session() as s:
        s.add(run)
        s.commit()
    return run


def get_run(run_id: str) -> Run | None:
    with session() as s:
        return s.get(Run, run_id)


def update_run(run_id: str, **fields: Any) -> Run:
    """Set any run columns; updated_at is always refreshed."""
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        for key, value in fields.items():
            if not hasattr(run, key):
                raise AttributeError(f"runs has no column {key}")
            setattr(run, key, value)
        run.updated_at = utcnow()
        s.add(run)
        s.commit()
        return run


def set_status(run_id: str, status: RunStatus, **fields: Any) -> Run:
    return update_run(run_id, status=status, **fields)


def set_cost_breakdown(run_id: str, part: str, values: dict) -> None:
    """Replace one part ("anthropic" or "apify") of the run's cost breakdown, keeping the other."""
    run = get_run(run_id)
    if run is not None:
        update_run(run_id, cost_breakdown={**(run.cost_breakdown or {}), part: values})


def set_stage(run_id: str, stage: RunStage) -> Run:
    """Move a run to a pipeline stage and emit a 'stage' event."""
    run = update_run(run_id, stage=stage)
    append_event(run_id, EventType.stage, {"stage": stage.value})
    return run


def heartbeat(run_id: str) -> None:
    update_run(run_id, heartbeat_at=utcnow())


def append_event(run_id: str, type: EventType, payload: dict[str, Any] | None = None) -> int:
    """Append an event with the next per-run number; returns that number."""
    payload = json.loads(json.dumps(payload or {}, default=str))  # JSON-safe copy
    for _ in range(5):
        with session() as s:
            last = s.exec(select(func.max(EventRow.seq)).where(EventRow.run_id == run_id)).one()
            seq = (last or 0) + 1
            s.add(EventRow(run_id=run_id, seq=seq, type=type, payload=payload))
            try:
                s.commit()
                return seq
            except IntegrityError:  # another writer took this number; try the next
                s.rollback()
    raise RuntimeError(f"could not append event for run {run_id}")


def list_runs(limit: int = 50) -> list[Run]:
    """The newest runs first (owner cost view)."""
    with session() as s:
        return list(s.exec(select(Run).order_by(Run.created_at.desc()).limit(limit)))


def queued_runs() -> list[Run]:
    """Waiting runs, first in line first (an interrupted run keeps its old place)."""
    with session() as s:
        return list(s.exec(select(Run).where(Run.status == RunStatus.queued)
                           .order_by(Run.queued_at, Run.created_at)))


def runs_with_status(status: RunStatus) -> list[Run]:
    with session() as s:
        return list(s.exec(select(Run).where(Run.status == status).order_by(Run.created_at)))


def claim_next_run() -> Run | None:
    """B13: take the oldest queued run and mark it running, so no other worker can take it.

    Postgres: SELECT ... FOR UPDATE SKIP LOCKED. SQLite (tests): a conditional
    UPDATE on the status flag - only one caller can move it from queued.
    """
    engine = get_engine()
    with session() as s:
        stmt = (select(Run).where(Run.status == RunStatus.queued)
                .order_by(Run.queued_at, Run.created_at).limit(1))
        if engine.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        run = s.exec(stmt).first()
        if run is None:
            return None
        now = utcnow()
        result = s.execute(update(Run).where(Run.id == run.id, Run.status == RunStatus.queued)
                           .values(status=RunStatus.running, claimed_at=now, heartbeat_at=now, updated_at=now))
        s.commit()
        if result.rowcount != 1:
            return None  # another worker was faster
    return get_run(run.id)


def get_events(run_id: str, after_seq: int = 0, limit: int = 500) -> list[EventRow]:
    with session() as s:
        stmt = (select(EventRow).where(EventRow.run_id == run_id, EventRow.seq > after_seq)
                .order_by(EventRow.seq).limit(limit))
        return list(s.exec(stmt))


# --------------------------------------------------------------------------
# Documents, clusters, packs
# --------------------------------------------------------------------------


def save_documents(docs: list[Document]) -> int:
    """Validate and insert or update documents (saved as they are cleaned)."""
    retention = timedelta(days=get_settings().retention_days)
    with session() as s:
        for doc in docs:
            data = Document.model_validate(doc.model_dump()).model_dump()  # re-validate (author hash etc.)
            data["expires_at"] = data.get("expires_at") or utcnow() + retention
            s.merge(DocumentRow(**data))
        s.commit()
    return len(docs)


def delete_documents(ids: list[str]) -> int:
    """Remove documents a better copy replaced (de-duplication keeps the higher-engagement one)."""
    if not ids:
        return 0
    with session() as s:
        result = s.exec(delete(DocumentRow).where(DocumentRow.id.in_(ids)))
        s.commit()
        return result.rowcount or 0


def count_documents(run_id: str, relevant_only: bool = False) -> int:
    with session() as s:
        stmt = select(func.count()).select_from(DocumentRow).where(DocumentRow.run_id == run_id)
        if relevant_only:
            stmt = stmt.where(DocumentRow.is_relevant == True)  # noqa: E712
        return s.exec(stmt).one()


def get_documents(run_id: str, relevant_only: bool = False) -> list[DocumentRow]:
    with session() as s:
        stmt = select(DocumentRow).where(DocumentRow.run_id == run_id)
        if relevant_only:
            stmt = stmt.where(DocumentRow.is_relevant == True)  # noqa: E712
        return list(s.exec(stmt))


def save_extractions(results: dict[str, tuple[dict, str | None]]) -> int:
    """Store extractor output per document id: {id: (extraction, text_en)}. Saved batch by batch."""
    with session() as s:
        for doc_id, (extraction, text_en) in results.items():
            row = s.get(DocumentRow, doc_id)
            if row is None:
                continue
            row.extraction = extraction
            if text_en is not None:
                row.text_en = text_en
            s.add(row)
        s.commit()
    return len(results)


def save_clusters(run_id: str, clusters: list[ClusterRow]) -> None:
    with session() as s:
        for cluster in clusters:
            cluster.run_id = run_id
            s.merge(cluster)
        s.commit()


def get_clusters(run_id: str) -> list[ClusterRow]:
    with session() as s:
        return sorted(s.exec(select(ClusterRow).where(ClusterRow.run_id == run_id)),
                      key=lambda c: int(c.id.split("-")[1]))


def delete_clusters(run_id: str, ids: list[str] | None = None) -> int:
    """Clustering again from scratch (--redo), or only the given cluster ids."""
    with session() as s:
        stmt = delete(ClusterRow).where(ClusterRow.run_id == run_id)
        if ids is not None:
            stmt = stmt.where(ClusterRow.id.in_(ids))
        result = s.exec(stmt)
        s.commit()
        return result.rowcount or 0


def save_pack(pack: ContextPack, run_id: str | None = None, featured: bool = False) -> str:
    """Validate and save a pack; returns its id. Links the run to the pack."""
    pack = ContextPack.model_validate(pack.model_dump())
    row = PackRow(
        id=pack.pack_id,
        run_id=run_id,
        brief_text=pack.brief.text,
        created_at=pack.generated_at,
        schema_version=pack.schema_version,
        pack=pack.model_dump(mode="json"),
        featured=featured,
        coverage_grade=pack.snapshot.coverage_grade.value,
    )
    with session() as s:
        s.merge(row)
        s.commit()
    if run_id and get_run(run_id) is not None:  # a pack outlives its run (featured packs, retention)
        update_run(run_id, pack_id=pack.pack_id)
    return pack.pack_id


def get_pack(pack_id: str) -> dict | None:
    """The pack as the current schema version (older stored packs are migrated on read)."""
    from ctxpack.schemas.migrate import current

    with session() as s:
        row = s.get(PackRow, pack_id)
        return current(row.pack) if row else None


def set_featured(pack_id: str, featured: bool = True) -> None:
    with session() as s:
        row = s.get(PackRow, pack_id)
        if row is not None:
            row.featured = featured
            s.add(row)
            s.commit()


def list_packs_for_run(run_id: str) -> list[PackRow]:
    with session() as s:
        return list(s.exec(select(PackRow).where(PackRow.run_id == run_id).order_by(PackRow.created_at)))


def get_pack_for_run(run_id: str) -> dict | None:
    """The latest pack built from a run (featured packs keep their run id even without the run)."""
    with session() as s:
        row = s.exec(select(PackRow).where(PackRow.run_id == run_id).order_by(PackRow.created_at.desc())).first()
        if row is None:
            return None
    from ctxpack.schemas.migrate import current

    return current(row.pack)


def latest_pack_for_brief(brief_text: str) -> PackRow | None:
    """The newest pack whose brief text matches (case and spaces ignored); used by the eval with --reuse."""
    key = " ".join(brief_text.split()).casefold()
    with session() as s:
        rows = s.exec(select(PackRow.id, PackRow.brief_text).order_by(PackRow.created_at.desc())).all()
        pack_id = next((i for i, text in rows if " ".join(text.split()).casefold() == key), None)
        return s.get(PackRow, pack_id) if pack_id else None


def list_featured_packs() -> list[PackRow]:
    with session() as s:
        return list(s.exec(select(PackRow).where(PackRow.featured == True).order_by(PackRow.created_at)))  # noqa: E712


# --------------------------------------------------------------------------
# Spend (daily cap)
# --------------------------------------------------------------------------


def _upsert_add(table: Any, keys: dict[str, Any], adds: dict[str, float]) -> Any:
    """INSERT the row, or ADD to its counters if it exists - one atomic statement (audit 2: concurrent writers
    used to read, add in Python and write back, losing updates). Postgres and SQLite both support it."""
    dialect = get_engine().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(table).values(**keys, **adds)
    return stmt.on_conflict_do_update(index_elements=list(keys),
                                      set_={k: table.c[k] + stmt.excluded[k] for k in adds})


def add_spend(apify_usd: float = 0.0, llm_usd: float = 0.0, run_id: str | None = None,
              analysis: bool = False) -> None:
    """Add cost to today's total (and to the run, if given; analysis spend also to its own budget).
    Database-side increments: parallel calls, other threads and other processes never lose an update."""
    today = utcnow().date()
    with session() as s:
        s.execute(_upsert_add(Spend.__table__, {"date": today}, {"usd_apify": apify_usd, "usd_llm": llm_usd}))
        if run_id:
            values: dict[str, Any] = {"cost_apify_usd": Run.cost_apify_usd + apify_usd,
                                      "cost_llm_usd": Run.cost_llm_usd + llm_usd, "updated_at": utcnow()}
            if analysis:
                values["cost_analysis_llm_usd"] = func.coalesce(Run.cost_analysis_llm_usd, 0.0) + llm_usd
            s.execute(update(Run).where(Run.id == run_id).values(**values))
        s.commit()


def asks_today(pack_id: str) -> int:
    with session() as s:
        row = s.get(AskCount, (pack_id, utcnow().date()))
        return row.questions if row else 0


def add_ask(pack_id: str, usd: float) -> None:
    """One more question for this pack today (its cost is in the spend table already)."""
    with session() as s:
        s.execute(_upsert_add(AskCount.__table__, {"pack_id": pack_id, "date": utcnow().date()},
                              {"questions": 1, "usd": usd}))
        s.commit()


def spend_today() -> float:
    with session() as s:
        row = s.get(Spend, utcnow().date())
        return (row.usd_apify + row.usd_llm) if row else 0.0


# --------------------------------------------------------------------------
# Startup tasks (B4 notes)
# --------------------------------------------------------------------------


def delete_expired_documents(now: datetime | None = None) -> int:
    """Retention (DH6): delete documents past expires_at, then what still held their text (data audit 6): the
    drafts and clusters of finished runs with no documents left, and cache files past their hours. The finished
    pack stays (short excerpts with links). Runs at start and hourly in the worker."""
    now = now or utcnow()
    with session() as s:
        result = s.execute(delete(DocumentRow).where(DocumentRow.expires_at < now))
        s.commit()
    deleted = result.rowcount or 0
    cleared = expire_run_working_data(now)
    removed = delete_expired_cache_files(now)
    if cleared or removed:
        log.info("retention: %d run drafts cleared, %d cache files removed", cleared, removed)
    return deleted


def expire_run_working_data(now: datetime | None = None) -> int:
    """Finished runs older than the retention period with no documents left: draft (evidence excerpts,
    translations, sections) and clusters are cleared. Returns how many runs were cleared."""
    cutoff = (now or utcnow()) - timedelta(days=get_settings().retention_days)
    finished = [RunStatus.complete, RunStatus.partial, RunStatus.failed, RunStatus.stopped]
    with session() as s:
        runs = s.exec(select(Run).where(Run.status.in_(finished), Run.created_at < cutoff,
                                        Run.draft.is_not(None))).all()
        cleared = 0
        for run in runs:
            if s.exec(select(func.count()).select_from(DocumentRow).where(DocumentRow.run_id == run.id)).one():
                continue
            run.draft = None
            run.updated_at = utcnow()
            s.add(run)
            s.execute(delete(ClusterRow).where(ClusterRow.run_id == run.id))
            cleared += 1
        s.commit()
    return cleared


def delete_expired_cache_files(now: datetime | None = None) -> int:
    """The 24 h collection cache (hashed, redacted posts on disk): files older than cache_hours are deleted."""
    folder = get_settings().data_path / "cache"
    if not folder.is_dir():
        return 0
    limit = (now or utcnow()).timestamp() - load_yaml("modes")["collection"]["cache_hours"] * 3600
    removed = 0
    for path in folder.glob("*.json"):
        try:
            if path.stat().st_mtime < limit:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def load_featured(folder: Path = FEATURED_DIR) -> int:
    """Featured packs from featured/*.json: added if missing, and updated if the file changed (the file in the
    repo is the published version, e.g. after a privacy or cleaning fix); featured packs without a file are
    un-featured. Returns how many were added, updated or un-featured."""
    if not folder.is_dir():
        return 0
    changed, on_disk = 0, set()
    for path in sorted(folder.glob("*.json")):
        if path.stem.startswith("evals"):  # evals.json, evals_human.json: eval results, not packs
            continue
        pack = ContextPack.model_validate_json(path.read_text(encoding="utf-8"))
        on_disk.add(pack.pack_id)
        data = pack.model_dump(mode="json")
        with session() as s:
            row = s.get(PackRow, pack.pack_id)
            if row is None:
                s.close()
                save_pack(pack, featured=True)
                changed += 1
            elif row.pack != data or not row.featured:
                row.pack, row.featured = data, True  # keep its run link
                s.add(row)
                s.commit()
                changed += 1
    # The files are the list: a pack featured in the database without a file (replaced by a rebuilt
    # version) is no longer featured. The pack itself stays readable by its id.
    with session() as s:
        for row in s.exec(select(PackRow).where(PackRow.featured == True)).all():  # noqa: E712
            if row.id not in on_disk:
                row.featured = False
                s.add(row)
                changed += 1
        s.commit()
    return changed


def mark_stale_runs_interrupted(now: datetime | None = None) -> list[str]:
    """B13: a running run whose heartbeat is older than stale_after_secs is 'interrupted'.

    Resuming it is the worker's job (worker.handle_interrupted).
    """
    cutoff = (now or utcnow()) - timedelta(seconds=load_yaml("modes")["worker"]["stale_after_secs"])
    with session() as s:
        runs = s.exec(select(Run).where(Run.status == RunStatus.running)).all()
        stale = [r for r in runs if r.heartbeat_at is None or _aware(r.heartbeat_at) < cutoff]
        for run in stale:
            run.status = RunStatus.interrupted
            run.updated_at = utcnow()
            s.add(run)
        s.commit()
        return [r.id for r in stale]


def _aware(value: datetime) -> datetime:
    """SQLite drops timezones; treat naive times as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def startup() -> dict[str, Any]:
    """Run at app start: tables, featured packs, retention, interrupted runs.

    The worker loop (started by the app) then resumes or closes interrupted runs.
    """
    applied = migrate()
    return {
        "migrated": applied,
        "featured_added": load_featured(),
        "documents_deleted": delete_expired_documents(),
        "runs_interrupted": mark_stale_runs_interrupted(),
    }
