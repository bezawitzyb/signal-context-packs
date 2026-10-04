"""Pointer segments (cost fix): long posts come back as start/end words and code cuts the exact
post from the page. Guard: both must be unique, else the post is copied in full. No network."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ctxpack.collect import web
from ctxpack.collect.web import Segment, resolve_pointer, resolve_segments
from ctxpack.config import get_settings
from ctxpack.llm.client import CallResult

PAGES = json.loads((Path(__file__).parent / "fixtures" / "tools" / "web_pages.json").read_text(encoding="utf-8"))
PAGE = ("Thread: heat pumps\nanna wrote:\nWe installed a heat pump in our 1970s house last winter and the "
        "bills went down a lot, although the installer took three visits to get the flow temperature right, and "
        "now it runs quietly.\n"
        "ben wrote:\nSame here, the installer took three visits to get the flow temperature right. Otherwise fine.\n")


def pointer(text: str, n: int = 8, **kw) -> Segment:
    words = text.split()
    return Segment(start=" ".join(words[:n]), end=" ".join(words[-n:]), **kw)


def test_unique_start_and_end_cut_the_exact_post():
    post = PAGE.split("anna wrote:\n")[1].split("\nben wrote")[0]
    assert resolve_pointer(pointer(post), PAGE) == post


def test_end_words_that_appear_twice_are_not_trusted():
    post = PAGE.split("anna wrote:\n")[1].split("\nben wrote")[0]
    seg = Segment(start="We installed a heat pump in our 1970s", end="three visits to get the flow temperature")
    assert seg.end in post and PAGE.count(seg.end) == 2
    assert resolve_pointer(seg, PAGE) is None                        # ben quotes the same words


def test_end_before_start_or_missing_words_are_rejected():
    assert resolve_pointer(Segment(start="Same here, the installer", end="We installed a heat pump"), PAGE) is None
    assert resolve_pointer(Segment(start="words that are not on the page", end="Otherwise fine."), PAGE) is None


def test_whitespace_differences_still_resolve_to_the_page_text():
    page = "intro\nI   switched to a heat\npump in May and\tI regret nothing at all, honestly.\nfooter"
    seg = Segment(start="I switched to a heat pump", end="regret nothing at all, honestly.")
    assert resolve_pointer(seg, page) == "I   switched to a heat\npump in May and\tI regret nothing at all, honestly."


async def test_ambiguous_pointers_are_copied_in_full_and_short_posts_kept(monkeypatch):
    copied_requests = []

    async def fake_structured(role, system, user, schema, tool_name, **kw):
        copied_requests.append(user)
        return CallResult(data=schema.model_validate({"segments": [
            {"position": 1, "text": PAGE.split("anna wrote:\n")[1].split("\nben wrote")[0]}]}), usd=0.003)

    monkeypatch.setattr(web, "structured", fake_structured)
    ambiguous = Segment(start="We installed a heat pump in our 1970s", end="three visits to get the flow temperature",
                        author="anna", position=1)
    short = Segment(text="Same here, the installer took three visits to get the flow temperature right. "
                         "Otherwise fine.", author="ben", position=2)
    segs, usd, copied = await resolve_segments(PAGE, [short, ambiguous])
    assert copied == 1 and usd == 0.003 and len(copied_requests) == 1
    assert "<untrusted_user_content" in copied_requests[0] and "position 1" in copied_requests[0]
    assert [s.position for s in segs] == [1, 2] and segs[0].author == "anna"   # metadata kept, page order
    assert all(s.text in PAGE for s in segs)


async def test_nothing_is_copied_when_every_pointer_is_unique(monkeypatch):
    async def must_not_call(*a, **k):
        raise AssertionError("no second call needed")

    monkeypatch.setattr(web, "structured", must_not_call)
    post = PAGE.split("anna wrote:\n")[1].split("\nben wrote")[0]
    segs, usd, copied = await resolve_segments(PAGE, [pointer(post, position=1)])
    assert (copied, usd, segs[0].text) == (0, 0.0, post)


@pytest.mark.parametrize("url", [u for u in PAGES if PAGES[u]["segments"]])
def test_recorded_pages_resolve_from_pointers(url):
    """Free check on real recorded forum pages: pointers for every long post cut out exactly
    the post that was recorded, or are refused (then copied in full) - never a wrong cut."""
    page = PAGES[url]["page_text"]
    for s in PAGES[url]["segments"]:
        original = web.locate(s["text"], page)
        if original is None or len(original.split()) <= 30:
            continue
        cut = resolve_pointer(pointer(original), page)
        assert cut in (original, None)


def test_pointer_answers_need_far_fewer_output_words():
    """Rough size of the model's answer: whole posts vs 8 + 8 words for each long post."""
    full = pointers = 0
    for page in PAGES.values():
        for s in page["segments"]:
            n = len(s["text"].split())
            full += n
            pointers += n if n <= 30 else 16
    assert pointers < full * 0.6, (pointers, full)


async def test_fetch_and_segment_uses_pointers_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("USE_FIXTURES", "false")
    monkeypatch.setenv("AUTHOR_HASH_SALT", "test-salt-not-a-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    post = PAGE.split("anna wrote:\n")[1].split("\nben wrote")[0]
    fetched = {"type": "web_fetch_tool_result", "content": {"type": "web_fetch_result", "content": {
        "source": {"type": "text", "media_type": "text/plain", "data": PAGE}}}}

    async def fake_structured(role, system, user, schema, tool_name, **kw):
        return CallResult(data=schema.model_validate({"segments": [
            pointer(post, author="anna", position=1).model_dump()]}), usd=0.01, blocks=[fetched])

    monkeypatch.setattr(web, "structured", fake_structured)
    res = await web.fetch_and_segment("https://forum.example.de/t/1", "forum", datetime.now(timezone.utc))
    get_settings.cache_clear()
    assert res.segments_returned == 1 and res.segments_not_exact == 0
    assert [d.text for d in res.drafts] == [post]
