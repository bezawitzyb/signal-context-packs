"""Runs the pipeline stages for one run (guide B5).

  collecting -> extracting -> clustering -> writing -> verifying -> packaging
  -> complete | partial | failed

Every stage saves its output to the database and writes its events to the
events table before the next one starts, so a restarted process can carry
on (worker.py, B13). Stop, a spent budget or a time limit skip to packaging
with what exists -> "partial".

Collection is finished once runs.finish_reason is set; a resumed run then
starts at extracting from its saved corpus (the same path as --from-run).

Collection is the agent loop (Step 2.4, collect/loop.py); extracting is
analysis/extract.py (Step 3.1); clustering is analysis/cluster.py + metrics.py
(Step 3.2); writing is synthesis/baseline.py + write.py (Step 3.3);
verifying is synthesis/verify.py + confidence.py (Step 3.4); packaging is
synthesis/playbook.py + compliance.py + finalize.py (Step 3.5).
"""

from __future__ import annotations

import logging
import resource
import sys
from typing import Any, Awaitable, Callable

from ctxpack import db
from ctxpack.agent.markets import countries as market_countries
from ctxpack.config import load_yaml, mode_limits
from ctxpack.guards import BudgetExceeded, StopRequested
from ctxpack.llm.client import tracking
from ctxpack.schemas.enums import EventType, FinishReason, RunStage, RunStatus
from ctxpack.schemas.plan import Interpretation, Plan, brand_names, confirmed_goal, offer_text

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
# Cost breakdown
# --------------------------------------------------------------------------


def cost_lines(run: db.Run) -> list[str]:
    """Where the run's money went, biggest first: one line per call type and per Apify actor."""
    parts = run.cost_breakdown or {}
    rows = [(v["usd"], f"anthropic {name:<28} {int(v['calls']):>3} calls  in {int(v['input_tokens']):>7}  "
                       f"out {int(v['output_tokens']):>6}  cache read {int(v['cache_read_tokens']):>7}")
            for name, v in parts.get("anthropic", {}).items()]
    rows += [(v["usd"], f"apify     {name:<28} {int(v['runs']):>3} runs   items {int(v['items']):>5}")
             for name, v in parts.get("apify", {}).items()]
    total = sum(usd for usd, _ in rows) or 1.0
    return [f"${usd:7.3f} {round(100 * usd / total):>3}%  {text}" for usd, text in sorted(rows, reverse=True)]


def source_units(run: db.Run) -> set[str]:
    """Every unit a run planned or used (plan + agent verdicts), lower-cased."""
    units = {u.source_unit for u in Plan.model_validate(run.plan).starting_units} if run.plan else set()
    col = run.collection or {}
    units |= {s["source_unit"] for s in col.get("sources_used", []) + col.get("sources_dropped", [])}
    return {u.casefold() for u in units}


def units_overlap(sets: list[set[str]]) -> dict[str, float]:
    """Units used by more than one run, as a share of all distinct units; and the largest pairwise Jaccard."""
    from collections import Counter
    from itertools import combinations

    counts = Counter(u for s in sets for u in s)
    shared = sum(1 for c in counts.values() if c > 1)
    pairs = [len(a & b) / len(a | b) for a, b in combinations(sets, 2) if a | b]
    return {"shared": shared, "total": len(counts), "share": shared / len(counts) if counts else 0.0,
            "max_pairwise": max(pairs, default=0.0)}


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


def brief_context(run: db.Run) -> Any:
    """What the worker calls (relevance, extraction) need to know about a planned run's brief."""
    from ctxpack.collect.relevance import BriefContext

    interp = Interpretation.model_validate(run.interpretation)
    plan = Plan.model_validate(run.plan)
    known = run.intake or {}
    brands, parents = brand_names(known, run.interpretation) if "brand_perception" in (known.get("goals") or []) \
        else ([], [])
    return BriefContext(topic=interp.topic, market=interp.market, languages=interp.languages,
                        countries=market_countries([m.model_dump() for m in interp.markets]),
                        audience=interp.audience,
                        research_questions={q.id: q.text for q in plan.research_questions},
                        goals=confirmed_goal(known), offer=offer_text(known),            # V12: every step sees them
                        key_question=known.get("key_question") or "", brands=brands, parent_brands=parents)


def loop_state(run_id: str, record: bool = False, no_apify: bool = False,
               apify_usd_cap: float | None = None) -> Any:
    """The loop's state for a planned run: RunContext from the interpretation and plan."""
    from ctxpack.collect.loop import LoopState
    from ctxpack.collect.tools import RunContext, db_store

    run = db.get_run(run_id)
    interp = Interpretation.model_validate(run.interpretation)
    plan = Plan.model_validate(run.plan)
    ctx = RunContext(
        run_id=run_id, mode=str(run.mode), window_days=interp.time_window_days, store=db_store(run_id),
        brief_text=run.brief_text, record=record, brief=brief_context(run))
    ctx.llm_usd = run.cost_llm_usd
    ctx.apify_unavailable, ctx.apify_usd_cap = no_apify, apify_usd_cap
    ctx.must_search = list((run.intake or {}).get("competitors_user") or [])  # V3: always searched
    ctx.must_search += [b for b in ctx.brief.brands[:1] + ctx.brief.parent_brands[:1]   # V12: the user's brand
                        if b.casefold() not in {c.casefold() for c in ctx.must_search}]
    known = run.intake or {}                                            # V6, V11: the user's goals, offer, key
    ctx.intake = {k: v for k, v in {"goals": confirmed_goal(known),      # question, roles and channels guide where
                                    "offer": offer_text(known), "key_question": known.get("key_question"),
                                    "audience_roles": known.get("audience_roles"),
                                    "channels_in_use": known.get("channels_in_use")}.items() if v}
    return LoopState(ctx=ctx, interp=interp, plan=plan, check_stop=lambda: check_stop(run_id))


async def collect_agent(run_id: str) -> None:
    """The agent loop with its fallback and top-up. Sets runs.finish_reason (collection finished),
    fallback_used, top_up_used and the collection record (decision log, verdicts, gaps)."""
    from ctxpack.collect.loop import run_loop

    await run_loop(loop_state(run_id))


# --------------------------------------------------------------------------
# Analysis stages (Steps 3.x; the rest are placeholders until their step)
# --------------------------------------------------------------------------


async def extract_stage(run_id: str) -> None:
    """Extraction (Step 3.1): relevant docs without an extraction yet, saved batch by batch."""
    from ctxpack.analysis.extract import extract_run

    await extract_run(run_id, brief_context(db.get_run(run_id)))


async def cluster_stage(run_id: str) -> None:
    """Clustering (Step 3.2): one reasoner call, the membership check, then the metrics (code only)."""
    from ctxpack.analysis.cluster import cluster_run
    from ctxpack.analysis.metrics import compute_run

    await cluster_run(run_id, brief_context(db.get_run(run_id)))
    compute_run(run_id)


async def write_stage(run_id: str) -> None:
    """Writing (Step 3.3): generic baseline, two writer calls, non_obvious; saves the draft."""
    from ctxpack.synthesis.write import write_run

    await write_run(run_id, brief_context(db.get_run(run_id)))


async def verify_stage(run_id: str) -> None:
    """Verifying (Step 3.4): exact quotes, claim checks, confidence; saves draft["verified"]."""
    from ctxpack.synthesis.verify import verify_run

    await verify_run(run_id)


async def _placeholder(run_id: str) -> None:
    return None


async def package_stage(run_id: str, partial: bool) -> str | None:
    """Packaging (Step 3.5): playbook (the run's brand voice), compliance, finalise, validate, save.
    Returns the pack id, or None when there is no verified draft to package yet."""
    from ctxpack.synthesis.finalize import package_run

    return (await package_run(run_id, partial)).pack_id


ANALYSIS_STAGES: list[tuple[RunStage, StageFn]] = [
    (RunStage.extracting, extract_stage),
    (RunStage.clustering, cluster_stage),
    (RunStage.writing, write_stage),
    (RunStage.verifying, verify_stage),
]


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------


def thin_floor() -> int:
    """Relevant posts needed for a pack. Offline mode (recorded samples, fake model) has its own, lower floor."""
    from ctxpack.config import get_settings

    cfg = load_yaml("modes")["worker"]
    return cfg["thin_evidence_floor_offline"] if get_settings().offline else cfg["thin_evidence_floor"]


async def _attempt(run_id: str, label: str, fn: Callable[[], Awaitable[Any]]) -> Any:
    """Run one step, trying again once (worker.step_attempts) on an unexpected error.
    Stop and budget limits are never retried: they end the step at once."""
    tries = load_yaml("modes")["worker"]["step_attempts"]
    for n in range(1, tries + 1):
        try:
            return await fn()
        except (StopRequested, BudgetExceeded):
            raise
        except Exception as exc:
            if n == tries:
                raise
            log.warning("run %s: %s failed (%s), trying again", run_id, label, type(exc).__name__)
            db.append_event(run_id, EventType.error, {
                "message": f"A step hit a problem while {label}; trying it again.", "recoverable": True})


def thin_reasons(run: db.Run, relevant: int, floor: int) -> dict[str, Any]:
    """Why a run has too few relevant posts, in plain words, plus the re-plans worth offering (V1)."""
    cfg = load_yaml("modes")["worker"]
    counters = next((e.payload for e in reversed(db.get_events(run.id, limit=100000))
                     if e.type == EventType.counters), {})
    collected, kept = int(counters.get("collected", 0)), int(counters.get("kept", 0))
    interp = Interpretation.model_validate(run.interpretation) if run.interpretation else None
    langs = set(interp.languages) if interp else set()
    docs = db.get_documents(run.id)
    in_lang = sum(1 for d in docs if (d.language or "") in langs)
    reasons = []
    if collected < cfg["thin_few_collected"]:
        reasons.append({"code": "few_posts", "text": "Very few public posts were found: this audience seems to "
                                                     "read more than it posts, or talks about this elsewhere."})
    if collected and int(counters.get("out_of_window", 0)) / collected > cfg["thin_old_share"]:
        reasons.append({"code": "too_old", "text": "Most posts found were older than the chosen time window."})
    if docs and langs and in_lang / len(docs) < cfg["thin_language_share"]:
        reasons.append({"code": "language", "text": "Very few posts were in the chosen languages."})
    if kept and relevant / kept < cfg["thin_offtopic_share"]:
        reasons.append({"code": "off_topic", "text": "Most posts found were about something else."})
    if not reasons:
        reasons.append({"code": "few_relevant", "text": "Too few posts were about this topic for a reliable pack."})
    replans = ["broaden_audience"]
    if interp and "en" not in langs:
        replans.append("include_english")
    if interp and interp.time_window_days < max(load_yaml("modes")["time_window_days_options"]):
        replans.append("widen_window")
    if str(run.mode) == "quick":
        replans.append("run_standard")
    return {"relevant": relevant, "needed": floor, "reasons": reasons, "replans": replans}


async def run_pipeline(run_id: str, *, collect: StageFn | None = None,
                       stages: list[tuple[RunStage, StageFn]] | None = None,
                       build_pack: PackFn | None = None) -> RunStatus:
    """Run one claimed run to the end. Returns the final status (V1: never lose a run).

    Above the thin-evidence floor a run ALWAYS ends with a pack: the analysis runs however collection
    ended; a step that fails twice, a stop or a budget limit during analysis gives an evidence-only pack.
    Below the floor it ends "failed" with plain reasons (runs.collection["thin"]).
    collect / stages / build_pack can be swapped (tests, --from-run).
    """
    from ctxpack.synthesis.finalize import package_evidence_only

    collect = collect or collect_agent
    stages = ANALYSIS_STAGES if stages is None else stages
    build_pack = build_pack or package_stage
    run = db.get_run(run_id)
    stage = RunStage.collecting
    try:
        limits = mode_limits(run.mode)
        if run.finish_reason is None:
            with tracking(run_id, llm_limit_usd=limits["llm_usd"]):  # collection budget
                db.set_stage(run_id, stage)
                try:
                    await collect(run_id)
                except StopRequested:
                    db.update_run(run_id, finish_reason=FinishReason.stopped)
                except BudgetExceeded as exc:
                    db.update_run(run_id, finish_reason=FinishReason.budget_limit, error=str(exc))
                except Exception as exc:  # V1: an error mid-collection keeps what was stored
                    log.exception("run %s: collection failed", run_id)
                    db.update_run(run_id, finish_reason=FinishReason.error)
                    db.append_event(run_id, EventType.error, {
                        "message": f"Collection stopped with an error ({type(exc).__name__}); "
                                   "continuing with what was collected.", "recoverable": True})
                record_memory(run_id, stage)
        else:
            log.info("run %s: collection already finished, resuming from the saved corpus", run_id)

        floor = thin_floor()
        relevant = db.count_documents(run_id, relevant_only=True)
        if relevant < floor:
            thin = thin_reasons(db.get_run(run_id), relevant, floor)
            message = f"Too few relevant posts for a pack ({relevant} of the {floor} needed)."
            db.update_run(run_id, collection={**(db.get_run(run_id).collection or {}), "thin": thin})
            db.append_event(run_id, EventType.error, {"message": message, "recoverable": False, "thin": True})
            db.set_status(run_id, RunStatus.failed, error=message)
            return RunStatus.failed

        # Analysis has its own budget, so an expensive collection never starves the pack.
        with tracking(run_id, llm_limit_usd=limits["analysis_llm_usd"], analysis=True):
            partial = db.get_run(run_id).finish_reason in PARTIAL_REASONS
            failure: str | None = None
            try:
                for stage, fn in stages:
                    check_stop(run_id)
                    db.set_stage(run_id, stage)
                    await _attempt(run_id, stage.value, lambda fn=fn: fn(run_id))
                    record_memory(run_id, stage)
            except StopRequested:
                failure = f"Partial pack: the run was stopped by hand while {stage.value}; it shows the collected posts."
            except BudgetExceeded as exc:
                db.update_run(run_id, error=str(exc))
                failure = (f"Partial pack: the analysis budget ran out while {stage.value}; it shows the collected "
                           "posts.")
            except Exception as exc:
                log.exception("run %s: %s failed twice", run_id, stage.value)
                failure = (f"Partial pack: the analysis could not finish ({stage.value} failed: "
                           f"{type(exc).__name__}); it shows the collected posts.")

            stage = RunStage.packaging
            db.set_stage(run_id, stage)
            pack_id = None
            if failure is None:
                try:
                    pack_id = await _attempt(run_id, "packaging", lambda: build_pack(run_id, partial))
                except (StopRequested, BudgetExceeded, Exception) as exc:
                    log.warning("run %s: packaging failed (%s)", run_id, type(exc).__name__)
                    failure = f"Partial pack: packaging failed ({type(exc).__name__}); it shows the collected posts."
                if pack_id is None and failure is None:
                    failure = "Partial pack: the analysis produced nothing to package; it shows the collected posts."
            if pack_id is None:
                pack_id = package_evidence_only(run_id, failure)
                db.append_event(run_id, EventType.fallback, {"kind": "evidence_only", "reason": failure})
            record_memory(run_id, stage)
            if pack_id:
                db.append_event(run_id, EventType.pack_ready, {"pack_id": pack_id})
            status = RunStatus.partial if (partial or failure) else RunStatus.complete
            db.set_status(run_id, status, pack_id=pack_id or db.get_run(run_id).pack_id)
            return status
    except Exception as exc:
        log.exception("run %s failed in stage %s", run_id, stage.value)
        message = f"The run failed while {stage.value} ({type(exc).__name__})."
        db.append_event(run_id, EventType.error, {"message": message, "recoverable": False})
        db.set_status(run_id, RunStatus.failed, error=message)
        return RunStatus.failed
