"""Change V7: news hooks and timing - nothing without a URL, never invented; fixture timing chips. No money."""

import copy
from datetime import date, timedelta

import pytest

from ctxpack import db
from ctxpack.schemas import pack as P
from ctxpack.synthesis import finalize, news
from tests.test_cluster import fake  # noqa: F401  (fixture)
from tests.test_pack import verified_run_id

TODAY = date(2026, 10, 7)


def item(**kw):
    base = {"kind": "news", "headline": "A fair", "date": "2026-10-20", "source_url": "https://fair.example/a",
            "why_it_matters": "They meet there.", "related_ids": ["THM-01", "XYZ-99"]}
    return news.NewsOut(**{**base, **kw})


def test_only_dated_cited_items_from_the_search_are_kept():
    items = [item(), item(source_url=""), item(source_url="https://not.returned/x"),
             item(date="2025-01-01", source_url="https://fair.example/old"),          # outside the span
             item(date="soon", source_url="https://fair.example/b"),                  # no real date
             item(kind="calendar", headline="Budget deadline", source_url="https://fair.example/c")]
    found = {"https://fair.example/a", "https://fair.example/old", "https://fair.example/b", "https://fair.example/c"}
    hooks, calendar = news.keep(items, found, {"THM-01"}, TODAY)
    assert [h["source_url"] for h in hooks] == ["https://fair.example/a"]
    assert hooks[0]["id"] == "NWS-01" and hooks[0]["related_ids"] == ["THM-01"] and hooks[0]["claim_type"] == "external"
    assert [c["headline"] for c in calendar] == ["Budget deadline"]                  # calendar: chips, not hooks


def test_timing_chips_carry_receipts():
    channels = [{"id": "CHN-01", "platform": "reddit"}, {"id": "CHN-02", "platform": "tiktok"}]
    moments = [{"id": "MOM-01", "name": "Sunday reset", "timing": "Sunday afternoons", "claim": "They prep on Sunday.",
                "evidence_ids": ["EV-0002"]}]
    evidence = [{"id": "EV-0002", "platform": "tiktok"}]
    hooks = [{"id": "NWS-01", "headline": "Fair", "date": (date.today() + timedelta(days=5)).isoformat(),
              "why_it_matters": "x", "source_url": "https://fair.example/a"}]
    out = news.channel_timing(channels, moments, evidence, hooks, [])
    assert out[0]["timing"][0]["claim_type"] == "external" and out[0]["timing"][0]["source_url"]
    assert out[1]["timing"] == [{"label": "Sunday reset", "when": "Sunday afternoons", "why": "They prep on Sunday.",
                                 "evidence_ids": ["EV-0002"], "claim_type": "observed", "source_url": None,
                                 "item_id": "MOM-01"}]                                 # the moment's own platform
    for chip in out[0]["timing"] + out[1]["timing"]:
        P.TimingItem.model_validate(chip)


def test_a_timing_item_or_news_hook_without_a_receipt_is_refused():
    with pytest.raises(ValueError, match="source URL"):
        P.TimingItem(label="x", when="y", why="z", claim_type="external")
    with pytest.raises(ValueError, match="evidence"):
        P.TimingItem(label="x", when="y", why="z", claim_type="observed")
    with pytest.raises(ValueError):
        P.NewsHook(id="NWS-01", headline="x", date="2026-10-20", kind="news", source_url="", why_it_matters="y")


async def test_the_fixture_pack_has_news_hooks_and_timing_chips(fake, temp_db):  # noqa: F811
    run_id = await verified_run_id()
    out = await finalize.package_run(run_id)
    pack = db.get_pack(out.pack_id)
    assert [h["id"] for h in pack["news_hooks"]] == ["NWS-01"]                     # the no-URL item was dropped
    assert all(h["source_url"].startswith("https://") for h in pack["news_hooks"])
    chips = [t for c in pack["channel_plan"] for t in c["timing"]]
    assert any(t["claim_type"] == "observed" and t["label"] == "Sundays" and len(t["evidence_ids"]) >= 2
               for t in chips)                                                      # "op zondag" in 2+ posts
    assert all(t["source_url"] for t in chips if t["claim_type"] == "external")
    assert pack["playbook"]["this_week"][0]["news_hook_id"] == "NWS-01"
    from ctxpack.exports.markdown import to_markdown

    md = to_markdown(pack)
    assert "### Ride this now" in md and "rides NWS-01" in md and "When: " in md   # V9: in the post briefs
    again = await finalize.package_run(run_id)                                     # saved: never searched twice
    assert again.usd == 0.0


def test_old_packs_get_timing_from_their_moments():
    import json
    from pathlib import Path

    from ctxpack.schemas.migrate import current

    old = json.loads((Path(__file__).parent / "fixtures" / "example_pack.json").read_text(encoding="utf-8"))
    old = {k: v for k, v in copy.deepcopy(old).items() if k != "news_hooks"}
    new = current(old)
    assert new["news_hooks"] == [] and all("timing" in c for c in new["channel_plan"])
