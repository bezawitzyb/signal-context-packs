"""Change V10: Ask this pack - answers from the pack only, checked citations, limits. LLM_FAKE: no money."""

import pytest

from ctxpack import guards
from ctxpack.agent import ask as ask_mod
from ctxpack.api import service
from ctxpack.config import load_yaml
from tests.test_cluster import fake  # noqa: F401  (fixture)
from tests.test_posts import packed  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def with_run_key(monkeypatch):
    """Asking needs a key (2026-10-09): tests ask as the run key unless they set another kind."""
    monkeypatch.setattr(guards, "key_kind", lambda _key: "run_key")


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


async def test_asking_needs_a_key_and_says_run_key_only(packed, monkeypatch):  # noqa: F811
    """Owner's decision (2026-10-09): no key, no questions. Users only ever hear about the run key."""
    def refuse(_key):
        raise guards.GuardError(401, "no key")

    monkeypatch.setattr(guards, "key_kind", refuse)
    with pytest.raises(guards.GuardError) as exc:
        await service.ask_pack(packed["pack_id"], "Anything?")
    assert exc.value.status == 401 and exc.value.message == "Asking needs a run key: add it on the start page."
    assert "guest" not in exc.value.message


async def test_the_run_key_has_no_question_limit(packed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(guards, "key_kind", lambda _key: "run_key")
    monkeypatch.setattr(service, "_VISITOR_ASKS", {})
    monkeypatch.setattr(ask_mod, "cfg", lambda: {**load_yaml("modes")["ask"], "guest_questions_per_pack": 1,
                                                 "guest_questions_per_visitor": 1})
    for _ in range(3):
        out = await service.ask_pack(packed["pack_id"], "Anything?", visitor="v1")
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


async def test_the_guest_key_has_per_pack_and_per_visitor_limits(packed, monkeypatch):  # noqa: F811
    """Guest key: 5 questions per pack and 15 per visitor a day (modes.yaml); a visitor is a salted hash of the
    address, kept in memory only. Audit finding 6: one person cannot drain the spend cap."""
    monkeypatch.setattr(guards, "key_kind", lambda _key: "guest")
    monkeypatch.setattr(service, "_VISITOR_ASKS", {})
    monkeypatch.setattr(ask_mod, "cfg", lambda: {**load_yaml("modes")["ask"], "guest_questions_per_pack": 3,
                                                 "guest_questions_per_visitor": 2})
    me, other = service.visitor_key("203.0.113.7"), service.visitor_key("198.51.100.9")
    assert me != other and "203.0.113.7" not in me                     # never the raw address
    first = await service.ask_pack(packed["pack_id"], "Anything?", visitor=me)
    assert first["questions_left_today"] == 1
    await service.ask_pack(packed["pack_id"], "Anything?", visitor=me)
    with pytest.raises(guards.GuardError, match="You have asked today's 2 questions"):
        await service.ask_pack(packed["pack_id"], "Anything?", visitor=me)
    await service.ask_pack(packed["pack_id"], "Anything?", visitor=other)      # pack: 3 of 3 used
    with pytest.raises(guards.GuardError, match="This pack has had its 3 questions"):
        await service.ask_pack(packed["pack_id"], "Anything?", visitor=service.visitor_key("192.0.2.1"))
    assert load_yaml("modes")["ask"]["guest_questions_per_pack"] == 5
    assert load_yaml("modes")["ask"]["guest_questions_per_visitor"] == 15
