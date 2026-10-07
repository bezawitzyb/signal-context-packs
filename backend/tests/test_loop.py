"""The agent loop (Step 2.4, guide B8): limits, finish() rules, fallback, top-up, concurrency.

USE_FIXTURES + LLM_FAKE: no network, no money. The model is a scripted
list of turns, so each test controls exactly what "the agent" does.
"""

import asyncio
import copy
import json
import time

import pytest

from ctxpack import db, orchestrator
from ctxpack.collect import apify, loop, tools
from ctxpack.config import get_settings, load_yaml
from ctxpack.guards import BudgetExceeded
from ctxpack.llm import client as llm
from ctxpack.schemas.enums import EventType, FinishReason, RunStatus
from tests.test_worker import OFFLINE_ENV, approved_run, events


@pytest.fixture
def offline(monkeypatch, tmp_path, temp_db):
    for key, value in OFFLINE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def with_limits(monkeypatch, **changes):
    """Override quick-mode limits (modes.yaml) for one test."""
    modes = copy.deepcopy(load_yaml("modes"))
    modes["modes"]["quick"].update(changes)
    monkeypatch.setattr(tools, "_modes", lambda: modes)
    monkeypatch.setattr(loop, "_modes", lambda: modes)


def use(name, **args):
    return {"type": "tool_use", "name": name, "input": args}


REDDIT = use("search_reddit", target="r/MealPrepSunday", limit=10, reason="where students post weekly preps")
TIKTOK = use("search_tiktok", target="#mealprep", limit=10, reason="Gen Z reactions in comments")
COVERAGE = use("coverage_report")


def scripted(turns, usd=0.0, seen=None):
    """A model that plays `turns` in order. A turn is a list of tool_use dicts, an exception
    to raise, or a function of the messages. After the script: plain text (no tool call)."""
    async def model(role, system, messages, tool_defs, **kwargs):
        if seen is not None:
            seen.append(copy.deepcopy(messages))
        n = sum(1 for m in messages if m["role"] == "assistant")
        turn = turns[n] if n < len(turns) else [{"type": "text", "text": "nothing more"}]
        if isinstance(turn, BaseException):
            raise turn
        if callable(turn):
            turn = turn(messages)
        return llm.RawResult(message=llm._fake_message(role, {"content": turn}), usd=usd)
    return model


def finish_all(verdict="kept", **extra):
    """finish() naming every unit the coverage report listed."""
    def turn(messages):
        cov = loop._last_coverage(messages)
        return [use("finish", summary="done", gaps=["RQ-04 thin"],
                    source_verdicts=[{"source_unit": u, "verdict": verdict, "reason": "on topic"}
                                     for u in cov["source_units"]], **extra)]
    return turn


async def run(run_id, model):
    return await loop.run_loop(orchestrator.loop_state(run_id), model)


def calls(run_id):
    return [(e.payload["tool"], e.payload["source_unit"]) for e in events(run_id, EventType.agent_call)]


# --- limits -------------------------------------------------------------------

async def test_tiny_llm_budget_stops_cleanly(offline, monkeypatch):
    with_limits(monkeypatch, llm_usd=0.01)
    ran = []
    monkeypatch.setattr(apify, "run_with_fallback", lambda *a, **k: ran.append(a))
    run_id = await approved_run()
    out = await run(run_id, scripted([[REDDIT], [TIKTOK]], usd=0.02))   # the first turn spends the budget
    assert out.finish_reason == FinishReason.budget_limit
    assert ran == [] and db.count_documents(run_id) == 0           # the tool refused; nothing was scraped
    assert out.collection["decision_log"][0]["result_summary"] == "limit_reached: llm budget spent"
    assert len(out.collection["decision_log"]) == 1                # no second model turn
    run_ = db.get_run(run_id)
    assert run_.finish_reason == FinishReason.budget_limit and run_.collection is not None
    assert not run_.fallback_used and not run_.top_up_used


async def test_budget_exceeded_mid_loop_keeps_what_was_collected(offline):
    run_id = await approved_run()
    out = await run(run_id, scripted([[REDDIT], BudgetExceeded("run LLM budget of $1.40 spent")]))
    assert out.finish_reason == FinishReason.budget_limit
    assert calls(run_id) == [("search_reddit", "reddit:r/MealPrepSunday")]
    assert out.collection["sources_used"][0]["source_unit"] == "reddit:r/MealPrepSunday"
    assert db.count_documents(run_id) > 0


async def test_tiny_apify_budget_refuses_the_call_without_running_it(offline, monkeypatch):
    with_limits(monkeypatch, apify_usd=0.0001)
    ran = []
    monkeypatch.setattr(apify, "run_with_fallback", lambda *a, **k: ran.append(a))
    run_id = await approved_run()
    out = await run(run_id, scripted([[REDDIT], [COVERAGE], finish_all()]))
    assert out.finish_reason == FinishReason.finish and ran == []
    assert out.collection["decision_log"][0]["result_summary"].startswith("limit_reached: social-source budget")


async def test_tool_call_limit_ends_the_loop(offline, monkeypatch):
    with_limits(monkeypatch, max_tool_calls=1)
    run_id = await approved_run()
    out = await run(run_id, scripted([[REDDIT], [TIKTOK]]))
    assert out.finish_reason == FinishReason.tool_call_limit
    assert [c[0] for c in calls(run_id)] == ["search_reddit"]


async def test_unit_over_its_share_is_refused(offline, monkeypatch):
    with_limits(monkeypatch, item_budget=40, min_relevant=1)   # 30% of 40 = 12 items per unit
    run_id = await approved_run()
    full = use("search_reddit", target="r/MealPrepSunday", limit=12, reason="weekly preps")
    again = use("search_reddit", target="r/MealPrepSunday", limit=5, reason="more of the same")
    out = await run(run_id, scripted([[full], [again], [COVERAGE], finish_all()]))
    first, second = out.collection["decision_log"][:2]
    assert first["result_summary"].startswith("collected 12")
    assert second["result_summary"] == "limit_reached: unit share reached"
    state_items = sum(1 for d in db.get_documents(run_id) if d.source_unit == "reddit:r/MealPrepSunday")
    assert state_items <= 12


# --- finish() -------------------------------------------------------------------

async def test_finish_without_fresh_coverage_report_is_refused(offline, monkeypatch):
    with_limits(monkeypatch, min_relevant=1)
    run_id = await approved_run()
    early_finish = use("finish", summary="done", gaps=[], source_verdicts=[
        {"source_unit": "reddit:r/MealPrepSunday", "verdict": "kept", "reason": "on topic"}])
    out = await run(run_id, scripted([[REDDIT], [early_finish], [COVERAGE], [TIKTOK], [early_finish],
                                      [COVERAGE], finish_all()]))
    log = [e["result_summary"] for e in out.collection["decision_log"]]
    assert log[1].startswith("refused: call coverage_report after your last collection call")
    # coverage, then a NEW collection call: coverage is stale again
    assert log[4].startswith("refused: call coverage_report after your last collection call")
    assert log[-1] == "finished" and out.finish_reason == FinishReason.finish


async def test_finish_must_name_every_unit_with_a_reason(offline, monkeypatch):
    with_limits(monkeypatch, min_relevant=1)
    run_id = await approved_run()
    vague = use("finish", summary="done", gaps=[], source_verdicts=[
        {"source_unit": "reddit:r/MealPrepSunday", "verdict": "kept", "reason": " "}])
    out = await run(run_id, scripted([[REDDIT, TIKTOK], [COVERAGE], [vague], finish_all()]))
    refused = out.collection["decision_log"][3]["result_summary"]
    assert "reason must not be empty" in refused and "tiktok:#mealprep" in refused
    assert out.finish_reason == FinishReason.finish


async def test_no_tool_call_is_nudged_once_then_ends(offline):
    run_id = await approved_run()
    seen = []
    out = await run(run_id, scripted([[{"type": "text", "text": "thinking"}]], seen=seen))
    assert seen[1][-1] == {"role": "user", "content": loop.NUDGE}
    assert out.finish_reason == FinishReason.no_tool_call


# --- fallback and top-up ----------------------------------------------------------

async def test_forced_error_runs_the_untried_starting_units_in_order(offline, monkeypatch):
    with_limits(monkeypatch, min_relevant=1)          # no top-up afterwards: only the fallback runs
    run_id = await approved_run()
    out = await run(run_id, scripted([[REDDIT], RuntimeError("model went away")]))
    assert out.finish_reason == FinishReason.error and out.fallback_used
    assert calls(run_id) == [("search_reddit", "reddit:r/MealPrepSunday"),       # the agent's call
                             ("search_tiktok", "tiktok:#mealprep"),               # fallback, plan order,
                             ("search_youtube", "youtube:search:student meal prep")]  # reddit not repeated
    fb = events(run_id, EventType.fallback)
    assert fb[0].payload["kind"] == "crash_fallback"
    assert all(e["reason"].startswith("fallback: ") for e in out.collection["decision_log"][1:])
    run_ = db.get_run(run_id)
    assert run_.fallback_used and run_.finish_reason == FinishReason.error
    # verdicts for units the agent never judged are computed in code
    reasons = [s["reason"] for s in out.collection["sources_used"] + out.collection["sources_dropped"]]
    assert all(r.startswith(("kept: ", "dropped: ")) and "% relevant" in r for r in reasons)


async def test_low_evidence_finish_tops_up_from_kept_units_only(offline, monkeypatch):
    with_limits(monkeypatch, min_relevant=500)             # unreachable: top-up keeps going until it runs dry
    run_id = await approved_run()
    finish = use("finish", summary="done", gaps=[], source_verdicts=[
        {"source_unit": "reddit:r/MealPrepSunday", "verdict": "kept", "reason": "first-person preps"},
        {"source_unit": "tiktok:#mealprep", "verdict": "dropped", "reason": "mostly creators selling"}],
        follow_up_queries=[{"source_unit": "reddit:r/MealPrepSunday", "query": "cheap lunches"},
                           {"source_unit": "tiktok:#mealprep", "query": "mealprep fail"}])
    out = await run(run_id, scripted([[REDDIT, TIKTOK], [COVERAGE], [finish]]))
    assert out.finish_reason == FinishReason.finish and out.top_up_used and not out.fallback_used
    after_finish = calls(run_id)[4:]
    assert after_finish == [("search_reddit", "reddit:r/MealPrepSunday"),       # follow-up searched INSIDE it
                            ("search_reddit", "reddit:r/MealPrepSunday")]       # fuller page of the kept unit
    top_up_reasons = [e["reason"] for e in out.collection["decision_log"][4:]]
    assert top_up_reasons[0] == "top-up: follow-up proposed for reddit:r/MealPrepSunday"
    assert not any(tool == "search_tiktok" for tool, _ in after_finish)          # dropped: never again
    assert events(run_id, EventType.fallback)[-1].payload["kind"] == "top_up"
    assert db.get_run(run_id).top_up_used
    assert "tiktok:#mealprep" in {s["source_unit"] for s in out.collection["sources_dropped"]}


async def test_tools_refuse_a_dropped_unit_and_an_identical_call(offline):
    run_id = await approved_run()
    state = orchestrator.loop_state(run_id)
    ctx = state.ctx
    ctx.dropped_units.add("tiktok:#mealprep")
    assert (await tools.search_tiktok(ctx, "#mealprep", 20, "again"))["status"] == "unit_dropped"
    assert (await tools.search_reddit(ctx, "r/MealPrepSunday", 10, "first"))["status"] == "ok"
    assert (await tools.search_reddit(ctx, "r/MealPrepSunday", 10, "same"))["status"] == "duplicate_call"


async def test_enough_evidence_means_no_top_up(offline, monkeypatch):
    with_limits(monkeypatch, min_relevant=1)
    run_id = await approved_run()
    out = await run(run_id, scripted([[REDDIT], [COVERAGE], finish_all()]))
    assert not out.top_up_used and events(run_id, EventType.fallback) == []


# --- concurrency --------------------------------------------------------------------

async def test_tool_calls_in_one_turn_run_concurrently_max_3_in_order(offline, monkeypatch):
    running, peak, spans = 0, 0, []

    async def slow_tool(ctx, name, args):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        start = time.monotonic()
        await asyncio.sleep(0.2)
        spans.append((start, time.monotonic()))
        running -= 1
        return {"status": "ok", "echo": args.get("target")}

    monkeypatch.setattr(tools, "call_tool", slow_tool)
    run_id = await approved_run()
    seen = []
    four = [use("search_reddit", target=f"r/sub{i}", reason="test") for i in range(4)]
    await run(run_id, scripted([four[:2], four], seen=seen))
    assert peak == 3                                   # never more than three at once
    first_six = spans[:6]                              # the two scripted turns (later: fallback calls)
    elapsed = max(e for _, e in first_six) - min(s for s, _ in first_six)
    assert elapsed < 0.9                               # 2 + 4 calls one by one would take 1.2 s; here ~0.6 s
    results = seen[2][-1]["content"]                   # tool_results of the 4-call turn, original order
    assert [json.loads(r["content"])["echo"] for r in results] == ["r/sub0", "r/sub1", "r/sub2", "r/sub3"]


async def test_two_calls_in_one_turn_overlap(offline, monkeypatch):
    spans = []

    async def slow_tool(ctx, name, args):
        start = time.monotonic()
        await asyncio.sleep(0.2)
        spans.append((start, time.monotonic()))
        return {"status": "ok"}

    monkeypatch.setattr(tools, "call_tool", slow_tool)
    run_id = await approved_run()
    await run(run_id, scripted([[REDDIT, TIKTOK]]))
    (a0, a1), (b0, b1) = spans[:2]                     # the first turn (later: fallback calls)
    assert a0 < b1 and b0 < a1                         # the two calls were running at the same time


# --- the pipeline -------------------------------------------------------------------

async def test_stop_during_the_loop_gives_a_partial_run(offline, monkeypatch):
    run_id = await approved_run()

    def press_stop(messages):
        orchestrator.request_stop(run_id)
        return [TIKTOK]

    monkeypatch.setattr(loop, "fake_model", lambda state: scripted([[REDDIT], press_stop]))
    from ctxpack import worker
    await worker.run_next()
    run_ = db.get_run(run_id)
    assert run_.status == RunStatus.partial and run_.finish_reason == FinishReason.stopped
    assert [c[0] for c in calls(run_id)] == ["search_reddit"]
    assert run_.collection["decision_log"]


def test_transcript_names_are_stable_and_hold_no_free_text(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "TRANSCRIPT_DIR", tmp_path)
    assert loop.transcript_path("Heat pumps for homeowners in Germany").name == \
        "heat_pumps_for_homeowners_in_germany.json"
    state = loop.LoopState(ctx=None, interp=None, plan=None)
    state.turns = [{"content": [REDDIT], "stop_reason": "tool_use"}]
    saved = json.loads(loop.save_transcript("x", state).read_text())
    assert saved["turns"][0]["content"][0]["type"] == "tool_use"


async def test_timeout_gives_the_crash_fallback_a_short_grace_only(offline, monkeypatch):
    with_limits(monkeypatch, collection_secs=0, min_relevant=500)
    run_id = await approved_run()
    out = await run(run_id, scripted([[REDDIT]]))
    assert out.finish_reason == FinishReason.time_limit and out.fallback_used
    assert [c[0] for c in calls(run_id)] == ["search_reddit", "search_tiktok", "search_youtube"]  # plan units
    assert not out.top_up_used                         # no top-up past the time cap


# --- time cap (Step 2.4 fix: a Quick run stays within its 300 s) ----------------------

def ctx_with_secs_left(run_id, secs):
    state = orchestrator.loop_state(run_id)
    state.ctx.started = time.monotonic() - (state.ctx.limits["collection_secs"] - secs)
    return state.ctx


async def test_a_call_that_cannot_finish_in_time_is_not_started(offline, monkeypatch):
    ran = []
    monkeypatch.setattr(apify, "run_actor", lambda *a, **k: ran.append(a))
    run_id = await approved_run()
    ctx = ctx_with_secs_left(run_id, 30)               # YouTube usually needs at least 60 s
    out = await tools.search_youtube(ctx, "meal prep", 20, "late call")
    assert out["status"] == "limit_reached" and out["reason"].startswith("not enough time left for search_youtube")
    assert ran == [] and ctx.calls == 0
    assert (await tools.web_search(ctx, "snacks", "NL", "nl", "quick search"))["status"] == "ok"   # needs ~10 s


async def test_actors_get_only_the_time_that_is_left(offline, monkeypatch):
    timeouts = []

    async def fake_actor(spec, run_input, limit, timeout=None):
        timeouts.append(timeout)
        return apify.ActorResult(spec["id"], [], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_actor)
    run_id = await approved_run()
    ctx = ctx_with_secs_left(run_id, 75)
    await tools.search_reddit(ctx, "r/MealPrepSunday", 10, "test")
    assert timeouts and all(t <= 75 for t in timeouts)     # not the usual 180 s


async def test_no_actor_or_fallback_starts_in_the_last_seconds(monkeypatch):
    called = []

    async def fake_actor(*a, **k):
        called.append(a)
        return apify.ActorResult("a", [], 0.0, "ERROR")

    monkeypatch.setattr(apify, "run_actor", fake_actor)
    res = await apify.run_with_fallback([({"id": "a"}, {}), ({"id": "b"}, {})], 10,
                                        deadline=time.monotonic() + 5)
    assert res.status == apify.NO_TIME and called == []


# --- Apify credit used up -------------------------------------------------------------

def test_apify_no_credit_message_is_recognised():
    seen = ("ApifyApiError: Your remaining usage of $0.373513 this billing cycle isn't enough for this "
            "run. Increase your limit by upgrading to a paid plan at https://console.apify.com/billing")
    assert apify.is_no_credit(seen)
    assert not apify.is_no_credit("ApifyApiError: Input is not valid: field maxItems must be a number")


async def test_no_apify_credit_switches_the_run_to_web_sources(offline, monkeypatch):
    actor_calls = []

    async def no_credit(spec, run_input, limit, timeout=None):
        actor_calls.append(spec["id"])
        return apify.ActorResult(spec["id"], status=apify.NO_CREDIT, error="remaining usage ... isn't enough")

    monkeypatch.setattr(apify, "run_actor", no_credit)
    run_id = await approved_run()
    ctx = orchestrator.loop_state(run_id).ctx
    first = await tools.search_reddit(ctx, "r/MealPrepSunday", 10, "test")
    assert first["status"] == "limit_reached" and first["reason"] == tools.NO_APIFY_CREDIT
    assert len(actor_calls) == 1                       # the backup actor was not tried
    for refused in (tools.search_youtube(ctx, "meal prep", 10, "test"),
                    tools.search_tiktok(ctx, "#mealprep", 10, "test"),
                    tools.get_trends(ctx, ["meal prep"], "NL", "test")):
        assert (await refused)["reason"] == tools.NO_APIFY_CREDIT
    assert len(actor_calls) == 1 and ctx.calls == 1    # refused at once: no actor, no call used
    assert (await tools.web_search(ctx, "snacks", "NL", "nl", "web instead"))["status"] == "ok"


# --- Reddit: search inside a subreddit -----------------------------------------------

async def test_reddit_query_searches_inside_the_subreddit(offline, monkeypatch):
    inputs = []

    async def fake_actor(spec, run_input, limit, timeout=None):
        inputs.append((spec["id"], run_input))
        return apify.ActorResult(spec["id"], [], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_actor)
    run_id = await approved_run()
    ctx = orchestrator.loop_state(run_id).ctx
    out = await tools.search_reddit(ctx, "r/de", 20, "national subreddit", query="Wärmepumpe Erfahrungen")
    assert out["source_unit"] == "reddit:r/de"                     # still the community's unit
    main, backup = inputs                                          # nothing came back: backup tried too
    assert main[1]["searchTerms"] == ["Wärmepumpe Erfahrungen"] and main[1]["withinCommunity"] == "de"
    assert "subredditUrls" not in main[1]
    assert backup[1]["searches"] == ["Wärmepumpe Erfahrungen"] and backup[1]["searchCommunityName"] == "de"
    # browsing the same subreddit is a different call, not a duplicate
    assert (await tools.search_reddit(ctx, "r/de", 20, "browse"))["status"] != "duplicate_call"
    assert "subredditUrls" in inputs[2][1]


def test_fallback_searches_a_planned_subreddit_with_its_query():
    from ctxpack.collect.fallback import starting_call
    from ctxpack.schemas.plan import Interpretation, StartingSourceUnit
    unit = StartingSourceUnit.model_validate({"platform": "reddit", "kind": "subreddit", "target": "r/de",
                                              "reason": "national", "queries": [
                                                  {"language": "de", "query": "Wärmepumpe Erfahrungen"}]})
    interp = Interpretation.model_validate({"topic": "heat pumps", "market": "DE", "languages": ["de"],
                                            "audience": "owners", "category": "heating",
                                            "compliance_category": "energy_environmental",
                                            "intent": "launch", "time_window_days": 180})
    name, args, unit_name = starting_call(unit, interp)
    assert (name, args["query"], unit_name) == ("search_reddit", "Wärmepumpe Erfahrungen", "reddit:r/de")


# --- cost breakdown per call type -------------------------------------------------------

async def test_cost_breakdown_per_call_type_is_saved_on_the_run(offline, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("ctxpack.guards.check_daily_cap", lambda: None)
    run_id = await approved_run()
    usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=500,
                            cache_creation_input_tokens=0)
    with llm.tracking(run_id):
        for _ in range(2):
            await llm._after_paid_call("worker", "record_relevance", "claude-haiku-4-5-20251001", usage, 1.0)
        await llm._after_paid_call("reasoner", "collector", "claude-sonnet-5-5", usage, 1.0)
    part = db.get_run(run_id).cost_breakdown["anthropic"]
    assert part["worker/record_relevance"]["calls"] == 2
    assert part["worker/record_relevance"]["input_tokens"] == 2000
    assert part["worker/record_relevance"]["cache_read_tokens"] == 1000
    assert part["reasoner/collector"]["usd"] > part["worker/record_relevance"]["usd"] / 2

    with llm.tracking(run_id):                       # a resumed run adds to what was saved
        await llm._after_paid_call("worker", "record_relevance", "claude-haiku-4-5-20251001", usage, 1.0)
    assert db.get_run(run_id).cost_breakdown["anthropic"]["worker/record_relevance"]["calls"] == 3


async def test_apify_spend_per_actor_is_saved_and_listed_biggest_first(offline, monkeypatch):
    with_limits(monkeypatch, min_relevant=1)

    async def paid_actor(spec, run_input, limit, timeout=None):
        items = json.loads(apify.fixture_path(spec["id"]).read_text())[:limit]
        return apify.ActorResult(spec["id"], items, 0.05, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", paid_actor)
    run_id = await approved_run()
    await run(run_id, scripted([[REDDIT], [COVERAGE], finish_all()]))
    run_ = db.get_run(run_id)
    assert run_.cost_breakdown["apify"]["harshmaur/reddit-scraper"] == {"runs": 1, "usd": 0.05, "items": 10}
    run_.cost_breakdown["anthropic"] = {"worker/record_relevance": {
        "calls": 1, "usd": 0.01, "input_tokens": 9, "output_tokens": 9, "cache_read_tokens": 0}}
    lines = orchestrator.cost_lines(run_)
    assert "apify     harshmaur/reddit-scraper" in lines[0] and "83%" in lines[0]   # biggest first
    assert "anthropic worker/record_relevance" in lines[1]


async def test_apify_switched_off_for_a_run_is_told_up_front_and_refused(offline, monkeypatch):
    ran = []
    monkeypatch.setattr(apify, "run_actor", lambda *a, **k: ran.append(a))
    run_id = await approved_run()
    state = orchestrator.loop_state(run_id, no_apify=True)
    assert "UNAVAILABLE this run" in loop.first_message(state.ctx, state.interp, state.plan)
    assert (await tools.search_reddit(state.ctx, "r/x", 10, "t"))["reason"] == tools.NO_APIFY_CREDIT
    assert ran == [] and state.ctx.calls == 0


async def test_a_lower_apify_cap_for_one_run(offline, monkeypatch):
    run_id = await approved_run()
    ctx = orchestrator.loop_state(run_id, apify_usd_cap=0.01).ctx
    out = await tools.search_reddit(ctx, "r/MealPrepSunday", 40, "too big for the cap")
    assert out["status"] == "limit_reached" and out["reason"].startswith("social-source budget")
    assert out["budget_left"]["apify_usd"] == 0.01


async def test_concurrent_apify_calls_are_recorded_once(offline, monkeypatch):
    async def paid_actor(spec, run_input, limit, timeout=None):
        await asyncio.sleep(0.05)                      # both calls are running at the same time
        items = json.loads(apify.fixture_path(spec["id"]).read_text())[:limit]
        return apify.ActorResult(spec["id"], items, 0.05, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", paid_actor)
    with_limits(monkeypatch, min_relevant=1)
    run_id = await approved_run()
    other = use("search_reddit", target="r/EatCheapAndHealthy", limit=10, reason="second sub")
    await run(run_id, scripted([[REDDIT, other], [COVERAGE], finish_all()]))
    run_ = db.get_run(run_id)
    assert round(run_.cost_apify_usd, 4) == 0.10                       # not 0.15
    assert round(sum(v["usd"] for v in run_.cost_breakdown["apify"].values()), 4) == 0.10


@pytest.mark.transcripts
@pytest.mark.parametrize("path", sorted(loop.TRANSCRIPT_DIR.glob("*.json")), ids=lambda p: p.stem)
async def test_recorded_transcripts_replay_in_fake_mode(offline, path):
    """Every saved real run replays against fixture tools without errors, and holds only tool calls."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert all(b["type"] == "tool_use" for t in data["turns"] for b in t["content"])
    run_id = await approved_run(data["brief"])
    db.update_run(run_id, mode="standard")             # recorded runs may be Standard
    out = await loop.run_loop(orchestrator.loop_state(run_id))
    assert out.finish_reason != FinishReason.error
    assert len(out.collection["decision_log"]) >= len(data["turns"])
