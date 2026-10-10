"""Baseline + synthesis (Step 3.3, F4-8, F4-10, F4-9 non_obvious). LLM_FAKE: no money."""

import json
from datetime import date
from pathlib import Path

from ctxpack import db, worker
from ctxpack.analysis.cluster import cluster_run
from ctxpack.analysis.metrics import compute_run
from ctxpack.schemas.enums import RunStatus
from ctxpack.schemas.plan import Plan
from ctxpack.synthesis import write as wr
from tests.test_cluster import CTX, doc, fake, row  # noqa: F401  (fixture)
from tests.test_worker import approved_run, offline  # noqa: F401  (fixture)

_RECORDED = json.loads((Path(__file__).parent / "fixtures/llm/record_plan.json").read_text())
INTERP = _RECORDED["interpretation"]
PLAN = {k: _RECORDED[k] for k in ("hypotheses", "research_questions", "starting_units")}


# --- evidence ------------------------------------------------------------------

def test_excerpt_is_an_exact_substring_around_the_first_phrase():
    short = doc(1, "Kort en krachtig.")
    assert wr.excerpt(short, 280) == "Kort en krachtig."
    long_text = ("Inleiding " * 40) + "die chips zijn echt sloffe chips geworden " + ("en verder " * 40)
    d = doc(2, long_text, extraction={"verbatim_phrases": ["sloffe chips geworden"]})
    ex = wr.excerpt(d, 280)
    assert ex in long_text and len(ex) <= 280 and "sloffe chips geworden" in ex
    assert not ex.startswith("nleiding")  # cut at a word boundary


def test_pool_is_round_robin_capped_and_lists_every_cluster_of_a_post():
    docs = {d.id: d for d in [doc(i, "x" * (100 + i)) for i in range(10)]}
    ids = list(docs)
    big = row("CL-01", "theme", ids[:6])
    small = row("CL-02", "theme", ids[5:8])
    pool = wr.select_pool([small, big], [], docs, {"evidence_per_cluster_max": 2, "evidence_per_call_max": 3})
    assert len(pool.local) == 3 and list(pool.local) == ["E01", "E02", "E03"]
    first = pool.local["E01"]
    assert first in big.verified_member_ids                     # biggest cluster first
    shared = ids[5]
    pool = wr.select_pool([small, big], [], docs, {"evidence_per_cluster_max": 3, "evidence_per_call_max": 60})
    assert pool.clusters_of[shared] == ["CL-01", "CL-02"]           # in both clusters, listed once


# --- building the draft (code checks) ---------------------------------------------

def builder(clusters, docs):
    return wr.Builder(clusters={c.id: c for c in clusters}, docs_by_id={d.id: d for d in docs}, total=len(docs),
                      today=date(2026, 10, 1), window_days=180, corpus_dates=[], trends=None,
                      outcome=wr.WriteOutcome())


def test_items_need_their_own_cluster_and_its_evidence():
    docs = [doc(i, f"Post nummer {i} over chips") for i in range(6)]
    theme = row("CL-01", "theme", [d.id for d in docs[:4]])
    other = row("CL-02", "objection", [d.id for d in docs[4:]], kind="objection")
    bld = builder([theme, other], docs)
    pool = wr.select_pool([theme, other], [], bld.docs_by_id, {"evidence_per_cluster_max": 3,
                                                               "evidence_per_call_max": 60})
    local = {v: k for k, v in pool.local.items()}
    e_theme, e_other = local[docs[0].id], local[docs[4].id]

    ok = wr.ThemeOut(cluster_id="cl-01", claim="c", label="l", evidence=[e_theme, e_other, "E99"],
                     quotes=[{"evidence": e_theme, "text": "Post nummer"}], claim_type="external")
    item = bld.item("themes", ok, {"theme"}, pool, label="l")
    assert item["evidence_docs"] == [docs[0].id] and item["claim_type"] == "inferred"
    assert item["counts"] == {"matching": 4, "of_total": 6}          # numbers from code, never the writer
    assert bld.outcome.dropped == {"evidence_not_in_cluster": 2}

    wrong_kind = wr.ThemeOut(cluster_id="CL-02", claim="c", label="l", evidence=[e_other])
    assert bld.item("themes", wrong_kind, {"theme"}, pool) is None
    no_evidence = wr.ThemeOut(cluster_id="CL-01", claim="c", label="l", evidence=[e_other])
    assert bld.item("themes", no_evidence, {"theme"}, pool) is None
    assert bld.outcome.dropped["wrong_or_unknown_cluster"] == 1 and bld.outcome.dropped["no_evidence_left"] == 1


def test_a_culture_item_counts_only_the_posts_that_show_it():
    """One hashtag or creator never carries its whole cluster's counts (eval 2026-10-10: '#GymTok' strong on 12)."""
    texts = ["Sunday prep #GymTok", "prep with me, gymtok approved", "Prep day again", "Prep day number 4",
             "Week prep", "Batch prep"]
    docs = [doc(i, t) for i, t in enumerate(texts)]
    fmt = row("CL-07", "theme", [d.id for d in docs])
    bld = builder([fmt], docs)
    pool = wr.select_pool([fmt], [], bld.docs_by_id, {"evidence_per_cluster_max": 6, "evidence_per_call_max": 60})
    local = {v: k for k, v in pool.local.items()}
    tag = wr.CultureOut(cluster_id="CL-07", claim="#GymTok is tagged on prep videos", kind="code", name="#GymTok",
                        evidence=[local[docs[0].id]])
    item = bld.item("culture", tag, {"theme"}, pool, kind="code", name="#GymTok")
    assert item["counts"]["matching"] == 2                     # the two posts that say it, not the cluster's 6
    one = wr.CultureOut(cluster_id="CL-07", claim="Posters invite you to prep with them", kind="format",
                        name="prep with me", evidence=[local[docs[3].id]])
    item = bld.item("culture", one, {"theme"}, pool, kind="format", name="prep with me")
    assert item["counts"]["matching"] == 2                     # the post that says it + the cited one
    described = wr.CultureOut(cluster_id="CL-07", claim="Weekly prep posts", kind="format",
                              name="weekly prep posts", evidence=[local[docs[4].id]])
    item = bld.item("culture", described, {"theme"}, pool, kind="format", name="weekly prep posts")
    assert item["counts"]["matching"] == 6                     # no post says it word for word: the cluster's count
    theme = wr.ThemeOut(cluster_id="CL-07", claim="c", label="l", evidence=[local[docs[0].id]])
    assert bld.item("themes", theme, {"theme"}, pool, label="l")["counts"]["matching"] == 6   # themes: whole cluster


def test_ids_by_rank_and_evidence_numbered_by_first_use():
    items = [{"cluster_id": "CL-02", "counts": {"matching": 3}, "evidence_docs": ["d2", "d1"]},
             {"cluster_id": "CL-01", "counts": {"matching": 9}, "evidence_docs": ["d1"]},
             {"cluster_id": "CL-01", "counts": {"matching": 9}, "evidence_docs": ["d3"]}]   # same cluster twice
    ranked = wr._rank(items, "THM")
    assert [(i["id"], i["cluster_id"]) for i in ranked] == [("THM-01", "CL-01"), ("THM-02", "CL-02")]
    sections = {name: [] for name in wr.SECTION_ORDER}
    sections["themes"] = ranked
    docs = {f"d{i}": doc(i).model_copy(update={"id": f"d{i}"}) for i in (1, 2, 3)}
    evidence = wr.number_evidence(sections, docs, 280)
    assert [e["id"] for e in evidence] == ["EV-0001", "EV-0002"]
    assert ranked[0]["evidence_ids"] == ["EV-0001"] and ranked[1]["evidence_ids"] == ["EV-0002", "EV-0001"]


# --- the stage ---------------------------------------------------------------------

async def prepared_run():
    run = db.create_run("snacks in NL")
    db.update_run(run.id, interpretation=INTERP, plan=PLAN)
    docs = [doc(i, f"Ik eet graag chips nummer {i}, echt lekker" + (" op zondag" if i % 4 == 0 else ""),
                extraction={"verbatim_phrases": [f"chips nummer {i}"], "pains": ["duur"] if i % 2 else [],
                            "brand_mentions": [{"name": "Lays", "stance": "negative"}] if i < 4 else []})
            for i in range(10)]
    db.save_documents([d.model_copy(update={"run_id": run.id}) for d in docs])
    await cluster_run(run.id, CTX)
    compute_run(run.id)
    return run.id


async def test_write_run_builds_a_draft_whose_evidence_all_checks_out(fake, temp_db, monkeypatch):
    run_id = await prepared_run()
    out = await wr.write_run(run_id, CTX)
    draft = db.get_run(run_id).draft
    s = draft["sections"]
    assert len(draft["generic_points"]) >= 8
    assert s["themes"] and s["tensions"] and s["lexicon"] and s["white_space"] and s["competitors"]
    assert wr.check_draft(draft, db.get_clusters(run_id)) == []
    t = s["tensions"][0]
    assert t["id"] == "TEN-01" and t["want"]["evidence_ids"] and t["but"]["evidence_ids"]
    assert all(it["non_obvious"] is True for it in s["themes"])          # fake: nothing covered
    assert s["opportunities"] and s["opportunities"][0]["builds_on"]
    assert len(s["hypotheses"]) == len(Plan.model_validate(PLAN).hypotheses)
    ev_ids = [e["id"] for e in draft["evidence"]]
    assert ev_ids == [f"EV-{i:04d}" for i in range(1, len(ev_ids) + 1)]
    assert all(e["text"] in next(d.text for d in db.get_documents(run_id) if d.id == e["doc_id"])
               for e in draft["evidence"])
    assert out.calls == 6           # baseline, A, B, non_obvious, consolidation (borderline pairs), notes (V4)
    assert "notes" in draft and isinstance(draft["notes"]["meta"], dict)

    calls = []
    real = wr.structured
    monkeypatch.setattr(wr, "structured", lambda *a, **k: calls.append(a[4]) or real(*a, **k))
    again = await wr.write_run(run_id, CTX)
    assert again.resumed and calls == []                                # a saved draft is never paid for again


async def test_check_draft_finds_foreign_evidence(fake, temp_db):
    run_id = await prepared_run()
    await wr.write_run(run_id, CTX)
    draft = db.get_run(run_id).draft
    clusters = db.get_clusters(run_id)
    theme = draft["sections"]["themes"][0]
    draft["evidence"].append({"id": "EV-0998", "doc_id": "DOC-not-a-member"})  # a post from outside the cluster
    theme["evidence_ids"].append("EV-0998")
    theme["evidence_ids"].append("EV-9999")
    problems = wr.check_draft(draft, clusters)
    assert any("does not resolve" in p for p in problems) and any("is not in" in p for p in problems)


async def test_the_pipeline_writes_a_draft(offline):  # noqa: F811
    run_id = await approved_run()
    assert await worker.run_next() == run_id
    run = db.get_run(run_id)
    assert run.status == RunStatus.complete
    assert run.draft["sections"]["themes"] and wr.check_draft(run.draft, db.get_clusters(run_id)) == []
