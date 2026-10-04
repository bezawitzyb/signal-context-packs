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
    "clarifying_question": {"question": "Which market and audience?",
                            "options": ["Young adults in the Netherlands", "Parents in Germany", "Global, Gen Z"]},
}


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
    out = asyncio.run(ip.interpret("Gen Z and meal prep"))
    assert out.result.plan and out.result.clarifying_question is None
    assert out.estimate.max_usd == pytest.approx(1.80 + 1.40 + 1.00)  # sum of the quick caps (modes.yaml)
    assert out.usd == 0


def test_estimate_comes_from_modes_yaml():
    est = ip.estimate("standard")
    assert est.max_usd == pytest.approx(4.00 + 3.50 + 2.50)
    assert (est.typical_usd_low, est.typical_usd_high, est.typical_minutes) == (5.0, 7.0, 12)


def test_question_allowed_for_people(mode, monkeypatch):
    mode(False)
    create = _mock(monkeypatch, QUESTION)
    out = asyncio.run(ip.interpret("snacks"))
    assert out.result.plan is None and len(out.result.clarifying_question.options) == 3
    kwargs = create.await_args.kwargs
    assert "clarifying_question" in kwargs["tools"][-1]["input_schema"]["properties"]
    assert "<brief>\nsnacks\n</brief>" in kwargs["messages"][0]["content"]


def test_agents_never_get_a_question(mode, monkeypatch):
    mode(False)
    create = _mock(monkeypatch, PLAN)
    out = asyncio.run(ip.interpret("snacks", allow_question=False))
    assert out.result.plan is not None
    schema = create.await_args.kwargs["tools"][-1]["input_schema"]
    assert "clarifying_question" not in schema["properties"]        # enforced by the schema, not the prompt
    assert "NOT allowed" in create.await_args.kwargs["messages"][0]["content"]


def test_after_the_answer_no_second_question(mode, monkeypatch):
    mode(False)
    create = _mock(monkeypatch, PLAN)
    asyncio.run(ip.interpret("snacks", clarification=("Which market?", "Young adults in the Netherlands")))
    kwargs = create.await_args.kwargs
    assert "clarifying_question" not in kwargs["tools"][-1]["input_schema"]["properties"]
    assert "Young adults in the Netherlands" in kwargs["messages"][0]["content"]


@pytest.mark.parametrize("breaks", [
    lambda p: p["starting_units"][0].update(kind="hashtag"),           # reddit has no hashtags
    lambda p: p["interpretation"].update(market="Netherlands"),
    lambda p: p["interpretation"].update(time_window_days=120),
    lambda p: p["starting_units"][1]["queries"][0].update(language="nl"),  # not a brief language
    lambda p: p["starting_units"][2].update(queries=[]),
    lambda p: p.update(clarifying_question=QUESTION["clarifying_question"]),   # both question and plan
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
    out = asyncio.run(ip.interpret("Gen Z and meal prep"))
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
    msg = ip._user_message("snacks", 180, True, None)
    assert "r/" not in msg and ".nl" not in msg and ".de" not in msg


def test_list_sent_as_a_json_string_is_accepted(mode, monkeypatch):
    mode(False)                                   # seen live: Sonnet sent a nested value as a JSON string
    create = _mock(monkeypatch, {**PLAN, "starting_units": json.dumps(PLAN["starting_units"])})
    out = asyncio.run(ip.interpret("Heat pumps for homeowners in Germany"))
    assert out.result.plan is not None and create.await_count == 1
