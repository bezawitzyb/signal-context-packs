"""Change V2: markets and languages decided in code; schema 1.1 and the 1.0 -> 1.1 migration. No money."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from ctxpack.agent import markets as mk
from ctxpack.schemas.migrate import current, migrate
from ctxpack.schemas.pack import ContextPack

MANUFACTURING = ("digital manufacturing / frontline operations software for plant managers in Europe incl. "
                 "Germany, Poland and the Nordics")
FIXTURE = Path(__file__).parent / "fixtures" / "example_pack.json"


def settle(brief: str, markets: list[dict], model_langs: list[str], mode: str = "standard"):
    ms = mk.normalise(markets, brief)
    return ms, *mk.choose_languages(ms, model_langs, mode, mk.places_in(brief)["countries"])


@pytest.mark.parametrize("brief", ["skincare in Europe", "HR software for the Nordics", "beer in DACH",
                                   "snacks in Poland", MANUFACTURING])
def test_a_brief_naming_a_place_is_never_global(brief):
    ms, langs, _ = settle(brief, [{"code": "global"}], ["en"])
    assert all(m["code"] != "global" for m in ms) and "en" in langs


def test_the_manufacturing_brief_gets_europe_with_germany_and_poland_first_and_their_languages():
    ms, langs, excluded = settle(MANUFACTURING, [{"code": "global"}], ["en"])
    assert ms[0]["code"] == "eu" and ms[0]["countries"][:2] == ["DE", "PL"]
    assert {"nordics"} <= {m["code"] for m in ms}
    assert {"de", "pl", "en"} <= set(langs) and len(langs) <= 6
    assert all(e["reason"] for e in excluded)                                  # every exclusion says why


def test_quick_caps_languages_and_says_how_to_include_the_rest():
    _, langs, excluded = settle(MANUFACTURING, [{"code": "global"}], ["en"], mode="quick")
    assert len(langs) == 4 and {"de", "pl", "en"} <= set(langs)
    left = [e for e in excluded if "choose Standard" in e["reason"]]
    assert left and left[0]["reason"].startswith("left out to keep the run fast (Quick covers up to 4")


def test_a_poland_brief_includes_polish_and_unsupported_languages_are_named():
    _, langs, _ = settle("protein bars for women in Poland", [{"code": "PL"}], ["pl"], mode="quick")
    assert langs[0] == "pl" and "en" in langs
    _, _, excluded = settle("software in central and eastern europe", [{"code": "cee"}], ["en"])
    assert any(e["reason"] == "not supported yet" for e in excluded)           # e.g. Czech, Hungarian


def test_single_country_and_global_briefs_stay_simple():
    assert settle("Launching a snack brand in the Netherlands", [{"code": "NL"}], ["nl", "en"], "quick")[1] == ["nl", "en"]
    ms, langs, excluded = settle("Gen Z and meal prep", [{"code": "global"}], ["en"], "quick")
    assert mk.label(ms) == "global" and langs == ["en"] and excluded == []


def test_labels_and_countries_for_trends():
    ms = mk.normalise([{"code": "eu", "countries": ["DE", "PL", "SE"], "weight": 2}, {"code": "US", "weight": 1}], "")
    assert mk.label(ms) == "EU (DE, PL, SE) + US"
    assert mk.primary_country(ms) == "DE" and mk.countries(ms)[:3] == ["DE", "PL", "SE"]
    assert round(sum(m["weight"] for m in ms), 3) == 1.0


def test_interpret_settles_markets_and_drops_queries_in_left_out_languages(monkeypatch):
    from ctxpack.agent import interpret as ip
    from ctxpack.schemas.plan import PlanResult

    from ctxpack.llm.client import FAKE_DIR

    recorded = json.loads((FAKE_DIR / f"{ip.TOOL}.json").read_text(encoding="utf-8"))
    answer = ip.PlanOnlyAnswer.model_validate(recorded)
    result: PlanResult = answer.to_result()
    result.plan.starting_units[0].queries[0].language = "en"
    result.interpretation.languages = ["en", "it"]                          # Italian: not a market language here
    result.plan.starting_units[1].queries = [q.model_copy(update={"language": "it"})
                                             for q in result.plan.starting_units[1].queries]
    n = len(result.plan.starting_units)
    ip.settle_markets(result, "Gen Z and meal prep in Poland", "quick")
    i = result.interpretation
    assert [m.code for m in i.markets] == ["PL"] and i.market == "PL" and "pl" in i.languages
    assert all(q.language in i.languages for u in result.plan.starting_units for q in u.queries)
    assert len(result.plan.starting_units) <= n


def test_1_0_packs_migrate_to_1_1_and_are_never_written_back():
    old = json.loads(FIXTURE.read_text(encoding="utf-8"))
    before = copy.deepcopy(old)
    new = current(old)
    assert old == before                                                    # the input is not changed
    assert new["schema_version"] == "1.2" and new["brief"]["interpreted"]["markets"][0]["code"]
    assert new["brief"]["interpreted"]["market"] == old["brief"]["interpreted"]["market"]
    assert ContextPack.model_validate(new).schema_version == "1.2"
    assert migrate(new) is new                                              # already current: untouched


def test_every_featured_and_example_pack_validates():
    root = Path(__file__).parents[2]
    files = [p for p in (root / "featured").glob("pk_*.json")] + list((root / "examples").glob("*.json"))
    assert files
    for path in files:
        assert ContextPack.model_validate_json(path.read_text(encoding="utf-8")).schema_version == "1.2", path


def test_old_runs_still_read(temp_db):
    """A run saved before V2 has a 1.0 interpretation: it still validates (market -> markets)."""
    from ctxpack.schemas.plan import Interpretation

    old = {"topic": "t", "market": "DE", "languages": ["de"], "audience": "a", "category": "c",
           "compliance_category": "other", "intent": "i", "time_window_days": 180, "assumed": []}
    i = Interpretation.model_validate(old)
    assert i.markets[0].countries == ["DE"] and i.market == "DE"
    asyncio.run(asyncio.sleep(0))


@pytest.mark.parametrize("text,days", [("il y a 3 jours", 3), ("hace 2 semanas", 14), ("3 giorni fa", 3),
                                       ("3 dni temu", 3), ("för 2 veckor sedan", 14), ("for 3 dage siden", 3),
                                       ("4 päivää sitten", 4), ("3 dias atrás", 3), ("wczoraj", 1), ("i går", 1)])
def test_relative_dates_in_the_new_languages(text, days):
    from datetime import datetime, timedelta, timezone

    from ctxpack.collect.cleaning import parse_date

    now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    assert parse_date(text, now)[0] == (now - timedelta(days=days)).date()


def test_a_duration_is_not_a_date():
    from datetime import datetime, timezone

    from ctxpack.collect.cleaning import parse_date

    assert parse_date("I have cooked for 3 days", datetime(2026, 10, 7, tzinfo=timezone.utc))[0] is None
