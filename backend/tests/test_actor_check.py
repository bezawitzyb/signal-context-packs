"""actor-check: health, prices and inputs of every catalogued Apify actor. No network, no money."""

from datetime import UTC, datetime

import pytest

from ctxpack import actor_check as ac
from ctxpack.config import load_yaml

NOW = datetime(2026, 10, 9, tzinfo=UTC)
CFG = load_yaml("catalog")["health_check"]
SCHEMA = {"properties": {
    "timeRange": {"type": "string", "enum": ["", "today 1-m", "today 3-m"]},
    "maxItems": {"type": "integer", "minimum": 1},
    "dataTypes": {"type": "array", "items": {"enum": ["interestOverTime", "relatedQueries"]}},
    "flag": {"type": "boolean"},
    "token": {"type": "string"}},
    "required": ["token"]}


def act(success=990, total=1000, users=500, deprecated=False, build="2026-10-01T00:00:00Z", rating=4.5,
        reviews=20, prices=None, pricing=None):
    events = {k: {"eventTieredPricingUsd": {"FREE": {"tieredEventPriceUsd": v}}}
              for k, v in (prices or {"result": 0.002, "init": 0.02}).items()}
    return {"isDeprecated": deprecated,
            "stats": {"publicActorRunStats30Days": {"SUCCEEDED": success, "TOTAL": total},
                      "totalUsers30Days": users, "actorReviewRating": rating, "actorReviewCount": reviews},
            "taggedBuilds": {"latest": {"finishedAt": build}},
            "pricingInfos": pricing or [{"pricingModel": "PAY_PER_EVENT", "startedAt": "2026-01-01T00:00:00Z",
                                         "pricingPerEvent": {"actorChargeEvents": events}}]}


SPEC = {"id": "a/b", "success_30d": 0.99, "price_usd": {"result": 0.002, "init": 0.02}}
BUILD = {"inputSchema": {"properties": {"q": {"type": "string"}}}}


def levels(findings):
    return [(f.level, f.text) for f in findings]


def test_every_catalogued_actor_gets_its_inputs_checked_offline():
    seen = ac.sent_inputs()
    missing = {spec["id"] for _, spec in ac.catalog_actors()} - set(seen)
    assert not missing, missing
    assert all(seen.values())


def test_check_input_catches_what_the_actor_no_longer_accepts():
    assert ac.check_input({"timeRange": "today 3-m", "maxItems": 5, "dataTypes": ["interestOverTime"],
                           "flag": False, "token": "x"}, SCHEMA) == []
    problems = ac.check_input({"timeRange": "today 12-m", "maxItems": 0, "dataTypes": ["nope"], "flag": "yes",
                               "gone": 1}, SCHEMA)
    assert "input 'timeRange' value 'today 12-m' is not allowed" in problems       # the 2026-10-09 trends bug
    assert "input 'maxItems' = 0 is below its minimum 1" in problems
    assert "input 'dataTypes' value 'nope' is not allowed" in problems
    assert "input 'flag' must be boolean, we send str" in problems
    assert "input 'gone' no longer exists" in problems
    assert "required input 'token' is not sent" in problems
    assert ac.check_input({"maxItems": True}, SCHEMA) == ["input 'maxItems' must be integer, we send bool",
                                                         "required input 'token' is not sent"]


def test_a_healthy_actor_has_no_findings():
    facts, findings, checked = ac.evaluate(SPEC, act(), BUILD, [{"q": "x"}], CFG, NOW)
    assert findings == [] and checked == 1 and facts["success_30d"] == pytest.approx(0.99)


def test_health_warnings_and_failures():
    _, findings, _ = ac.evaluate(SPEC, act(success=900, total=1000, users=3, build="2025-01-01T00:00:00Z",
                                           rating=2.0, deprecated=True), BUILD, [{"q": "x"}], CFG, NOW)
    found = levels(findings)
    assert ("fail", "deprecated by its author") in found
    assert ("warn", "success 90.0% is below 95%") in found
    assert ("warn", "success fell from 99.0% (catalog) to 90.0%") in found
    assert ("warn", "only 3 users in 30 days") in found
    assert any(t.startswith("no new build for") for _, t in found)
    assert ("warn", "rating 2.0 from 20 reviews") in found


def test_price_changes_and_rental_pricing():
    _, findings, _ = ac.evaluate(SPEC, act(prices={"result": 0.003, "init": 0.02}), BUILD, [{"q": "x"}], CFG, NOW)
    assert levels(findings) == [("warn", "catalog price result = 0.002 is not a live price now")]
    later = [{"pricingModel": "PAY_PER_EVENT", "startedAt": "2026-01-01T00:00:00Z",
              "pricingPerEvent": {"actorChargeEvents": {"result": {"eventPriceUsd": 0.002},
                                                        "init": {"eventPriceUsd": 0.02}}}},
             {"pricingModel": "PAY_PER_EVENT", "startedAt": "2026-11-01T00:00:00Z"}]
    _, findings, _ = ac.evaluate(SPEC, act(pricing=later), BUILD, [{"q": "x"}], CFG, NOW)
    assert levels(findings) == [("warn", "price change announced from 2026-11-01")]
    rental = [{"pricingModel": "FLAT_PRICE_PER_MONTH", "startedAt": "2026-01-01T00:00:00Z"}]
    _, findings, _ = ac.evaluate(SPEC, act(pricing=rental), BUILD, [{"q": "x"}], CFG, NOW)
    assert ("fail", "pricing model is FLAT_PRICE_PER_MONTH (rental or paid plan: not usable)") in levels(findings)


def test_input_problems_fail_and_unreached_actors_warn():
    _, findings, _ = ac.evaluate(SPEC, act(), BUILD, [{"q": "x", "old": 1}, {"q": "y", "old": 2}], CFG, NOW)
    assert levels(findings) == [("fail", "input 'old' no longer exists")]                # reported once
    _, findings, _ = ac.evaluate(SPEC, act(), BUILD, [], CFG, NOW)
    assert ("warn", "no tool call reached this actor: its inputs were not checked") in levels(findings)


def test_run_reads_each_actor_once_and_reports_errors(monkeypatch):
    calls = []

    def get(actor_id):
        calls.append(actor_id)
        if actor_id.startswith("harshmaur"):
            raise ConnectionError("down")
        return act(), {"inputSchema": {"properties": {}}}

    reports = ac.run(get)
    assert len(reports) == len(ac.catalog_actors()) and len(calls) == len(set(calls))
    broken = next(r for r in reports if r.actor_id == "harshmaur/reddit-scraper")
    assert broken.level == "fail" and broken.findings[0].text == "could not read the actor (ConnectionError)"
