"""X (Twitter) as a source and the 2026-10-07 fallback actors - fixture contract, privacy, refusals. No money."""

import json
import re

import pytest

from ctxpack.collect import apify, tools
from ctxpack.collect.cleaning import scrub_url
from ctxpack.collect.fallback import _follow_up_call, starting_call
from ctxpack.collect.mappers import MAPPERS, map_items
from ctxpack.config import load_yaml
from ctxpack.schemas.plan import StartingSourceUnit
from ctxpack.synthesis import finalize
from tests.test_tools import check_contract, make_ctx, offline, run  # noqa: F401  (fixture)

POST = "xquik/x-tweet-scraper"


def test_tool_contract_on_its_fixture(offline):  # noqa: F811
    ctx, stored = make_ctx(topic="meal prep")
    summary = run(tools.call_tool(ctx, "search_x", {"target": "meal prep", "limit": 20, "reason": "test"}))
    check_contract(summary, stored)
    assert summary["source_unit"] == "x:search:meal prep" and summary["actor"] == POST
    for d in stored:
        assert str(d.platform) == "x"
        assert re.fullmatch(r"https://x\.com/i/status/\d+", d.url)
    dumped = json.dumps([d.model_dump(mode="json") for d in stored])
    assert not re.search(r"x\.com/(?!i/)\w+/status", dumped)                   # no handles inside links


@pytest.mark.parametrize("target", ["@someone", "https://x.com/someone", "from:someone meal prep",
                                    "x.com/i/lists/123", "to:brand", " "])
def test_people_and_accounts_are_refused(offline, target):  # noqa: F811
    ctx, stored = make_ctx()
    out = run(tools.search_x(ctx, target, 10, "test"))
    assert out["status"] == "refused" and ctx.calls == 0 and not stored


def test_links_are_rebuilt_without_the_handle():
    assert scrub_url("https://x.com/jane_doe/status/2107863794978304023?s=20") == \
        "https://x.com/i/status/2107863794978304023"
    assert scrub_url("https://twitter.com/jane/status/123456789") == "https://x.com/i/status/123456789"
    item = {"id": "2107863794978304023", "text": "Meal prep sundays save my whole week honestly",
            "createdAt": "Wed Oct 07 16:01:05 +0000 2026", "author": {"username": "jane_doe"},
            "likeCount": 3, "replyCount": 2, "url": "https://x.com/jane_doe/status/2107863794978304023"}
    (p,) = map_items(POST, [item])
    assert p["url"] == "https://x.com/i/status/2107863794978304023" and p["comments"] == 2
    assert p["date"].startswith("2026-10-07T16:01:05")                          # X's own date format parsed
    assert not map_items(POST, [{**item, "isRetweet": True}])                   # reposts are not their words


def test_replies_are_chained_on_posts_that_have_some(offline, monkeypatch):  # noqa: F811
    seen = []

    async def fake_run(spec, run_input, limit, timeout=None):
        seen.append((spec["id"], run_input))
        if "replyTweetIds" not in run_input:
            return apify.ActorResult(POST, [{"id": "2107758993389302137", "text": "Meal prep is a scam when "
                                             "the containers cost more than the food", "replyCount": 4,
                                             "createdAt": "Wed Oct 07 08:00:00 +0000 2026",
                                             "author": {"username": "user_1"}}], 0.0, "SUCCEEDED")
        return apify.ActorResult(POST, [{"id": "2107841644863148363", "rootTweetId": "2107758993389302137",
                                         "text": "Glass containers paid for themselves in two months for me",
                                         "createdAt": "Wed Oct 07 14:33:04 +0000 2026",
                                         "author": {"username": "user_2"}}], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    ctx, stored = make_ctx(topic="meal prep containers")
    out = run(tools.search_x(ctx, "meal prep containers", 10, "test"))
    assert out["comments_actor"] == POST and out["collected"] == 2
    assert seen[0][1]["since"] and seen[0][1]["queryType"] == "Top"
    assert seen[1][1]["mode"] == "replies" and seen[1][1]["replyTweetIds"] == ["2107758993389302137"]
    comment = next(d for d in stored if d.permalink)
    assert comment.permalink == "https://x.com/i/status/2107841644863148363"


def test_a_plan_unit_and_a_follow_up_route_to_search_x():
    unit = StartingSourceUnit(platform="x", kind="hashtag", target="#mealprep", reason="Fans post their weekly prep.")
    tool, args, source_unit = starting_call(unit, None)                       # x needs no market or language
    assert tool == "search_x" and args["target"] == "#mealprep" and source_unit == "x:#mealprep"
    assert _follow_up_call("x:#mealprep", "meal prep containers", None) == \
        ("search_x", {"target": "meal prep containers", "reason": "top-up: follow-up proposed for x:#mealprep"})


def test_x_is_named_when_it_fails():
    assert finalize._PLATFORM_NAME["x"] == "X" and "x" in finalize._FAILED_IMPACT


# --- 2026-10-07 fallbacks: each one reads its own (sanitised, recorded) output ---------------------

FALLBACKS = {
    "fatihtahta/reddit-scraper-search-fast": {"post", "comment"},
    "novi/fast-tiktok-api": {"post"},
    "scrapeforge/tiktok-comments-extractor": {"comment"},
    "grow_media/youtube-search-api": {"post"},
    "solidcode/youtube-comments-scraper": {"comment"},
    "scraping_solutions/instagram-hashtag-scraper-pro-no-cookies": {"post"},
    "supreme_coder/instagram-comments-scraper": {"comment"},
    "datadoping/linkedin-post-comments-scraper": {"comment"},
    "scraper_one/x-posts-search": {"post"},
    "scraper_one/x-post-replies-scraper": {"comment"},
}


@pytest.mark.parametrize("actor", sorted(FALLBACKS))
def test_each_new_actor_maps_its_recorded_output(actor):
    items = json.loads(apify.fixture_path(actor).read_text(encoding="utf-8"))
    posts = map_items(actor, items)
    assert posts and {p["kind"] for p in posts} == FALLBACKS[actor]
    for p in posts:
        assert p["text"] and p["date"] and p["url"].startswith("https://")
        assert re.fullmatch(r"user_\d+", p["author"] or "user_0")                 # fixtures hold no real names
        assert "/@" not in p["url"].replace("/@/", "") and "linkedin.com/in/" not in json.dumps(p)


def test_every_catalogued_actor_has_a_mapper_or_is_trends():
    for name, src in load_yaml("catalog")["sources"].items():
        if src["kind"] != "apify" or name == "google_trends":
            continue
        comments = src.get("comments") or {}
        for spec in (src["actor"], src.get("fallback"), comments.get("actor"), comments.get("fallback")):
            if spec:
                assert spec["id"] in MAPPERS, spec["id"]


def test_reddit_fallback_engagement_is_unknown_not_zero():
    items = json.loads(apify.fixture_path("fatihtahta/reddit-scraper-search-fast").read_text(encoding="utf-8"))
    assert all(p["engagement"] == {} for p in map_items("fatihtahta/reddit-scraper-search-fast", items))


def test_youtube_channel_units_skip_the_search_only_fallback(offline, monkeypatch):  # noqa: F811
    ids = []

    async def fake_run(spec, run_input, limit, timeout=None):
        ids.append(spec["id"])
        return apify.ActorResult(spec["id"], [], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    ctx, _ = make_ctx()
    run(tools.search_youtube(ctx, "@somechannel", 10, "test"))
    assert ids == ["streamers/youtube-scraper"]                                # grow_media is never sent a channel
    run(tools.search_youtube(ctx, "meal prep", 10, "test"))
    assert ids[1:] == ["streamers/youtube-scraper", "grow_media/youtube-search-api"]


def test_comment_fallbacks_get_a_cap_and_no_replies(offline, monkeypatch):  # noqa: F811
    seen = {}

    async def fake_run(spec, run_input, limit, timeout=None):
        seen[spec["id"]] = run_input
        if spec["id"] == "clockworks/tiktok-scraper":
            return apify.ActorResult(spec["id"], [{"webVideoUrl": "https://www.tiktok.com/@/video/1", "id": "1",
                                                   "text": "meal prep for the whole week in one hour",
                                                   "createTimeISO": "2026-10-01T00:00:00Z", "commentCount": 9,
                                                   "authorMeta": {"name": "user_1"}}], 0.0, "SUCCEEDED")
        return apify.ActorResult(spec["id"], [], 0.0, "SUCCEEDED")              # comments: main and backup empty

    monkeypatch.setattr(apify, "run_actor", fake_run)
    ctx, _ = make_ctx()
    run(tools.search_tiktok(ctx, "#mealprep", 10, "test"))
    backup = seen["scrapeforge/tiktok-comments-extractor"]
    assert backup["commentsPerPost"] > 0 and backup["maxRepliesPerComment"] == 0  # 0 would mean ALL comments


def test_trends_fallback_reads_one_item_per_term():
    items = json.loads(apify.fixture_path("scrapesage/google-trends-scraper").read_text(encoding="utf-8"))
    series = tools.trend_series(items)
    assert set(series) == {"meal prep", "hellofresh"} and all(len(v) >= 3 for v in series.values())
    assert load_yaml("catalog")["sources"]["google_trends"]["fallback"]["bills_per"] == "term"

