"""Change V12: the pack follows the user's goals; brand perception as the brand_perception goal's analysis.
LLM_FAKE and mocks only: no money."""

import asyncio
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from ctxpack import db
from ctxpack.cli import app
from ctxpack.collect.relevance import BriefContext, brief_block
from ctxpack.exports.markdown import to_markdown
from ctxpack.exports.skill import skill_zip
from ctxpack.exports.views import digest_view
from ctxpack.llm.client import FAKE_DIR, load_prompt
from ctxpack.schemas.plan import Intake
from ctxpack.synthesis import finalize, playbook
from tests.test_cluster import fake  # noqa: F401  (fixture)
from tests.test_pack import sections, verified_run_id

PLAN = json.loads((FAKE_DIR / "record_plan.json").read_text(encoding="utf-8"))


# --- goals: at most 3, and every analysis step sees them --------------------------------------------------

def test_at_most_three_goals_the_rest_left_out_with_the_reason():
    i = Intake(goals=["positioning", "content_plan", "sales_enablement", "market_entry"])
    assert [g.value for g in i.goals] == ["positioning", "content_plan", "sales_enablement"]
    assert [(x.goal.value, "at most 3" in x.reason) for x in i.goals_left_out] == [("market_entry", True)]


def test_goals_offer_key_question_and_brand_reach_every_analysis_prompt():
    block = brief_block(BriefContext(topic="snacks", goals="Positioning, then Content plan", offer="oat bars",
                                     key_question="why trust a new brand?", brands=["Oatly"],
                                     parent_brands=["Oatly Group"]))
    assert "The user's goals (main first; they decide emphasis, never what is on-topic): Positioning" in block
    assert "What the user offers: oat bars" in block and "Their key question: why trust a new brand?" in block
    assert "The user's own brand: Oatly (parent brand: Oatly Group)" in block
    assert "never make an on-topic item irrelevant" in load_prompt("relevance")
    assert "Goal" not in brief_block(BriefContext(topic="snacks"))             # nothing added when not given


def test_brief_context_carries_the_goals_and_only_a_brand_perception_brand():
    from ctxpack.orchestrator import brief_context

    plan = {k: PLAN[k] for k in ("hypotheses", "research_questions", "starting_units")}
    run = SimpleNamespace(interpretation=PLAN["interpretation"], plan=plan,
                          intake={"goals": ["brand_perception", "positioning"], "brand": "Oatly", "parent_brand": "X"})
    ctx = brief_context(run)
    assert ctx.goals == "Brand perception, then Positioning" and (ctx.brands, ctx.parent_brands) == (["Oatly"], ["X"])
    run.intake = {"goals": ["positioning"], "brand": "Oatly"}
    assert brief_context(run).brands == []                    # a brand only matters for brand perception


# --- the playbook writes one checked block per goal -------------------------------------------------------

async def test_goal_blocks_follow_the_users_goals_and_point_at_real_items(fake, temp_db):
    s = sections(await verified_run_id())
    ten = s["tensions"][0]["id"]
    out = playbook.PlaybookOut.model_validate({
        "do_first": [{"action": "a", "why_ids": ["THM-99"]}, {"action": "b", "why_ids": [ten], "goal": "positioning"},
                     {"action": "c", "why_ids": [ten], "goal": "world_peace"}],
        "for_goals": [{"goal": "content_plan", "headline": "c", "first_moves": ["DO-03"], "item_ids": [ten, "X-99"]},
                      {"goal": "positioning", "headline": "p", "first_moves": ["DO-01", "DO-02"]},
                      {"goal": "sales_enablement", "headline": "not a goal of theirs"}]})
    parts = playbook.validate(out, s, playbook.PlaybookStats(), intake={"goals": ["positioning", "content_plan"]})
    assert [(d["id"], d["action"], d["goal"]) for d in parts["do_first"]] == [("DO-01", "b", "positioning"),
                                                                              ("DO-02", "c", None)]
    assert [(b["goal"], b["first_moves"], b["item_ids"]) for b in parts["for_goals"]] == [
        ("positioning", ["DO-01"], []), ("content_plan", ["DO-02"], [ten])]   # user's order; DO ids renumbered


# --- the pack follows the goals ---------------------------------------------------------------------------

async def _pack(goals: list[str], **intake) -> dict:
    run_id = await verified_run_id()
    db.update_run(run_id, intake={"goals": goals, **intake})
    out = await finalize.package_run(run_id)
    return db.get_pack(out.pack_id)


async def test_the_same_brief_with_other_goals_gives_another_order_and_summary(fake, temp_db):
    pos, plan = await _pack(["positioning"]), await _pack(["content_plan"])
    assert pos["section_order"][0] == "want-stops" and plan["section_order"][0] == "plan"
    assert [b["goal"] for b in pos["snapshot"]["for_goals"]] == ["positioning"]
    assert [b["goal"] for b in plan["snapshot"]["for_goals"]] == ["content_plan"]
    assert {d["goal"] for d in pos["do_first"]} == {"positioning"}
    assert pos["post_briefs"] and plan["post_briefs"]                          # owner's decision: always kept
    md_pos, md_plan = to_markdown(pos), to_markdown(plan)
    assert md_pos.index("### Opportunities") < md_pos.index("### Channels")   # positioning: opportunities first
    assert md_plan.index("### Channels") < md_plan.index("### Opportunities")
    assert "### For your goal: Positioning" in md_pos and pos["brand_perception"] is None


async def test_brand_perception_goal_adds_the_brand_section_everywhere(fake, temp_db):
    p = await _pack(["brand_perception", "content_plan"], brand="snacks", parent_brand="chips")
    assert p["schema_version"] == "1.3" and p["section_order"][0] == "brand"
    bp = p["brand_perception"]
    assert [b["name"] for b in bp["brands"]] == ["snacks", "chips"] and "not a survey" in bp["note"]
    assert "### How people see your brand" in to_markdown(p)
    assert digest_view(p)["brand_perception"]["brands"][0]["name"] == "snacks"
    assert [g["goal"] for g in digest_view(p)["goals"]] == ["brand_perception", "content_plan"]
    name, data = skill_zip(p)
    assert f"{name.removesuffix('.zip')}/references/brand.md" in zipfile.ZipFile(io.BytesIO(data)).namelist()


# --- asking for the brand -----------------------------------------------------------------------------

def test_brand_perception_without_a_brand_gets_a_required_brand_question(monkeypatch):
    from ctxpack.agent import interpret as ip
    from ctxpack.config import get_settings

    monkeypatch.setenv("LLM_FAKE", "true")
    get_settings.cache_clear()
    try:
        out = asyncio.run(ip.interpret("snacks", intake=Intake(goals=["brand_perception"], offer_stage="selling")))
        qs = out.result.clarifying_questions
        assert qs[0].fills == "brand" and qs[0].required and qs[0].options == []
        told = Intake(goals=["brand_perception"], offer_stage="selling", brand="Oatly")
        assert asyncio.run(ip.interpret("snacks", intake=told)).result.plan is not None
    finally:
        get_settings.cache_clear()


def test_answers_need_the_brand_for_brand_perception():
    from ctxpack.api.service import intake_from_answers

    goal_q = {"id": "Q1", "fills": "goal", "required": True, "question": "g"}
    offer_q = {"id": "Q2", "fills": "offer", "required": True, "question": "o"}
    offer_a = {"id": "Q2", "chosen": ["Already selling"]}
    with pytest.raises(ValueError, match="which brand"):
        intake_from_answers([goal_q, offer_q], [{"id": "Q1", "chosen": ["Brand perception"]}, offer_a], False)
    intake, _ = intake_from_answers([goal_q, offer_q], [
        {"id": "Q1", "chosen": ["Brand perception"], "brand": " Oatly ", "parent_brand": "Oatly Group"}, offer_a],
        False)
    assert (intake["brand"], intake["parent_brand"]) == ("Oatly", "Oatly Group")
    brand_q = {"id": "Q1", "fills": "brand", "required": True, "question": "b"}
    with pytest.raises(ValueError, match="which brand"):
        intake_from_answers([brand_q], [{"id": "Q1", "skipped": True}], True)
    assert intake_from_answers([brand_q], [{"id": "Q1", "text": "Oatly"}], False)[0]["brand"] == "Oatly"
    known, _ = intake_from_answers([goal_q, offer_q], [{"id": "Q1", "chosen": ["Brand perception"]}, offer_a],
                                   False, brand_known=True)              # the brief already named the brand
    assert known["goals"] == ["brand_perception"]


async def test_agents_and_the_cli_must_name_the_brand(fake, temp_db):
    from ctxpack.api import service

    with pytest.raises(ValueError, match="needs intake.brand"):
        await service.create_run("snacks", auto_approve=True, intake={"goals": ["brand_perception"]})
    out = CliRunner().invoke(app, ["research", "snacks", "--fixtures", "--auto-approve", "--goal", "brand_perception"],
                             terminal_width=200)
    assert out.exit_code == 1 and "needs --brand" in out.output
