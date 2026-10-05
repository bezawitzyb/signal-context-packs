"""Demo agent (Step 5.2, FR-G3): the tool loop and the automatic checks. LLM_FAKE: no money."""

import asyncio
import json
from pathlib import Path

import pytest

from scripts import demo_agent as da
from tests.test_cluster import fake  # noqa: F401  (fixture)

PACK = json.loads((Path(__file__).parents[2] / "featured" / f"{da.NL_PACK}.json").read_text(encoding="utf-8"))


def script(hook="Welke snack mis je nog?", cited=("THM-01",), facts=(("Je mist die snack nog.", "THM-01"),),
           extra="") -> dict:
    return {"title": "t", "hook": hook, "beats": ["a", "b", f"c {extra}"], "on_screen_text": ["x"],
            "caption": "c", "hashtags": ["#snack"], "cited_ids": list(cited),
            "facts_stated": [{"text": t, "about": "audience", "item_id": i} for t, i in facts]}


def scripts_input(**kw) -> dict:
    return {"scripts": [script(**kw) for _ in range(3)]}


def test_good_scripts_pass_every_check():
    s = [script(extra="frikandelbroodje kaassoufflé bamischijf")] * 3
    assert all(c["pass"] for c in da.check(s, PACK)), da.check(s, PACK)


def test_checks_catch_each_problem():
    quote = next(e["text"] for e in PACK["evidence"] if len(e["text"].split()) > 12)
    s = [script(hook="Er staat 'gezond' op de zak", cited=("THM-01", "XYZ-99"),
                facts=(("Gezonde snacks zijn duur.", "TEN-01"), ("Iedereen snackt.", "")),
                extra="verslavend lekker " + quote)]
    res = {c["check"]: c for c in da.check(s, PACK)}
    assert res[">= 3 lexicon terms"]["pass"] is False                          # verslavend lekker does not count
    assert "verslavend lekker" in res[">= 3 lexicon terms"]["detail"]          # ... and says why
    assert res["0 not_this / never_claim phrases"]["pass"] is False
    assert "'gezond' op de zak" in res["0 not_this / never_claim phrases"]["detail"]
    assert res["facts only from safe_to_assert items"]["pass"] is False
    assert "TEN-01" in res["facts only from safe_to_assert items"]["detail"]
    assert "no id" in res["facts only from safe_to_assert items"]["detail"]
    assert res["cited ids exist"]["pass"] is False and "XYZ-99" in res["cited ids exist"]["detail"]
    assert res["no copied quotes"]["pass"] is False


def test_without_pack_cites_nothing():
    res = {c["check"]: c for c in da.check([script(cited=(), facts=())], PACK)}
    assert res["cited ids exist"]["pass"] is False and res["cited ids exist"]["detail"] == "no ids cited"


def test_loop_opens_references_on_demand_and_wraps_them(fake):  # noqa: F811
    seen = []

    def fake_turn(messages):
        seen.append(messages)
        if len(messages) == 1:
            return {"content": [{"type": "tool_use", "name": "read_reference", "input": {"file": "lexicon.md"}}],
                    "stop_reason": "tool_use"}
        return {"content": [{"type": "tool_use", "name": "submit_scripts", "input": scripts_input()}],
                "stop_reason": "tool_use"}

    run = asyncio.run(da.run_agent(PACK, fake=fake_turn))
    assert run.opened == ["lexicon.md"] and len(run.scripts) == 3 and run.turns == 2
    result = seen[1][2]["content"][0]["content"]  # user, assistant, tool results
    assert result.startswith("<untrusted_user_content") and "frikandelbroodje" in result
    assert "Installed skill" in seen[0][0]["content"]


def test_without_pack_has_no_skill_and_no_reference_tool(fake):  # noqa: F811
    def fake_turn(messages):
        assert "Installed skill" not in messages[0]["content"]
        return {"content": [{"type": "tool_use", "name": "submit_scripts", "input": scripts_input(cited=(), facts=())}],
                "stop_reason": "tool_use"}

    run = asyncio.run(da.run_agent(None, fake=fake_turn))
    assert len(run.scripts) == 3 and run.opened == []
    assert [t["name"] for t in da.tools(False, [])] == ["submit_scripts"]


def test_invalid_submission_gets_one_more_turn(fake):  # noqa: F811
    turns = []

    def fake_turn(messages):
        turns.append(1)
        bad = {"scripts": [script()]}  # only one script
        return {"content": [{"type": "tool_use", "name": "submit_scripts",
                             "input": bad if len(turns) == 1 else scripts_input()}], "stop_reason": "tool_use"}

    run = asyncio.run(da.run_agent(None, fake=fake_turn))
    assert run.turns == 2 and len(run.scripts) == 3


def test_render_is_side_by_side(fake):  # noqa: F811
    a = da.AgentRun(with_pack=False, scripts=scripts_input(cited=(), facts=())["scripts"])
    b = da.AgentRun(with_pack=True, scripts=scripts_input()["scripts"], opened=["lexicon.md"])
    text = da.render(PACK, a, b, {"without": da.check(a.scripts, PACK), "with": da.check(b.scripts, PACK)})
    assert "| Check | Without pack | With pack |" in text and text.count("## Script ") == 3
    assert "Opened: lexicon.md" in text


@pytest.mark.parametrize("phrase,text,hit", [("zoutje", "een zoutje erbij", True), ("zoutje", "zoutjes", False)])
def test_phrase_match_is_whole_word(phrase, text, hit):
    assert da._has(text, phrase) is hit


def test_pack_phrases_are_not_copied_quotes_and_brand_claims_do_not_fail():
    s = script(extra="zodat jij dat niet hoeft te doen ribbelchips")
    s["facts_stated"].append({"text": "Wij lezen de kcal voor.", "about": "brand", "item_id": ""})
    res = {c["check"]: c for c in da.check([s], PACK)}
    assert res["no copied quotes"]["pass"] is True
    assert "ribbelchips" in res[">= 3 lexicon terms"]["detail"].split("(")[0]   # only part of a banned phrase
    assert res["facts only from safe_to_assert items"]["pass"] is True
    assert "1 brand claim(s) to verify" in res["facts only from safe_to_assert items"]["detail"]
