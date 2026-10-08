"""Change V10: Ask this pack - answers from the pack only, checked citations, limits. LLM_FAKE: no money."""

import pytest

from ctxpack import db, guards
from ctxpack.agent import ask as ask_mod
from ctxpack.api import service
from tests.test_cluster import fake  # noqa: F401  (fixture)
from tests.test_posts import packed  # noqa: F401  (fixture)


def _pain_word(pack: dict) -> str:
    """A word from a real post behind the first pain point (or any finding), so the fake search finds it."""
    item = (pack.get("pain_points") or pack["tensions"] or pack["motivations"])[0]
    text = next(e["text"] for e in pack["evidence"] if e["id"] in item["evidence_ids"])
    return max(text.split(), key=len).strip(".,!?\"'()")


async def test_a_pain_point_question_cites_real_posts_and_strips_invented_ids(packed):  # noqa: F811
    out = await service.ask_pack(packed["pack_id"], f"{_pain_word(packed)}?")   # the fake searches its longest word
    assert out["citations"] and "[1]" in out["answer"]
    evidence = {e["id"]: e for e in packed["evidence"]}
    first = out["citations"][0]
    assert first["kind"] == "post" and first["url"] == evidence[first["id"]]["url"]
    assert first["url"].startswith(("http://", "https://"))
    assert "TEN-99" not in out["answer"] and all(c["id"] != "TEN-99" for c in out["citations"])
    assert "usd" not in out                                                       # customers never see costs


async def test_an_unanswerable_question_says_so(packed):  # noqa: F811
    out = await service.ask_pack(packed["pack_id"], "Zzyzxqwv?")
    assert out["answer"].startswith(ask_mod.NO_EVIDENCE) and out["citations"] == []


def test_invented_ids_are_stripped_and_real_ones_numbered():
    pack = {"evidence": [{"id": "EV-0001", "url": "https://example.com/p/1", "platform": "reddit",
                          "posted_at": "2026-09-01"}],
            "tensions": [{"id": "TEN-01", "claim": "Want X but Y", "evidence_ids": ["EV-0001"]}]}
    text, cites, stripped = ask_mod.citations("They say X [EV-0001] and Y [TEN-01] and Z [OBJ-77].", pack)
    assert text == "They say X [1] and Y [2] and Z." and stripped == ["OBJ-77"]
    assert [(c["n"], c["id"], c["kind"]) for c in cites] == [(1, "EV-0001", "post"), (2, "TEN-01", "finding")]
    assert cites[1]["url"] == "https://example.com/p/1"                            # a finding opens its first post


async def test_posts_reach_the_model_only_inside_untrusted_tags(packed):  # noqa: F811
    out = ask_mod.run_tool(packed["pack_id"], "search_evidence", {"query": _pain_word(packed)})
    assert out["evidence"] and all(e["text"].startswith("<untrusted_user_content") for e in out["evidence"])
    other = ask_mod.run_tool(packed["pack_id"], "get_insight", {"item_id": "NOPE-01"})
    assert "error" in other                                                        # a missing id is a readable error


async def test_without_a_key_each_pack_has_a_daily_limit(packed, monkeypatch):  # noqa: F811
    def refuse(_key):
        raise guards.GuardError(401, "no key")

    monkeypatch.setattr(guards, "check_run_key", refuse)
    limit = ask_mod.cfg()["questions_per_pack_per_day"]
    for _ in range(limit):
        db.add_ask(packed["pack_id"], 0.0)
    with pytest.raises(guards.GuardError) as exc:
        await service.ask_pack(packed["pack_id"], "Anything?")
    assert exc.value.status == 429 and f"{limit} questions for today" in exc.value.message
    monkeypatch.setattr(guards, "check_run_key", lambda _key: None)               # with a key: no per-pack limit
    out = await service.ask_pack(packed["pack_id"], "Anything?")
    assert out["questions_left_today"] is None


async def test_the_daily_spend_cap_stops_questions(packed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(guards, "daily_spend_left", lambda: 0.0)
    with pytest.raises(guards.GuardError) as exc:
        await service.ask_pack(packed["pack_id"], "Anything?")
    assert exc.value.status == 429 and "allowance" in exc.value.message


async def test_running_out_of_reads_never_claims_no_evidence(packed, monkeypatch):  # noqa: F811
    """Real run 2026-10-08: a capped answer came back empty and was shown as "no evidence" - wrong."""
    monkeypatch.setattr(ask_mod, "_fake", lambda messages: {"content": [{"type": "tool_use", "name": "search_evidence",
                                                                        "input": {"query": "x"}}], "stop_reason": "tool_use"})
    real = ask_mod.cfg
    monkeypatch.setattr(ask_mod, "cfg", lambda: {**real(), "max_tool_calls": 1})
    out = await ask_mod.ask(packed["pack_id"], "What is their strongest objection?")
    assert out.answer == ask_mod.OUT_OF_READS and out.reads == 1
