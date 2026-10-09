"""Scraper audit fixes (2026-10-09): actor inputs that match the live input schemas, unreadable actor
output, Apify cost recording, web-search links and dates, failing sites, the cache. No network, no money."""

import asyncio
import os
import time
from types import SimpleNamespace

import pytest

from ctxpack.collect import apify, tools, web
from ctxpack.collect.relevance import BriefContext
from ctxpack.config import get_settings
from ctxpack.llm.client import CallResult


@pytest.fixture
def live(monkeypatch, tmp_path):
    """Real (non-fixture) mode with every network call mocked."""
    monkeypatch.setenv("USE_FIXTURES", "false")
    monkeypatch.setenv("LLM_FAKE", "false")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTHOR_HASH_SALT", "test-salt-not-a-secret")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def make_ctx(window_days=180):
    return tools.RunContext(run_id="RUN-A", mode="quick", window_days=window_days, store=lambda d, r: None,
                            brief=BriefContext(topic="meal prep", market="NL", languages=["en"],
                                               research_questions={"RQ1": "Why?"}))


def capture(monkeypatch, items=None):
    seen: dict = {}

    async def fake_run(spec, run_input, limit, timeout=None):
        seen[spec["id"]] = run_input
        return apify.ActorResult(spec["id"], list(items or []), 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    return seen


# --- 1. Google Trends: apify's actor has no 'today 12-m' -----------------------------------

def test_trends_12_months_is_the_empty_value_for_apify(live, monkeypatch):
    seen = capture(monkeypatch)
    asyncio.run(tools.get_trends(make_ctx(180), ["meal prep"], "NL", "test"))
    assert seen["apify/google-trends-scraper"]["timeRange"] == ""           # = past 12 months
    assert seen["scrapesage/google-trends-scraper"]["timeRange"] == "today 12-m"
    seen.clear()
    asyncio.run(tools.get_trends(make_ctx(90), ["meal prep"], "DE", "test"))
    assert seen["apify/google-trends-scraper"]["timeRange"] == "today 3-m"


# --- 2. Reddit searches keep relevance ------------------------------------------------------

def test_reddit_wide_search_keeps_relevance_and_subreddits_keep_the_date(live, monkeypatch):
    seen = capture(monkeypatch)
    asyncio.run(tools.search_reddit(make_ctx(180), "meal prep cost", 20, "test"))
    search = seen["harshmaur/reddit-scraper"]
    assert search["searchSort"] == "relevance" and search["searchTime"] == "year" and "postedAfter" not in search
    asyncio.run(tools.search_reddit(make_ctx(180), "r/MealPrepSunday", 20, "test", query="budget"))
    inside = seen["harshmaur/reddit-scraper"]
    assert inside["withinCommunity"] == "MealPrepSunday" and inside["postedAfter"] == tools._cutoff(make_ctx(180))
    assert "searchTime" not in inside                                       # inside a subreddit: newest-first
    asyncio.run(tools.search_reddit(make_ctx(30), "r/EatCheapAndHealthy", 20, "test"))
    assert "postedAfter" in seen["harshmaur/reddit-scraper"]                # browsing is newest-first anyway
    assert [tools.reddit_search_time(d) for d in (7, 30, 90, 365, 400)] == ["week", "month", "year", "year", "all"]


# --- 3. Output we cannot read counts as a failure -------------------------------------------

def test_unreadable_output_runs_the_fallback_and_is_a_blind_spot(live, monkeypatch):
    ids = []

    async def fake_run(spec, run_input, limit, timeout=None):
        ids.append(spec["id"])
        return apify.ActorResult(spec["id"], [{"renamedField": "a post"}] * 3, 0.01, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    ctx = make_ctx()
    out = asyncio.run(tools.search_reddit(ctx, "meal prep cost", 20, "test"))
    assert ids == ["harshmaur/reddit-scraper", "fatihtahta/reddit-scraper-search-fast"]
    assert out["actor_status"] == apify.UNREADABLE and "source_problem" in out
    assert ctx.source_failures and ctx.apify_usd == pytest.approx(0.02)    # both runs are still paid for


# --- 4 + 5. Apify cost: counted when items cannot be read; no margin on what came back -------

class _FakeClient:
    def __init__(self, fail_items=False, usage=0.0):
        self.fail_items, self.usage = fail_items, usage

    def actor(self, actor_id):
        async def call(**kwargs):
            return {"id": "run1", "defaultDatasetId": "ds1", "status": "SUCCEEDED", "usageTotalUsd": self.usage}
        return SimpleNamespace(call=call)

    def dataset(self, dataset_id):
        async def list_items(limit):
            if self.fail_items:
                raise ConnectionError("network down")
            return SimpleNamespace(items=[{"n": i} for i in range(10)])
        return SimpleNamespace(list_items=list_items)

    def run(self, run_id):
        async def get():
            return {"id": run_id, "usageTotalUsd": self.usage}
        return SimpleNamespace(get=get)


SPEC = {"id": "x/y", "price_usd": {"result": 0.002, "init": 0.02}}


def test_items_read_failure_still_counts_the_cost(live, monkeypatch):
    import apify_client
    monkeypatch.setattr(apify_client, "ApifyClientAsync", lambda token: _FakeClient(fail_items=True))
    res = asyncio.run(apify.run_actor(SPEC, {}, 10))
    assert res.status == "ERROR" and not res.items and "reading items failed" in res.error
    assert res.usd == pytest.approx(0.02 + 0.002 * 10)                     # the whole limit, no margin


def test_recorded_cost_has_no_margin(live, monkeypatch):
    import apify_client
    monkeypatch.setattr(apify_client, "ApifyClientAsync", lambda token: _FakeClient(usage=0.0))
    res = asyncio.run(apify.run_actor(SPEC, {}, 10))
    assert len(res.items) == 10 and res.usd == pytest.approx(0.04)          # not 0.048
    monkeypatch.setattr(apify_client, "ApifyClientAsync", lambda token: _FakeClient(usage=0.05))
    assert asyncio.run(apify.run_actor(SPEC, {}, 10)).usd == pytest.approx(0.05)   # settled cost wins


# --- 6 + 7. Web search: only links a search returned; dates shown -----------------------------

def _search_block(*results):
    return {"type": "web_search_tool_result", "tool_use_id": "s1",
            "content": [{"type": "web_search_result", "url": u, "title": "t", "page_age": age} for u, age in results]}


def test_discover_drops_links_no_search_returned(live, monkeypatch):
    async def fake_structured(*args, **kwargs):
        data = web.Discovery(pages=[
            web.FoundPage(url="https://forum.nl/t/1/", page_type="forum", language="nl", why="real"),
            web.FoundPage(url="https://made-up.nl/t/9", page_type="forum", language="nl", why="invented"),
            web.FoundPage(url="http://www.reviews.nl/p#top", page_type="review", language="nl", why="real",
                          estimated_date="2026-09-01")])
        return CallResult(data=data, usd=0.01, web_searches=1,
                          blocks=[_search_block(("https://www.forum.nl/t/1", "March 3, 2026"),
                                                ("https://reviews.nl/p", None))])

    monkeypatch.setattr(web, "structured", fake_structured)
    res = asyncio.run(web.discover("snacks", "NL", "nl"))
    assert [p.url for p in res.pages] == ["https://forum.nl/t/1/", "http://www.reviews.nl/p#top"]
    assert res.unlisted == 1
    assert res.pages[0].estimated_date == "March 3, 2026"                   # page_age fills a missing date
    assert res.pages[1].estimated_date == "2026-09-01"                      # the model's own date is kept


def test_web_search_summary_shows_dates_and_the_cutoff(live, monkeypatch):
    async def fake_discover(query, country, language, blocked=None):
        return web.DiscoverResult([web.FoundPage(url="https://f.nl/t/1", page_type="forum", language="nl",
                                                 why="x", estimated_date="2015-04-01")], unlisted=2)

    monkeypatch.setattr(web, "discover", fake_discover)
    out = asyncio.run(tools.web_search(make_ctx(180), "snacks forum", "NL", "nl", "find forums"))
    assert out["pages"][0]["estimated_date"] == "2015-04-01"
    assert out["oldest_wanted"] == tools._cutoff(make_ctx(180)) and out["unlisted_pages_dropped"] == 2


# --- 8. Sites that keep failing are skipped for the rest of the run ---------------------------

def test_a_site_failing_twice_is_skipped_for_the_run_only(live, monkeypatch):
    fetched = []

    async def fake_fetch(url, page_type, fetched_at):
        fetched.append(url)
        if "walled" in url:
            return web.PageResult(url, error="url_not_accessible")
        return web.PageResult(url)                                          # JavaScript page: no posts

    monkeypatch.setattr(web, "fetch_and_segment", fake_fetch)
    ctx = make_ctx()
    first = asyncio.run(tools.fetch_and_segment(ctx, ["https://walled.nl/t/1", "https://js.nl/t/1"], "x"))
    assert "blocked_sites" not in first                                    # one failure each: still allowed
    second = asyncio.run(tools.fetch_and_segment(ctx, ["https://walled.nl/t/2", "https://js.nl/t/2"], "x"))
    assert second["blocked_sites"] == ["js.nl", "walled.nl"]
    third = asyncio.run(tools.fetch_and_segment(ctx, ["https://walled.nl/t/3"], "x"))
    assert third["status"] == "nothing_to_fetch" and len(fetched) == 4
    assert web.blocked_sites() == {}                                       # never remembered across runs


# --- the cache ---------------------------------------------------------------------------------

def test_cache_is_per_window_and_old_files_are_deleted(live, monkeypatch):
    seen = capture(monkeypatch)
    asyncio.run(tools.search_reddit(make_ctx(30), "meal prep cost", 20, "test"))
    seen.clear()
    asyncio.run(tools.search_reddit(make_ctx(365), "meal prep cost", 20, "test"))
    assert "harshmaur/reddit-scraper" in seen                              # another window: not the cache
    folder = live / "cache"
    old = folder / "old.json"
    old.write_text("{}")
    past = time.time() - 25 * 3600
    os.utime(old, (past, past))
    assert apify.purge_cache(folder) == 1 and not old.exists() and list(folder.glob("*.json"))


# --- local results: TikTok and YouTube search in the brief's country (2026-10-09) -----------------

def local_ctx(countries=("NL",), languages=("nl", "en")):
    ctx = make_ctx()
    ctx.brief.countries, ctx.brief.languages = list(countries), list(languages)
    return ctx


def test_tiktok_searches_as_in_the_country(live, monkeypatch):
    seen = capture(monkeypatch)
    asyncio.run(tools.search_tiktok(local_ctx(), "#snacks", 20, "test"))
    assert seen["clockworks/tiktok-scraper"]["proxyCountryCode"] == "NL"
    assert seen["novi/fast-tiktok-api"]["region"] == "NL"                   # never its GB default
    seen.clear()
    asyncio.run(tools.search_tiktok(local_ctx(("DE", "AT", "CH"), ("de",)), "#snacks", 20, "test"))
    assert "proxyCountryCode" not in seen["clockworks/tiktok-scraper"]      # several countries: worldwide
    assert seen["novi/fast-tiktok-api"]["region"] == "DE"


def test_youtube_non_english_single_country_tries_the_local_actor_first(live, monkeypatch):
    ids, seen = [], {}

    async def fake_run(spec, run_input, limit, timeout=None):
        ids.append(spec["id"])
        seen[spec["id"]] = run_input
        return apify.ActorResult(spec["id"], [], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    asyncio.run(tools.search_youtube(local_ctx(), "gezonde snacks", 20, "test"))
    assert ids == ["grow_media/youtube-search-api", "streamers/youtube-scraper"]
    assert seen["grow_media/youtube-search-api"]["regionCode"] == "NL"
    assert seen["grow_media/youtube-search-api"]["relevanceLanguage"] == "nl"
    ids.clear()
    asyncio.run(tools.search_youtube(local_ctx(("US",), ("en",)), "healthy snacks", 20, "test"))
    assert ids == ["streamers/youtube-scraper", "grow_media/youtube-search-api"]    # English: order unchanged
    ids.clear()
    asyncio.run(tools.search_youtube(local_ctx(), "@somechannel", 20, "test"))
    assert ids == ["streamers/youtube-scraper"]                             # channels: primary only


def test_country_add_on_is_counted_only_when_sent():
    spec = {"id": "t", "price_usd": {"result": 0.0037}, "addons_per_item": {"proxyCountryCode": 0.0013}}
    assert apify.expected_cost(spec, 10, False, {"searchQueries": ["x"]}) == pytest.approx(0.037)
    assert apify.expected_cost(spec, 10, False, {"proxyCountryCode": "NL"}) == pytest.approx(0.05)
    assert apify.expected_cost(spec, 10, False) == pytest.approx(0.05)     # budget check: assume it is used


# --- source-selection audit (2026-10-09) ------------------------------------------------------

def test_one_failing_page_never_loses_the_others(live, monkeypatch):
    from ctxpack.llm.client import LLMError

    async def fake_fetch(url, page_type, fetched_at):
        if "huge" in url:
            raise LLMError("record_segments: no valid answer after one retry")
        return web.PageResult(url, error="url_not_accessible")

    monkeypatch.setattr(web, "fetch_and_segment", fake_fetch)
    ctx = make_ctx()
    out = asyncio.run(tools.fetch_and_segment(ctx, ["https://forum.de/huge", "https://other.de/t/1"], "x"))
    assert out["status"] == "ok"
    assert {p["url"]: p.get("error") for p in out["pages"]} == {
        "https://forum.de/huge": web.SEGMENT_FAILED, "https://other.de/t/1": "url_not_accessible"}


def test_budget_stop_still_stops_a_page_batch(live, monkeypatch):
    from ctxpack.guards import BudgetExceeded

    async def fake_fetch(url, page_type, fetched_at):
        raise BudgetExceeded("run budget")

    monkeypatch.setattr(web, "fetch_and_segment", fake_fetch)
    with pytest.raises(BudgetExceeded):
        asyncio.run(tools.fetch_and_segment(make_ctx(), ["https://forum.de/t/1"], "x"))


def test_platforms_with_their_own_tool_are_never_web_searched_or_read(live, monkeypatch):
    seen = {}

    async def fake_discover(query, country, language, blocked=None):
        seen["blocked"] = blocked
        return web.DiscoverResult([web.FoundPage(url="https://old.reddit.com/r/x/1", page_type="forum",
                                                 language="en", why="x"),
                                   web.FoundPage(url="https://forum.nl/t/1", page_type="forum", language="nl",
                                                 why="y")])

    monkeypatch.setattr(web, "discover", fake_discover)
    out = asyncio.run(tools.web_search(make_ctx(), "snacks reddit", "NL", "nl", "x"))
    assert {"reddit.com", "quora.com", "tiktok.com"} <= set(seen["blocked"])
    assert [p["url"] for p in out["pages"]] == ["https://forum.nl/t/1"] and out["blocked_sites_hidden"] == 1
    fetched = []

    async def fake_fetch(url, page_type, fetched_at):
        fetched.append(url)
        return web.PageResult(url)

    monkeypatch.setattr(web, "fetch_and_segment", fake_fetch)
    ctx = make_ctx()
    res = asyncio.run(tools.fetch_and_segment(ctx, ["https://www.reddit.com/r/x/1", "https://quora.com/q"], "x"))
    assert res["status"] == "nothing_to_fetch" and not fetched and ctx.calls == 0
    assert res["not_read_here"] == {"https://www.reddit.com/r/x/1": "use search_reddit",
                                    "https://quora.com/q": "nothing (login wall, JavaScript)"}


def test_probe_per_search_with_trusted_platforms_and_proven_searches(live, monkeypatch):
    from collections import Counter
    from ctxpack.schemas.enums import Platform

    sizes = []

    async def fake_run(spec, run_input, limit, timeout=None):
        sizes.append(limit)
        return apify.ActorResult(spec["id"], [], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    ctx = make_ctx()
    ctx.mode = "standard"
    probe = tools._modes()["collection"]["probe_items"]
    out = asyncio.run(tools.search_tiktok(ctx, "snack review", 80, "test"))
    assert "first tiktok search" in out["limited"] and sizes[-1] <= probe
    # a good TikTok query (79%) does NOT let a new hashtag in at full size (NL rerun: #snacktip 60 posts, 16%)
    ctx.unit_stats["tiktok:search:snack review"], ctx.unit_platform["tiktok:search:snack review"] = \
        Counter(kept=19, relevant=15), Platform.tiktok
    assert "new tiktok search" in asyncio.run(tools.search_tiktok(ctx, "#snacktip", 80, "test"))["limited"]
    # ... but repeating the proven search gets full size
    assert "limited" not in asyncio.run(tools.search_tiktok(ctx, "snack review", 80, "again, bigger"))
    # two searches averaging at least the trusted share let new searches start at full size
    ctx.unit_stats["tiktok:search:snack proeven"], ctx.unit_platform["tiktok:search:snack proeven"] = \
        Counter(kept=20, relevant=16), Platform.tiktok
    assert "limited" not in asyncio.run(tools.search_tiktok(ctx, "nieuwe snacks", 80, "test"))
    # a search that proved poor stays small; a blind subreddit browse is always small
    ctx.unit_stats["tiktok:#snacktip"], ctx.unit_platform["tiktok:#snacktip"] = Counter(kept=20, relevant=3), \
        Platform.tiktok
    assert "15% relevant" in asyncio.run(tools.search_tiktok(ctx, "#snacktip", 60, "retry"))["limited"]
    assert "without a query" in asyncio.run(tools.search_reddit(ctx, "r/de", 80, "test"))["limited"]


def test_a_search_that_finds_nothing_is_not_a_blind_spot(live, monkeypatch):
    async def placeholder(spec, run_input, limit, timeout=None):        # one "no results" row each
        return apify.ActorResult(spec["id"], [{"message": "no results"}], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", placeholder)
    ctx = make_ctx()
    out = asyncio.run(tools.search_youtube(ctx, "lidl aldi jumbo huismerk", 20, "x"))
    assert out["actor_status"] == apify.NO_RESULTS and "no_results" in out and "source_problem" not in out
    assert ctx.source_failures == []

    async def broken(spec, run_input, limit, timeout=None):
        return apify.ActorResult(spec["id"], [], 0.0, "FAILED", error="boom")

    monkeypatch.setattr(apify, "run_actor", broken)
    out = asyncio.run(tools.search_youtube(ctx, "something else", 20, "x"))
    assert "source_problem" in out and ctx.source_failures                  # a real failure still is one

def test_top_up_gets_its_own_time_after_the_agent_used_all_of_it(live, monkeypatch):
    from types import SimpleNamespace
    from ctxpack.collect import fallback

    ctx = make_ctx()
    ctx.started -= ctx.limits["collection_secs"] + 5                        # the agent used all its time
    seen = {}

    async def fake_top_up(state):
        seen["seconds_left"] = state.ctx.seconds_left()
        return True

    monkeypatch.setattr(fallback, "_top_up", fake_top_up)
    assert asyncio.run(fallback.top_up(SimpleNamespace(ctx=ctx)))
    assert seen["seconds_left"] > 60 and ctx.extra_secs == 0                # grace during the top-up only


# --- rerun findings (2026-10-09) ---------------------------------------------------------------

def test_invalid_subreddit_names_are_refused_with_a_reason(live, monkeypatch):
    seen = capture(monkeypatch)
    ctx = make_ctx()
    out = asyncio.run(tools.search_reddit(ctx, "r/wärmepumpe", 20, "x", query="kosten"))
    assert out["status"] == "refused" and "r/waermepumpe" in out["error"] and ctx.calls == 0 and not seen
    ok = asyncio.run(tools.search_reddit(ctx, "r/de", 20, "x", query="wärmepumpe"))
    assert ok["status"] == "ok" and seen["harshmaur/reddit-scraper"]["withinCommunity"] == "de"


def test_a_query_with_a_reddit_wide_target_is_never_dropped(live, monkeypatch):
    seen = capture(monkeypatch)
    asyncio.run(tools.search_reddit(make_ctx(), "wärmepumpe", 20, "x", query="altbau kosten"))
    assert seen["harshmaur/reddit-scraper"]["searchTerms"] == ["wärmepumpe altbau kosten"]


def test_empty_what_performs_says_why_when_posts_were_found():
    from ctxpack.synthesis import finalize
    pack = {"landscape": {"themes": [], "platform_lens": []}, "pain_points": [], "tensions": [], "motivations": [],
            "objections": [], "segments": [], "opportunities": [], "what_performs": [], "moments": [], "culture": {}}
    found = finalize.sections_meta(pack, {}, set(), None, {"what_performs": [{"doc_id": "D1"}]})["what_performs"]
    assert "none of them" in found["empty_reason"]
    none = finalize.sections_meta(pack, {}, set(), None, {"what_performs": []})["what_performs"]
    assert "no engagement numbers" in none["empty_reason"]


def test_top_posts_the_writer_skipped_get_one_small_follow_up(monkeypatch):
    from types import SimpleNamespace
    from ctxpack.synthesis import write as W
    from ctxpack.llm.client import CallResult

    docs = {f"D{i}": SimpleNamespace(id=f"D{i}", platform="facebook", language="de", text=f"Post {i} über Kosten",
                                     extraction={}) for i in range(1, 4)}
    pool = W.Pool(local={"E01": "D1", "E02": "D2", "E03": "D3"}, clusters_of={"D1": [], "D2": [], "D3": []})
    b = W.AnswerB(what_performs=[W.PerformOut(evidence="E01", format="question", why_it_worked="asks")])
    calls = []

    async def fake_structured(role, system, user, schema, tool, **kw):
        calls.append(user)
        return CallResult(data=schema.model_validate(W._fake_perform(user)), usd=0.02)

    monkeypatch.setattr(W, "structured", fake_structured)
    outcome = W.WriteOutcome()
    ctx = BriefContext(topic="Wärmepumpe", market="DE", languages=["de"])
    asyncio.run(W.describe_missing_performers(ctx, b, pool, ["D1", "D2", "D3"], docs,
                                              {"evidence_chars": 280, "perform_max_tokens": 3000}, outcome))
    assert len(calls) == 1 and "E01" not in calls[0] and "E02" in calls[0] and "E03" in calls[0]
    assert sorted(o.evidence for o in b.what_performs) == ["E01", "E02", "E03"] and outcome.calls == 1
    asyncio.run(W.describe_missing_performers(ctx, b, pool, ["D1", "D2", "D3"], docs,
                                              {"evidence_chars": 280, "perform_max_tokens": 3000}, outcome))
    assert len(calls) == 1                                                  # nothing missing: no call


def test_what_performs_comes_early_in_the_writer_answer():
    from ctxpack.synthesis import write as W
    fields = list(W.AnswerB.model_fields)
    assert fields.index("what_performs") < fields.index("motivations")


def test_top_up_tries_new_material_first_and_fuller_pages_only_for_strong_searches(monkeypatch):
    from collections import Counter
    from types import SimpleNamespace
    from ctxpack.collect import fallback

    ctx = make_ctx()
    ctx.limits  # noqa: B018 - quick mode limits
    ctx.unit_stats = {"youtube:search:strong": Counter(kept=20, relevant=18),
                      "youtube:search:weak": Counter(kept=20, relevant=8)}
    ctx.finished = {"follow_up_queries": [{"source_unit": "youtube:search:weak", "query": "sharper words"}]}
    state = SimpleNamespace(ctx=ctx, interp=None)
    monkeypatch.setattr(fallback, "_kept_units", lambda st: ["youtube:search:weak", "youtube:search:strong"])
    monkeypatch.setattr(fallback, "_last_call_for", lambda st, unit: (
        "search_youtube", {"query": unit.rsplit(":", 1)[1], "limit": 20, "reason": "x"}))
    calls = list(fallback._candidates(state))
    assert calls[0] == ("search_youtube", {"query": "sharper words",
                                           "reason": "top-up: follow-up proposed for youtube:search:weak"})
    fuller = [c for c in calls if c[1]["reason"].startswith("top-up: fuller page")]
    assert [c[1]["query"] for c in fuller] == ["strong"]                     # 90% yes, 40% no


def test_web_search_hints_a_retry_when_no_recent_voice_page_is_found(live, monkeypatch):
    def found(*pages):
        async def fake_discover(query, country, language, blocked=None):
            return web.DiscoverResult([web.FoundPage(url=u, page_type=t, language="nl", why="x", estimated_date=d)
                                       for u, t, d in pages])
        monkeypatch.setattr(web, "discover", fake_discover)

    ctx = make_ctx(180)
    found(("https://radar.nl/forum/t/1", "forum", "2011"), ("https://blog.nl/a", "article", "2026-09-01"))
    assert "hint" in asyncio.run(tools.web_search(ctx, "gezonde snack forum", "NL", "nl", "x"))
    found(("https://forum.fok.nl/topic/1", "forum", "2026"))                # a year-only date this year: recent enough
    assert "hint" not in asyncio.run(tools.web_search(ctx, "snacks fok", "NL", "nl", "x"))
    found(("https://forum.nl/t/9", "forum", None))                         # no date known: worth reading
    assert "hint" not in asyncio.run(tools.web_search(ctx, "snacks forum", "NL", "nl", "x"))


def test_standard_probes_with_more_items_than_quick(live, monkeypatch):
    capture(monkeypatch)
    quick, std = make_ctx(), make_ctx()
    std.mode = "standard"
    assert tools._probe_limit(quick, tools.Platform.tiktok, "tiktok:search:x", 80)[0] == quick.limits["probe_items"]
    assert tools._probe_limit(std, tools.Platform.tiktok, "tiktok:search:x", 80)[0] == std.limits["probe_items"]
    assert std.limits["probe_items"] > quick.limits["probe_items"]


def test_a_failed_web_search_is_an_error_with_advice(live, monkeypatch):
    from ctxpack.llm.client import LLMError

    async def failing(query, country, language, blocked=None):
        raise LLMError("record_pages: no valid answer after one retry")

    monkeypatch.setattr(web, "discover", failing)
    out = asyncio.run(tools.web_search(make_ctx(), "site:tweakers.net snacks", "NL", "nl", "x"))
    assert out["status"] == "error" and "try once more" in out["error"]


def test_discovery_keeps_pages_when_no_result_blocks_are_visible(live, monkeypatch):
    async def fake_structured(*args, **kwargs):            # dynamic filtering: results not in result blocks
        return CallResult(data=web.Discovery(pages=[web.FoundPage(url="https://forum.nl/t/1", page_type="forum",
                                                                  language="nl", why="x")]), web_searches=1)

    monkeypatch.setattr(web, "structured", fake_structured)
    res = asyncio.run(web.discover("snacks", "NL", "nl"))
    assert [p.url for p in res.pages] == ["https://forum.nl/t/1"] and res.unlisted == 0


def test_english_voices_missing_only_when_english_is_a_market_language():
    from types import SimpleNamespace
    from ctxpack.synthesis.finalize import missing_languages

    de = SimpleNamespace(languages=["de", "en"], markets=[{"code": "DE", "countries": ["DE"], "weight": 1.0}])
    assert missing_languages(de, ["de"]) == []                              # English was only the second language
    assert missing_languages(de, ["en"]) == ["de"]                          # the market language is still a gap
    uk = SimpleNamespace(languages=["en"], markets=[{"code": "GB", "countries": ["GB"], "weight": 1.0}])
    assert missing_languages(uk, []) == ["en"]
    world = SimpleNamespace(languages=["en"], markets=[{"code": "global", "countries": [], "weight": 1.0}])
    assert missing_languages(world, []) == ["en"]


def test_featured_cards_build_for_every_featured_pack():
    """2026-10-09: post briefs carry a bare confidence label; the card code expected a dict and the live
    /api/v1/packs returned 500 for the new featured packs."""
    import glob
    import json as _json
    from pathlib import Path
    from ctxpack.api.service import featured_card

    files = glob.glob(str(Path(__file__).parents[2] / "featured" / "pk_*.json"))
    assert files
    for f in files:
        card = featured_card(_json.loads(Path(f).read_text(encoding="utf-8")))
        assert card["relevant_posts"] > 0 and card["strong_findings"] >= 0
