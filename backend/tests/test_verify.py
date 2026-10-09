"""Verification and confidence (Step 3.4, F4-9 claim mode, PRD 5.4). LLM_FAKE: no money."""

import pytest

from ctxpack import db, worker
from ctxpack.schemas.enums import RunStatus
from ctxpack.synthesis import confidence as conf
from ctxpack.synthesis import verify as vf
from ctxpack.synthesis import write as wr
from tests.test_cluster import CTX, fake  # noqa: F401  (fixture)
from tests.test_worker import approved_run, offline  # noqa: F401  (fixture)
from tests.test_write import prepared_run


def ev(members=12, authors=8, platforms=3, sources=3, engagement=60, recency=0.6, verifier="supported",
       claim_type="observed", top=0.1, thin=False) -> conf.Evidence:
    return conf.Evidence(members=members, authors=authors, platforms=platforms, sources=sources,
                         engagement_median=engagement, recency=recency, verifier=verifier, claim_type=claim_type,
                         top_author_share=top, thin_evidence=thin)


# --- confidence: PRD 5.4 worked examples and every rule ----------------------------

def test_prd_worked_example_strong():
    r = conf.assess(ev())
    assert (r.score, r.label, r.safe_to_assert) == (0.92, "strong", True)


def test_prd_worked_example_moderate():
    r = conf.assess(ev(members=10, authors=6, platforms=2))
    assert (r.score, r.label) == (0.71, "moderate")


def test_gates_are_necessary_not_sufficient():
    assert conf.assess(ev(platforms=1)).label == "moderate"            # score 0.72 but strong needs 2 platforms
    assert conf.assess(ev(verifier=None)).label == "moderate"          # strong needs "supported"
    assert conf.assess(ev(members=3, authors=3, platforms=1, sources=1)).label == "emerging"   # moderate needs 4
    assert conf.assess(ev(members=1, authors=1, platforms=1, sources=1, engagement=0, recency=0)).label == "speculative"


def test_caps():
    assert conf.assess(ev(top=0.6)).label == "emerging"                # one author > 50%
    assert conf.assess(ev(thin=True)).label == "emerging"              # thin-evidence run
    partial = conf.assess(ev(verifier="partially_supported"))
    # strong needs "supported" -> moderate, then one level down (PRD 5.4 caps) -> emerging
    assert (partial.label, partial.claim_type, partial.safe_to_assert) == ("emerging", "inferred", False)
    assert conf.assess(ev(claim_type="inferred", verifier=None)).label == "speculative"   # unverified inference
    inferred = conf.assess(ev(claim_type="inferred"))
    assert inferred.label == "strong" and not inferred.safe_to_assert   # safe needs observed


def test_unknown_engagement_and_undated_recency_use_the_config_values():
    comp = conf.components(ev(engagement=None, recency=0.5))
    assert comp["engagement"] == 0.0 and comp["recency"] == 0.5


# --- stage 1: quotes --------------------------------------------------------------------

def test_exact_quote_allows_only_whitespace_differences():
    text = "Ik wil gotver\ngewoon  zout en vet"
    assert vf.exact_quote("Ik wil gotver gewoon zout en vet", text) == "Ik wil gotver\ngewoon  zout en vet"
    assert vf.exact_quote("gewoon  zout", text) == "gewoon  zout"
    assert vf.exact_quote("gewoon zout én vet", text) is None             # one changed letter: not a quote
    assert vf.exact_quote("I want salt and fat", text) is None            # a translation is not a quote
    assert vf.exact_quote("   ", text) is None


def test_planted_fake_quote_is_removed_and_phrases_must_be_verbatim():
    ev_text = {"EV-0001": "Die gezonde snacks zijn allemaal zo duur!!", "EV-0002": "Noten vullen wel"}
    sections = {name: [] for name in wr.INSIGHT_SECTIONS}
    sections["themes"] = [{"id": "THM-01", "evidence_ids": ["EV-0001"], "quotes": [
        {"evidence_id": "EV-0001", "text": "zo duur!!"},
        {"evidence_id": "EV-0001", "text": "gezonde snacks zijn spotgoedkoop"},      # planted fake quote
        {"evidence_id": "EV-0002", "text": "zo duur"}]}]                              # real words, wrong post
    sections["phrases"] = [{"id": "PHR-01", "text": "Noten vullen", "evidence_ids": ["EV-0002"], "quotes": []},
                           {"id": "PHR-02", "text": "Noten vullen altijd", "evidence_ids": ["EV-0002"], "quotes": []}]
    sections["moments"] = [{"id": "MOM-01", "evidence_ids": ["EV-9999"], "quotes": []}]   # evidence gone
    report = vf.Report()
    vf.check_quotes(sections, ev_text, report)
    assert sections["themes"][0]["quotes"] == [{"evidence_id": "EV-0001", "text": "zo duur!!"}]
    assert (report.quotes_checked, report.quotes_removed) == (3, 2)
    assert [p["id"] for p in sections["phrases"]] == ["PHR-01"] and report.phrases_dropped == 1
    assert sections["moments"] == [] and report.items_dropped_no_evidence == 1


def test_references_to_dropped_items_and_unused_evidence_are_pruned():
    s = {name: [] for name in wr.SECTION_ORDER + ["risks"]}
    s["themes"] = [{"id": "THM-01", "evidence_ids": ["EV-0001"], "quotes": [], "segment_ids": ["SEG-01"]}]
    s["white_space"] = [{"id": "WSP-01", "evidence_ids": ["EV-0002"], "quotes": []}]
    s["opportunities"] = [{"id": "OPP-01", "builds_on": ["WSP-01", "MOT-09"], "evidence_ids": ["EV-0002"]},
                          {"id": "OPP-02", "builds_on": ["MOT-09"], "evidence_ids": ["EV-0003"]}]
    s["risks"] = [{"id": "RSK-01", "item_ids": ["THM-01", "THM-07"]}]
    s["platform_lens"] = [{"id": "PLT-01", "theme_shares": [{"theme_id": "THM-01"}, {"theme_id": "THM-07"}],
                           "evidence_ids": []}]
    evidence = [{"id": f"EV-000{i}"} for i in (1, 2, 3, 4)]
    kept = vf.prune_references(s, evidence)
    assert [o["id"] for o in s["opportunities"]] == ["OPP-01"] and s["opportunities"][0]["builds_on"] == ["WSP-01"]
    assert s["risks"][0]["item_ids"] == ["THM-01"] and s["themes"][0]["segment_ids"] == []
    assert s["platform_lens"][0]["theme_shares"] == [{"theme_id": "THM-01"}]
    assert [e["id"] for e in kept] == ["EV-0001", "EV-0002"]


# --- the stage ---------------------------------------------------------------------------

async def verified_run(monkeypatch=None, verdict_for=None):
    run_id = await prepared_run()
    await wr.write_run(run_id, CTX)
    if verdict_for:
        real = vf._fake_verdicts

        def answer(user):
            out = real(user)
            for item in out["items"]:
                item["verdict"] = verdict_for.get(item["id"], item["verdict"])
            return out
        monkeypatch.setattr(vf, "_fake_verdicts", answer)
    return run_id


async def test_verify_run_scores_every_claim_and_keeps_quotes_grounded(fake, temp_db, monkeypatch):
    run_id = await verified_run(monkeypatch, {"THM-01": "not_supported", "TEN-01": "partially_supported",
                                              "MOT-01": "nonsense"})
    rep = await vf.verify_run(run_id)
    v = db.get_run(run_id).draft["verified"]
    s = v["sections"]
    assert "THM-01" not in [t["id"] for t in s["themes"]] and rep.not_supported == 1
    ten = s["tensions"][0]
    assert ten["claim_type"] == "inferred" and ten["verification"]["verdict"] == "partially_supported"
    mot = next(m for m in s["motivations"] if m["id"] == "MOT-01")
    assert mot["verification"]["verdict"] == "unchecked" and rep.unchecked == 1       # unknown verdict, two tries
    assert rep.groundedness == 1.0 and rep.thin_evidence is True                       # 10 docs < 200
    for name in wr.INSIGHT_SECTIONS:
        for it in s[name]:
            assert it["confidence"]["label"] in conf.LEVELS and 0 <= it["confidence"]["score"] <= 1
            assert it["confidence"]["label"] != "strong" and not it["safe_to_assert"]  # thin evidence: <= emerging
    ev_ids = {e["id"] for e in v["evidence"]}
    assert all(q["evidence_id"] in ev_ids for t in s["themes"] for q in t["quotes"])
    assert db.get_run(run_id).draft["sections"]["themes"][0]["id"] == "THM-01"         # the written draft is kept

    again = await vf.verify_run(run_id)
    assert again.resumed and again.calls == 0
    redo = await vf.verify_run(run_id, redo=True)
    assert redo.calls >= 1 and not redo.resumed


async def test_the_pipeline_verifies_the_draft(offline):  # noqa: F811
    run_id = await approved_run()
    assert await worker.run_next() == run_id
    run = db.get_run(run_id)
    assert run.status == RunStatus.complete
    assert run.draft["verified"]["report"]["groundedness"] == 1.0


def test_verdict_spellings():
    assert vf.Verdict(id="X-01", verdict="Partially supported").verdict == "partially_supported"
    assert vf.Verdict(id="X-01", verdict="unsupported").verdict == "not_supported"
    assert vf.Verdict(id="X-01", verdict="maybe").verdict is None


@pytest.mark.parametrize("share,label", [(0.5, "strong"), (0.51, "emerging")])
def test_single_author_cap_boundary(share, label):
    assert conf.assess(ev(top=share)).label == label


def test_undated_posts_count_as_neutral_and_cap_a_mostly_undated_claim_at_moderate():
    """PRD 5.4, owner's change (2026-10-09): 56% of live posts had no date, so the time window could not be shown
    for them. Recency counts an undated post as 0.5; more than half undated -> at most moderate."""
    from datetime import date
    from types import SimpleNamespace

    from ctxpack.analysis import metrics as met

    today = date(2026, 10, 9)
    new, old, undated = (SimpleNamespace(posted_at=d) for d in (date(2026, 9, 1), date(2026, 5, 1), None))
    assert met.recency_share([new, new, undated, undated], today, 180) == 0.75      # (2 + 0.5 x 2) / 4
    assert met.recency_share([old, undated], today, 180) == 0.25
    assert met.recency_share([new, old], today, 180) == 0.5                          # all dated: as before
    assert met.recency_share([undated], today, 180) == 0.5                           # none dated: as before
    assert met.undated_share([new, undated, undated]) == pytest.approx(0.667, abs=1e-3)
    strong = ev(12, 8, 3, engagement=60, recency=0.6, verifier="supported")
    assert conf.assess(strong).label == "strong"                                     # worked example unchanged
    strong.undated_share = 0.5
    assert conf.assess(strong).label == "strong"                                     # half undated: allowed
    strong.undated_share = 0.6
    assert (conf.assess(strong).label, conf.assess(strong).safe_to_assert) == ("moderate", False)
