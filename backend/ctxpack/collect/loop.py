"""The agent loop (guide B8a, prompt F4-2).

messages = [user: interpretation + plan + research questions + limits].
Repeat: one reasoner turn with the tool definitions -> run every tool_use
block (collection calls concurrently, max 3; coverage_report and finish
after them, in order) -> append the tool_results in the original order ->
events + decision log -> stop on finish() or a limit. A turn without a
tool call is nudged once; a second one ends the loop.

The tools own the data and enforce every limit (tools.py); this module
only drives the conversation, records what happened and hands over to
fallback.py (crash fallback, low-evidence top-up).

LLM_FAKE=true: the model's turns come from a recorded transcript
(tests/fixtures/transcripts/<brief>.json, B8f), or, without one, from a
plan-driven stand-in agent (starting units -> coverage_report -> finish),
so tests and the keyless local run work for any brief.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from ctxpack import db
from ctxpack.collect import tools
from ctxpack.collect.tools import RunContext
from ctxpack.config import BACKEND_DIR, load_yaml
from ctxpack.guards import BudgetExceeded, StopRequested
from ctxpack.llm import client as llm
from ctxpack.schemas.enums import EventType, FinishReason
from ctxpack.schemas.plan import Interpretation, Plan

log = logging.getLogger(__name__)

TRANSCRIPT_DIR = BACKEND_DIR / "tests" / "fixtures" / "transcripts"
NUDGE = "Call a tool or finish."
LAST_TOOLS = ("coverage_report", "finish")       # run after the turn's collection calls

ModelFn = Callable[..., Awaitable[llm.RawResult]]

_LIMIT_REASONS = {"max_tool_calls reached": FinishReason.tool_call_limit,
                  "collection time is up": FinishReason.time_limit,
                  "llm budget spent": FinishReason.budget_limit}


def _modes() -> dict[str, Any]:
    return load_yaml("modes")


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------


@dataclass
class LoopState:
    ctx: RunContext
    interp: Interpretation
    plan: Plan
    check_stop: Callable[[], None] = lambda: None
    counters: Counter = field(default_factory=Counter)
    decision_log: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)   # (tool, args) of every call
    turns: list[dict[str, Any]] = field(default_factory=list)               # the model's tool calls (transcript)
    seq: int = 0
    stopped: bool = False
    budget_hit: bool = False
    fallback_used: bool = False
    top_up_used: bool = False

    @property
    def run_id(self) -> str:
        return self.ctx.run_id


@dataclass
class LoopOutcome:
    finish_reason: FinishReason
    fallback_used: bool
    top_up_used: bool
    collection: dict[str, Any]


# --------------------------------------------------------------------------
# One tool call: events, decision log, spend
# --------------------------------------------------------------------------


def call_unit(name: str, args: dict[str, Any]) -> str | None:
    """Source unit of a call, for the events and the decision log."""
    if unit := tools.unit_for(name, args):
        return unit
    if name == "fetch_and_segment":
        return ", ".join(sorted({tools.web_unit(u) for u in args.get("urls") or []})) or None
    if name == "web_search":
        return f"web:search:{(args.get('query') or '').strip().casefold()}"
    if name == "get_trends":
        return f"trends:{(args.get('geo') or 'global').upper()}"
    return None


def result_summary(result: dict[str, Any]) -> str:
    """One line for the decision log (counts only, never scraped text)."""
    status = result.get("status", "error")
    if "kept" in result and status == "ok":
        return (f"collected {result.get('collected', 0)}, kept {result['kept']}, "
                f"relevant {round(100 * result.get('relevant_share', 0))}%")
    if "pages" in result and status == "ok":
        return f"{len(result['pages'])} pages found"
    if "relevant_total" in result:
        thin = result.get("thin_research_questions") or []
        return f"relevant so far {result['relevant_total']}; thin: {', '.join(thin) or 'none'}"
    if status == "ok" and result.get("finished"):
        return "finished"
    if status == "ok" and "signal" in result:
        return f"trends for {len(result['signal'].get('series', {}))} terms"
    if status == "refused":
        return "refused: " + "; ".join(result.get("problems", []))[:300]
    if status == "limit_reached":
        return f"limit_reached: {result.get('reason', '')}"
    if status == "error":
        return f"error: {result.get('error', '')}"[:300]
    return status


async def run_tool(state: LoopState, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool with its agent_call / agent_result / counters / cost / coverage events."""
    ctx = state.ctx
    state.seq += 1
    seq = state.seq
    unit = call_unit(name, args)
    reason = str(args.get("reason", ""))
    state.calls.append((name, dict(args)))
    db.append_event(ctx.run_id, EventType.agent_call,
                    {"seq": seq, "tool": name, "source_unit": unit, "reason": reason})
    try:
        result = await tools.call_tool(ctx, name, args)
    except BudgetExceeded as exc:            # a cleaning call inside the tool hit the run budget or daily cap
        state.budget_hit = True
        result = {"status": "limit_reached", "reason": "llm budget spent", "detail": str(exc)}
    except Exception as exc:                 # a failed source degrades gracefully (FR-B6)
        log.exception("tool %s failed", name)
        result = {"status": "error", "error": f"{name} failed ({type(exc).__name__})"}
    # Record only what is not yet recorded: with concurrent calls a per-call "before" snapshot
    # would count a neighbour's spend twice.
    if ctx.apify_usd > ctx.apify_recorded_usd:
        new = ctx.apify_usd - ctx.apify_recorded_usd
        ctx.apify_recorded_usd = ctx.apify_usd
        db.add_spend(apify_usd=new, run_id=ctx.run_id)
        run = db.get_run(ctx.run_id)
        db.append_event(ctx.run_id, EventType.cost, {"apify_usd": round(run.cost_apify_usd, 4),
                                                     "llm_usd": round(run.cost_llm_usd, 4)})
    db.append_event(ctx.run_id, EventType.agent_result, {
        "seq": seq, "tool": name, "source_unit": result.get("source_unit", unit),
        "collected": result.get("collected", 0), "kept": result.get("kept", 0),
        "relevant_share": result.get("relevant_share", 0.0), "new_terms": result.get("new_terms", []),
        "status": result.get("status", "error")})
    if "collected" in result:
        dropped = result.get("dropped", {})
        state.counters.update({"collected": result["collected"], "duplicates": dropped.get("duplicate", 0),
                               "spam": dropped.get("spam", 0), "out_of_window": dropped.get("out_of_window", 0),
                               "undated": result.get("undated", 0),
                               "relevant": result.get("relevant", 0), "kept": result.get("kept", 0)})
        db.append_event(ctx.run_id, EventType.counters, {k: state.counters[k] for k in (
            "collected", "duplicates", "spam", "out_of_window", "undated", "relevant", "kept")})
    if name == "coverage_report" and result.get("status") == "ok":
        db.append_event(ctx.run_id, EventType.coverage, {
            "questions": [{"id": rid, "text": v["question"], "docs": v["relevant_docs"]}
                          for rid, v in result["research_questions"].items()],
            "units": [{"source_unit": u, **v} for u, v in result["source_units"].items()]})
    state.decision_log.append({"seq": seq, "tool": name, "source_unit": result.get("source_unit", unit),
                               "reason": reason, "result_summary": result_summary(result)})
    return result


async def _guarded(state: LoopState, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Stop is checked before every call; a pressed Stop turns the rest of the turn into no-ops."""
    if state.stopped:
        return {"status": "stopped"}
    try:
        state.check_stop()
    except StopRequested:
        state.stopped = True
        return {"status": "stopped"}
    return await run_tool(state, name, args)


async def run_turn(state: LoopState, blocks: list[Any]) -> list[dict[str, Any]]:
    """Run one model turn's tool calls. Collection calls run concurrently (max 3);
    coverage_report and finish run after them, in order. Results come back in the original order."""
    gate = asyncio.Semaphore(_modes()["parallel_tool_calls_max"])
    results: list[dict[str, Any] | None] = [None] * len(blocks)

    async def one(i: int) -> None:
        async with gate:
            results[i] = await _guarded(state, blocks[i].name, dict(blocks[i].input or {}))

    await asyncio.gather(*(one(i) for i, b in enumerate(blocks) if b.name not in LAST_TOOLS))
    for i, b in enumerate(blocks):
        if b.name in LAST_TOOLS:
            results[i] = await _guarded(state, b.name, dict(b.input or {}))
    return results  # type: ignore[return-value]


# --------------------------------------------------------------------------
# The conversation
# --------------------------------------------------------------------------


def first_message(ctx: RunContext, interp: Interpretation, plan: Plan) -> str:
    lim = ctx.limits
    units = "\n".join(
        f"- {u.source_unit} ({u.kind.value}): {u.reason}"
        + "".join(f"\n    query [{q.language}]: {q.query}" for q in u.queries)
        for u in plan.starting_units if u.enabled)
    return "\n\n".join([
        "INTERPRETATION\n" + json.dumps(interp.model_dump(mode="json"), ensure_ascii=False, indent=1),
        "HYPOTHESES\n" + "\n".join(f"- {h.id}: {h.statement}" for h in plan.hypotheses),
        "RESEARCH QUESTIONS\n" + "\n".join(f"- {q.id}: {q.text}" for q in plan.research_questions),
        "STARTING SOURCE UNITS (from the plan; adapt as you learn)\n" + units,
        *(["WHAT THE USER TOLD US (use it to decide where this audience talks)\n"
           + "\n".join(f"- {k.replace('_', ' ')}: {', '.join(v) if isinstance(v, list) else v}"
                       for k, v in ctx.intake.items())] if ctx.intake else []),
        *(["BRANDS THE USER NAMED - competitors, and their own brand and parent brand for brand perception "
           "(search each at least once by name; finish is refused until you do)\n"
           + "\n".join(f"- {c}" for c in ctx.must_search)] if ctx.must_search else []),
        "LIMITS (enforced by the tools)\n"
        f"- tool calls: {lim['max_tool_calls']} (coverage_report and finish do not count)\n"
        f"- collection time: {lim['collection_secs']} s\n"
        f"- raw items: {lim['item_budget']} in total, at most {lim['items_per_call_max']} per call, "
        f"at most {int(lim['unit_share_max'] * lim['item_budget'])} per source unit\n"
        f"- web pages per fetch_and_segment call: {lim['web_pages_per_call_max']}\n"
        f"- budgets: Apify {tools.apify_cap(ctx):.2f} USD, LLM {lim['llm_usd']:.2f} USD\n"
        f"- target: at least {lim['min_relevant']} relevant documents\n"
        f"- time window: posts from the last {interp.time_window_days} days"
        + ("\n- Apify tools (search_reddit, search_tiktok, search_youtube, search_instagram, search_linkedin, "
           "search_x, search_facebook, get_trends) "
           "are UNAVAILABLE this run: use web_search and fetch_and_segment only" if ctx.apify_unavailable else ""),
        "Start now. Batch independent calls in one turn.",
    ])


def _limit_reason(ctx: RunContext) -> FinishReason | None:
    why = tools._general_limit(ctx)
    return _LIMIT_REASONS.get(why) if why else None


def _block_dict(b: Any) -> dict[str, Any]:
    return {"type": "tool_use", "name": b.name, "input": dict(b.input or {})}


async def converse(state: LoopState, model: ModelFn) -> FinishReason:
    """The model <-> tools loop. Returns why it ended."""
    ctx = state.ctx
    system = llm.load_prompt("collector")
    tool_defs = tools.tool_definitions()
    messages: list[dict[str, Any]] = [{"role": "user", "content": first_message(ctx, state.interp, state.plan)}]
    nudged = False
    while True:
        if reason := _limit_reason(ctx):
            return reason
        state.check_stop()
        res = await model("reasoner", system, messages, tool_defs, name="collector",
                          max_tokens=_modes()["agent"]["turn_max_tokens"])
        ctx.llm_usd += res.usd
        msg = res.message
        blocks = [b for b in msg.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": msg.content})
        if not blocks:
            if nudged:
                return FinishReason.no_tool_call
            nudged = True
            messages.append({"role": "user", "content": NUDGE})
            continue
        nudged = False
        state.turns.append({"content": [_block_dict(b) for b in blocks], "stop_reason": "tool_use"})
        results = await run_turn(state, blocks)
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(r, ensure_ascii=False, default=str),
             **({"is_error": True} if r.get("status") in ("error", "refused") else {})}
            for b, r in zip(blocks, results)]})
        save_progress(state)
        if state.stopped:
            raise StopRequested()
        if ctx.finished:
            return FinishReason.finish
        if state.budget_hit:
            return FinishReason.budget_limit


# --------------------------------------------------------------------------
# Verdicts -> sources_used / sources_dropped
# --------------------------------------------------------------------------


def unit_share(ctx: RunContext, unit: str) -> float:
    st = ctx.unit_stats.get(unit)
    return round(st["relevant"] / st["kept"], 2) if st and st["kept"] else 0.0


def verdicts(ctx: RunContext) -> dict[str, dict[str, str]]:
    """unit -> {verdict, reason}: the agent's from finish(), the rest computed in code ("kept: 58% relevant")."""
    out: dict[str, dict[str, str]] = {}
    for v in (ctx.finished or {}).get("source_verdicts", []):
        out[v["source_unit"]] = {"verdict": v["verdict"], "reason": v["reason"].strip()}
    keep = _modes()["agent"]["code_verdict_keep_share"]
    for unit in sorted(set(ctx.unit_stats) | ctx.tried_units):
        if unit in out:
            continue
        share = unit_share(ctx, unit)
        if not ctx.unit_stats.get(unit, {}).get("kept"):
            out[unit] = {"verdict": "dropped", "reason": "dropped: nothing usable came back"}
        elif share >= keep:
            out[unit] = {"verdict": "kept", "reason": f"kept: {round(100 * share)}% relevant"}
        else:
            out[unit] = {"verdict": "dropped", "reason": f"dropped: only {round(100 * share)}% relevant"}
    return out


def _platform(ctx: RunContext, unit: str) -> str:
    if unit in ctx.unit_platform:
        return str(ctx.unit_platform[unit].value)
    return "web_forum" if unit.startswith("web:") else unit.split(":", 1)[0]


def collection_record(state: LoopState) -> dict[str, Any]:
    """What the pack's coverage section needs from collection (saved on the run)."""
    ctx = state.ctx
    used, dropped = [], []
    for unit, v in verdicts(ctx).items():
        if v["verdict"] == "kept":
            used.append({"source_unit": unit, "platform": _platform(ctx, unit), "reason": v["reason"],
                         "kept": ctx.unit_stats.get(unit, {}).get("kept", 0),
                         "relevant_share": unit_share(ctx, unit)})
        else:
            dropped.append({"source_unit": unit, "reason": v["reason"]})
    fin = ctx.finished or {}
    return {"summary": fin.get("summary", ""), "gaps": fin.get("gaps", []),
            "follow_up_queries": fin.get("follow_up_queries", []),
            "decision_log": list(state.decision_log), "sources_used": used, "sources_dropped": dropped,
            "relevant_total": ctx.relevant_total, "external_signals": list(ctx.external_signals),
            "source_failures": list(ctx.source_failures)}


def save_progress(state: LoopState) -> None:
    """Every call lands in the decision log on the run, so a cut-off run keeps it."""
    db.update_run(state.run_id, tool_calls=state.ctx.calls,
                  collection={"decision_log": list(state.decision_log)})
    if state.ctx.apify_by_actor:
        db.set_cost_breakdown(state.run_id, "apify", state.ctx.apify_by_actor)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


async def run_loop(state: LoopState, model: ModelFn | None = None) -> LoopOutcome:
    """Agent loop -> crash fallback / top-up (fallback.py) -> verdicts. Never raises for
    a budget, a limit or a loop error; Stop ends it cleanly as "stopped"."""
    from ctxpack.collect import fallback

    if model is None:
        model = llm.call
        from ctxpack.config import get_settings
        if get_settings().llm_fake:
            model = fake_model(state)
    try:
        reason = await converse(state, model)
    except StopRequested:
        reason = FinishReason.stopped
    except BudgetExceeded as exc:
        log.info("run %s: %s", state.run_id, exc)
        reason = FinishReason.budget_limit
    except Exception:
        log.exception("run %s: agent loop error", state.run_id)
        reason = FinishReason.error

    try:
        if reason in (FinishReason.error, FinishReason.time_limit, FinishReason.no_tool_call) \
                and not state.ctx.finished:
            await fallback.crash_fallback(state, reason)
        if reason not in (FinishReason.stopped, FinishReason.budget_limit):
            await fallback.top_up(state)
    except StopRequested:
        reason = FinishReason.stopped
    except BudgetExceeded:
        reason = FinishReason.budget_limit

    record = collection_record(state)
    if state.ctx.apify_by_actor:
        db.set_cost_breakdown(state.run_id, "apify", state.ctx.apify_by_actor)
    db.update_run(state.run_id, tool_calls=state.ctx.calls, collection=record, finish_reason=reason,
                  fallback_used=state.fallback_used, top_up_used=state.top_up_used)
    return LoopOutcome(reason, state.fallback_used, state.top_up_used, record)


# --------------------------------------------------------------------------
# Transcripts and fake mode (B8f)
# --------------------------------------------------------------------------


def transcript_path(brief: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", brief.casefold()).strip("_")[:80] or "brief"
    return TRANSCRIPT_DIR / f"{slug}.json"


def save_transcript(brief: str, state: LoopState) -> Path:
    """The model's tool calls (names, inputs, reasons) - no scraped text, no free text."""
    path = transcript_path(brief)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"brief": brief, "turns": state.turns}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def _assistant_turns(messages: list[dict[str, Any]]) -> int:
    return sum(1 for m in messages if m["role"] == "assistant")


def _last_coverage(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for m in reversed(messages):
        if m["role"] == "user" and isinstance(m["content"], list):
            for part in m["content"]:
                data = json.loads(part.get("content") or "{}")
                if "source_units" in data:
                    return data
    return {}


def _plan_turns(state: LoopState) -> Callable[[list[dict[str, Any]]], dict[str, Any]]:
    """Stand-in agent without a transcript: starting units -> coverage_report -> finish."""
    from ctxpack.collect.fallback import starting_call

    def fake(messages: list[dict[str, Any]]) -> dict[str, Any]:
        n = _assistant_turns(messages)
        if n == 0:
            calls = [starting_call(u, state.interp) for u in state.plan.starting_units if u.enabled]
            return {"content": [{"type": "tool_use", "name": c[0], "input": c[1]} for c in calls if c],
                    "stop_reason": "tool_use"}
        if n == 1:
            return {"content": [{"type": "tool_use", "name": "coverage_report", "input": {}}],
                    "stop_reason": "tool_use"}
        if n == 2:
            cov = _last_coverage(messages)
            keep = _modes()["agent"]["code_verdict_keep_share"]
            verdicts_ = [{"source_unit": u, "verdict": "kept" if v["relevant_share"] >= keep else "dropped",
                          "reason": f"{round(100 * v['relevant_share'])}% relevant"}
                         for u, v in cov.get("source_units", {}).items()]
            return {"content": [{"type": "tool_use", "name": "finish", "input": {
                "summary": "Collected the plan's starting units.", "source_verdicts": verdicts_,
                "gaps": cov.get("thin_research_questions", [])}}], "stop_reason": "tool_use"}
        return {"content": [{"type": "text", "text": "Done."}], "stop_reason": "end_turn"}
    return fake


def fake_model(state: LoopState) -> ModelFn:
    """LLM_FAKE: replay the brief's recorded transcript, or the plan-driven stand-in."""
    path = transcript_path(state.ctx.brief_text) if state.ctx.brief_text else None
    if path is not None and path.exists():
        turns = json.loads(path.read_text(encoding="utf-8"))["turns"]

        def fake(messages: list[dict[str, Any]]) -> dict[str, Any]:
            n = _assistant_turns(messages)
            return turns[n] if n < len(turns) else {"content": [{"type": "text", "text": "Done."}],
                                                    "stop_reason": "end_turn"}
    else:
        fake = _plan_turns(state)

    async def model(role: str, system: str, messages: list[dict[str, Any]], tool_defs: list[dict[str, Any]],
                    **kwargs: Any) -> llm.RawResult:
        return await llm.call(role, system, messages, tool_defs, fake=fake, **kwargs)
    return model
