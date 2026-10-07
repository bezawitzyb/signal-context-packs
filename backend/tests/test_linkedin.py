"""Change V6: LinkedIn as a source - fixture contract, privacy of links, refusals, failures, balance. No money."""

import json
import re
from types import SimpleNamespace

import pytest

from ctxpack.agent.interpret import balance_sources
from ctxpack.collect import apify, tools
from ctxpack.collect.cleaning import redact, scrub_url
from ctxpack.collect.mappers import map_items
from ctxpack.schemas.plan import Plan
from ctxpack.synthesis import finalize
from ctxpack.synthesis.write import evidence_entry, requires_login
from tests.test_tools import check_contract, make_ctx, offline, run  # noqa: F401  (fixture)

POST = "harvestapi/linkedin-post-search"


def test_tool_contract_on_its_fixture(offline):  # noqa: F811
    ctx, stored = make_ctx(topic="heat pump installation costs")
    summary = run(tools.call_tool(ctx, "search_linkedin", {"query": "heat pump installation costs", "limit": 20,
                                                           "reason": "test"}))
    check_contract(summary, stored)
    assert summary["source_unit"] == "linkedin:search:heat pump installation costs" and summary["actor"] == POST
    for d in stored:
        assert str(d.platform) == "linkedin"
        assert re.fullmatch(r"https://www\.linkedin\.com/feed/update/urn:li:activity:\d+/", d.url)
    dumped = json.dumps([d.model_dump(mode="json") for d in stored])
    assert "/posts/" not in dumped and "linkedin.com/in/" not in dumped        # no names inside links


@pytest.mark.parametrize("query", ["https://www.linkedin.com/in/someone", "linkedin.com/groups/123",
                                   "www.linkedin.com/company/acme", "https://example.com/messaging/x", " "])
def test_private_or_personal_targets_are_refused(offline, query):  # noqa: F811
    ctx, stored = make_ctx()
    out = run(tools.search_linkedin(ctx, query, 10, "test"))
    assert out["status"] == "refused" and ctx.calls == 0 and not stored


def test_author_links_are_rebuilt_without_the_name():
    url = "https://www.linkedin.com/posts/jane-doe-12ab_heat-activity-7512784312690409474-AbCd?utm_source=x"
    assert scrub_url(url) == "https://www.linkedin.com/feed/update/urn:li:activity:7512784312690409474/"
    text, changed = redact("see linkedin.com/posts/jane-doe_x-7512784312690409474-AbCd or linkedin.com/in/jane")
    assert changed and "jane" not in text
    item = {"id": "7512784312690409474", "type": "post", "content": "Real text here about pumps",
            "author": {"name": "Jane Doe"}, "postedAt": {"date": "2026-10-05T08:02:40Z"},
            "engagement": {"likes": 2, "comments": 4}}
    (p,) = map_items(POST, [item])
    assert "jane" not in p["url"].lower() and p["comments"] == 4 and p["thread_id"] == "7512784312690409474"


def test_comments_are_chained_on_posts_that_have_some(offline, monkeypatch):  # noqa: F811
    seen = []

    async def fake_run(spec, run_input, limit, timeout=None):
        seen.append((spec["id"], run_input))
        if spec["id"] == POST:
            return apify.ActorResult(POST, [{"id": "7512784312690409474", "type": "post", "content": "Heat pump "
                                             "install costs are the real barrier for us homeowners",
                                             "author": {"name": "user_1"}, "postedAt": {"date": "2026-10-05"},
                                             "engagement": {"likes": 9, "comments": 3}}], 0.0, "SUCCEEDED")
        return apify.ActorResult(spec["id"], [{"postId": "urn:li:activity:7512784312690409474", "commentary":
                                               "Our installer quoted twice the heat pump price, so we waited",
                                               "createdAt": "2026-10-06T10:00:00Z", "actor": {"name": "user_2"},
                                               "linkedinUrl": "https://www.linkedin.com/feed/update/urn:li:"
                                               "activity:7512784312690409474?commentUrn=x"}], 0.0, "SUCCEEDED")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    ctx, stored = make_ctx(topic="heat pump costs")
    out = run(tools.search_linkedin(ctx, "heat pump costs", 10, "test"))
    assert out["comments_actor"] == "harvestapi/linkedin-post-comments" and out["collected"] == 2
    post_input = seen[0][1]
    assert not post_input["scrapeComments"] and not post_input["scrapeReactions"]   # billed extras stay off
    assert seen[1][1]["posts"] == ["https://www.linkedin.com/feed/update/urn:li:activity:7512784312690409474/"]


def test_actor_and_fallback_fail_once_then_a_blind_spot(offline, monkeypatch):  # noqa: F811
    calls = []

    async def fake_run(spec, run_input, limit, timeout=None):
        calls.append(spec["id"])
        return apify.ActorResult(spec["id"], [], 0.0, "FAILED", error="blocked")

    monkeypatch.setattr(apify, "run_actor", fake_run)
    ctx, _ = make_ctx()
    out = run(tools.search_linkedin(ctx, "heat pump costs", 10, "test"))
    assert calls == [POST, "datadoping/linkedin-posts-search-scraper"]           # fallback exactly once
    assert "blind spot" in out["source_problem"]
    assert ctx.source_failures == [{"source_unit": "linkedin:search:heat pump costs", "platform": "linkedin",
                                    "status": "FAILED"}]
    run_row = SimpleNamespace(finish_reason=None, fallback_used=False, top_up_used=False,
                              collection={"source_failures": ctx.source_failures})
    sections = {"what_performs": [1], "segments": [], **{n: [] for n in finalize.INSIGHT_SECTIONS}}
    spots = finalize.blind_spots(run_row, sections, {"coverage": {"languages": ["en"], "dated_share": 1}},
                                 SimpleNamespace(languages=["en"]), [])
    assert any(s.startswith("LinkedIn could not be searched") and "B2B" in s for s in spots)


def _plan(platforms, reason=""):
    unit = {"reddit": ("query", "meal prep"), "web": ("query", "forum"), "linkedin": ("query", "b2b buying"),
            "youtube": ("query", "review")}
    return Plan.model_validate({
        "hypotheses": [{"id": f"HYP-0{n}", "statement": "s"} for n in range(1, 4)],
        "research_questions": [{"id": f"RQ-0{n}", "text": "q"} for n in range(1, 6)],
        "starting_units": [{"platform": p, "kind": unit[p][0], "target": f"{unit[p][1]} {n}", "reason": "r",
                            "queries": [{"language": "en", "query": "x"}]} for n, p in enumerate(platforms)],
        "source_balance_reason": reason})


def test_no_platform_above_half_of_the_plan_unless_it_says_why():
    plan = _plan(["reddit", "reddit", "reddit", "linkedin", "web"])
    assert balance_sources(plan) == ["reddit:meal prep 2"]                     # cap = int(0.5 * 5) = 2
    assert [u.enabled for u in plan.starting_units] == [True, True, False, True, True]
    explained = _plan(["reddit", "reddit", "reddit", "web"], reason="this audience only talks on Reddit")
    assert balance_sources(explained) == [] and all(u.enabled for u in explained.starting_units)


def test_linkedin_evidence_says_login_and_open_posts_are_quoted_first():
    assert requires_login("linkedin") and not requires_login("reddit")
    doc = SimpleNamespace(id="d1", platform="linkedin", source_unit="linkedin:search:x", url="https://l/1",
                          permalink=None, fragment_anchor_start=None, posted_at=None, date_precision="unknown",
                          language="en", text="t", text_en=None, redacted=False, short_form=False,
                          engagement_percentile=None, author_hash=None, extraction={})
    assert evidence_entry(doc, "EV-0001", 280)["requires_login"] is True
    from ctxpack.synthesis.write import Builder

    b = Builder.__new__(Builder)
    b.docs_by_id = {"li": SimpleNamespace(platform="linkedin"), "rd": SimpleNamespace(platform="reddit")}
    b.outcome = SimpleNamespace(drop=lambda why: None)
    pool = SimpleNamespace(doc=lambda local: local)
    quotes = [SimpleNamespace(evidence="li", text="a"), SimpleNamespace(evidence="rd", text="b")]
    assert [q["doc_id"] for q in b.quotes(pool, quotes, {"li", "rd"})] == ["rd", "li"]


def test_linkedin_period_covers_the_window():
    assert tools.linkedin_period(30, POST) == "month" and tools.linkedin_period(180, POST) == "6months"
    assert tools.linkedin_period(365, POST) == "year"
    assert tools.linkedin_period(180, "datadoping/linkedin-posts-search-scraper") == "past-month"
