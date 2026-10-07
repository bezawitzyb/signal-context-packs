"""Change V4: every finding once, in its best place, with links instead of repeats. No money."""

import asyncio

import pytest

from ctxpack.synthesis import consolidate as cs
from ctxpack.synthesis import finalize as fin
from ctxpack.synthesis.notes import section_notes
from tests.test_cluster import fake  # noqa: F401  (fixture)


def item(id_, claim, docs, cluster):
    return {"id": id_, "claim": claim, "evidence_docs": docs, "quotes": [], "cluster_id": cluster}


def sample():
    return {
        "themes": [item("THM-01", "Meal prepping stresses me out and I don't want to spend my weekend in the kitchen.",
                        ["d1", "d2"], "CL-01"),
                   item("THM-02", "I prep ingredients on Sunday and mix them during the week.", ["d5", "d6"], "CL-02")],
        "objections": [item("OBJ-01", "Meal prepping stresses me out and I don't want to spend my weekend in the kitchen.",
                            ["d1", "d3"], "CL-03")],
        "pain_points": [item("PAIN-01", "Reheating takes so long that prep feels like a waste of time.", ["d3", "d4"],
                             "CL-04")],
        "motivations": [item("MOT-01", "I want cheap healthy food without cooking every night.", ["d3", "d7"], "CL-05")],
        "tensions": [], "white_space": [],
        "opportunities": [{"id": "OPP-01", "builds_on": ["THM-01"]}],
        "risks": [{"id": "RSK-01", "item_ids": ["THM-01", "THM-02"]}],
    }


def test_a_repeated_finding_stays_once_in_the_best_section_and_links_elsewhere(fake):  # noqa: F811
    s, meta = sample(), {}
    rep = asyncio.run(cs.consolidate(s, meta))
    assert rep.merged == [("THM-01", "OBJ-01")]                       # objections fit "why say no" better
    assert [t["id"] for t in s["themes"]] == ["THM-02"]
    assert set(s["objections"][0]["evidence_docs"]) == {"d1", "d2", "d3"}   # evidence merged
    assert meta["themes"]["see_also"] == ["OBJ-01"]
    assert s["opportunities"][0]["builds_on"] == ["OBJ-01"] and s["risks"][0]["item_ids"] == ["OBJ-01", "THM-02"]


def test_no_two_sections_state_the_same_finding_afterwards(fake):  # noqa: F811
    s = sample()
    asyncio.run(cs.consolidate(s, {}))
    items = [it for name in cs.SECTIONS for it in s[name]]
    cfg = cs._cfg()
    assert all(cs.similarity(a, b) < cfg["merge_at"] for n, a in enumerate(items) for b in items[n + 1:])


def test_objections_link_the_pain_behind_them_and_the_motivation_they_block(fake):  # noqa: F811
    s = sample()
    asyncio.run(cs.consolidate(s, {}))
    rel = {r["id"]: r["kind"] for r in s["objections"][0]["relations"]}
    assert rel == {"PAIN-01": "comes_from", "MOT-01": "blocks"}


def test_borderline_pairs_go_to_the_model_and_its_verdict_counts(fake, monkeypatch):  # noqa: F811
    s = {"themes": [item("THM-01", "Kits are pricey for small portions.", ["d1"], "CL-01")],
         "objections": [item("OBJ-01", "The portions are really small and the kit is expensive.", ["d1"], "CL-02")],
         "pain_points": [], "motivations": [], "tensions": [], "white_space": []}
    assert cs._cfg()["borderline_from"] <= cs.similarity(s["themes"][0], s["objections"][0]) < cs._cfg()["merge_at"]
    monkeypatch.setattr(cs, "_fake", lambda user: {"items": [{"pair": "P01", "same": True, "keep": "b"}]})
    rep = asyncio.run(cs.consolidate(s, {}))
    assert rep.checked_by_model == 1 and rep.merged == [("THM-01", "OBJ-01")] and s["themes"] == []


def test_section_notes_give_so_what_lines_and_takeaways(fake):  # noqa: F811
    s = {"themes": [item("THM-01", "x", ["d1"], "CL-01")],
         "what_performs": [{"id": "PERF-01", "platform": "tiktok", "format": "label check", "why_it_worked": "y"}]}
    so_what, takeaways, _ = asyncio.run(section_notes(s, "content calendar"))
    assert so_what["themes"] and takeaways[0]["id"] == "TKW-01" and takeaways[0]["post_ids"] == ["PERF-01"]


@pytest.mark.parametrize("section", ["pain_points", "segments", "what_performs"])
def test_empty_sections_say_why_and_what_to_do(section):
    assert fin.EMPTY[section][0] and 1 <= len(fin.EMPTY[section][1]) <= 2
