"""Runs the pipeline stages for one run (guide B5).

  collecting -> extracting -> clustering -> writing -> verifying -> packaging
  -> complete | partial | failed

Every stage saves its output to the database and writes its events to the
events table before the next one starts, so a restarted process can carry
on (worker.py, B13). Stop, a spent budget or a time limit skip to packaging
with what exists -> "partial".

Collection is finished once runs.finish_reason is set; a resumed run then
starts at extracting from its saved corpus (the same path as --from-run).

Collection is the agent loop (Step 2.4, collect/loop.py); extracting..
verifying and the pack itself are placeholders filled in by later steps.
"""

from __future__ import annotations

import logging
import resource
import sys
from typing import Any, Awaitable, Callable

from ctxpack import db
from ctxpack.config import mode_limits
from ctxpack.guards import BudgetExceeded, StopRequested
from ctxpack.llm.client import tracking
from ctxpack.schemas.enums import EventType, FinishReason, RunStage, RunStatus
from ctxpack.schemas.plan import Interpretation, Plan

log = logging.getLogger(__name__)

StageFn = Callable[[str], Awaitable[None]]
PackFn = Callable[[str, bool], Awaitable[str | None]]

# Collection ended early for one of these -> the pack is "partial".
PARTIAL_REASONS = {FinishReason.stopped, FinishReason.budget_limit, FinishReason.time_limit, FinishReason.error}
TERMINAL = {RunStatus.complete, RunStatus.partial, RunStatus.failed, RunStatus.stopped}
NOT_STARTED = {RunStatus.created, RunStatus.needs_clarification, RunStatus.awaiting_approval, RunStatus.queued}


# --------------------------------------------------------------------------
# Queue and stop
# --------------------------------------------------------------------------


def enqueue(run_id: str) -> db.Run:
    """Plan approved (or auto_approve): the run waits for the worker. Never fails with "busy"."""
    run = db.set_status(run_id, RunStatus.queued, queued_at=db.utcnow())
    emit_queue_positions()
    return run


def emit_queue_positions() -> None:
    """'queue' event for every waiting run: its place and a rough start time (typical minutes)."""
    ahead = sum(_typical_secs(r) for r in db.runs_with_status(RunStatus.running))
    for position, run in enumerate(db.queued_runs(), start=1):
        db.append_event(run.id, EventType.queue, {"position": position, "estimated_start_secs": ahead})
        ahead += _typical_secs(run)


def _typical_secs(run: db.Run) -> int:
    return int(mode_limits(run.mode)["typical_minutes"] * 60)


def request_stop(run_id: str) -> RunStatus:
    """Stop button. A run that has not started is simply stopped; a working run is
    flagged in the database and the worker packages what it has ("partial")."""
    run = db.get_run(run_id)
    if run is None:
        raise KeyError(f"run {run_id} not found")
    if run.status in NOT_STARTED:
        db.set_status(run_id, RunStatus.stopped, finish_reason=FinishReason.stopped, stop_requested_at=db.utcnow())
        emit_queue_positions()
        return RunStatus.stopped
    if run.status not in TERMINAL and run.stop_requested_at is None:
        db.update_run(run_id, stop_requested_at=db.utcnow())
    return db.get_run(run_id).status


def check_stop(run_id: str) -> None:
    """Called between stages and between tool calls."""
    run = db.get_run(run_id)
    if run is not None and run.stop_requested_at is not None:
        raise StopRequested()


# --------------------------------------------------------------------------
# Memory (B13)
# --------------------------------------------------------------------------


def peak_mem_mb() -> float:
    """Peak resident memory of this process so far (macOS reports bytes, Linux KB)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024, 1)


def record_memory(run_id: str, stage: RunStage) -> float:
    mb = peak_mem_mb()
    log.info("run %s stage %s peak memory %.1f MB", run_id, stage.value, mb)
    run = db.get_run(run_id)
    if run is not None and (run.peak_mem_mb or 0) < mb:
        db.update_run(run_id, peak_mem_mb=mb)
    return mb


# --------------------------------------------------------------------------
# Collection: the agent loop (collect/loop.py, guide B8)
# --------------------------------------------------------------------------


def loop_state(run_id: str, record: bool = False) -> Any:
    """The loop's state for a planned run: RunContext from the interpretation and plan."""
    from ctxpack.collect.loop import LoopState
    from ctxpack.collect.relevance import BriefContext
    from ctxpack.collect.tools import RunContext, db_store

    run = db.get_run(run_id)
    interp = Interpretation.model_validate(run.interpretation)
    plan = Plan.model_validate(run.plan)
    ctx = RunContext(
        run_id=run_id, mode=str(run.mode), window_days=interp.time_window_days, store=db_store(run_id),
        brief_text=run.brief_text, record=record,
        brief=BriefContext(topic=interp.topic, market=interp.market, languages=interp.languages,
                           audience=interp.audience,
                           research_questions={q.id: q.text for q in plan.research_questions}))
    ctx.llm_usd = run.cost_llm_usd
    return LoopState(ctx=ctx, interp=interp, plan=plan, check_stop=lambda: check_stop(run_id))


async def collect_agent(run_id: str) -> None:
    """The agent loop with its fallback and top-up. Sets runs.finish_reason (collection finished),
    fallback_used, top_up_used and the collection record (decision log, verdicts, gaps)."""
    from ctxpack.collect.loop import run_loop

    await run_loop(loop_state(run_id))


# --------------------------------------------------------------------------
# Later stages (placeholders until Steps 3.x)
# --------------------------------------------------------------------------


async def _placeholder(run_id: str) -> None:
    return None


async def build_pack_placeholder(run_id: str, partial: bool) -> str | None:
    """Packaging builds and saves the pack (later step); returns its id, or None for now."""
    return None


ANALYSIS_STAGES: list[tuple[RunStage, StageFn]] = [
    (RunStage.extracting, _placeholder),
    (RunStage.clustering, _placeholder),
    (RunStage.writing, _placeholder),
    (RunStage.verifying, _placeholder),
]


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------


async def run_pipeline(run_id: str, *, collect: StageFn | None = None,
                       stages: list[tuple[RunStage, StageFn]] | None = None,
                       build_pack: PackFn | None = None) -> RunStatus:
    """Run one claimed run to the end. Returns the final status.

    collect / stages / build_pack can be swapped (tests, --from-run).
    """
    collect = collect or collect_agent
    stages = ANALYSIS_STAGES if stages is None else stages
    build_pack = build_pack or build_pack_placeholder
    run = db.get_run(run_id)
    stage = RunStage.collecting
    try:
        with tracking(run_id, llm_limit_usd=mode_limits(run.mode)["llm_usd"]):
            partial = False
            if run.finish_reason is None:
                db.set_stage(run_id, stage)
                try:
                    await collect(run_id)
                except StopRequested:
                    db.update_run(run_id, finish_reason=FinishReason.stopped)
                except BudgetExceeded as exc:
                    db.update_run(run_id, finish_reason=FinishReason.budget_limit, error=str(exc))
                record_memory(run_id, stage)
            else:
                log.info("run %s: collection already finished, resuming from the saved corpus", run_id)

            partial = db.get_run(run_id).finish_reason in PARTIAL_REASONS
            if not partial:
                try:
                    for stage, fn in stages:
                        check_stop(run_id)
                        db.set_stage(run_id, stage)
                        await fn(run_id)
                        record_memory(run_id, stage)
                except StopRequested:
                    partial = True
                except BudgetExceeded as exc:
                    partial = True
                    db.update_run(run_id, error=str(exc))

            stage = RunStage.packaging
            db.set_stage(run_id, stage)
            pack_id = await build_pack(run_id, partial)
            record_memory(run_id, stage)
            if pack_id:
                db.append_event(run_id, EventType.pack_ready, {"pack_id": pack_id})
            status = RunStatus.partial if partial else RunStatus.complete
            db.set_status(run_id, status, pack_id=pack_id or db.get_run(run_id).pack_id)
            return status
    except Exception as exc:
        log.exception("run %s failed in stage %s", run_id, stage.value)
        message = f"The run failed while {stage.value} ({type(exc).__name__})."
        db.append_event(run_id, EventType.error, {"message": message, "recoverable": False})
        db.set_status(run_id, RunStatus.failed, error=message)
        return RunStatus.failed
