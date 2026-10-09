"""Collection tools (Step 1.6): contract tests on fixtures, limits, cache, coverage, finish.

USE_FIXTURES + LLM_FAKE: no network, no money.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ctxpack.collect import apify, tools, web
from ctxpack.collect.mappers import MAPPERS, sanitize_for_fixture
from ctxpack.collect.relevance import BriefContext
from ctxpack.config import get_settings

FIXTURES = Path(__file__).parent / "fixtures" / "tools"
NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("USE_FIXTURES", "true")
    monkeypatch.setenv("LLM_FAKE", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTHOR_HASH_SALT", "test-salt-not-a-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_ctx(mode="quick", topic="meal prep", languages=("en",), window_days=365):
    stored: list = []
    ctx = tools.RunContext(
        run_id="RUN-T", mode=mode, window_days=window_days,
        brief=BriefContext(topic=topic, market="NL", languages=list(languages),
                           research_questions={"RQ1": "Why do people meal prep?", "RQ2": "What snacks?"}),
        store=lambda docs, replaced: stored.extend(docs))
    return ctx, stored


def run(coro):
    return asyncio.run(coro)


SUMMARY_KEYS = {"status", "source_unit", "collected", "kept", "relevant", "undated", "relevant_share", "new_terms",
                "samples", "budget_left", "calls_left", "seconds_left"}


def check_contract(summary, stored):
    assert summary["status"] == "ok", summary
    assert SUMMARY_KEYS <= set(summary)
    assert summary["collected"] > 0 and summary["kept"] == len(stored)
    assert summary["undated"] == sum(d.posted_at is None for d in stored)
    assert len(summary["samples"]) <= 3
    for s in summary["samples"]:
        assert s.startswith("<untrusted_user_content") and len(s) < 300
    for d in stored:
        assert d.url and d.text
        assert d.author_hash is None or re.fullmatch(r"[0-9a-f]{64}", d.author_hash)
    dumped = json.dumps([d.model_dump(mode="json") for d in stored])
    assert not re.search(r"user_\d+", dumped), "a fixture pseudonym leaked into a document"


# --- one contract test per source ----------------------------------------

@pytest.mark.parametrize("tool, args", [
    ("search_reddit", {"target": "r/MealPrepSunday", "limit": 20, "reason": "test"}),
    ("search_tiktok", {"target": "#mealprep", "limit": 20, "reason": "test"}),
    ("search_youtube", {"query": "meal prep", "limit": 20, "reason": "test"}),
    ("search_instagram", {"hashtag": "mealprep", "limit": 20, "reason": "test"}),
])
def test_apify_tool_contract(offline, tool, args):
    ctx, stored = make_ctx()
    summary = run(tools.call_tool(ctx, tool, args))
    check_contract(summary, stored)
    assert ctx.calls == 1 and ctx.apify_usd == 0.0


def test_apify_posts_record_the_search_that_found_them(offline):
    ctx, stored = make_ctx()
    run(tools.search_reddit(ctx, "r/MealPrepSunday", 10, "test", query="budget"))
    assert stored and {d.found_by for d in stored} == {"r/MealPrepSunday budget"}


def test_chained_comments_are_collected(offline):
    ctx, stored = make_ctx()
    summary = run(tools.search_tiktok(ctx, "#mealprep", 20, "test"))
    assert summary["comments_actor"] == "clockworks/tiktok-comments-scraper"
    posts = json.loads(apify.fixture_path("clockworks/tiktok-scraper").read_text(encoding="utf-8"))
    assert summary["collected"] > len([p for p in posts if p.get("text")])   # comments came on top


def test_web_contract(offline):
    ctx, stored = make_ctx(topic="snacks na school", languages=("nl",))
    found = run(tools.web_search(ctx, "snacks", "NL", "nl", "test"))
    assert found["status"] == "ok" and all(p["page_type"] in ("forum", "qa", "review", "article")
                                           for p in found["pages"])
    summary = run(tools.fetch_and_segment(ctx, ["https://forum.example.nl/t/snacks"], "test"))
    check_contract(summary, stored)
    assert summary["pages"][0]["not_exact"] == 1          # the invented segment is thrown away
    assert len({d.author_hash for d in stored}) == 2       # two different authors
    assert set(ctx.page_queries.values()) == {"snacks"} and len(ctx.page_queries) == len(found["pages"])
    assert {d.found_by for d in stored} == {None}           # audit 3: fetched without a search -> none recorded
    texts = {d.text for d in stored}
    assert "Bij ons is het altijd een stroopwafel, de kinderen willen niks anders." in texts  # page spelling
    assert all(d.fragment_anchor_start for d in stored)


def test_trends(offline):
    ctx, _ = make_ctx()
    out = run(tools.get_trends(ctx, ["meal prep"], "NL", "test"))
    series = out["signal"]["series"]["meal prep"]
    assert out["status"] == "ok" and series["points"] >= 20 and series["trend"] in ("rising", "stable", "fading")
    assert out["actor"] == "apify/google-trends-scraper"
    assert ctx.external_signals


# --- limits ----------------------------------------------------------------

def test_second_identical_call_is_refused_and_cache_is_used(offline, monkeypatch):
    monkeypatch.setenv("USE_FIXTURES", "false")           # real mode: cache on
    get_settings.cache_clear()
    actor_calls = []

    async def fake_actor(spec, run_input, limit, timeout=None):
        actor_calls.append(spec["id"])
        items = json.loads(apify.fixture_path(spec["id"]).read_text(encoding="utf-8"))
        return apify.ActorResult(spec["id"], items[:limit], 0.01, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_actor)
    ctx, _ = make_ctx()
    first = run(tools.search_reddit(ctx, "r/MealPrepSunday", 20, "test"))
    assert first["cached"] is False
    assert run(tools.search_reddit(ctx, "r/MealPrepSunday", 20, "again"))["status"] == "duplicate_call"
    ctx2, stored2 = make_ctx()                              # a new run within 24 h: cache hit
    second = run(tools.search_reddit(ctx2, "r/MealPrepSunday", 20, "test"))
    assert second["cached"] is True and second["kept"] == first["kept"]
    assert actor_calls == ["harshmaur/reddit-scraper"]        # the actor ran once
    cache_files = list((get_settings().data_path / "cache").glob("*.json"))
    assert cache_files and "user_" not in cache_files[0].read_text()  # cached drafts hold hashes only


def test_call_limit(offline):
    ctx, _ = make_ctx()
    ctx.calls = ctx.limits["max_tool_calls"]
    out = run(tools.search_reddit(ctx, "r/MealPrepSunday", 20, "test"))
    assert out["status"] == "limit_reached" and "max_tool_calls" in out["reason"]


def test_time_limit(offline):
    ctx, _ = make_ctx()
    ctx.started -= ctx.limits["collection_secs"] + 1
    assert run(tools.search_youtube(ctx, "meal prep", 20, "x"))["status"] == "limit_reached"


def test_unit_share_and_items_per_call(offline):
    ctx, _ = make_ctx()
    lim = ctx.limits
    assert tools._item_limit(ctx, "reddit:r/x", 999)[0] == lim["items_per_call_max"]
    ctx.unit_items["reddit:r/x"] = int(lim["unit_share_max"] * lim["item_budget"])
    assert tools._item_limit(ctx, "reddit:r/x", 10) == (0, "unit share reached")
    ctx.items = lim["item_budget"]
    assert tools._item_limit(ctx, "reddit:r/y", 10) == (0, "item budget spent")


def test_apify_budget_uses_expected_cost(offline):
    ctx, _ = make_ctx()
    ctx.apify_usd = ctx.limits["apify_usd"] - 0.001
    out = run(tools.search_tiktok(ctx, "#mealprep", 20, "test"))
    assert out["status"] == "limit_reached" and "social-source budget" in out["reason"]


def test_dropped_unit_is_never_called_again(offline):
    ctx, _ = make_ctx()
    ctx.dropped_units.add("reddit:r/MealPrepSunday")
    assert run(tools.search_reddit(ctx, "r/MealPrepSunday", 20, "x"))["status"] == "unit_dropped"


def test_web_pages_are_never_fetched_twice(offline):
    ctx, _ = make_ctx(topic="snacks", languages=("nl",))
    url = "https://forum.example.nl/t/snacks"
    run(tools.fetch_and_segment(ctx, [url], "x"))
    assert run(tools.fetch_and_segment(ctx, [url], "x"))["status"] == "nothing_to_fetch"


# --- coverage and finish ---------------------------------------------------------

def test_finish_rules(offline):
    ctx, _ = make_ctx()
    run(tools.search_reddit(ctx, "r/MealPrepSunday", 20, "x"))
    refused = run(tools.finish(ctx, "done", [], []))
    assert refused["status"] == "refused" and len(refused["problems"]) >= 2
    cov = run(tools.coverage_report(ctx))
    assert "reddit:r/MealPrepSunday" in cov["source_units"] and "RQ1" in cov["research_questions"]
    no_reason = run(tools.finish(ctx, "done", [{"source_unit": "reddit:r/MealPrepSunday", "verdict": "kept",
                                                "reason": " "}], []))
    assert no_reason["status"] == "refused"
    ok = run(tools.finish(ctx, "done", [{"source_unit": "reddit:r/MealPrepSunday", "verdict": "dropped",
                                         "reason": "mostly US posts"}], ["no Dutch voices"]))
    assert ok["status"] == "ok" and "reddit:r/MealPrepSunday" in ctx.dropped_units


def test_tool_definitions_state_latency():
    defs = {d["name"]: d for d in tools.tool_definitions()}
    assert {"search_reddit", "web_search", "fetch_and_segment", "coverage_report", "finish"} <= set(defs)
    for name in ("search_reddit", "search_tiktok", "search_youtube", "web_search", "fetch_and_segment", "get_trends"):
        assert "usually" in defs[name]["description"]
        assert "reason" in defs[name]["input_schema"]["required"]


def test_unknown_tool_and_bad_args(offline):
    ctx, _ = make_ctx()
    assert run(tools.call_tool(ctx, "rm_rf", {}))["status"] == "error"
    assert run(tools.call_tool(ctx, "search_reddit", {"nope": 1}))["status"] == "error"


# --- actor runner ------------------------------------------------------------

def test_expected_cost_and_margin():
    spec = {"id": "x", "price_usd": {"result": 0.002, "init": 0.02}}
    assert apify.expected_cost(spec, 10) == pytest.approx((0.02 + 0.02) * 1.2)
    lite = {"id": "y", "price_usd": {"result": 0.004, "actor_start_per_gb": 0.02}, "memory_mbytes": 2048}
    assert apify.expected_cost(lite, 0) == pytest.approx(0.04 * 1.2)


def test_fallback_runs_when_actor_fails(monkeypatch):
    calls = []

    async def fake_run(spec, run_input, limit, timeout=None):
        calls.append(spec["id"])
        if spec["id"] == "a":
            return apify.ActorResult("a", [], 0.01, "FAILED")
        return apify.ActorResult("b", [{"x": 1}] * 15, 0.02, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    res = run(apify.run_with_fallback([({"id": "a"}, {}), ({"id": "b"}, {})], 10))
    assert calls == ["a", "b"] and res.used_fallback and res.usd == pytest.approx(0.03)


# --- privacy of fixtures (the repo is public) ---------------------------------------

def test_sanitize_for_fixture():
    raw = [{"dataType": "comment", "body": "mail me@x.com or ask @bob", "authorName": "RealPerson",
            "commentCreatedAt": "2026-09-01", "url": "https://reddit.com/r/x/1", "secretField": "drop me"}]
    out = sanitize_for_fixture("harshmaur/reddit-scraper", raw)
    assert out == [{"dataType": "comment", "body": "mail [email] or ask [user]", "commentCreatedAt": "2026-09-01",
                    "url": "https://reddit.com/r/x/1", "authorName": "user_1"}]


def test_committed_fixtures_hold_only_pseudonyms():
    for actor_id, (_, _, author_fields, _) in MAPPERS.items():
        path = apify.fixture_path(actor_id)
        if not path.exists():
            continue
        for item in json.loads(path.read_text(encoding="utf-8")):
            for f in author_fields:
                value = item
                for part in f.split("."):
                    value = value.get(part) if isinstance(value, dict) else None
                assert value is None or re.fullmatch(r"user_\d+", value), f"{path.name}: {f}={value!r}"
    pages = json.loads((FIXTURES / "web_pages.json").read_text(encoding="utf-8"))
    for page in pages.values():
        for seg in page["segments"]:
            assert seg["author"] is None or re.fullmatch(r"user_\d+", seg["author"])


# --- quote links (DH12) ----------------------------------------------------------

PAGE = ("Thread\nanna_k wrote:\nWe always eat stroopwafels after school, mail me at anna@x.nl if you want "
        "the recipe from my oma because it is really good.\nbart wrote:\nWe always eat apples.\n")


def test_anchors_are_unique_pii_free_and_from_original():
    original = web.locate("We always eat stroopwafels after school, mail me at anna@x.nl if you want the "
                          "recipe from my oma because it is really good.", PAGE)
    start, end = web.choose_anchors(original, PAGE, ["anna_k", "bart"], 4)
    assert start and end
    assert PAGE.count(start) == 1 and "@" not in start + end and "anna" not in (start + end).casefold()
    url = web.text_fragment_url("https://f.nl/t/1#top", start, end)
    assert url.startswith("https://f.nl/t/1#:~:text=") and "," in url.split("#:~:text=")[1]


def test_text_fragment_encoding():
    assert web.text_fragment_url("https://a.nl/x", "half-time, snack", None) == \
        "https://a.nl/x#:~:text=half%2Dtime%2C%20snack"


def test_locate_tolerates_whitespace_only():
    assert web.locate("a  b\nc", "x a b c y") == "a b c"
    assert web.locate("a b d", "x a b c y") is None


def test_fetched_text_parsing():
    ok = {"type": "web_fetch_tool_result", "content": {"type": "web_fetch_result", "url": "u",
          "content": {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "hi"}}}}
    err = {"type": "web_fetch_tool_result", "content": {"type": "web_fetch_tool_error", "error_code": "url_not_accessible"}}
    assert web._fetched_text([ok]) == ("hi", None)
    assert web._fetched_text([err]) == (None, "url_not_accessible")
    assert web._fetched_text([]) == (None, "no_fetch_result")


def test_trend_direction():
    assert tools.trend_direction([10, 10, 10, 20, 20, 20]) == "rising"
    assert tools.trend_direction([20, 20, 20, 10, 10, 10]) == "fading"
    assert tools.trend_direction([10, 11, 10, 10, 11, 10]) == "stable"


def test_fixture_mode_never_writes_the_cache(offline):
    ctx, _ = make_ctx()
    run(tools.search_reddit(ctx, "r/MealPrepSunday", 20, "x"))
    assert not (get_settings().data_path / "cache").exists()


def test_finish_is_refused_until_user_competitors_are_searched():
    """V3: competitors the user named are always searched; at the limits they become a gap instead."""
    import asyncio

    from ctxpack.collect import tools as t

    ctx = t.RunContext(run_id="r", mode="quick", brief=t.BriefContext(topic="x"), window_days=180,
                       store=None)
    ctx.must_search = ["HelloFresh"]
    ctx.coverage_after_last_collection = True
    out = asyncio.run(t.finish(ctx, "done", [], []))
    assert out["status"] == "refused" and "HelloFresh" in out["problems"][0]
    ctx.queries.append("hellofresh ervaringen")
    assert asyncio.run(t.finish(ctx, "done", [], []))["status"] == "ok"
    ctx2 = t.RunContext(run_id="r", mode="quick", brief=t.BriefContext(topic="x"), window_days=180, store=None)
    ctx2.must_search, ctx2.coverage_after_last_collection = ["Factor"], True
    ctx2.calls = ctx2.limits["max_tool_calls"]                        # no calls left: finish, with a gap
    assert asyncio.run(t.finish(ctx2, "done", [], []))["status"] == "ok"
    assert ctx2.finished["gaps"] == ["Not searched (limits reached): Factor, named by the user"]


def test_a_page_found_by_a_search_records_that_query(offline, monkeypatch):
    """Audit finding 3: web posts are stored by domain, so the search that found the page is recorded."""
    from ctxpack.collect.cleaning import make_draft

    ctx, stored = make_ctx(topic="snacks na school", languages=("nl",))
    found = run(tools.web_search(ctx, "snacks", "NL", "nl", "test"))
    url = found["pages"][0]["url"]

    async def fake_fetch(u, page_type, fetched_at):
        d = make_draft(platform=tools.Platform.web_forum, source_unit="web:x", url=u, text="Ik eet graag snacks na school",
                       author="a", date_raw="2026-09-01", fetched_at=fetched_at, salt="s")
        return web.PageResult(u, [d])

    monkeypatch.setattr(web, "fetch_and_segment", fake_fetch)
    run(tools.fetch_and_segment(ctx, [url], "test"))
    assert stored and {d.found_by for d in stored} == {"snacks"}
