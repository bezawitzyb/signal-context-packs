"""Change V13: RSS / Atom feeds - the URL guard, feed reading, the read_feed tool and Google News candidates.

No network and no money: downloads go to an httpx MockTransport and a fake DNS resolver; the tool runs on
tests/fixtures/tools/web_feeds.json (synthetic forum, invented people).
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from ctxpack.collect import feeds, safe_fetch, tools
from ctxpack.collect.loop import call_unit
from ctxpack.config import get_settings
from ctxpack.synthesis import news
from tests.test_tools import make_ctx, offline  # noqa: F401

FEED_XML = (Path(__file__).parent / "fixtures" / "feeds" / "forum.xml").read_bytes()
FORUM = "https://forum.example.org/t/sunday-prep-failing/101"
NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def resolver(table: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        return table.get(host, [])
    return resolve


PUBLIC = resolver({"forum.example.org": ["93.184.216.34"], "example.org": ["93.184.216.34"],
                   "evil.example.net": ["10.0.0.5"], "mixed.example.net": ["93.184.216.34", "127.0.0.1"],
                   "news.google.com": ["142.250.0.1"]})


def transport(routes: dict[str, httpx.Response], seen: list | None = None) -> httpx.MockTransport:
    """routes: path -> response. Records every request (host it went to, Host header, SNI)."""
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return routes.get(request.url.path, httpx.Response(404))
    return httpx.MockTransport(handle)


def rss(body: bytes = FEED_XML) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "application/rss+xml; charset=utf-8"}, content=body)


@pytest.fixture
def live(monkeypatch, tmp_path):
    """Not offline: the code paths that download, still without any network (mock transport)."""
    monkeypatch.setenv("USE_FIXTURES", "false")
    monkeypatch.setenv("LLM_FAKE", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTHOR_HASH_SALT", "test-salt-not-a-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- the URL guard ----------------------------------------------------------

@pytest.mark.parametrize("url, why", [
    ("ftp://forum.example.org/feed", "only http and https"),
    ("file:///etc/passwd", "only http and https"),
    ("https://user:pw@forum.example.org/feed", "user name or password"),
    ("https://forum.example.org:8443/feed", "standard ports"),
    ("https://evil.example.net/feed", "not a public website"),
    ("https://mixed.example.net/feed", "not a public website"),
    ("http://127.0.0.1/feed", "not a public website"),
    ("http://169.254.169.254/latest/meta-data/", "not a public website"),
    ("http://[::1]/feed", "not a public website"),
    ("http://[::ffff:10.0.0.1]/feed", "not a public website"),
    ("https://unknown.example.com/feed", "could not be found"),
])
def test_the_guard_refuses_anything_but_a_public_website(url, why):
    seen: list = []
    with pytest.raises(safe_fetch.FetchRefused, match=why):
        run(safe_fetch.fetch(url, transport=transport({"/feed": rss()}, seen), resolver=PUBLIC))
    assert not seen, "a refused URL must never be requested"


def test_the_guard_connects_to_the_checked_address_with_the_real_host_name():
    seen: list = []
    got = run(safe_fetch.fetch("https://forum.example.org/feed", transport=transport({"/feed": rss()}, seen),
                               resolver=PUBLIC))
    assert got.body == FEED_XML and got.content_type == "application/rss+xml"
    req = seen[0]
    assert req.url.host == "93.184.216.34"                       # pinned: no second DNS lookup
    assert req.headers["host"] == "forum.example.org"
    assert req.extensions["sni_hostname"] == "forum.example.org"  # TLS still checked against the name
    assert "SIGNAL" in req.headers["user-agent"]


def test_every_redirect_is_checked_again():
    seen: list = []
    routes = {"/feed": httpx.Response(302, headers={"location": "https://evil.example.net/feed"})}
    with pytest.raises(safe_fetch.FetchRefused, match="not a public website"):
        run(safe_fetch.fetch("https://forum.example.org/feed", transport=transport(routes, seen), resolver=PUBLIC))
    assert len(seen) == 1


def test_endless_redirects_stop():
    routes = {"/feed": httpx.Response(301, headers={"location": "/feed"})}
    with pytest.raises(safe_fetch.FetchRefused, match="too many redirects"):
        run(safe_fetch.fetch("https://forum.example.org/feed", transport=transport(routes), resolver=PUBLIC))


@pytest.mark.parametrize("response, why", [
    (httpx.Response(200, headers={"content-type": "image/png"}, content=b"x"), "not a web page or feed"),
    (httpx.Response(200, headers={"content-type": "text/xml", "content-length": "99999999"}, content=b"x"),
     "too large"),
    (httpx.Response(200, headers={"content-type": "text/xml"}, content=b"x" * 2_000_001), "too large"),
    (httpx.Response(500), "answered 500"),
])
def test_wrong_type_oversize_and_errors_are_refused(response, why):
    with pytest.raises(safe_fetch.FetchRefused, match=why):
        run(safe_fetch.fetch("https://forum.example.org/feed", transport=transport({"/feed": response}),
                             resolver=PUBLIC))


# --- reading feeds ----------------------------------------------------------

def test_a_feed_is_parsed_newest_first_with_dates_and_without_quoted_replies():
    items = feeds.parse(FEED_XML)
    assert [i.link.rsplit("/", 1)[-1] for i in items] == ["101", "102", "103"]   # javascript: link dropped
    first = items[0]
    assert first.date.startswith("2026-09-21T08:15")
    assert "Quoted reply" not in first.text                                       # blockquote = someone else
    assert "Every Sunday I cook five lunches" in first.text and "<p>" not in first.text


def test_feed_furniture_is_not_kept_as_their_words():
    html = ("<p>I gave up on meal prep after two weeks.</p><p><small>12 posts - 5 participants</small></p>"
            '<p><a href="https://forum.example.org/t/1">Read full topic</a></p>'
            '<p>See <a href="https://forum.example.org/t/2">this thread</a> too.</p>')
    assert feeds.html_to_text(html) == "I gave up on meal prep after two weeks.\n\nSee this thread too."


def test_the_parser_never_opens_a_local_file(tmp_path):
    secret = tmp_path / "not_for_you.xml"
    secret.write_bytes(FEED_XML)
    assert feeds.parse(str(secret).encode()) == []        # the bytes are content, never a file name


def test_a_page_announces_its_feed_on_the_same_site_only():
    html = (b'<html><head><link rel="alternate" type="application/rss+xml" href="https://tracker.example.net/x.rss">'
            b'<link rel="alternate" type="application/atom+xml" href="/latest.atom"></head></html>')
    assert feeds.feed_links(html, "https://forum.example.org/t/1") == ["https://forum.example.org/latest.atom"]


def test_a_category_page_prefers_its_own_feed():
    html = (b'<link rel="alternate" type="application/rss+xml" href="/posts.rss">'
            b'<link rel="alternate" type="application/rss+xml" href="/latest.rss">'
            b'<link rel="alternate nofollow" type="application/rss+xml" href="/c/packaging/14.rss">')
    assert feeds.feed_links(html, "https://forum.example.org/c/packaging/14")[0] == \
        "https://forum.example.org/c/packaging/14.rss"


def test_read_finds_the_feed_from_a_page(live):
    page = httpx.Response(200, headers={"content-type": "text/html"},
                          content=b'<link rel="alternate" type="application/rss+xml" href="/latest.rss">')
    res = run(feeds.read("https://forum.example.org/t/1",
                         transport=transport({"/t/1": page, "/latest.rss": rss()}), resolver=PUBLIC))
    assert res.error is None and res.feed_url == "https://forum.example.org/latest.rss" and len(res.items) == 3


def test_read_reports_a_page_without_a_feed(live):
    page = httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>no feed</html>")
    res = run(feeds.read("https://forum.example.org/t/1", transport=transport({"/t/1": page}), resolver=PUBLIC))
    assert res.items == [] and res.error == "this page announces no feed"


def test_feed_authors_are_hashed_and_their_names_and_emails_redacted(offline):  # noqa: F811
    res = feeds.FeedResult(FORUM, "https://forum.example.org/latest.rss", feeds.parse(FEED_XML))
    drafts, threads = tools._feed_drafts(res, NOW)
    assert len(drafts) == 2 and threads == ["https://forum.example.org/t/freezing-rice/103"]
    dumped = json.dumps([d.to_cache() for d in drafts])
    assert "Jane Exampleton" not in dumped and "pat.k_99" not in dumped and "jane@example.org" not in dumped
    assert all(re.fullmatch(r"[0-9a-f]{64}", d.author_hash) for d in drafts)
    assert drafts[0].text.startswith("Sunday prep keeps failing by Wednesday\n\n")   # the title leads
    assert drafts[0].source_unit == "feed:forum.example.org" and drafts[0].platform == "web_forum"


def test_a_recorded_fixture_holds_no_names(offline):  # noqa: F811
    res = feeds.FeedResult(FORUM, "https://forum.example.org/latest.rss", feeds.parse(FEED_XML))
    fixture = json.dumps(feeds.sanitize_fixture(res))
    assert "Jane Exampleton" not in fixture and "pat.k_99" not in fixture and "jane@example.org" not in fixture
    assert '"author": "user_1"' in fixture


# --- the read_feed tool -------------------------------------------------------

def test_read_feed_only_reads_sites_web_search_returned(offline):  # noqa: F811
    ctx, stored = make_ctx()
    out = run(tools.call_tool(ctx, "read_feed", {"urls": [FORUM, "https://www.reddit.com/r/x/.rss"],
                                                 "reason": "test"}))
    assert out["status"] == "nothing_to_read" and ctx.calls == 0 and not stored
    assert "use web_search first" in out["refused"][FORUM]
    assert out["refused"]["https://www.reddit.com/r/x/.rss"] == "use search_reddit"


def test_read_feed_stores_posts_and_returns_teasers_to_read(offline):  # noqa: F811
    ctx, stored = make_ctx()
    ctx.page_types["https://forum.example.org/t/other/9"] = "forum"     # web_search returned this site
    out = run(tools.call_tool(ctx, "read_feed", {"urls": [FORUM], "reason": "test"}))
    assert out["status"] == "ok" and out["source_unit"] == "feed:forum.example.org"
    assert out["collected"] == 2 and out["kept"] == len(stored) == 2
    assert out["threads_to_read"] == ["https://forum.example.org/t/freezing-rice/103"]
    assert ctx.page_types["https://forum.example.org/t/freezing-rice/103"] == "forum"   # ready for fetch_and_segment
    assert all(d.posted_at is not None for d in stored)                                   # feeds are dated
    assert not re.search(r"user_\d+", json.dumps([d.model_dump(mode="json") for d in stored]))
    again = run(tools.call_tool(ctx, "read_feed", {"urls": [FORUM], "reason": "test"}))
    assert again["status"] == "nothing_to_read" and again["skipped"] == [FORUM] and ctx.calls == 1


def test_read_feed_never_reads_a_dropped_unit(offline):  # noqa: F811
    ctx, _ = make_ctx()
    ctx.page_types["https://forum.example.org/t/other/9"] = "forum"
    ctx.dropped_units.add("feed:forum.example.org")
    out = run(tools.call_tool(ctx, "read_feed", {"urls": [FORUM], "reason": "test"}))
    assert out["status"] == "nothing_to_read" and ctx.calls == 0


def test_read_feed_is_offered_to_the_agent_and_logged_by_unit():
    names = [d["name"] for d in tools.tool_definitions()]
    assert "read_feed" in names
    assert call_unit("read_feed", {"urls": [FORUM, "https://www.forum.example.org/x"]}) == "feed:forum.example.org"


# --- Google News candidates for news hooks ----------------------------------------

GOOGLE_NEWS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Snack makers cut sugar ahead of new rules - Example Times</title>
<link>https://news.google.com/rss/articles/abc</link><pubDate>Tue, 06 Oct 2026 07:00:00 GMT</pubDate>
<source url="https://times.example">Example Times</source></item>
<item><title>No date, so never a candidate</title><link>https://news.google.com/rss/articles/nodate</link></item>
</channel></rss>"""


def test_google_news_search_feed_url():
    url = feeds.google_news_url("snacks", "nl", "NL", 30)
    assert url == "https://news.google.com/rss/search?q=snacks+when%3A30d&hl=nl-NL&gl=NL&ceid=NL:nl"


def test_google_news_headlines_are_dated_and_offline_gives_none(live):
    seen: list = []
    got = run(feeds.google_news("snacks", "nl", "NL", 30, transport=transport({"/rss/search": rss(GOOGLE_NEWS)}, seen),
                                resolver=PUBLIC))
    assert got == [{"headline": "Snack makers cut sugar ahead of new rules - Example Times", "date": "2026-10-06",
                    "url": "https://news.google.com/rss/articles/abc", "source": "Example Times"}]
    assert seen[0].url.params["hl"] == "nl-NL"


def test_google_news_is_never_called_offline(offline):  # noqa: F811
    assert run(feeds.google_news("snacks", "nl", "NL", 30)) == []


def plan_with(*queries):
    return {"starting_units": [{"queries": [{"language": lang, "query": q}]} for lang, q in queries]}


def test_the_core_term_comes_from_the_plan_in_the_market_language():
    de = plan_with(("de", "wärmepumpe erfahrungen altbau"), ("de", "wärmepumpe förderung kfw"),
                   ("de", "erfahrungsbericht wärmepumpe"), ("en", "heat pump germany"))
    assert news.core_term(de, "de") == "wärmepumpe"
    en = plan_with(("en", "meal prep on a budget"), ("en", "student meal prep"), ("en", "meal prep fails"))
    assert news.core_term(en, "en") == "meal prep"
    assert news.core_term(None, "de") == "" and news.core_term(de, "nl") == ""


def test_news_candidates_use_the_main_market_and_language(monkeypatch):
    calls = []

    async def fake(query, language, country, days):
        calls.append((query, language, country, days))
        return [{"headline": f"{query} news", "date": "2026-10-0" + str(len(calls)), "url": "https://n/same",
                 "source": "S"}]

    monkeypatch.setattr(feeds, "google_news", fake)
    market = SimpleNamespace(model_dump=lambda: {"code": "DE", "countries": ["DE"], "weight": 1.0})
    interp = SimpleNamespace(category="heat pump installation", topic="heat pumps", languages=["de", "en"],
                             markets=[market])
    plan = plan_with(("de", "wärmepumpe erfahrungen"), ("de", "wärmepumpe kosten"))
    run(news.feed_candidates(interp, plan))
    assert [c[:3] for c in calls] == [("wärmepumpe", "de", "DE")]          # never the English category here
    calls.clear()
    interp.languages = ["en"]
    got = run(news.feed_candidates(interp, plan_with(("en", "heat pump cost"), ("en", "heat pump noise"))))
    assert [c[0] for c in calls] == ["heat pump", "heat pump installation"]
    assert len(got) == 1                                                       # the same URL twice is one candidate


def test_web_search_points_to_the_feeds_of_the_forums_it_found(offline):  # noqa: F811
    ctx, _ = make_ctx(languages=("de",))
    found = run(tools.web_search(ctx, "wärmepumpe erfahrungen", "DE", "de", "test"))
    hint = found["feeds_hint"]
    assert "read_feed" in hint and "never pass a forum's home page" in hint.casefold()
    assert hint.count("haustechnikdialog.de") == 1                   # one page per site
    ctx.tried_units.add("feed:haustechnikdialog.de")                  # its feed was read: no longer suggested
    assert "haustechnikdialog.de" not in " ".join(tools._feed_hint_pages(ctx, found["pages"]))
