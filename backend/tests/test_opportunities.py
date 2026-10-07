"""Change V5: opportunities you can trust - counts in code, early signals, existing-solution search. No money."""

import asyncio
from types import SimpleNamespace

import pytest

from ctxpack.synthesis import opportunities as opp
from tests.test_cluster import fake  # noqa: F401  (fixture)

INTERP = SimpleNamespace(market="NL", languages=["nl", "en"])


def doc(i, author, unit):
    return SimpleNamespace(id=f"d{i}", is_relevant=True, short_form=False, author_hash=author, url=f"u{i}",
                           source_unit=unit)


def sections(ws_claim="People ask where to buy paprika ribbel chips?"):
    conf = {"score": 0.8, "label": "strong"}
    return {"white_space": [{"id": "WSP-01", "claim": ws_claim, "kind": "unanswered_question", "cluster_id": "CL-01",
                             "confidence": conf, "evidence_ids": ["EV-0001"], "related_ids": []}],
            "opportunities": [{"id": "OPP-01", "title": "Healthy snack, solved elsewhere",
                               "description": "Show kcal up front", "builds_on": ["PAIN-01", "WSP-01"],
                               "cluster_id": "CL-02", "score": 0.4, "components": None, "evidence_ids": ["EV-0002"]}],
            "pain_points": [{"id": "PAIN-01", "confidence": {"score": 0.6, "label": "moderate"}}], "motivations": []}


def clusters():
    return {"CL-01": SimpleNamespace(verified_member_ids=["d1"]),                       # one post
            "CL-02": SimpleNamespace(verified_member_ids=["d2", "d3", "d4", "d5"])}      # 3 authors, 2 communities


DOCS = [doc(1, "a1", "web:fok.nl"), doc(2, "a2", "web:fok.nl"), doc(3, "a3", "reddit:r/thenetherlands"),
        doc(4, "a4", "web:fok.nl"), doc(5, "a2", "web:fok.nl")]


def test_counts_status_search_and_renaming(fake):  # noqa: F811
    out, mapping, _ = asyncio.run(opp.build(sections(), clusters(), DOCS, INTERP))
    scored, ws = out
    assert mapping == {"OPP-01": "OPP-01", "WSP-01": "OPP-02"}
    assert (scored["distinct_authors"], len(scored["communities"]), scored["status"]) == (3, 2, "supported")
    assert scored["existing_solutions"] == [{"name": "Example tool", "url": "https://example.com/tool"}]
    assert scored["builds_on"] == ["PAIN-01", "OPP-02"]                       # white space id renamed
    assert (ws["distinct_authors"], ws["status"], ws["confidence"]["label"]) == (1, "signal", "emerging")
    assert ws["search_note"] == opp.NOT_FOUND and ws["kind"] == "content_idea"   # a single post: never supported


def test_only_the_first_n_are_searched(fake, monkeypatch):  # noqa: F811
    monkeypatch.setattr(opp, "load_yaml", lambda name: {"opportunities": {"searches_max": 1, "solutions_max": 3},
                                                        **({"opportunities": {"supported_min_authors": 3,
                                                                              "supported_min_communities": 2}}
                                                           if name == "scoring" else {})}
                        if name == "scoring" else {"opportunities": {"searches_max": 1, "solutions_max": 3}})
    out, _, _ = asyncio.run(opp.build(sections(), clusters(), DOCS, INTERP))
    assert out[1]["search_note"] == opp.NOT_SEARCHED


@pytest.mark.parametrize("text,kept", [
    ("People want gluten-free snacks; nobody offers them in Dutch supermarkets.", "People want gluten-free snacks"),
    ("No one serves this need.", ""),
    ("People ask why a snack was pulled from shops.", "People ask why a snack was pulled from shops."),
])
def test_nobody_serves_is_never_kept(text, kept):
    assert opp.no_nobody(text).rstrip(";.").startswith(kept.rstrip("."))


def test_urls_the_search_did_not_return_are_dropped(monkeypatch):
    from ctxpack.config import get_settings

    monkeypatch.setenv("LLM_FAKE", "false")
    get_settings.cache_clear()
    block = SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url="https://real.example/a")])

    async def fake_structured(*a, **k):
        data = opp.CheckOut(existing_solutions=[opp.Solution(name="Real", url="https://real.example/a"),
                                                opp.Solution(name="Invented", url="https://made.up/b")],
                            opportunity="Cheaper, Dutch-language version.", kind="product_idea")
        return SimpleNamespace(data=data, usd=0.01, blocks=[block])

    monkeypatch.setattr(opp, "structured", fake_structured)
    out, usd = asyncio.run(opp.check("x", "NL", ["nl"]))
    get_settings.cache_clear()
    assert [s.name for s in out.existing_solutions] == ["Real"] and usd == 0.01
