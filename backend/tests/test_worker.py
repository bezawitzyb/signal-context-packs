"""Orchestrator + job worker (Step 2.3, guide B5 and B13).

USE_FIXTURES + LLM_FAKE: no network, no money. The plan comes from the
recorded interpret answer (tests/fixtures/llm/record_plan.json).
"""

import asyncio
import os
import subprocess
import sys
import textwrap
from datetime import timedelta
from pathlib import Path

import pytest

from ctxpack import db, orchestrator, worker
from ctxpack.collect import loop
from ctxpack.agent.interpret import interpret
from ctxpack.config import get_settings
from ctxpack.guards import BudgetExceeded
from ctxpack.schemas.enums import EventType, FinishReason, RunStage, RunStatus

BACKEND = Path(__file__).resolve().parent.parent
OFFLINE_ENV = {"USE_FIXTURES": "true", "LLM_FAKE": "true", "AUTHOR_HASH_SALT": "test-salt-not-a-secret"}


@pytest.fixture
def offline(monkeypatch, tmp_path, temp_db):
    for key, value in OFFLINE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


async def approved_run(brief: str = "Gen Z and meal prep") -> str:
    """A run with the recorded plan, approved and waiting in the queue."""
    res = await interpret(brief, allow_question=False)  # an approved run never waits for a question
    interp = res.result.interpretation.model_copy(update={"time_window_days": 365})  # fixtures are older
    run = db.create_run(brief)
    db.update_run(run.id, interpretation=interp.model_dump(mode="json"),
                  plan=res.result.plan.model_dump(mode="json"))
    orchestrator.enqueue(run.id)
    return run.id


def events(run_id: str, type: EventType | None = None) -> list[db.EventRow]:
    return [e for e in db.get_events(run_id) if type is None or e.type == type]


def stages(run_id: str) -> list[str]:
    return [e.payload["stage"] for e in events(run_id, EventType.stage)]


ALL_STAGES = ["collecting", "extracting", "clustering", "writing", "verifying", "packaging"]


# --- a normal run -----------------------------------------------------------

async def test_queued_run_goes_through_every_stage(offline):
    run_id = await approved_run()
    assert await worker.run_next() == run_id
    run = db.get_run(run_id)
    assert run.status == RunStatus.complete
    assert run.finish_reason == FinishReason.finish
    assert stages(run_id) == ALL_STAGES
    # plan-driven stand-in agent: 3 starting units, then coverage_report and finish
    calls = [e.payload["tool"] for e in events(run_id, EventType.agent_call)]
    assert calls[-2:] == ["coverage_report", "finish"] and len(calls) == len(events(run_id, EventType.agent_result))
    assert len(run.collection["decision_log"]) == len(calls)
    judged = {s["source_unit"] for s in run.collection["sources_used"] + run.collection["sources_dropped"]}
    assert judged == {"reddit:r/MealPrepSunday", "tiktok:#mealprep", "youtube:search:student meal prep"}
    assert events(run_id, EventType.counters)[-1].payload["kept"] == db.count_documents(run_id) > 0
    assert events(run_id, EventType.counters)[-1].payload["undated"] == sum(
        d.posted_at is None for d in db.get_documents(run_id))                   # the live counter is right
    assert run.tool_calls == 3
    assert run.peak_mem_mb and run.peak_mem_mb > 0
    seqs = [e.seq for e in events(run_id)]
    assert seqs == list(range(1, len(seqs) + 1))


async def test_empty_queue_does_nothing(offline):
    assert await worker.run_next() is None


# --- stop, budget, crash ----------------------------------------------------

async def test_stop_during_collection_packages_a_partial_pack(offline, monkeypatch):
    run_id = await approved_run()
    real_run_tool = loop.run_tool

    async def run_tool_then_stop(*args, **kwargs):
        result = await real_run_tool(*args, **kwargs)
        orchestrator.request_stop(run_id)  # Stop pressed after the first call
        return result

    monkeypatch.setattr(loop, "run_tool", run_tool_then_stop)
    monkeypatch.setattr(loop, "_modes", lambda: {**db.load_yaml("modes"), "parallel_tool_calls_max": 1})
    await worker.run_next()
    run = db.get_run(run_id)
    assert run.finish_reason == FinishReason.stopped
    assert len(events(run_id, EventType.agent_call)) == 1
    assert db.count_documents(run_id) > 0
    if db.count_documents(run_id, relevant_only=True) >= orchestrator.thin_floor():
        assert run.status == RunStatus.partial and run.pack_id                      # V1: analysis still ran
        assert stages(run_id) == ALL_STAGES
        assert db.get_pack(run.pack_id)["blind_spots"][0]["text"].startswith("Partial pack: collection was stopped")
    else:
        assert run.status == RunStatus.failed and run.collection["thin"]["reasons"]  # V1: thin state


async def test_stop_during_analysis_packages_a_partial_pack(offline):
    run_id = await approved_run()
    ran = []

    async def press_stop(rid):
        ran.append("extracting")
        orchestrator.request_stop(rid)

    async def never(rid):
        ran.append("clustering")

    await worker.run_next(stages=[(RunStage.extracting, press_stop), (RunStage.clustering, never)])
    assert db.get_run(run_id).status == RunStatus.partial
    assert ran == ["extracting"]
    assert stages(run_id) == ["collecting", "extracting", "packaging"]


async def test_stop_before_start_never_runs(offline):
    run_id = await approved_run()
    assert orchestrator.request_stop(run_id) == RunStatus.stopped
    assert await worker.run_next() is None
    assert stages(run_id) == []


async def test_budget_hit_before_collecting_gives_the_thin_state(offline):
    run_id = await approved_run()

    async def over_budget(rid):
        raise BudgetExceeded("run LLM budget of $1.40 spent")

    await worker.run_next(collect=over_budget)
    run = db.get_run(run_id)
    assert run.finish_reason == FinishReason.budget_limit
    assert run.status == RunStatus.failed                       # nothing collected: V1 thin state, never a hang
    thin = run.collection["thin"]
    assert thin["relevant"] == 0 and thin["reasons"] and "broaden_audience" in thin["replans"]
    assert run.error.startswith("Too few relevant posts")


async def test_crash_in_analysis_gives_an_evidence_only_pack(offline):
    run_id = await approved_run()

    async def crash(rid):
        raise RuntimeError("boom")

    await worker.run_next(stages=[(RunStage.clustering, crash)])
    run = db.get_run(run_id)
    assert run.status == RunStatus.partial and run.pack_id      # V1: an evidence-only pack, never lost
    pack = db.get_pack(run.pack_id)
    assert pack["blind_spots"][0]["text"] == ("Partial pack: the analysis could not finish (clustering failed: "
                                             "RuntimeError); it shows the collected posts.")
    assert pack["evidence"] and pack["coverage"]["thin_evidence"]
    retry = events(run_id, EventType.error)[0].payload
    assert retry["recoverable"] is True and "trying it again" in retry["message"]       # tried twice
    assert events(run_id, EventType.fallback)[-1].payload["kind"] == "evidence_only"
    assert "boom" not in str(pack)                                                      # no raw error text


# --- the queue --------------------------------------------------------------

async def test_two_queued_runs_are_processed_one_after_the_other(offline):
    first = await approved_run("Gen Z and meal prep")
    second = await approved_run("Gen Z and meal prep, again")
    assert events(second, EventType.queue)[-1].payload["position"] == 2
    log: list[tuple[str, str]] = []

    async def slow_collect(rid):
        log.append((rid, "start"))
        other = second if rid == first else first
        assert db.get_run(other).status in (RunStatus.queued, RunStatus.complete, RunStatus.failed)  # never two at once
        await asyncio.sleep(0.05)
        db.update_run(rid, finish_reason=FinishReason.finish)
        log.append((rid, "end"))

    stop = asyncio.Event()
    loop = asyncio.create_task(worker.worker_loop(stop, collect=slow_collect))
    for _ in range(200):
        if all(db.get_run(r).status in (RunStatus.complete, RunStatus.failed) for r in (first, second)):
            break
        await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(loop, 5)
    assert log == [(first, "start"), (first, "end"), (second, "start"), (second, "end")]
    # the second run was told it moved up the queue
    assert [e.payload["position"] for e in events(second, EventType.queue)][-1] == 1


async def test_queue_is_first_in_first_out_by_approval_time(offline):
    created_first = await approved_run()
    created_second = await approved_run()
    orchestrator.enqueue(created_first)  # approved again later -> now behind
    assert db.claim_next_run().id == created_second


async def test_a_run_is_claimed_only_once(offline):
    run_id = await approved_run()
    assert db.claim_next_run().id == run_id
    assert db.claim_next_run() is None
    run = db.get_run(run_id)
    assert run.status == RunStatus.running and run.claimed_at and run.heartbeat_at


# --- killed process, restart, resume once ----------------------------------

KILL_AFTER_COLLECTION = textwrap.dedent("""
    import asyncio, os, pathlib, signal, sys, tempfile
    from ctxpack import db, worker
    from ctxpack.collect import loop
    from ctxpack.schemas.enums import RunStage

    loop.TRANSCRIPT_DIR = pathlib.Path(tempfile.mkdtemp())  # the stand-in agent, as in the other tests

    async def killed(run_id):
        os.kill(os.getpid(), signal.SIGKILL)  # no clean-up, like a crash or a redeploy

    db.init_engine(sys.argv[1])
    asyncio.run(worker.run_next(stages=[(RunStage.extracting, killed)]))
""")


def run_and_kill(db_url: str, data_dir: Path) -> None:
    env = {**os.environ, **OFFLINE_ENV, "DATA_DIR": str(data_dir)}
    proc = subprocess.run([sys.executable, "-c", KILL_AFTER_COLLECTION, db_url], cwd=BACKEND, env=env,
                          capture_output=True, timeout=120)
    assert proc.returncode == -9, proc.stderr.decode()[-2000:]


def restart_later(run_id: str) -> dict:
    """The process is gone: its heartbeat goes stale, then the new worker looks."""
    db.update_run(run_id, heartbeat_at=db.utcnow() - timedelta(minutes=3))
    return worker.handle_interrupted()


async def test_killed_after_collection_resumes_from_saved_corpus_once(offline):
    run_id = await approved_run()
    db_url = str(db.get_engine().url)

    run_and_kill(db_url, offline)
    run = db.get_run(run_id)
    assert run.status == RunStatus.running and run.stage == RunStage.extracting
    assert run.finish_reason == FinishReason.finish
    corpus = db.count_documents(run_id)
    assert corpus > 0

    assert restart_later(run_id) == {"resumed": [run_id], "failed": []}
    run = db.get_run(run_id)
    assert run.status == RunStatus.queued and run.resume_count == 1
    assert events(run_id, EventType.error)[-1].payload["recoverable"] is True

    async def must_not_collect(rid):
        raise AssertionError("a resumed run must not collect again")

    await worker.run_next(collect=must_not_collect)
    run = db.get_run(run_id)
    assert run.status == RunStatus.complete
    assert db.count_documents(run_id) == corpus  # the saved corpus was reused
    assert stages(run_id) == ALL_STAGES[:2] + ALL_STAGES[1:]  # collecting, extracting, then extracting again


async def test_killed_twice_fails_instead_of_resuming_again(offline):
    run_id = await approved_run()
    db_url = str(db.get_engine().url)
    run_and_kill(db_url, offline)
    restart_later(run_id)
    run_and_kill(db_url, offline)  # the resumed run dies too
    assert restart_later(run_id) == {"resumed": [], "failed": [run_id]}
    run = db.get_run(run_id)
    assert run.status == RunStatus.failed and run.resume_count == 1
    assert "interrupted again" in run.error


class Killed(BaseException):
    """Stands in for a process kill inside this test process (nothing catches it)."""


async def test_interrupted_during_collection_is_packaged_from_what_was_stored(offline, monkeypatch):
    run_id = await approved_run()
    real_collect = orchestrator.collect_agent

    async def collect_then_die(rid):
        await real_collect(rid)
        db.update_run(rid, finish_reason=None)  # as if it died before the last call finished
        raise Killed()

    with pytest.raises(Killed):
        await worker.run_next(collect=collect_then_die)
    relevant = db.count_documents(run_id, relevant_only=True)
    assert relevant > 0
    monkeypatch.setattr(worker, "_cfg", lambda: {**db.load_yaml("modes")["worker"], "thin_evidence_floor": relevant})

    assert restart_later(run_id)["resumed"] == [run_id]
    await worker.run_next()
    run = db.get_run(run_id)
    assert run.status == RunStatus.partial and run.finish_reason == FinishReason.error


async def test_interrupted_during_collection_below_the_floor_fails(offline):
    run_id = await approved_run()
    db.claim_next_run()
    db.set_stage(run_id, RunStage.collecting)  # dies before anything was saved
    assert restart_later(run_id)["failed"] == [run_id]
    run = db.get_run(run_id)
    assert run.status == RunStatus.failed and "too little was collected" in run.error


async def test_fresh_heartbeat_is_left_alone(offline):
    run_id = await approved_run()
    db.claim_next_run()
    assert worker.handle_interrupted() == {"resumed": [], "failed": []}
    assert db.get_run(run_id).status == RunStatus.running
