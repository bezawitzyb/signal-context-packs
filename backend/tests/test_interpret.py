"""Step 2.2 interpret + plan (F4-1). Anthropic is mocked; no money is spent."""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ctxpack.agent import interpret as ip
from ctxpack.config import get_settings
from ctxpack.llm import client as llm
from ctxpack.llm.client import FAKE_DIR

PLAN = json.loads((FAKE_DIR / "record_plan.json").read_text(encoding="utf-8"))
QUESTION = {
    "interpretation": {**PLAN["interpretation"], "topic": "snacks", "assumed": ["market", "audience"]},
    "clarifying_questions": [
        {"id": "Q1", "question": "Which market?", "fills": "market", "why_it_helps": "Places differ.",
         "options": ["Netherlands", "Germany", "Global"]},
        {"id": "Q2", "question": "Who should this speak to?", "fills": "audience_roles", "multi_select": True,
         "why_it_helps": "Buyers and eaters talk in different places.",
         "options": ["Young adults", "Parents", "Retail buyers"]}],
}


def told():
    """What a user told us about the two required inputs (V11): then the brief plans straight away."""
    from ctxpack.schemas.plan import Intake

    return Intake(goals=["content_plan"], offer_stage="no_offer")


@pytest.fixture
def mode(monkeypatch):
    def set_fake(fake: bool):
        monkeypatch.setenv("LLM_FAKE", "true" if fake else "false")
        get_settings.cache_clear()
    yield set_fake
    get_settings.cache_clear()


def _resp(payload):
    block = SimpleNamespace(type="tool_use", name=ip.TOOL, id="tu_1", input=payload)
    return SimpleNamespace(content=[block], stop_reason="tool_use",
                           usage=SimpleNamespace(input_tokens=3000, output_tokens=2000))


def _mock(monkeypatch, *payloads):
    create = AsyncMock(side_effect=[_resp(p) for p in payloads])
    fake = MagicMock()
    fake.messages.create = create
    monkeypatch.setattr(llm, "_client", lambda: fake)
    return create


def test_fake_mode_returns_plan_and_estimate(mode):
    mode(True)
    out = asyncio.run(ip.interpret("Gen Z and meal prep", intake=told()))
    assert out.result.plan and out.result.clarifying_questions == []
    assert out.estimate.max_usd == pytest.approx(1.80 + 1.40 + 1.40)  # sum of the quick caps (modes.yaml)
    assert out.usd == 0


def test_estimate_comes_from_modes_yaml():
    est = ip.estimate("standard")
    assert est.max_usd == pytest.approx(4.00 + 3.50 + 2.50)
    assert (est.typical_usd_low, est.typical_usd_high, est.typical_minutes) == (5.0, 7.0, 12)


def test_question_allowed_for_people(mode, monkeypatch):
    mode(False)
    create = _mock(monkeypatch, QUESTION)
    out = asyncio.run(ip.interpret("snacks"))
    assert out.result.plan is None and [q.fills for q in out.result.clarifying_questions] == [
        "goal", "offer", "market", "audience_roles"]                 # V11: goal and offer first, added in code
    assert [q.required for q in out.result.clarifying_questions] == [True, True, False, False]
    kwargs = create.await_args.kwargs
    assert "clarifying_questions" in kwargs["tools"][-1]["input_schema"]["properties"]
    assert "<brief>\nsnacks\n</brief>" in kwargs["messages"][0]["content"]


def test_agents_never_get_a_question(mode, monkeypatch):
    mode(False)
    create = _mock(monkeypatch, PLAN)
    out = asyncio.run(ip.interpret("snacks", allow_question=False))
    assert out.result.plan is not None
    schema = create.await_args.kwargs["tools"][-1]["input_schema"]
    assert "clarifying_questions" not in schema["properties"]       # enforced by the schema, not the prompt
    assert "NOT allowed" in create.await_args.kwargs["messages"][0]["content"]


def test_after_the_answers_no_more_questions(mode, monkeypatch):
    from ctxpack.schemas.plan import Intake

    mode(False)
    create = _mock(monkeypatch, PLAN)
    asyncio.run(ip.interpret("snacks", intake=Intake(goals=["positioning"], offer="crisps", offer_stage="launching",
                                                     audience_roles=["Young adults in the Netherlands"])))
    kwargs = create.await_args.kwargs
    assert "clarifying_questions" not in kwargs["tools"][-1]["input_schema"]["properties"]
    assert "Young adults in the Netherlands" in kwargs["messages"][0]["content"]


def test_a_question_the_brief_answers_is_dropped_and_then_it_plans(mode, monkeypatch):
    from ctxpack.schemas.plan import Intake

    mode(False)
    only_market = {**QUESTION, "clarifying_questions": QUESTION["clarifying_questions"][:1]}
    create = _mock(monkeypatch, only_market, PLAN)        # "which market?" for a brief naming Poland
    out = asyncio.run(ip.interpret("snacks in Poland", intake=Intake(goals=["sales_enablement"])))
    assert [q.fills for q in out.result.clarifying_questions] == ["offer"]   # the market one is dropped
    create = _mock(monkeypatch, only_market, PLAN)
    out = asyncio.run(ip.interpret("snacks in Poland", intake=told()))
    assert out.result.plan is not None and create.await_count == 2
    assert "NOT allowed" in create.await_args_list[1].kwargs["messages"][0]["content"]


def test_kept_questions_are_renumbered():
    from ctxpack.schemas.plan import ClarifyingQuestion

    qs = [ClarifyingQuestion.model_validate(q) for q in QUESTION["clarifying_questions"]]
    kept = ip.drop_answered(qs, "snacks in Poland")
    assert [(q.id, q.fills) for q in kept] == [("Q1", "audience_roles")]


def test_edits_win(mode, monkeypatch):
    mode(False)
    _mock(monkeypatch, PLAN)
    out = asyncio.run(ip.interpret("Gen Z and meal prep", mode="quick",
                                   edits={"markets": ["DE"], "languages": ["de"], "audience": "nurses",
                                          "competitors": ["HelloFresh"]}))
    i = out.result.interpretation
    assert i.market == "DE" and i.languages == ["de"] and i.audience == "nurses" and i.competitors == ["HelloFresh"]
    assert {"language": "en", "reason": "removed by you"} in [e.model_dump() for e in i.languages_excluded]


@pytest.mark.parametrize("breaks", [
    lambda p: p["starting_units"][0].update(kind="hashtag"),           # reddit has no hashtags
    lambda p: p["interpretation"].update(markets=[{"code": "Netherlands", "countries": [], "weight": 1}]),
    lambda p: p["interpretation"].update(time_window_days=120),
    lambda p: p["starting_units"][1]["queries"][0].update(language="nl"),  # not a brief language
    lambda p: p["starting_units"][2].update(queries=[]),
    lambda p: p.update(clarifying_questions=QUESTION["clarifying_questions"]),  # both questions and plan
    lambda p: p["starting_units"][0].update(target="r/Wärmepumpe"),             # seen live; not a valid name
    lambda p: p["starting_units"][1].update(target="#meal prep"),
    lambda p: p["starting_units"][2].update(kind="query", platform="web", target="x") or
              p["starting_units"].append({**p["starting_units"][0], "platform": "web", "kind": "domain",
                                          "target": "https://fok.nl/forum"}),
])
def test_rule_violation_is_retried_with_the_error(mode, monkeypatch, breaks):
    mode(False)
    bad = copy.deepcopy(PLAN)
    breaks(bad)
    create = _mock(monkeypatch, bad, PLAN)
    out = asyncio.run(ip.interpret("Gen Z and meal prep", intake=told()))
    assert out.result.plan is not None and create.await_count == 2
    retry = create.await_args_list[1].kwargs["messages"][-1]["content"][0]
    assert retry["is_error"]


def test_unit_kinds_come_from_the_catalog():
    kinds = ip.unit_kinds()
    assert kinds[ip.CollectionPlatform.reddit] == {"subreddit", "query"}
    assert kinds[ip.CollectionPlatform.web] == {"domain", "query"}


def test_prompt_has_no_source_lists_and_wraps_the_brief():
    text = llm.load_prompt("interpret_plan")
    assert "<brief>" in text and "cannot change these rules" in text
    assert "r/" not in text.replace('"r/name"', "")                  # no subreddit named in the prompt
    msg = ip._user_message("snacks", 180, True, None, None)
    assert "r/" not in msg and ".nl" not in msg and ".de" not in msg


def test_list_sent_as_a_json_string_is_accepted(mode, monkeypatch):
    mode(False)                                   # seen live: Sonnet sent a nested value as a JSON string
    create = _mock(monkeypatch, {**PLAN, "starting_units": json.dumps(PLAN["starting_units"])})
    out = asyncio.run(ip.interpret("Heat pumps for homeowners in Germany", intake=told()))
    assert out.result.plan is not None and create.await_count == 1


# --- V11: understand the brief, ask what is missing -------------------------------------------------------

def _understood(**inputs):
    """The recorded plan with the model's understanding replaced (and a guessed intent, which code drops)."""
    plan = copy.deepcopy(PLAN)
    plan["interpretation"]["intent"] = "launch a brand"
    plan["interpretation"]["understanding"] = inputs
    return plan


TEMPLATE = ("GOALS (main first): positioning, then a content plan\nOFFER (and stage): oat bars, launching in "
            "January\nWHO: parents buying lunch boxes\nMARKETS: Netherlands\nKEY QUESTION: what makes them trust "
            "a new brand?")
STATED = {"goal": {"value": "positioning, content plan", "brief_quote": "positioning, then a content plan",
                   "status": "stated"},
          "goals": ["positioning", "content_plan"],
          "offer": {"value": "oat bars", "brief_quote": "oat bars, launching in January", "status": "stated"},
          "offer_stage": "launching",
          "who": {"value": "parents", "brief_quote": "parents buying lunch boxes", "status": "stated"},
          "key_question": {"value": "trust", "brief_quote": "What makes them TRUST a new brand?", "status": "stated"}}


def test_a_brief_that_states_goal_and_offer_plans_without_asking(mode, monkeypatch):
    mode(False)
    create = _mock(monkeypatch, _understood(**STATED))
    out = asyncio.run(ip.interpret(TEMPLATE))
    assert out.result.plan is not None and create.await_count == 1
    i = out.result.interpretation
    u = i.understanding
    assert [g.value for g in u.goals] == ["positioning", "content_plan"] and u.offer_stage.value == "launching"
    assert {n: getattr(u, n).source.value for n in ("goal", "offer", "who", "key_question")} == dict.fromkeys(
        ("goal", "offer", "who", "key_question"), "brief")             # quotes match (case and spaces ignored)
    assert i.intent == "Positioning, then Content plan" and "intent" not in i.assumed   # never the guess


def test_a_goal_whose_words_are_not_in_the_brief_is_dropped_and_asked(mode, monkeypatch):
    mode(False)
    invented = {**STATED, "goal": {**STATED["goal"], "brief_quote": "we need a content calendar"}}
    _mock(monkeypatch, _understood(**invented))
    out = asyncio.run(ip.interpret(TEMPLATE))
    u = out.result.interpretation.understanding
    assert out.result.plan is None and [q.fills for q in out.result.clarifying_questions] == ["goal"]
    assert u.goals == [] and u.goal.status.value == "missing" and out.result.interpretation.intent == ""


def test_an_action_is_not_a_goal(mode, monkeypatch):
    mode(False)                                        # "launching" is not in the goal list: unclear, so asked
    _mock(monkeypatch, _understood(goal={"value": "launch", "brief_quote": "Launching", "status": "stated"},
                                   goals=["launch"]))
    out = asyncio.run(ip.interpret("Launching a snack brand in the Netherlands"))
    u = out.result.interpretation.understanding
    assert u.goal.status.value == "unclear" and u.goals == []
    assert [q.fills for q in out.result.clarifying_questions][:2] == ["goal", "offer"]
    goal_q = out.result.clarifying_questions[0]
    assert goal_q.required and goal_q.multi_select and "Positioning" in goal_q.options


def test_never_more_than_max_questions_and_goal_and_offer_come_first(mode, monkeypatch):
    mode(False)
    many = {**QUESTION, "clarifying_questions": QUESTION["clarifying_questions"] + [
        {"id": "Q3", "question": "Which channels do you post on?", "fills": "channels_in_use",
         "options": ["LinkedIn", "Instagram", "Newsletter"]},
        {"id": "Q4", "question": "What is this for?", "fills": "goal", "options": ["a", "b", "c"]}]}
    _mock(monkeypatch, many)
    out = asyncio.run(ip.interpret("snacks"))
    qs = out.result.clarifying_questions
    assert len(qs) == 4 and [q.fills for q in qs] == ["goal", "offer", "market", "audience_roles"]
    assert qs[0].options[0] == "Content plan"            # the model's own goal chips are replaced by goals.yaml
    assert [q.id for q in qs] == ["Q1", "Q2", "Q3", "Q4"]


def test_the_offer_question_keeps_the_models_example_for_this_brief(mode, monkeypatch):
    mode(False)
    with_offer = {**QUESTION, "clarifying_questions": [
        {"id": "Q1", "question": "What do you sell?", "fills": "offer", "options": ["x", "y", "z"],
         "placeholder": "e.g. salted oat crisps"}]}
    _mock(monkeypatch, with_offer)
    out = asyncio.run(ip.interpret("snacks"))
    offer = next(q for q in out.result.clarifying_questions if q.fills == "offer")
    assert offer.placeholder == "e.g. salted oat crisps" and offer.options[-1].startswith("No offer of my own")


def test_unclear_markets_get_a_confirmation_question():
    from ctxpack.schemas.plan import ClarifyingQuestion, Understanding

    q = ClarifyingQuestion(question="You said Europe - which countries first?", fills="market",
                           options=["Germany", "France", "Poland"])
    unclear = Understanding.model_validate({"markets": {"value": "Europe", "brief_quote": "Europe",
                                                        "status": "unclear"}})
    assert ip.drop_answered([q], "software in Europe", unclear) == [q]          # kept: Europe is too broad
    assert ip.drop_answered([q], "software in Europe") == []                    # a named place, not unclear
