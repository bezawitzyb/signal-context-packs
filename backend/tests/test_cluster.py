"""Clustering, membership check and metrics (Step 3.2, F4-7, F4-9, PRD 5.3-5.5). LLM_FAKE: no money."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from ctxpack import db, worker
from ctxpack.analysis import cluster as clu
from ctxpack.analysis import metrics as met
from ctxpack.analysis.cluster import ClusterAnswer, ClusterOutcome, cluster_run, code_check, digests, to_rows
from ctxpack.collect.relevance import BriefContext
from ctxpack.config import get_settings
from ctxpack.db import ClusterRow
from ctxpack.schemas.document import Document
from ctxpack.schemas.enums import Platform, RunStatus
from tests.test_worker import approved_run, offline  # noqa: F401  (fixture)

CTX = BriefContext(topic="snacks", market="NL", languages=["nl"], audience="Dutch snackers")
H = "a" * 63  # author hash prefix: H + one hex digit = a valid sha256 hex string


def doc(i: int, text: str = "Ik eet graag chips na het sporten.", *, author: str | None = None,
        platform: Platform = Platform.web_forum, short: bool = False, extraction: dict | None = None,
        **kw) -> Document:
    ex = {"needs": [], "pains": [], "objections": [], "questions": [], "unanswered_question": None,
          "brand_mentions": [], "verbatim_phrases": [], "stance": "neutral", "emotion": [],
          "humour_or_irony": False, "code_switching": False, "time_occasion_cues": [], **(extraction or {})}
    return Document(id=f"DOC-{i:016d}", run_id="run_x", platform=platform, source_unit=f"web:site{i % 3}.nl",
                    url=f"https://site{i % 3}.nl/t/{i}", text=text, language="nl", is_relevant=True,
                    author_hash=author, short_form=short, extraction=ex, **kw)


def row(cid: str, cluster_kind: str, members: list[str], verified: list[str] | None = None,
        **details) -> ClusterRow:
    return ClusterRow(run_id="run_x", id=cid, kind=cluster_kind, label=f"label {cid}", member_ids=members,
                      verified_member_ids=members if verified is None else verified,
                      details={"point": f"point {cid}", **details})


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("LLM_FAKE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- digests and the clusterer's answer ---------------------------------------

def test_digests_use_short_ids_mark_short_posts_and_shrink_to_fit():
    docs = [doc(1, "x" * 500, extraction={"pains": ["too expensive"], "verbatim_phrases": ["xxx"],
                                          "brand_mentions": [{"name": "AH", "stance": "positive"}]}),
            doc(2, "lekker", short=True)]
    text, aliases = digests(docs, max_chars=100_000, summary_chars=160)
    assert aliases == {"D001": docs[0].id, "D002": docs[1].id}
    line1, line2 = text.split("\n")
    assert line1.startswith("D001 | web_forum |") and "pains: too expensive" in line1 and "AH (positive)" in line1
    assert "summary: " + "x" * 160 + " |" in line1
    assert line2 == "D002 SHORT | web_forum | text: lekker"
    small, _ = digests(docs, max_chars=len(text) - 100, summary_chars=160)
    assert len(small) <= len(text) - 100 and "summary: " + "x" * 40 + " |" in small  # 160 -> 80 -> 40


def test_answer_maps_ids_drops_invented_and_keeps_short_posts_for_lexicon_only():
    aliases = {"D001": "DOC-1", "D002": "DOC-2", "D003": "DOC-S"}
    answer = ClusterAnswer.model_validate({
        "themes": [{"label": "Snacking as a reward", "point": "p", "member_ids": ["D001", "d002", "D003", "D999"]}],
        "tensions": [{"label": "health vs taste", "want": {"text": "healthy", "member_ids": ["D001"]},
                      "but": {"text": "tasty wins", "member_ids": ["D002"]}},
                     {"label": "one-sided", "want": {"text": "x", "member_ids": ["D001"]},
                      "but": {"text": "y", "member_ids": []}}],
        "lexicon": [{"term": "lekker", "meaning": "tasty", "language": "NL", "member_ids": ["D003", "D001"]}],
        "segments": [{"label": "empty", "point": "p", "member_ids": ["D999"]}],
    })
    out = ClusterOutcome()
    rows = to_rows(answer, aliases, {"DOC-S"}, out)
    assert [(r.id, r.kind) for r in rows] == [("CL-01", "theme"), ("CL-02", "tension_want"),
                                              ("CL-03", "tension_but"), ("CL-04", "lexicon")]
    assert rows[0].member_ids == ["DOC-1", "DOC-2"]           # short post and invented id left out
    assert rows[1].details["pair_id"] == "CL-03" and rows[2].details["pair_id"] == "CL-02"
    assert rows[3].member_ids == ["DOC-S", "DOC-1"] and rows[3].details["language"] == "nl"
    assert out.invented_ids == 2


def test_lexicon_and_competitor_members_are_checked_in_code():
    docs = {d.id: d for d in [doc(1, "Echt lekker die Lays"), doc(2, "Niet te eten"),
                              doc(3, "Chips van de AH", extraction={"brand_mentions": [{"name": "Albert Heijn",
                                                                                         "stance": "neutral"}]})]}
    ids = list(docs)
    lex = row("CL-01", "lexicon", ids, term="Lekker")
    assert code_check(lex, docs) == [ids[0]]
    comp = row("CL-02", "competitor", ids, name="Albert Heijn", aliases=["Lay's", "lays"])
    assert code_check(comp, docs) == [ids[0], ids[2]]
    assert code_check(row("CL-03", "theme", ids), docs) is None


# --- membership check (fake worker) -------------------------------------------

async def test_membership_keeps_only_confirmed_members_with_one_retry(fake, monkeypatch):
    docs = {d.id: d for d in [doc(i) for i in range(6)]}
    ids = list(docs)
    rows = [row("CL-01", "theme", ids, verified=[]), row("CL-02", "lexicon", ids[:2], verified=[], term="chips")]
    calls = []

    def answer(user):
        calls.append(user)
        sent = __import__("re").findall(r'<untrusted_user_content id="([^"]+)">', user)
        if len(calls) == 1:  # says no to the first post and skips the last one
            return {"items": [{"id": i, "member": i != ids[0]} for i in sent if i != ids[-1]]}
        return {"items": [{"id": i, "member": True} for i in sent]}

    monkeypatch.setattr(clu, "_fake_membership", answer)
    out = ClusterOutcome()
    await clu.verify_members(rows, docs, out)
    assert rows[0].verified_member_ids == ids[1:] and rows[0].details["verified"] is True
    assert rows[1].verified_member_ids == ids[:2]           # lexicon: in code, no worker call
    assert len(calls) == 2 and ids[-1] in calls[1] and ids[0] not in calls[1]
    assert "Cluster point: point CL-01" in calls[0]
    assert (out.proposed, out.verified, out.rejected, out.unchecked) == (8, 7, 1, 0)
    assert out.by_cluster["CL-01"] == {"proposed": 6, "verified": 5, "rejected": 1}


async def test_pairs_without_a_verdict_are_not_counted(fake, monkeypatch):
    docs = {d.id: d for d in [doc(i) for i in range(3)]}
    rows = [row("CL-01", "theme", list(docs), verified=[])]
    monkeypatch.setattr(clu, "_fake_membership", lambda user: {"items": []})
    out = ClusterOutcome()
    await clu.verify_members(rows, docs, out)
    assert rows[0].verified_member_ids == [] and out.unchecked == 3 and out.calls == 2


# --- metrics (code only) --------------------------------------------------------

def test_changing_members_changes_counts_and_strength():
    docs = {d.id: d for d in [doc(1, author=H + "1"), doc(2, author=H + "1"), doc(3, author=H + "2"),
                              doc(4, platform=Platform.reddit, author=H + "3"), doc(5, short=True)]}
    ids = list(docs)
    c = row("CL-01", "theme", ids, verified=ids[:2])
    m1 = met.cluster_metrics(c, docs, 4, date(2026, 10, 1), 180, [], None)
    assert m1["counts"] == {"matching": 2, "of_total": 4}
    assert m1["strength"]["distinct_authors"] == 1 and m1["strength"]["platforms"] == ["web_forum"]
    c.verified_member_ids = ids                              # now with doc 3, the reddit post and a short post
    m2 = met.cluster_metrics(c, docs, 4, date(2026, 10, 1), 180, [], None)
    assert m2["counts"]["matching"] == 4                     # short_form never counted
    assert m2["strength"]["distinct_authors"] == 3 and m2["strength"]["platforms"] == ["reddit", "web_forum"]


def test_pages_without_authors_count_as_one_author_each():
    ms = [doc(1), doc(4), doc(2)]  # site1, site1, site2 - but different URLs (pages)
    assert met.strength(ms)["distinct_authors"] == 3
    same_page = [doc(1), doc(1).model_copy(update={"id": "DOC-x"})]
    assert met.strength(same_page)["distinct_authors"] == 1


def test_emotion_mix_dissatisfaction_and_saturation():
    ms = [doc(1, extraction={"emotion": ["frustration", "frustration"], "stance": "negative"}),
          doc(2, extraction={"emotion": ["nostalgia"], "brand_mentions": [{"name": "AH", "stance": "positive"}]}),
          doc(3, extraction={"unanswered_question": "Waar koop je dit?"}),
          doc(4)]
    assert met.emotion_mix(ms) == [{"emotion": "frustration", "share": 0.25}, {"emotion": "nostalgia", "share": 0.25}]
    assert met.dissatisfaction(ms) == 0.5 and met.saturation(ms) == 0.25


def test_recency_and_undated():
    today = date(2026, 10, 1)
    ms = [doc(i, posted_at=today - timedelta(days=d)) for i, d in enumerate([10, 20, 100, 150])]
    assert met.recency_share(ms, today, 180) == 0.5 and met.recency_month(ms) == "2026-06"  # lower median of 4
    assert met.recency_share([doc(1)], today, 180) == 0.5 and met.recency_month([doc(1)]) is None


def test_momentum_needs_enough_dated_members_and_trends_agreeing():
    start = date(2026, 1, 1)
    corpus = [start + timedelta(days=i) for i in range(0, 120, 2)]          # 60 posts over ~17 weeks
    rising = [doc(i, posted_at=start + timedelta(days=d)) for i, d in enumerate(range(80, 120, 1))][:40]
    rising += [doc(100 + i, posted_at=start + timedelta(days=i)) for i in range(5)]
    assert met.trend(rising, corpus, "rising") == "rising"
    assert met.trend(rising, corpus, None) == "insufficient_data"          # no Trends data
    assert met.trend(rising, corpus, "fading") == "insufficient_data"      # Trends disagrees
    assert met.trend(rising[:10], corpus, "rising") == "insufficient_data" # too few dated members
    signals = {"external_signals": [{"series": {"a": {"trend": "rising"}, "b": {"trend": "rising"},
                                                "c": {"trend": "stable"}}}]}
    assert met.trends_direction(signals) == "rising" and met.trends_direction({}) is None


def test_whats_new_needs_a_clear_recent_burst():
    today = date(2026, 10, 1)
    old = [doc(i, posted_at=today - timedelta(days=100)) for i in range(20)]
    new = [doc(50 + i, posted_at=today - timedelta(days=5)) for i in range(4)]
    docs = old + new
    by_id = {d.id: d for d in docs}
    burst = row("CL-01", "theme", [d.id for d in new] + [old[0].id])
    steady = row("CL-02", "theme", [d.id for d in old[:10]] + [new[0].id])
    out = met.whats_new([burst, steady], docs, by_id, today)
    assert [o["cluster_id"] for o in out] == ["CL-01"] and out[0]["recent_members"] == 4


def test_what_performs_caps_authors_and_threads():
    docs = [doc(i, author=H + str(i % 2), thread_id=f"t{i % 4}", engagement_percentile=99 - i) for i in range(8)]
    docs.append(doc(20, engagement_percentile=None))
    out = met.what_performs(docs)
    # authors alternate 0/1 (max 2 each), threads t0..t3 (max 1 each)
    assert [o["doc_id"] for o in out] == [docs[0].id, docs[1].id, docs[2].id, docs[3].id]


def test_competitor_shares_list_only_brands_with_three_mentions():
    comps = [row("CL-01", "competitor", []), row("CL-02", "competitor", []), row("CL-03", "competitor", [])]
    for c, n in zip(comps, [6, 3, 1]):
        c.metrics = {"counts": {"matching": n, "of_total": 50}}
    out = met.competitor_shares(comps)
    assert [(o["cluster_id"], o["mentions"], o["share"]) for o in out] == [("CL-01", 6, 0.6), ("CL-02", 3, 0.3)]


def test_opportunity_score_follows_prd_5_5():
    def c(cid, cluster_kind, n, diss=0.5, sat=0.2, **details):
        r = row(cid, cluster_kind, [], **details)
        r.metrics = {"counts": {"matching": n, "of_total": 100}, "dissatisfaction": diss, "saturation": sat}
        return r

    clusters = [c("CL-01", "motivation", 20, kind="need"), c("CL-02", "white_space", 5, diss=1.0, sat=0.0),
                c("CL-03", "motivation", 10, kind="pain"), c("CL-04", "theme", 10), c("CL-05", "lexicon", 99)]
    out = met.opportunities(clusters)
    p90 = met.percentile([20, 5, 10, 10], 90)                      # lexicon is not in the demand pool
    assert [o["cluster_id"] for o in out] == ["CL-01", "CL-02"]    # needs and white space only
    first = out[0]["components"]
    assert first["demand"] == round(min(1, 20 / p90), 3)
    assert out[0]["score_if_non_obvious"] == round(first["demand"] * 0.5 * 1.0 * 0.8, 3)
    assert met.opportunity_score({"demand": 1, "dissatisfaction": 0.5, "saturation": 0.2}, False) == (0.16, 0.4)


def test_coverage_grade():
    assert met.coverage_grade(320, ["reddit", "tiktok", "youtube", "web_forum"], ["nl", "en"], ["nl", "en"]) == "a"
    assert met.coverage_grade(320, ["reddit", "tiktok", "youtube", "web_forum"], ["nl"], ["nl", "en"]) == "b"
    assert met.coverage_grade(150, ["reddit", "web_forum"], ["nl"], ["nl"]) == "c"
    assert met.coverage_grade(99, ["reddit", "web_forum"], ["nl"], ["nl"]) == "d"
    assert met.coverage_grade(500, ["web_forum"], ["nl"], ["nl"]) == "d"


def test_platform_lens_needs_fifteen_posts():
    docs = [doc(i, extraction={"emotion": ["humour"]}) for i in range(15)] + \
           [doc(100 + i, platform=Platform.reddit) for i in range(14)]
    by_id = {d.id: d for d in docs}
    theme = row("CL-01", "theme", [d.id for d in docs[:6]] + [docs[20].id])
    lenses = met.platform_lens([theme], docs, by_id)
    assert [lens["platform"] for lens in lenses] == ["web_forum"]
    assert lenses[0]["theme_shares"] == [{"cluster_id": "CL-01", "label": "label CL-01", "share": 0.4}]
    assert lenses[0]["emotion_mix"] == [{"emotion": "humour", "share": 1.0}]


# --- the stage, saved to the database ---------------------------------------------

async def test_cluster_run_saves_clusters_and_a_resume_skips_the_paid_call(fake, temp_db, monkeypatch):
    run = db.create_run("snacks in NL")
    plan = json.loads((Path(__file__).parent / "fixtures/llm/record_plan.json").read_text())
    db.update_run(run.id, interpretation=plan["interpretation"])
    docs = [doc(i, f"Ik eet graag chips nummer {i}",
                extraction={"verbatim_phrases": [f"chips nummer {i}"],
                            "brand_mentions": [{"name": "Lays", "stance": "positive"}] if i < 3 else []})
            for i in range(8)] + [doc(50, "lekker", short=True)]
    db.save_documents([d.model_copy(update={"run_id": run.id}) for d in docs])

    out = await cluster_run(run.id, CTX)
    rows = db.get_clusters(run.id)
    kinds = {r.kind for r in rows}
    assert {"theme", "motivation", "tension_want", "tension_but", "segment", "lexicon", "competitor",
            "white_space"} <= kinds
    assert all(r.details["verified"] for r in rows) and out.calls >= 2 and not out.resumed
    theme = next(r for r in rows if r.kind == "theme")
    assert docs[-1].id not in theme.member_ids                       # short post: lexicon only
    lex = next(r for r in rows if r.kind == "lexicon")
    assert docs[-1].id in lex.member_ids

    calls = []
    real = clu.structured
    monkeypatch.setattr(clu, "structured", lambda *a, **k: calls.append(a[4]) or real(*a, **k))
    again = await cluster_run(run.id, CTX)
    assert again.resumed and calls == []                             # nothing paid again

    run_metrics = met.compute_run(run.id)
    theme = next(r for r in db.get_clusters(run.id) if r.kind == "theme")
    assert theme.metrics["counts"] == {"matching": 8, "of_total": 8}
    assert run_metrics["competitors"][0]["name"] == "Lays" and run_metrics["coverage"]["grade"] == "d"
    assert db.get_run(run.id).analysis["relevant_counted"] == 8


async def test_the_pipeline_clusters_and_computes_metrics(offline):  # noqa: F811
    run_id = await approved_run()
    assert await worker.run_next() == run_id
    run = db.get_run(run_id)
    assert run.status == RunStatus.complete
    clusters = db.get_clusters(run_id)
    assert clusters and all(c.metrics and c.details["verified"] for c in clusters)
    assert run.analysis["coverage"]["grade"] in {"a", "b", "c", "d"}


def test_brands_come_from_the_extraction_and_merge_spellings():
    docs = [doc(1, extraction={"brand_mentions": [{"name": "Lay's", "stance": "negative"}]}),
            doc(2, extraction={"brand_mentions": [{"name": "Lays", "stance": "neutral"},
                                                  {"name": "AH", "stance": "positive"}]}),
            doc(3, extraction={"brand_mentions": [{"name": "Lay's", "stance": "neutral"}]}),
            doc(4, short=True, extraction={"brand_mentions": [{"name": "Croky", "stance": "neutral"}]})]
    rows = [row("CL-01", "theme", [docs[0].id]),
            row("CL-02", "competitor", [docs[1].id], name="Albert Heijn", aliases=["AH"])]
    assert clu.add_brand_clusters(rows, docs) == 1
    lays = rows[-1]
    assert (lays.id, lays.kind, lays.label) == ("CL-03", "competitor", "Lay's")
    assert lays.member_ids == [docs[0].id, docs[1].id, docs[2].id] and lays.details["aliases"] == ["Lays"]
    assert clu.add_brand_clusters(rows, docs) == 1 and len(rows) == 3  # rebuilt, not duplicated
    assert all(docs[3].id not in r.member_ids for r in rows)         # short posts never counted
    by_id = {d.id: d for d in docs}
    assert code_check(lays, by_id) == lays.member_ids


def test_brand_spellings_brackets_accents_and_products_merge():
    names = ["Lay's paprika", "Lays", "AH (Albert Heijn)", "Albert Heijn", "AH chips", "Calvé", "Calve", "Croky"]
    docs = [doc(i, extraction={"brand_mentions": [{"name": n, "stance": "neutral"}]}) for i, n in enumerate(names)]
    rows: list = []
    clu.add_brand_clusters(rows, docs)
    groups = {r.label: len(r.member_ids) for r in rows}
    assert groups == {"Lays": 2, "AH (Albert Heijn)": 3, "Calvé": 2, "Croky": 1} or \
           groups == {"Lays": 2, "AH (Albert Heijn)": 3, "Calve": 2, "Croky": 1}
    rows.insert(0, row("CL-01", "theme", [docs[0].id]))
    clu.add_brand_clusters(rows, docs)                               # rebuilt, not duplicated
    assert sum(r.kind == "competitor" for r in rows) == 4
