"""Counts, strength, emotion mixes, platform lens, momentum, what's new, what performs,
competitor shares, opportunity components and the coverage grade (PRD 5.3-5.5, FR-C6).

Code only: no model ever outputs these numbers. Every count comes from VERIFIED
cluster members, and short_form posts are never counted (not as members, not
in totals). Thresholds live in config/scoring.yaml.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import date, timedelta
from typing import Any, Iterable

from ctxpack.config import load_yaml
from ctxpack.schemas.enums import ClusterKind, Trend

# Clusters that are claims about people (demand pool for opportunity scores); lexicon and
# competitor clusters are word and brand lists, not claims.
CLAIM_KINDS = {ClusterKind.theme, ClusterKind.motivation, ClusterKind.tension_want, ClusterKind.tension_but,
               ClusterKind.objection, ClusterKind.segment, ClusterKind.moment, ClusterKind.white_space}


def _scoring() -> dict:
    return load_yaml("scoring")


# --------------------------------------------------------------------------
# One cluster
# --------------------------------------------------------------------------


def members(cluster: Any, docs_by_id: dict[str, Any]) -> list[Any]:
    """Verified members that count: known docs, short_form excluded."""
    return [docs_by_id[i] for i in cluster.verified_member_ids
            if i in docs_by_id and not docs_by_id[i].short_form]


def author_key(doc: Any) -> str:
    """PRD 5.4: a distinct author hash; a web page with no detectable authors counts as one author."""
    return doc.author_hash or f"page:{doc.url}"


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (q in 0-100)."""
    vals = sorted(values)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * q / 100
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def strength(ms: list[Any]) -> dict[str, Any]:
    engagement = [d.engagement_percentile for d in ms if d.engagement_percentile is not None]
    return {"evidence_count": len(ms),
            "distinct_authors": len({author_key(d) for d in ms}),
            "platforms": sorted({str(d.platform) for d in ms}),
            "distinct_sources": len({d.source_unit for d in ms}),
            "engagement_percentile_median": round(statistics.median(engagement), 1) if engagement else None}


def recency_share(ms: list[Any], today: date, window_days: int) -> float:
    """PRD 5.4 (owner's change, 2026-10-09): (dated members in the newer half of the window + 0.5 per undated
    member) / all members. An undated post is neutral, not left out; all dated -> unchanged; none dated -> 0.5."""
    if not ms:
        return _scoring()["confidence"]["recency_if_undated"]
    cutoff = today - timedelta(days=window_days / 2)
    newer = sum(1 for d in ms if d.posted_at and d.posted_at >= cutoff)
    undated = sum(1 for d in ms if not d.posted_at)
    return round((newer + _scoring()["confidence"]["recency_if_undated"] * undated) / len(ms), 3)


def undated_share(ms: list[Any]) -> float:
    """Share of members without a posting date (PRD 5.4 undated cap)."""
    return round(sum(1 for d in ms if not d.posted_at) / len(ms), 3) if ms else 0.0


def recency_month(ms: list[Any]) -> str | None:
    """Median date of dated members, as YYYY-MM."""
    dated = sorted(d.posted_at for d in ms if d.posted_at)
    return dated[(len(dated) - 1) // 2].strftime("%Y-%m") if dated else None


def emotion_mix(ms: list[Any]) -> list[dict[str, Any]]:
    """Share of members expressing each emotion, biggest first."""
    counts = Counter(e for d in ms for e in set((d.extraction or {}).get("emotion", [])))
    return [{"emotion": e, "share": round(n / len(ms), 3)}
            for e, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))] if ms else []


def dissatisfaction(ms: list[Any]) -> float:
    """PRD 5.5: share of members with a pain, a negative stance, frustration or an unanswered question."""
    def unhappy(d: Any) -> bool:
        ex = d.extraction or {}
        return bool(ex.get("pains") or ex.get("stance") == "negative" or "frustration" in ex.get("emotion", [])
                    or ex.get("unanswered_question"))
    return round(sum(map(unhappy, ms)) / len(ms), 3) if ms else 0.0


def saturation(ms: list[Any]) -> float:
    """PRD 5.5: share of members naming a brand or product as solving it (brand mention + positive stance)."""
    def served(d: Any) -> bool:
        return any(b.get("stance") == "positive" for b in (d.extraction or {}).get("brand_mentions", []))
    return round(sum(map(served, ms)) / len(ms), 3) if ms else 0.0


def trends_direction(collection: dict | None) -> str | None:
    """The most common Google Trends direction among the run's external signals; None without Trends data."""
    directions = [s.get("trend") for sig in (collection or {}).get("external_signals", [])
                  for s in (sig.get("series") or {}).values() if s.get("trend")]
    return Counter(directions).most_common(1)[0][0] if directions else None


def trend(ms: list[Any], corpus_dates: list[date], trends: str | None) -> str:
    """rising / stable / fading only with enough dated members over enough weeks AND Trends agreeing.

    The members' share of the corpus in the last third of the corpus's date range is compared with
    their share in the first third, so a burst of collection in one month is not read as momentum.
    """
    m = _scoring()["metrics"]
    dated = sorted(d.posted_at for d in ms if d.posted_at)
    if len(dated) < m["momentum_min_dated"] or (dated[-1] - dated[0]).days < 7 * m["momentum_min_weeks"]:
        return Trend.insufficient_data.value
    start, end = min(corpus_dates), max(corpus_dates)
    third = (end - start) / 3
    first_end, last_start = start + third, end - third

    def share(lo: date, hi: date) -> float | None:
        corpus = sum(lo <= p <= hi for p in corpus_dates)
        return sum(lo <= p <= hi for p in dated) / corpus if corpus else None

    first, last = share(start, first_end), share(last_start, end)
    if not first or last is None:
        return Trend.insufficient_data.value
    change = (last - first) / first
    direction = "rising" if change > m["momentum_change"] else "fading" if change < -m["momentum_change"] else "stable"
    return direction if trends == direction else Trend.insufficient_data.value


def cluster_metrics(cluster: Any, docs_by_id: dict[str, Any], total: int, today: date, window_days: int,
                    corpus_dates: list[date], trends: str | None) -> dict[str, Any]:
    ms = members(cluster, docs_by_id)
    return {"counts": {"matching": len(ms), "of_total": total},
            "strength": strength(ms),
            "recency_share": recency_share(ms, today, window_days),
            "recency": recency_month(ms),
            "emotion_mix": emotion_mix(ms),
            "dissatisfaction": dissatisfaction(ms),
            "saturation": saturation(ms),
            "trend": trend(ms, corpus_dates, trends)}


# --------------------------------------------------------------------------
# Whole run
# --------------------------------------------------------------------------


def platform_lens(themes: list[Any], docs: list[Any], docs_by_id: dict[str, Any]) -> list[dict[str, Any]]:
    """Per platform with enough relevant posts: theme shares and emotion mix."""
    m = _scoring()["metrics"]
    by_platform: dict[str, list[Any]] = {}
    for d in docs:
        by_platform.setdefault(str(d.platform), []).append(d)
    lenses = []
    for platform, pdocs in sorted(by_platform.items(), key=lambda kv: -len(kv[1])):
        if len(pdocs) < m["platform_lens_min_docs"]:
            continue
        shares = []
        for t in themes:
            on_platform = sum(1 for d in members(t, docs_by_id) if str(d.platform) == platform)
            if on_platform:
                shares.append({"cluster_id": t.id, "label": t.label, "share": round(on_platform / len(pdocs), 3)})
        lenses.append({"platform": platform, "kept_posts": len(pdocs),
                       "theme_shares": sorted(shares, key=lambda s: -s["share"]),
                       "emotion_mix": emotion_mix(pdocs)})
    return lenses


def whats_new(clusters: list[Any], docs: list[Any], docs_by_id: dict[str, Any], today: date) -> list[dict]:
    """Themes and terms clearly more frequent in the last 30 days than the corpus as a whole."""
    m = _scoring()["metrics"]
    since = today - timedelta(days=m["whats_new_days"])
    dated = [d.posted_at for d in docs if d.posted_at]
    corpus_share = sum(p >= since for p in dated) / len(dated) if dated else 0.0
    if not corpus_share:
        return []
    out = []
    for c in clusters:
        if c.kind not in (ClusterKind.theme, ClusterKind.lexicon):
            continue
        cdated = [d.posted_at for d in members(c, docs_by_id) if d.posted_at]
        recent = sum(p >= since for p in cdated)
        if cdated and recent >= m["whats_new_min_members"]:
            ratio = (recent / len(cdated)) / corpus_share
            if ratio >= m["whats_new_min_ratio"]:
                out.append({"cluster_id": c.id, "label": c.label, "recent_members": recent, "ratio": round(ratio, 2)})
    return sorted(out, key=lambda x: -x["ratio"])


def what_performs(docs: list[Any]) -> list[dict[str, Any]]:
    """Top posts by engagement percentile: at most 2 per author and 1 per thread."""
    m = _scoring()["metrics"]
    authors: Counter = Counter()
    threads: Counter = Counter()
    out = []
    for d in sorted((d for d in docs if d.engagement_percentile is not None),
                    key=lambda d: (-d.engagement_percentile, d.id)):
        thread = d.thread_id or d.id
        if authors[author_key(d)] >= m["what_performs_per_author"] or threads[thread] >= m["what_performs_per_thread"]:
            continue
        authors[author_key(d)] += 1
        threads[thread] += 1
        out.append({"doc_id": d.id, "platform": str(d.platform), "url": d.permalink or d.url,
                    "engagement_percentile": d.engagement_percentile})
        if len(out) >= m["what_performs_max"]:
            break
    return out


def competitor_shares(clusters: list[Any]) -> list[dict[str, Any]]:
    """Share of all competitor mentions; brands with fewer than 3 mentions are not listed."""
    m = _scoring()["metrics"]
    comps = [(c, c.metrics["counts"]["matching"]) for c in clusters if c.kind == ClusterKind.competitor]
    total = sum(n for _, n in comps)
    return sorted(({"cluster_id": c.id, "name": c.label, "mentions": n, "share": round(n / total, 3)}
                   for c, n in comps if n >= m["competitor_min_mentions"]), key=lambda x: -x["mentions"])


def opportunity_score(components: dict[str, float], non_obvious: bool) -> tuple[float, float]:
    """PRD 5.5: (score, novelty). score = demand x dissatisfaction x novelty x (1 - saturation)."""
    o = _scoring()["opportunity"]
    novelty = o["novelty_non_obvious"] if non_obvious else o["novelty_obvious"]
    score = components["demand"] * components["dissatisfaction"] * novelty * (1 - components["saturation"])
    return round(score, 3), novelty


def opportunities(clusters: list[Any]) -> list[dict[str, Any]]:
    """Components per need or white-space cluster. novelty needs non_obvious (Step 3.4), so the score
    is given as the upper bound 'if non-obvious' until then."""
    pool = [c.metrics["counts"]["matching"] for c in clusters
            if c.kind in CLAIM_KINDS and c.metrics["counts"]["matching"]]
    p90 = percentile(pool, _scoring()["opportunity"]["demand_percentile"]) if pool else 0
    out = []
    for c in clusters:
        is_need = c.kind == ClusterKind.motivation and (c.details or {}).get("kind") == "need"
        n = c.metrics["counts"]["matching"]
        if not (is_need or c.kind == ClusterKind.white_space) or not n:
            continue
        comp = {"demand": round(min(1.0, n / p90), 3) if p90 else 0.0,
                "dissatisfaction": c.metrics["dissatisfaction"], "saturation": c.metrics["saturation"]}
        score, _ = opportunity_score(comp, non_obvious=True)
        out.append({"cluster_id": c.id, "kind": c.kind, "label": c.label, "members": n, "components": comp,
                    "score_if_non_obvious": score})
    return sorted(out, key=lambda x: -x["score_if_non_obvious"])


def coverage_grade(kept: int, platforms: Iterable[str], languages: Iterable[str | None],
                   target_languages: Iterable[str]) -> str:
    """Highest grade whose minimums all pass (scoring.yaml); otherwise d."""
    rules = _scoring()["metrics"]["coverage_grade"]
    n_platforms = len(set(platforms))
    all_languages = {t.lower() for t in target_languages} <= {(lang or "").lower() for lang in languages}
    for grade in ("a", "b", "c"):
        r = rules[grade]
        if kept >= r["min_kept"] and n_platforms >= r["min_platforms"] and (all_languages or not r["all_languages"]):
            return grade
    return "d"


def compute_run(run_id: str) -> dict[str, Any]:
    """Metrics for every saved cluster (clusters.metrics) and for the run (runs.analysis)."""
    from ctxpack import db
    from ctxpack.schemas.plan import Interpretation

    run = db.get_run(run_id)
    interp = Interpretation.model_validate(run.interpretation)
    relevant = db.get_documents(run_id, relevant_only=True)
    docs_by_id = {d.id: d for d in relevant}
    counted = [d for d in relevant if not d.short_form]
    corpus_dates = sorted(d.posted_at for d in counted if d.posted_at)
    today = run.created_at.date()
    trends = trends_direction(run.collection)

    clusters = db.get_clusters(run_id)
    for c in clusters:
        c.metrics = cluster_metrics(c, docs_by_id, len(counted), today, interp.time_window_days, corpus_dates, trends)
    db.save_clusters(run_id, clusters)

    analysis = {
        "relevant_counted": len(counted),
        "short_form": len(relevant) - len(counted),
        "platform_lens": platform_lens([c for c in clusters if c.kind == ClusterKind.theme], counted, docs_by_id),
        "whats_new": whats_new(clusters, counted, docs_by_id, today),
        "what_performs": what_performs(counted),
        "competitors": competitor_shares(clusters),
        "opportunities": opportunities(clusters),
        "coverage": {
            "grade": coverage_grade(db.count_documents(run_id), {str(d.platform) for d in counted},
                                    {d.language for d in counted}, interp.languages),
            "kept": db.count_documents(run_id),
            "platforms": sorted({str(d.platform) for d in counted}),
            "languages": sorted({d.language for d in counted if d.language}),
            "dated_share": round(len(corpus_dates) / len(counted), 3) if counted else 0.0,
            "trends_direction": trends,
        },
    }
    db.update_run(run_id, analysis=analysis)
    return analysis
