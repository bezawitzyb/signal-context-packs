"""Change V9: summary findings, grade cap, generic-point comparison, position, quick brief, hand-off. No money."""

import json
from pathlib import Path

from ctxpack.api import service
from ctxpack.config import load_yaml
from ctxpack.exports.handoff import handoff_options, length_label
from ctxpack.exports.quick_brief import to_quick_brief
from ctxpack.schemas.pack import ContextPack
from ctxpack.synthesis import finalize
from tests.test_cluster import fake  # noqa: F401  (fixture)
from tests.test_posts import packed  # noqa: F401  (fixture)


def fixture_pack(pack_id: str) -> dict:
    """A finished pack kept under tests/fixtures/packs: tests must not depend on the featured packs' words."""
    raw = json.loads((Path(__file__).parent / "fixtures" / "packs" / f"{pack_id}.json").read_text(encoding="utf-8"))
    return ContextPack.model_validate(raw).model_dump(mode="json")


async def test_a_new_pack_has_findings_position_and_measures(packed):  # noqa: F811
    s = packed["snapshot"]
    assert 1 <= len(s["findings"]) <= 3 and s["represents"].startswith(f"{packed['coverage']['counts']['relevant']} public posts")
    for f in s["findings"]:
        assert f["strength_text"].split(" - ")[0] in {"Strong", "Moderate", "Emerging", "Early signal"}
        assert f["good_enough_to"] in {v["good_enough_to"] for v in load_yaml("scoring")["plain_labels"].values()}
    assert s["position"]["statement"] and s["position"]["item_ids"]
    assert all(d["success_measure"] for d in packed["do_first"])
    assert all(b["success_measure"] for b in packed["post_briefs"])


async def test_every_generic_point_gets_a_status(packed):  # noqa: F811
    rows = packed["snapshot"]["generic_vs_found"]["comparison"]
    assert len(rows) == len(packed["snapshot"]["generic_vs_found"]["generic_points"])
    assert {r["status"] for r in rows} <= {"confirmed", "contradicted", "not_seen"}
    assert any(r["status"] == "confirmed" and r["item_ids"] for r in rows)          # the fake check matched point 1


def test_a_thin_pack_never_shows_a_top_grade_or_commit_budget():
    assert finalize.capped_grade("a", True)[0] == "c" and "Capped at c" in finalize.capped_grade("a", True)[1]
    assert finalize.capped_grade("a", False) == ("a", "")
    assert finalize.capped_grade("d", True) == ("d", "")
    item = {"id": "TEN-01", "claim": "x", "confidence": {"label": "strong"}, "quotes": [],
            "strength": {"distinct_authors": 9, "platforms": ["reddit", "youtube"]}}
    assert finalize.finding(item, {}, thin=True)["good_enough_to"] == "brief creative"
    assert finalize.finding(item, {}, thin=False)["good_enough_to"] == "commit budget"


def test_featured_packs_are_migrated_to_the_new_summary_for_free():
    # the 2026-10-06 heat-pump pack (featured until 2026-10-09, kept as test data): thin, grade a before V9
    raw = json.loads((Path(__file__).parent / "fixtures" / "packs" / "pk_WPKWWfPABYxN_pre_v9.json").read_text("utf-8"))
    p = ContextPack.model_validate(raw).model_dump(mode="json")
    s = p["snapshot"]
    assert s["coverage_grade"] == "c" and s["grade_note"]
    assert len(s["findings"]) == 3 and s["represents"].startswith("101 public posts")
    german = [f for f in s["findings"] if f["quote"] and f["quote_en"]]
    assert german                                                    # English shown under German quotes
    ev = {e["id"]: e["text"] for e in p["evidence"]}
    assert all(f["quote"]["text"] in ev[f["quote"]["evidence_id"]] for f in s["findings"] if f["quote"])


def test_quick_brief_is_half_a_page_and_keeps_the_quote_rule():
    p = fixture_pack("pk_i4iFso1HnLWR")
    text = to_quick_brief(p)
    assert len(text.split()) <= load_yaml("modes")["exports"]["quick_brief_max_words"]
    assert "WHO:" in text and "DON'T:" in text and p["guardrails"]["quote_reuse_note"] in text


def test_handoff_options_are_written_for_marketers():
    options = handoff_options(fixture_pack("pk_i4iFso1HnLWR"))
    main = [o["title"] for o in options if not o["more"]]
    assert main == ["Quick brief", "Brief for your AI writer", "Full report", "Content calendar"]
    text = json.dumps(options).lower()
    assert "token" not in text and "json schema" not in text and "evidence id" not in text
    assert all(o["purpose"] and o["length"] for o in options)
    per_page = load_yaml("modes")["exports"]["words_per_page"]
    assert length_label(per_page // 2) == "half a page" and length_label(per_page * 2) == "about 2 pages"


def test_reading_guide_comes_from_scoring_yaml():
    guide = service.reading_guide()
    assert set(guide["labels"]) == {"strong", "moderate", "emerging", "speculative"}
    assert guide["claim_types"]["observed"] == "seen in posts"


async def test_quick_export_and_handoff_api(packed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(service, "pack", lambda pack_id: packed)
    data, media, name = service.export("x", "quick")
    assert name == "quick_brief.txt" and data.decode().startswith("WHO:")
    assert [o["kind"] for o in service.handoff("x")][:4] == ["quick", "prompt", "md", "calendar"]
