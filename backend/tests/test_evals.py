"""Evaluation harness (Step 5.1, PRD 14.3). Code metrics on a fixture pack; the claim re-check in LLM_FAKE. No money."""

import asyncio
import copy
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ctxpack import evaluation as ev
from ctxpack.api.main import app
from tests.test_cluster import fake  # noqa: F401  (fixture)

FIXTURE = Path(__file__).parent / "fixtures" / "example_pack.json"
TARGETS = ev.load_briefs()["targets"]
SPEC = {"id": "genz_meal_prep", "brief": "Gen Z and meal prep", "mode": "quick",
        "expect": {"market": "global", "languages": ["en"]}}


@pytest.fixture
def pack():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def out_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(ev, "FEATURED_EVALS", tmp_path / "featured" / "evals.json")
    monkeypatch.setattr(ev, "HUMAN_FILE", tmp_path / "featured" / "evals_human.json")
    (tmp_path / "featured").mkdir()
    return tmp_path


def test_briefs_file_has_the_f5_briefs_plus_the_v2_brief():
    briefs = ev.load_briefs()["briefs"]
    assert [b["brief"] for b in briefs][:4] == ["Gen Z and meal prep", "Launching a snack brand in the Netherlands",
                                               "Heat pumps for homeowners in Germany", "snacks"]
    assert briefs[4]["id"] == "eu_manufacturing" and briefs[4]["expect"]["languages"] == ["de", "pl"]
    assert [b["mode"] for b in briefs[2:4]] == ["standard", "quick"]
    assert briefs[3]["source_diversity_exempt"] and briefs[3]["expect"]["questions_fill"] == ["goal", "offer", "market",
                                                                                         "audience_roles"]


def test_groundedness_and_claims_with_evidence(pack):
    assert ev.groundedness(pack)["pass"] and ev.claims_with_evidence(pack)["pass"]
    broken = copy.deepcopy(pack)
    q = ev.quotes(broken)[0]
    q["text"] = q["text"] + " not in the post"
    g = ev.groundedness(broken)
    assert g["pass"] is False and g["value"] < 1 and q["evidence_id"] in g["detail"]
    item = ev.claim_items(broken)[0]
    item["evidence_ids"] = ["EV-9999"]
    for side in ("want", "but"):
        item.pop(side, None)
    c = ev.claims_with_evidence(broken)
    assert c["pass"] is False and item["id"] in c["detail"]


def test_allocation_is_simulated_from_per_unit_yields():
    log = [{"source_unit": "reddit:r/a", "result_summary": "collected 50, kept 50, relevant 80%"},
           {"source_unit": "tiktok:#b", "result_summary": "collected 10, kept 10, relevant 10%"},
           {"source_unit": "web:search:x", "result_summary": "12 pages found"},
           {"source_unit": "web:a, web:b", "result_summary": "collected 5, kept 5, relevant 100%"}]
    assert ev.unit_yields(log) == {"reddit:r/a": {"collected": 50, "relevant": 40},
                                   "tiktok:#b": {"collected": 10, "relevant": 1}}
    m = ev.allocation_efficiency({"coverage": {"decision_log": log}}, collection_usd=2.0)
    # equal split: 30 items each -> 30 * 0.8 + 30 * 0.1 = 27 relevant; the agent got 41
    assert m["simulated"] is True and m["value"] == round(41 / 27, 2) and m["pass"] is True
    assert m["relevant_per_usd"] == {"agent": 20.5, "equal_split": 13.5}


def test_plan_divergence_counts_shared_units():
    d = ev.plan_divergence({"a": {"reddit:r/x", "web:a"}, "b": {"reddit:r/x", "tiktok:#y"}, "c": {"web:c"}}, 0.5)
    assert d["value"] == 0.25 and d["pass"] is True and d["pairwise_jaccard"]["a / b"] == round(1 / 3, 3)
    assert "reddit:r/x" in d["detail"]


def test_relevance_failure_names_the_weakest_sources(pack):
    p = copy.deepcopy(pack)
    p["coverage"]["counts"].update(kept=100, relevant=40)
    m = ev.relevance_rate(p, 0.6)
    assert m["pass"] is False and m["value"] == 0.4 and "weakest kept sources" in m["detail"]


def test_vague_brief_is_exempt_from_source_diversity(pack):
    assert ev.source_diversity(pack, 99, exempt=True)["pass"] is None
    assert ev.source_diversity(pack, 99, exempt=False)["pass"] is False


def test_recheck_uses_the_evaluator_and_counts_entailment(pack, fake, monkeypatch):  # noqa: F811
    from ctxpack.synthesis import verify

    roles = []
    real = verify.structured

    async def spy(role, *a, **k):
        roles.append(role)
        return await real(role, *a, **k)

    monkeypatch.setattr(verify, "structured", spy)
    ent = asyncio.run(ev.recheck_claims(pack, 30))
    assert roles and set(roles) == {"evaluator"}
    assert ent["sampled"] == min(30, len(ev.entailment_sample(pack, 999))) and ent["rate"] == 1.0
    assert [r["id"] for r in ent["rows"]] == [r["id"] for r in asyncio.run(ev.recheck_claims(pack, 30))["rows"]]
    m = ev.entailment_metric(ent, 0.95)
    assert m["pass"] is True


def test_partial_counts_only_when_the_pack_already_says_inferred():
    ent = {"checked": 2, "entailed": 1, "rate": 0.5, "strict_rate": 0.0,
           "rows": [{"id": "A-1", "verdict": "partially_supported", "entailed": True},
                    {"id": "B-1", "verdict": "partially_supported", "entailed": False}]}
    m = ev.entailment_metric(ent, 0.95)
    assert m["pass"] is False and "B-1" in m["detail"] and "A-1" not in m["detail"].split("not entailed:")[1]


def test_score_save_and_publish_with_human_ratings(pack, out_dirs):
    scored = [ev.score_brief(SPEC, pack, None, TARGETS, entailment=None, clarifying=None, reused=True)]
    b = scored[0]
    assert b["metrics"]["schema_valid"]["pass"] and b["metrics"]["cost_usd"]["value"] is None
    assert {e["check"] for e in b["expectations"]} >= {"market is global"}
    path = ev.save(ev.build_result(scored, TARGETS, 0.0))
    assert path.exists() and ev.FEATURED_EVALS.read_text() == path.read_text()
    ev.HUMAN_FILE.write_text(json.dumps({"session": None, "briefs": {"genz_meal_prep": {"hooks_would_use": 7,
                                                                                         "hooks_rated": 10}}}))
    data = ev.published()
    assert data["status"] == "ok" and data["human"]["briefs"]["genz_meal_prep"]["hooks_would_use"] == 7
    assert "units" not in data["briefs"][0]
    assert ev.previous("genz_meal_prep", pack["pack_id"])["pack_id"] == pack["pack_id"]


def test_clarifying_questions_expectations():
    """V3: how many questions, about what, and never one the brief already answers."""
    p = {"brief": {"text": "snacks in Poland", "interpreted": {"market": "PL"}}, "coverage": {}}
    qs = {"questions": [{"id": "Q1", "question": "Which market?", "fills": "market", "options": []},
                        {"id": "Q2", "question": "Who?", "fills": "audience_roles", "options": []}]}
    res = {c["check"]: c for c in ev.expectations(p, {"questions_max": 1, "questions_fill": ["audience_roles"]}, 0.05, qs)}
    assert res["at most 1 question(s)"]["pass"] is False
    assert res["asks about audience_roles"]["pass"] is True
    assert res["never asks what the brief already says"]["pass"] is False          # it names Poland
    assert ev.expectations(p, {"questions_max": 1}, 0.05, None)[0]["pass"] is None   # not checked yet


def test_api_evals_before_and_after_a_run(pack, out_dirs, monkeypatch):
    import threading

    from ctxpack import db as _db

    ready = threading.Event()
    ready.set()                                       # the app's start-up migration is not part of this test
    monkeypatch.setattr(_db, "SCHEMA_READY", ready)
    client = TestClient(app)
    body = client.get("/api/v1/evals").json()
    assert body["status"] == "not_run_yet" and body["briefs"] == []
    ev.save(ev.build_result([ev.score_brief(SPEC, pack, None, TARGETS, entailment=None, clarifying=None,
                                            reused=True)], TARGETS, 0.0))
    body = client.get("/api/v1/evals").json()
    assert body["status"] == "ok" and body["briefs"][0]["pack_id"] == pack["pack_id"]
    assert body["headline"]["allocation_efficiency"]["simulated"] is True


def test_featured_loader_skips_eval_files(temp_db, tmp_path):
    shutil.copy(FIXTURE, tmp_path / "pk_example.json")
    (tmp_path / "evals.json").write_text("{}")
    (tmp_path / "evals_human.json").write_text("{}")
    assert temp_db.load_featured(tmp_path) == 1


def test_plan_mix_expectations():
    """V6: brief 5 plans LinkedIn and keeps Reddit at most half; Gen Z does not lean on LinkedIn."""
    p = {"brief": {"text": "x", "interpreted": {"market": "eu"}}, "coverage": {}}
    plan = {"starting_units": [{"platform": "linkedin"}, {"platform": "reddit"}, {"platform": "web"},
                               {"platform": "reddit", "enabled": False}]}
    assert ev.plan_mix(plan) == {"linkedin": 0.33, "reddit": 0.33, "web": 0.33}
    res = {c["check"]: c["pass"] for c in ev.expectations(
        p, {"plans_platforms": ["linkedin"], "platform_share_max": {"reddit": 0.5}}, 0.05, None, plan)}
    assert res == {"plans linkedin": True, "reddit at most 50% of the plan": True}
    assert ev.expectations(p, {"plans_platforms": ["linkedin"]}, 0.05, None, None)[0]["pass"] is None


def test_label_sheets_and_scores(tmp_path):
    """Data audit 9: a human-labelled gold set for relevance and claim entailment (tools only; labels are yours)."""
    from types import SimpleNamespace

    from ctxpack import evaluation as ev

    docs = [SimpleNamespace(id=f"d{i}", platform="reddit", language="en", text=f"=cmd {i}", text_en=None,
                            is_relevant=i % 2 == 0, short_form=False) for i in range(20)]
    rows = ev.relevance_sample(docs, 10)
    assert len(rows) == 10 and sum(r[5] == "yes" for r in rows) == 5
    assert all(r[3].startswith("'=") for r in rows)                        # formula-safe cells
    labelled = [dict(zip(ev.RELEVANCE_COLUMNS, r)) for r in rows]
    for r in labelled:
        r["your_label"] = "yes" if r["doc_id"] in ("d0", "d2", "d1") else "no"
    score = ev.score_labels("relevance", labelled)
    assert score["labelled"] == 10 and 0 <= score["precision"] <= 1 and 0 <= score["agreement"] <= 1
    claims = [{"your_label": x} for x in ("supported", "partly", "not", "supported", "")]
    assert ev.score_labels("claims", claims) == {"labelled": 4, "supported": 2, "partly": 1, "not": 1,
                                                 "entailment": 0.75, "strictly_supported": 0.5}
