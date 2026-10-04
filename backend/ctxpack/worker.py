"""Job worker: claims queued runs from the runs table (guide B13).

Started with the app (one per process) and runs one job at a time:
  - claims the oldest queued run with a row lock (db.claim_next_run)
  - updates heartbeat_at every heartbeat_secs while the run works
  - at startup and every interrupted_check_secs: runs with an old heartbeat
    become "interrupted" and are resumed once from what was saved, or
    closed with a plain message (handle_interrupted)
Timings come from modes.yaml (worker:).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ctxpack import db, orchestrator
from ctxpack.config import load_yaml
from ctxpack.schemas.enums import EventType, FinishReason, RunStatus

log = logging.getLogger(__name__)


def _cfg() -> dict[str, Any]:
    return load_yaml("modes")["worker"]


# --------------------------------------------------------------------------
# Interrupted runs
# --------------------------------------------------------------------------


def _fail(run_id: str, message: str) -> None:
    db.append_event(run_id, EventType.error, {"message": message, "recoverable": False})
    db.set_status(run_id, RunStatus.failed, error=message)


def _requeue(run: db.Run, message: str, **fields: Any) -> None:
    """Back in the queue at its old place (queued_at is kept), counted as a resume."""
    db.append_event(run.id, EventType.error, {"message": message, "recoverable": True})
    db.set_status(run.id, RunStatus.queued, resume_count=run.resume_count + 1,
                  queued_at=run.queued_at or run.created_at, **fields)


def handle_interrupted() -> dict[str, list[str]]:
    """Mark runs with an old heartbeat as interrupted, then decide what happens to each.

    - collection finished           -> resumed once from the saved corpus
    - cut off during collection     -> packaged from what was stored (partial),
                                       or failed below the thin-evidence floor
    - already resumed once          -> failed
    """
    cfg = _cfg()
    db.mark_stale_runs_interrupted()
    runs = db.runs_with_status(RunStatus.interrupted)
    out: dict[str, list[str]] = {"resumed": [], "failed": []}
    for run in runs:
        if run.resume_count >= cfg["max_resumes"]:
            _fail(run.id, "The run was interrupted again after a restart. Please start it again.")
            out["failed"].append(run.id)
        elif run.finish_reason is not None:
            _requeue(run, "The service restarted. Resuming from the collected posts.")
            out["resumed"].append(run.id)
        elif db.count_documents(run.id, relevant_only=True) >= cfg["thin_evidence_floor"]:
            _requeue(run, "The service restarted during collection. Building the pack from what was collected.",
                     finish_reason=FinishReason.error)
            out["resumed"].append(run.id)
        else:
            _fail(run.id, "The service restarted during collection and too little was collected "
                          "to build a pack. Please start the run again.")
            out["failed"].append(run.id)
    if out["resumed"]:
        orchestrator.emit_queue_positions()
    for kind, ids in out.items():
        for run_id in ids:
            log.info("interrupted run %s %s", run_id, kind)
    return out


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


async def _heartbeat(run_id: str) -> None:
    every = _cfg()["heartbeat_secs"]
    while True:
        await asyncio.sleep(every)
        try:
            await asyncio.to_thread(db.heartbeat, run_id)
        except Exception as exc:  # a missed beat is not fatal; the next one may work
            log.warning("heartbeat for %s failed (%s)", run_id, type(exc).__name__)


async def run_job(run_id: str, **pipeline: Any) -> RunStatus:
    """Run one claimed job with a heartbeat. `pipeline` overrides orchestrator stages (tests)."""
    beat = asyncio.create_task(_heartbeat(run_id))
    try:
        return await orchestrator.run_pipeline(run_id, **pipeline)
    finally:
        beat.cancel()


async def run_next(**pipeline: Any) -> str | None:
    """Claim and run the oldest queued run. Returns its id, or None if the queue is empty."""
    run = await asyncio.to_thread(db.claim_next_run)
    if run is None:
        return None
    log.info("worker claimed run %s (resume %d)", run.id, run.resume_count)
    await asyncio.to_thread(orchestrator.emit_queue_positions)
    await run_job(run.id, **pipeline)
    return run.id


async def worker_loop(stop: asyncio.Event | None = None, **pipeline: Any) -> None:
    """Started with the app. One job at a time, oldest first, until `stop` is set."""
    cfg = _cfg()
    stop = stop or asyncio.Event()
    next_check = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_check:
                await asyncio.to_thread(handle_interrupted)
                next_check = time.monotonic() + cfg["interrupted_check_secs"]
            if await run_next(**pipeline):
                continue
        except Exception as exc:  # keep the loop alive; the database may be waking up
            log.error("worker loop error (%s)", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=cfg["poll_secs"])
        except TimeoutError:
            pass
