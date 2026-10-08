"""Crash fallback and low-evidence top-up (guide B8e, PRD 8.6).

Crash: loop error, a timeout or a model that stopped calling tools, all
without finish() -> run the plan's starting units NOT yet tried, in
order, with default limits. "fallback" {kind: crash_fallback}.
Low evidence: fewer than min_relevant relevant docs -> top up from units
with verdict kept (more pages from a kept forum, the agent's follow-up
queries inside kept units, a fuller page of a kept unit) until
min_relevant, the budget or the time is reached. "fallback" {kind: top_up}.

Every call goes through the same tools, so every limit still holds; a
dropped unit is never called again and no identical call is repeated.
"""

from __future__ import annotations

from typing import Any, Iterator

from ctxpack import db
from ctxpack.collect import tools
from ctxpack.agent.markets import primary_country
from ctxpack.config import load_yaml
from ctxpack.schemas.enums import EventType, FinishReason
from ctxpack.schemas.plan import Interpretation, StartingSourceUnit

# A result with one of these reasons ends the fallback: nothing more can run.
_FINAL = ("max_tool_calls reached", "collection time is up", "llm budget spent", "item budget spent", "social-source budget")


def _agent_cfg() -> dict[str, Any]:
    return load_yaml("modes")["agent"]


def _final(result: dict[str, Any]) -> bool:
    return result.get("status") == "limit_reached" and str(result.get("reason", "")).startswith(_FINAL)


# --------------------------------------------------------------------------
# Starting units -> tool calls
# --------------------------------------------------------------------------


def _web_query(unit: StartingSourceUnit) -> str:
    query = unit.queries[0].query if unit.queries else unit.target
    return f"site:{unit.target} {query}" if unit.kind.value == "domain" and unit.queries else query


def starting_call(unit: StartingSourceUnit, interp: Interpretation) -> tuple[str, dict[str, Any], str | None] | None:
    """(tool, args, source unit) for a plan unit, with default limits. Web units start with web_search."""
    platform, reason = unit.platform.value, unit.reason
    if platform == "reddit":
        args = {"target": unit.target, "reason": reason}
        if unit.kind.value == "subreddit" and unit.queries:   # search inside it, never browse blind
            args["query"] = unit.queries[0].query
        return "search_reddit", args, tools.unit_for("search_reddit", args)
    if platform == "tiktok":
        args = {"target": unit.target, "reason": reason}
        return "search_tiktok", args, tools.unit_for("search_tiktok", args)
    if platform == "youtube":
        args = {"query": unit.target, "reason": reason}
        return "search_youtube", args, tools.unit_for("search_youtube", args)
    if platform == "instagram":
        args = {"hashtag": unit.target.lstrip("#"), "reason": reason}
        return "search_instagram", args, tools.unit_for("search_instagram", args)
    if platform == "linkedin":
        args = {"query": unit.queries[0].query if unit.queries else unit.target, "reason": reason}
        return "search_linkedin", args, tools.unit_for("search_linkedin", args)
    if platform == "x":
        args = {"target": unit.queries[0].query if unit.queries and unit.kind.value == "query" else unit.target,
                "reason": reason}
        return "search_x", args, tools.unit_for("search_x", args)
    if platform == "web":
        country = primary_country([m.model_dump() for m in interp.markets])  # V2: first country of the top market
        language = (unit.queries[0].language if unit.queries else interp.languages[0])
        return "web_search", {"query": _web_query(unit), "country": country, "language": language,
                              "reason": reason}, None
    return None


def tried(ctx: tools.RunContext, state_calls: list[tuple[str, dict]], unit: StartingSourceUnit,
          interp: Interpretation) -> bool:
    call = starting_call(unit, interp)
    if call is None:
        return True
    name, args, source_unit = call
    if source_unit is not None:
        return source_unit in ctx.tried_units or source_unit in ctx.dropped_units
    # web: the same search was made, or the domain was already read
    if unit.kind.value == "domain" and tools.web_unit(f"https://{unit.target}") in ctx.tried_units:
        return True
    query = args["query"].casefold().strip()
    return any(n == "web_search" and (a.get("query") or "").casefold().strip() == query for n, a in state_calls)


# --------------------------------------------------------------------------
# Crash fallback
# --------------------------------------------------------------------------


async def _fetch_found(state: Any, urls: list[str], reason: str) -> dict[str, Any] | None:
    ctx = state.ctx
    todo = [u for u in urls if u not in ctx.fetched_urls and tools.web_unit(u) not in ctx.dropped_units]
    todo = todo[:ctx.limits["web_pages_per_call_max"]]
    if not todo:
        return None
    return await state_run(state, "fetch_and_segment", {"urls": todo, "reason": reason})


async def state_run(state: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    from ctxpack.collect.loop import _guarded

    result = await _guarded(state, name, args)
    if result.get("status") == "stopped":
        from ctxpack.guards import StopRequested
        raise StopRequested()
    return result


async def crash_fallback(state: Any, reason: FinishReason) -> bool:
    """Run the plan's untried starting units in order. Returns True if anything ran."""
    ctx = state.ctx
    untried = [u for u in state.plan.starting_units
               if u.enabled and not tried(ctx, state.calls, u, state.interp)]
    if not untried:
        return False
    if reason == FinishReason.time_limit:
        ctx.extra_secs = _agent_cfg()["crash_fallback_extra_secs"]
    db.append_event(ctx.run_id, EventType.fallback, {"reason": f"loop ended without finish ({reason.value})",
                                                     "kind": "crash_fallback"})
    state.fallback_used = True
    try:
        for unit in untried:
            name, args, _ = starting_call(unit, state.interp)
            args["reason"] = f"fallback: {args['reason']}"
            result = await state_run(state, name, args)
            if name == "web_search" and result.get("status") == "ok":
                result = await _fetch_found(state, [p["url"] for p in result["pages"]], args["reason"]) or result
            if _final(result):
                break
    finally:
        ctx.extra_secs = 0              # the grace is for these units only; a top-up keeps the normal cap
    return True


# --------------------------------------------------------------------------
# Top-up
# --------------------------------------------------------------------------


def _kept_units(state: Any) -> list[str]:
    from ctxpack.collect.loop import verdicts, unit_share

    ctx = state.ctx
    kept = [u for u, v in verdicts(ctx).items() if v["verdict"] == "kept" and u not in ctx.dropped_units]
    return sorted(kept, key=lambda u: unit_share(ctx, u), reverse=True)


def _last_call_for(state: Any, unit: str) -> tuple[str, dict[str, Any]] | None:
    for name, args in reversed(state.calls):
        if tools.unit_for(name, args) == unit:
            return name, args
    return None


def _follow_up_call(unit: str, query: str, interp: Interpretation) -> tuple[str, dict[str, Any]] | None:
    """A follow-up query INSIDE a kept unit."""
    reason = f"top-up: follow-up proposed for {unit}"
    family, _, rest = unit.partition(":")
    if family == "reddit":
        if rest.startswith("r/"):
            return "search_reddit", {"target": rest, "query": query, "reason": reason}
        return "search_reddit", {"target": query, "reason": reason}
    if family == "tiktok":
        return "search_tiktok", {"target": query, "reason": reason}
    if family == "youtube":
        return "search_youtube", {"query": query, "reason": reason}
    if family == "instagram":
        return "search_instagram", {"hashtag": query.replace(" ", ""), "reason": reason}
    if family == "linkedin":
        return "search_linkedin", {"query": query, "reason": reason}
    if family == "x":
        return "search_x", {"target": query, "reason": reason}
    if family == "web":
        country = primary_country([m.model_dump() for m in interp.markets])  # V2: first country of the top market
        return "web_search", {"query": f"site:{rest} {query}", "country": country,
                              "language": interp.languages[0], "reason": reason}
    return None


def _candidates(state: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    ctx = state.ctx
    follow_ups = (ctx.finished or {}).get("follow_up_queries", [])
    per_call = ctx.limits["items_per_call_max"]
    for unit in _kept_units(state):
        if unit.startswith("web:"):
            more = [u for u in ctx.page_types if tools.web_unit(u) == unit and u not in ctx.fetched_urls]
            if more:
                yield "fetch_and_segment", {"urls": more[:_agent_cfg()["top_up_pages_per_unit"]],
                                            "reason": f"top-up: more pages from kept {unit}"}
        for f in follow_ups:
            if f["source_unit"] == unit and (call := _follow_up_call(unit, f["query"], state.interp)):
                yield call
        last = _last_call_for(state, unit)
        if last and (last[1].get("limit") or per_call) < per_call:   # a fuller page of the same unit
            yield last[0], {**last[1], "limit": per_call, "reason": f"top-up: fuller page of kept {unit}"}


async def top_up(state: Any) -> bool:
    """Below min_relevant: top up from kept units. Returns True if anything ran."""
    ctx = state.ctx
    if ctx.relevant_total >= ctx.limits["min_relevant"] or tools._general_limit(ctx):
        return False
    started = False
    for name, args in list(_candidates(state)):     # planned from the agent's calls, before any top-up call
        if ctx.relevant_total >= ctx.limits["min_relevant"]:
            break
        if name != "web_search" and tools.unit_for(name, args) in ctx.dropped_units:
            continue
        if not started:
            db.append_event(ctx.run_id, EventType.fallback, {
                "reason": f"{ctx.relevant_total} relevant documents, fewer than {ctx.limits['min_relevant']}",
                "kind": "top_up"})
            state.top_up_used = started = True
        result = await state_run(state, name, args)
        if name == "web_search" and result.get("status") == "ok":
            result = await _fetch_found(state, [p["url"] for p in result["pages"]], args["reason"]) or result
        if _final(result):
            break
    return started
