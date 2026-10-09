"""Change V12: brand-perception numbers in code, findings verified like every claim. No money."""

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from ctxpack.analysis import brand as an
from ctxpack.config import get_settings


def doc(i, text, mentions, unit="reddit:meal prep", author=None, platform="reddit", relevant=True, eng=50.0):
    return SimpleNamespace(id=f"d{i}", text=text, text_en=None, extraction={"brand_mentions": mentions},
                           source_unit=unit, platform=platform, author_hash=author or f"a{i}", url=f"https://x/{i}",
                           is_relevant=relevant, short_form=False, engagement_percentile=eng,
                           posted_at=date(2026, 9, 1), permalink=None,
                           fragment_anchor_start=None, fragment_anchor_end=None, date_precision="day",
                           language="en", redacted=False)


def m(name, stance="neutral", aspect=None, relation=None):
    return {"name": name, "stance": stance, "aspect": aspect, "relation": relation}


DOCS = [
    doc(1, "Lidl Deluxe mince pies beat the fancy shops", [m("Lidl Deluxe", "positive", "quality")]),
    doc(2, "Deluxe range is just Lidl with a nicer box", [m("Deluxe", "negative", "price", "same_as_parent"),
                                                         m("Lidl")], unit="reddit:lidl deluxe"),
    doc(3, "Tesco Finest or Lidl Deluxe for christmas?", [m("Tesco Finest"), m("Lidl Deluxe", "mixed")]),
    doc(4, "Tesco Finest is my go-to", [m("Tesco Finest", "positive")]),
    doc(5, "nothing about brands here", []),
    doc(6, "Lidl Deluxe again", [m("Lidl Deluxe", "positive", "quality")], relevant=False),   # not counted
]
DOCS[2].posted_at = None               # undated posts count as "recency unknown" (stored dates are plain dates)


def test_brand_numbers_are_computed_in_code():
    own, members = an.stats(DOCS, ["Lidl Deluxe", "Deluxe"], "Lidl Deluxe", parent=["Lidl"])
    assert [d.id for d in members] == ["d1", "d2", "d3"] and own["mentions"] == 3
    assert own["unprompted"] == 2                         # d2 was found by searching the brand's name
    assert own["share_of_voice"] == round(2 / 3, 3)       # unprompted posts naming any brand: d1, d3, d4
    assert own["with_parent"] == 1 and own["relation_mix"] == [{"relation": "same_as_parent", "share": 1.0}]
    assert {x["stance"]: x["share"] for x in own["stance_mix"]} == {"positive": 0.333, "negative": 0.333,
                                                                   "mixed": 0.333}
    assert own["aspects_praised"] == ["quality"] and own["aspects_criticised"] == ["price"]
    parent, _ = an.stats(DOCS, ["Lidl"], "Lidl", exclude=["Lidl Deluxe", "Deluxe"], is_parent=True)
    assert parent["mentions"] == 1 and parent["is_parent"] and parent["relation_mix"] == []


def test_bases_group_the_brands_posts_by_stance_aspect_and_relation():
    _, members = an.stats(DOCS, ["Lidl Deluxe", "Deluxe"], "Lidl Deluxe", parent=["Lidl"])
    groups = an.bases(members, ["Lidl Deluxe", "Deluxe"])
    assert [d.id for d in groups["all"]] == ["d1", "d2", "d3"]
    assert [d.id for d in groups["aspect:price:negative"]] == ["d2"]
    assert [d.id for d in groups["relation:same_as_parent"]] == ["d2"]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("LLM_FAKE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _run(goals, brand="Lidl Deluxe, Deluxe", parent="Lidl"):
    return SimpleNamespace(intake={"goals": goals, "brand": brand, "parent_brand": parent}, interpretation={})


def test_findings_are_verified_and_counted_from_their_basis(fake, monkeypatch):
    from ctxpack.synthesis import brand

    monkeypatch.setattr(brand, "load_yaml", lambda name: {"scoring": {"brand": {
        "min_mentions": 2, "min_unprompted": 1, "findings_max": 5, "member_texts_max": 25, "aspects_max": 5}},
        "modes": {"synthesis": {"evidence_chars": 280}}}[name])
    interp = SimpleNamespace(time_window_days=180)
    section, new_ev, usd = asyncio.run(brand.build(_run(["brand_perception"]), interp, DOCS, evidence=[]))
    assert usd == 0 and [b["name"] for b in section["brands"]] == ["Lidl Deluxe", "Lidl"]
    [f] = section["findings"]
    assert f["id"] == "BRP-01" and f["counts"] == {"matching": 3, "of_total": 5}   # basis "all", relevant only
    assert f["strength"]["distinct_authors"] == 3 and f["confidence"]["label"] in ("emerging", "speculative",
                                                                                   "moderate", "strong")
    ev = {e["id"]: e for e in new_ev}
    assert all(q["text"] in ev[q["evidence_id"]]["text"] for q in f["quotes"])          # exact substrings
    assert "not a survey" in section["note"]


def test_too_few_mentions_means_no_findings_and_a_plain_note(fake):
    from ctxpack.synthesis import brand

    section, new_ev, usd = asyncio.run(brand.build(_run(["brand_perception"]), SimpleNamespace(time_window_days=180),
                                                   DOCS, evidence=[]))
    assert section["findings"] == [] and new_ev == [] and usd == 0                    # 3 mentions < 5 (scoring.yaml)
    assert "too few mentions to judge" in section["note"]


def test_no_brand_section_without_the_goal(fake):
    from ctxpack.synthesis import brand

    assert asyncio.run(brand.build(_run(["positioning"]), SimpleNamespace(time_window_days=180), DOCS, [])) == (
        None, [], 0.0)


def test_section_order_follows_the_ranked_goals():
    from ctxpack.schemas.plan import section_order

    pos, plan = section_order(["positioning"]), section_order(["content_plan"])
    assert pos[0] == "want-stops" and plan[0] == "plan" and sorted(pos) == sorted(plan)   # ordered, never dropped
    assert "brand" not in pos and section_order(["brand_perception"], True)[0] == "brand"


def test_a_finding_never_borrows_counts_from_a_wider_basis():
    """Seen live (V12 paid run): a differentiation claim on basis "all" showed 11 posts though 2 showed it."""
    assert an.basis_fits("differentiation", "relation:part_of_parent") and not an.basis_fits("differentiation", "all")
    assert an.basis_fits("praise", "aspect:taste:positive") and not an.basis_fits("praise", "aspect:taste:negative")
    assert an.basis_fits("criticism", "stance:mixed") and an.basis_fits("perception", "all")
    assert an.aspect_words("scones; fruit and veg, taste") == ["scones", "fruit and veg", "taste"]


def test_findings_on_an_unfitting_basis_count_only_the_cited_posts(fake, monkeypatch):
    from ctxpack.synthesis import brand

    monkeypatch.setattr(brand, "load_yaml", lambda name: {"scoring": {"brand": {
        "min_mentions": 2, "min_unprompted": 1, "findings_max": 5, "member_texts_max": 25, "aspects_max": 5}},
        "modes": {"synthesis": {"evidence_chars": 280}}}[name])
    monkeypatch.setattr(brand, "_fake", lambda user: {"findings": [
        {"kind": "differentiation", "claim": "They see it as part of Lidl.", "basis": "all", "doc_ids": ["d2"]}]})
    section, _, _ = asyncio.run(brand.build(_run(["brand_perception"]), SimpleNamespace(time_window_days=180),
                                            DOCS, evidence=[]))
    assert section["findings"][0]["counts"]["matching"] == 1                     # d2 only, not all 3 brand posts
