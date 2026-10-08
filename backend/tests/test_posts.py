"""Change V8: post briefs, drafts and the content calendar - receipts, claim checks, CSV. No money."""

import csv
import io
from datetime import date

import pytest

from ctxpack import db
from ctxpack.api import service
from ctxpack.exports.calendar_csv import COLUMNS, to_calendar_csv
from ctxpack.exports.markdown import to_markdown
from ctxpack.exports.prompt_block import to_prompt_block
from ctxpack.exports.safe_cells import safe_cell
from ctxpack.exports.skill import references
from ctxpack.schemas.pack import DRAFT_LABEL, ContextPack
from ctxpack.synthesis import finalize, playbook, posts
from tests.test_cluster import fake  # noqa: F401  (fixture)
from tests.test_pack import verified_run_id


@pytest.fixture
async def packed(fake, temp_db):  # noqa: F811
    run_id = await verified_run_id()
    out = await finalize.package_run(run_id)
    return db.get_pack(out.pack_id)


# --- the pack -------------------------------------------------------------------------------------

async def test_every_key_point_cites_evidence_from_the_items_it_names(packed):
    pack = ContextPack.model_validate(packed)
    assert 5 <= len(pack.post_briefs) <= 8
    evidence = {e.id for e in pack.evidence}
    items = {i.id: i for i in pack.iter_items()}
    for b in pack.post_briefs:
        assert 3 <= len(b.key_points) <= 5
        for k in b.key_points:
            assert k.evidence_ids and set(k.evidence_ids) <= evidence
            named = {e for i in k.item_ids for e in getattr(items[i], "evidence_ids", [])}
            assert set(k.evidence_ids) <= named                       # receipts come from the items, never the model


async def test_drafts_are_labelled_and_numbers_without_a_receipt_are_removed(packed):
    pack = ContextPack.model_validate(packed)
    assert len(pack.drafts) == 3 and [d.post_brief_id for d in pack.drafts] == [b.id for b in pack.post_briefs[:3]]
    for d in pack.drafts:
        assert d.label == DRAFT_LABEL and d.voice == "neutral"
        assert "90%" not in d.body and d.removed_sentences >= 1       # the fake draft invents "90%"
        assert "Tell us yours" in d.body


async def test_the_calendar_respects_each_channels_cadence(packed):
    pack = ContextPack.model_validate(packed)
    assert pack.content_calendar and all(e.status == "idea" for e in pack.content_calendar)
    assert {e.post_brief_id for e in pack.content_calendar} <= {b.id for b in pack.post_briefs}
    cadence = {posts.PLAN_TO_POST.get(c.platform): c.posts_per_week or posts.cfg()["posts_per_week_default"]
               for c in pack.channel_plan}
    per_week: dict = {}
    for e in pack.content_calendar:
        per_week[(e.channel, e.week)] = per_week.get((e.channel, e.week), 0) + 1
        assert 1 <= e.week <= posts.cfg()["calendar_weeks"]
    assert all(n <= cadence.get(ch, posts.cfg()["posts_per_week_default"]) for (ch, _), n in per_week.items())


# --- briefs: channels and receipts ---------------------------------------------------------------

def _raw(channel: str, ids: list[str], n_points: int = 3) -> posts.PostBriefOut:
    return posts.PostBriefOut(channel=channel, role="r", goal="g", hook="h", angle="a", structure="s", cta="c",
                              key_points=[{"text": f"p{k}", "item_ids": ids} for k in range(n_points)])


def test_the_users_channels_come_first_and_unbacked_channels_are_dropped():
    s = {"tensions": [{"id": "TEN-01", "evidence_ids": ["EV-0001"], "confidence": {"label": "moderate"}}],
         "lexicon": [], "themes": []}
    channels = [{"platform": "reddit"}, {"platform": "tiktok"}]
    stats = playbook.PlaybookStats()
    kept = posts.validate_briefs([_raw("reddit", ["TEN-01"]), _raw("tiktok", ["TEN-01"]),
                                  _raw("linkedin", ["TEN-01"]), _raw("youtube", ["TEN-01"]),
                                  _raw("reddit", ["THM-99"]), _raw("tiktok", ["TEN-01"], 2)], s,
                                 hooks={}, hook_id_of={}, channels=channels,
                                 intake={"channels_in_use": ["LinkedIn company page", "our TikTok"]}, stats=stats)
    assert [b["channel"] for b in kept] == ["linkedin", "tiktok", "reddit"]   # user channels first, then the plan
    assert [b["id"] for b in kept] == ["PST-01", "PST-02", "PST-03"]
    assert stats.dropped["post_brief_channel_without_evidence"] == 1          # youtube: no evidence, not theirs
    assert stats.dropped["post_brief_under_min_key_points"] == 2              # unknown item; only 2 points
    assert kept[0]["confidence"] == "moderate"


@pytest.mark.parametrize("said, expected", [(["LinkedIn", "Instagram + TikTok"], ["linkedin", "instagram", "tiktok"]),
                                            (["X / Twitter"], ["x"]), (["e-mail newsletter", "blog"],
                                                                         ["newsletter", "blog"]), ([], [])])
def test_user_channels_are_read_from_free_text(said, expected):
    assert posts.user_channels({"channels_in_use": said}) == expected


# --- drafts: claim and guardrail checks in code ---------------------------------------------------

def test_check_draft_removes_unsupported_numbers_and_forbidden_phrases():
    body = ("Slide 1: Why meal prep fails.\nPeople told us 3 hours is too long. Prep saves 40% on groceries.\n"
            "It is a superfood bowl. Try it this Sunday!")
    clean, removed = posts.check_draft(body, allowed_numbers={"3"}, forbidden=["superfood"], max_chars=1000)
    assert "Slide 1:" in clean and "3 hours" in clean and "Try it this Sunday!" in clean
    assert "40%" not in clean and "superfood" not in clean and removed == 2


def test_check_draft_cuts_at_a_sentence_end():
    clean, _ = posts.check_draft("One idea here. " * 40, allowed_numbers=set(), forbidden=[], max_chars=100)
    assert len(clean) <= 100 and clean.endswith(".")


# --- calendar --------------------------------------------------------------------------------------

def test_a_news_hook_brief_lands_in_its_week_and_day():
    start = date(2026, 10, 12)  # a Monday
    briefs = [{"id": "PST-01", "channel": "instagram", "news_hook_id": "NWS-01"},
              {"id": "PST-02", "channel": "instagram", "news_hook_id": None},
              {"id": "PST-03", "channel": "instagram", "news_hook_id": None}]
    channels = [{"platform": "instagram", "posts_per_week": 1,
                 "timing": [{"label": "Sunday reset", "when": "Sunday afternoons", "claim_type": "observed"}]}]
    news = [{"id": "NWS-01", "date": "2026-10-22", "headline": "Food fair"}]
    cal = posts.build_calendar(briefs, channels, [], news, start)
    by = {e["post_brief_id"]: e for e in cal}
    assert by["PST-01"]["week"] == 2 and by["PST-01"]["suggested_day"] == "thursday"
    assert by["PST-01"]["timing_kind"] == "news_hook"
    assert by["PST-02"]["suggested_day"] == "sunday" and by["PST-02"]["timing_kind"] == "channel_timing"
    assert sorted(e["week"] for e in cal) == [1, 2, 3]                        # one a week: the cadence holds


# --- exports ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["=SUM(A1)", "+31 6", "-2", "@cmd", "\t=1", " =HYPERLINK(1)"])
def test_cells_that_could_run_as_formulas_are_neutralised(text):
    assert safe_cell(text).startswith("'")


async def test_calendar_csv_imports_with_accents_and_safe_cells(packed):
    packed["post_briefs"][0]["role"] = "Właściciele domów in Groningen (één woning)"
    packed["post_briefs"][0]["hook"] = "=HYPERLINK(\"http://evil\")"
    data = to_calendar_csv(packed)
    assert data.startswith(b"\xef\xbb\xbf")                                  # UTF-8 BOM for Excel / Notion
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert rows[0] == COLUMNS and len(rows) == len(packed["content_calendar"]) + 1
    row = next(r for r in rows[1:] if "Właściciele" in r[4])
    assert "één woning" in row[4] and row[5].startswith("'=HYPERLINK")
    assert row[9] == "Idea" and row[10].endswith(f"/packs/{packed['pack_id']}#PST-01")
    assert all(not cell.startswith(("=", "+", "-", "@")) for r in rows for cell in r)


async def test_briefs_reach_every_export(packed):
    md = to_markdown(packed)
    assert "## Post briefs and content calendar" in md and DRAFT_LABEL in md and "| Week | Day |" in md
    assert "POST BRIEFS" in to_prompt_block(packed)
    assert "PST-01" in references(packed)["posts.md"]


async def test_api_returns_briefs_and_calendar(packed, monkeypatch):
    monkeypatch.setattr(service, "pack", lambda pack_id: packed)
    out = service.post_briefs("x")
    assert out["post_briefs"] and out["drafts"] and out["guardrails"]
    cal = service.calendar("x")["calendar"]
    assert cal and all(e["hook"] for e in cal)
    data, media, name = service.export("x", "calendar")
    assert name == "content_calendar.csv" and media.startswith("text/csv") and data.startswith(b"\xef\xbb\xbf")
