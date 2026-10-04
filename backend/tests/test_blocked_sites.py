"""Sites that refuse fetching (url_not_allowed) are remembered and skipped; web search gets them as
blocked_domains. Network and model are mocked: no money."""

import json
from datetime import date, timedelta

import pytest

from ctxpack.collect import tools, web
from ctxpack.collect.relevance import BriefContext
from ctxpack.config import get_settings, load_yaml


@pytest.fixture
def live(monkeypatch, tmp_path):
    """Real (non-fixture) mode with the network mocked, so the blocked list is used."""
    monkeypatch.setenv("USE_FIXTURES", "false")
    monkeypatch.setenv("LLM_FAKE", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTHOR_HASH_SALT", "test-salt-not-a-secret")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def ctx():
    return tools.RunContext(run_id="RUN-B", mode="quick", window_days=365, store=lambda d, r: None,
                            brief=BriefContext(topic="snacks", market="NL", languages=["nl"]))


async def test_a_refusing_site_is_remembered_and_never_fetched_again(live, monkeypatch):
    fetched = []

    async def fake_fetch(url, page_type, fetched_at):
        fetched.append(url)
        return web.PageResult(url, error="url_not_allowed")

    monkeypatch.setattr(web, "fetch_and_segment", fake_fetch)
    first = await tools.fetch_and_segment(ctx(), ["https://www.blocked-forum.nl/t/1"], "try it")
    assert first["blocked_sites"] == ["blocked-forum.nl"] and "choose other sites" in first["blocked_note"]
    assert json.loads((live / "blocked_sites.json").read_text()) == {"blocked-forum.nl": date.today().isoformat()}

    second_ctx = ctx()                                          # a later run: the file remembers it
    again = await tools.fetch_and_segment(second_ctx, ["https://blocked-forum.nl/t/2"], "another thread")
    assert again["status"] == "nothing_to_fetch" and again["blocked_sites"] == ["blocked-forum.nl"]
    assert fetched == ["https://www.blocked-forum.nl/t/1"] and second_ctx.calls == 0   # no call, no cost


async def test_web_search_passes_blocked_sites_and_hides_them(live, monkeypatch):
    web.remember_blocked({"blocked-forum.nl"})
    seen = {}

    async def fake_discover(query, country, language, blocked=None):
        seen["blocked"] = blocked
        return web.DiscoverResult([web.FoundPage(url="https://blocked-forum.nl/t/9", page_type="forum",
                                                 language="nl", why="x"),
                                   web.FoundPage(url="https://open-forum.nl/t/1", page_type="forum",
                                                 language="nl", why="y")])

    monkeypatch.setattr(web, "discover", fake_discover)
    out = await tools.web_search(ctx(), "snacks forum", "NL", "nl", "find forums")
    assert seen["blocked"] == ["blocked-forum.nl"]
    assert [p["url"] for p in out["pages"]] == ["https://open-forum.nl/t/1"] and out["blocked_sites_hidden"] == 1


def test_blocked_sites_expire(live):
    old = (date.today() - timedelta(days=load_yaml("modes")["collection"]["blocked_site_days"] + 1)).isoformat()
    (live / "blocked_sites.json").write_text(json.dumps({"old-site.de": old, "new-site.de": date.today().isoformat()}))
    assert set(web.blocked_sites()) == {"new-site.de"}


def test_fixture_mode_never_reads_or_writes_the_list(monkeypatch, tmp_path):
    monkeypatch.setenv("USE_FIXTURES", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    web.remember_blocked({"x.nl"})
    assert web.blocked_sites() == {} and not (tmp_path / "blocked_sites.json").exists()
    get_settings.cache_clear()


def test_web_search_allows_two_searches_per_call():
    assert load_yaml("modes")["collection"]["web_search_max_uses"] == 2
