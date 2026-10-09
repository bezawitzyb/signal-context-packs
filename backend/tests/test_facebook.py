"""Facebook (2026-10-09): keyword search of public posts, comments chained, links without names, and author
names redacted from texts on every platform. Recorded fixtures only: no network, no money."""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from ctxpack.collect import apify, tools
from ctxpack.collect.cleaning import facebook_url, make_draft, name_like, scrub_url
from ctxpack.collect.mappers import map_items, sanitize_for_fixture
from ctxpack.collect.relevance import BriefContext
from ctxpack.config import get_settings
from ctxpack.schemas.enums import Platform

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
ACTORS = ["scrapeforge/facebook-search-posts", "scraper_one/facebook-posts-search",
          "apify/facebook-comments-scraper", "thedoor/facebook-comment-scraper"]


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("USE_FIXTURES", "true")
    monkeypatch.setenv("LLM_FAKE", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_ctx(window_days=180):
    stored: list = []
    ctx = tools.RunContext(run_id="RUN-FB", mode="standard", window_days=window_days,
                           brief=BriefContext(topic="Wärmepumpe", market="DE", countries=["DE"], languages=["de"],
                                              research_questions={"RQ1": "Lohnt sich eine Wärmepumpe?"}),
                           store=lambda docs, replaced: stored.extend(docs))
    return ctx, stored


def fixture(actor):
    return json.loads(apify.fixture_path(actor).read_text(encoding="utf-8"))


@pytest.mark.parametrize("actor", ACTORS)
def test_every_fixture_item_maps_with_a_name_free_link(actor):
    posts = map_items(actor, fixture(actor))
    assert posts and len(posts) == len(fixture(actor))
    for p in posts:
        assert p["url"].startswith("https://www.facebook.com/") and p["url"].split(".com/")[1].isdigit()
        assert p.get("permalink") is None or p["permalink"].startswith(p["url"] + "?comment_id=")
        assert p["text"] and p["date"]


def test_search_runs_posts_then_comments_on_the_most_discussed(offline):
    ctx, stored = make_ctx()
    out = asyncio.run(tools.search_facebook(ctx, "Wärmepumpe Erfahrung", 30, "homeowners in public groups"))
    assert out["status"] == "ok" and out["actor"] == "scrapeforge/facebook-search-posts"
    assert out["comments_actor"] == "apify/facebook-comments-scraper"
    assert {d.platform for d in stored} == {Platform.facebook} and out["source_unit"] == "facebook:search:wärmepumpe erfahrung"
    assert all("facebook.com/" in d.url and d.url.split(".com/")[1].isdigit() for d in stored)


@pytest.mark.parametrize("query", ["https://www.facebook.com/groups/123", "facebook.com/somebody", "@somebody",
                                   "www.example.com", " "])
def test_only_keywords_are_accepted(offline, query):
    ctx, _ = make_ctx()
    out = asyncio.run(tools.search_facebook(ctx, query, 20, "x"))
    assert out["status"] == "refused" and ctx.calls == 0


def test_inputs_and_comment_inputs(offline, monkeypatch):
    seen = {}

    async def fake_run(spec, run_input, limit, timeout=None):
        seen[spec["id"]] = run_input
        items = fixture(spec["id"]) if spec["id"] == "scraper_one/facebook-posts-search" else []
        return apify.ActorResult(spec["id"], items[:limit], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    ctx, _ = make_ctx()
    asyncio.run(tools.search_facebook(ctx, "Wärmepumpe", 40, "x"))
    assert seen["scrapeforge/facebook-search-posts"]["search_type"] == "posts"
    assert seen["scrapeforge/facebook-search-posts"]["start_date"] == tools._cutoff(ctx)
    main, backup = seen["apify/facebook-comments-scraper"], seen["thedoor/facebook-comment-scraper"]
    assert "onlyCommentsNewerThan" not in main                                 # billed per comment: never sent
    assert main["includeNestedComments"] is False and backup["includeReplies"] is False
    for url in [s["url"] for s in main["startUrls"]] + backup["postUrls"]:
        assert url.split(".com/")[1].isdigit()                                   # name-free links only


def test_links_with_names_are_rebuilt():
    assert scrub_url("https://www.facebook.com/some.person/posts/1234567890123456") == \
        "https://www.facebook.com/1234567890123456"
    assert scrub_url("https://www.facebook.com/groups/heatpumps/permalink/987654321098765/") == \
        "https://www.facebook.com/987654321098765"
    assert facebook_url("123456789", "42") == "https://www.facebook.com/123456789?comment_id=42"


# --- names in the text (every platform, found while adding Facebook) ---------------------------

def test_name_like_keeps_full_names_and_handles_but_not_plain_words():
    assert name_like(["Anna Schmidt", "max_mueller", "j.doe", "snacks", "Anna", None, "@ab"]) == \
        ["Anna Schmidt", "j.doe", "max_mueller"]


def test_a_post_signed_with_its_authors_name_is_redacted():
    d = make_draft(platform=Platform.facebook, source_unit="facebook:search:x", url="https://www.facebook.com/1",
                   text="Unsere Wärmepumpe läuft super. Viele Grüße, Anna Schmidt", author="Anna Schmidt",
                   date_raw=None, fetched_at=NOW, salt="s")
    assert "Anna Schmidt" not in d.text and "[user]" in d.text and d.redacted


def test_names_of_other_authors_in_the_batch_are_redacted(offline, monkeypatch):
    raw = [{"post_id": "111111111", "type": "post", "message": "Hat jemand Erfahrung mit Luft-Wasser?",
            "timestamp": 1791371948, "comments_count": 2, "author": {"name": "Peter Meyer"}},
           {"post_id": "222222222", "type": "post", "message": "Peter Meyer genau das gleiche Problem hier",
            "timestamp": 1791371948, "comments_count": 0, "author": {"name": "Jana Weber"}}]

    async def fake_run(spec, run_input, limit, timeout=None):
        return apify.ActorResult(spec["id"], raw if "search" in spec["id"] else [], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    monkeypatch.setenv("USE_FIXTURES", "false")
    get_settings.cache_clear()
    ctx, stored = make_ctx()
    asyncio.run(tools.search_facebook(ctx, "Wärmepumpe", 20, "x"))
    assert stored and not any("Peter Meyer" in d.text for d in stored)


def test_fixture_sanitiser_redacts_names_written_in_the_text():
    raw = [{"postId": "1234567890", "postText": "Grüße, Hans Peter Wolf", "timestamp": 1, "author": {"name": "Hans Peter Wolf"}}]
    out = sanitize_for_fixture("scraper_one/facebook-posts-search", raw)
    assert out[0]["author"]["name"] == "user_1" and "Hans" not in out[0]["postText"]


def test_committed_facebook_fixtures_hold_no_profile_links():
    for actor in ACTORS:
        text = apify.fixture_path(actor).read_text(encoding="utf-8")
        assert not any(k in text for k in ("profileUrl", "profile_url", "profilePicture", "fbcdn", "gender"))
        assert "facebook.com/" not in text or all(
            seg.split("?")[0].split('"')[0].isdigit() for seg in text.split("facebook.com/")[1:])
