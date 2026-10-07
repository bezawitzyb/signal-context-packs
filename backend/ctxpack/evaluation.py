"""Evaluation on the four test briefs (guide Step 5.1, Appendix F5, PRD 14).

Every number is computed in code from a finished pack (and its run row, when the
database still has it). Only claim entailment uses a model: a sample of claims is
re-checked by the evaluator role (Sonnet, not the pipeline's Haiku verifier) with
the same claim-check prompt. Allocation efficiency is SIMULATED: the agent's
relevant posts vs. an equal split of the same item budget over the same units,
estimated from each unit's observed yield.

Results: backend/evals/results/<date>.json, copied to featured/evals.json (the
/evals page). Human ratings live in featured/evals_human.json and are merged when
the page asks for them, so they can be filled in without re-running anything.
"""

from __future__ import annotations

import json
import random
import statistics
import re
import shutil
from datetime import UTC, date, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from ctxpack.config import BACKEND_DIR, REPO_DIR, mode_limits

EVALS_DIR = BACKEND_DIR / "evals"
BRIEFS_FILE = EVALS_DIR / "briefs.yaml"
RESULTS_DIR = EVALS_DIR / "results"
FEATURED_EVALS = REPO_DIR / "featured" / "evals.json"
HUMAN_FILE = REPO_DIR / "featured" / "evals_human.json"

_YIELD = re.compile(r"collected (\d+), kept (\d+), relevant (\d+)%")


def load_briefs() -> dict[str, Any]:
    return yaml.safe_load(BRIEFS_FILE.read_text(encoding="utf-8"))


def _metric(value: Any, target: Any = None, passed: bool | None = None, detail: str = "") -> dict[str, Any]:
    return {"value": value, "target": target, "pass": passed, "detail": detail}


def _pct(x: float) -> str:
    return f"{round(100 * x)}%"


# --------------------------------------------------------------------------
# Walking a pack
# --------------------------------------------------------------------------


def claim_items(pack: dict) -> list[dict]:
    """Every claim-like item (has a claim and evidence_ids), in pack order."""
    out: list[dict] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if "claim" in x and "evidence_ids" in x:
                out.append(x)
            for k, v in x.items():
                if k != "evidence":
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk({k: v for k, v in pack.items() if k != "evidence"})
    return out


def quotes(pack: dict) -> list[dict]:
    """Every {evidence_id, text} quote anywhere in the pack."""
    out: list[dict] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for q in x.get("quotes") or []:
                if isinstance(q, dict) and "evidence_id" in q and "text" in q:
                    out.append(q)
            for k, v in x.items():
                if k != "evidence":
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(pack)
    return out


def item_evidence_ids(it: dict) -> list[str]:
    ids = list(it.get("evidence_ids", []))
    for side in ("want", "but"):
        if isinstance(it.get(side), dict):
            ids += [e for e in it[side].get("evidence_ids", []) if e not in ids]
    return ids


# --------------------------------------------------------------------------
# Metrics from the pack alone (code)
# --------------------------------------------------------------------------


def groundedness(pack: dict) -> dict[str, Any]:
    ev = {e["id"]: e["text"] for e in pack.get("evidence", [])}
    qs = quotes(pack)
    bad = [q["evidence_id"] for q in qs if q["text"] not in ev.get(q["evidence_id"], "")]
    value = 1.0 if not qs else round((len(qs) - len(bad)) / len(qs), 4)
    detail = f"{len(qs) - len(bad)} of {len(qs)} quotes are exact substrings of their evidence"
    if bad:
        detail += f"; not found: {', '.join(sorted(set(bad))[:8])}"
    return _metric(value, 1.0, value >= 1.0, detail)


def claims_with_evidence(pack: dict) -> dict[str, Any]:
    ev = {e["id"] for e in pack.get("evidence", [])}
    items = claim_items(pack)
    bad = [it.get("id", "?") for it in items if not [e for e in item_evidence_ids(it) if e in ev]]
    value = 1.0 if not items else round((len(items) - len(bad)) / len(items), 4)
    detail = f"{len(items) - len(bad)} of {len(items)} claims cite evidence that is in the pack"
    if bad:
        detail += f"; without: {', '.join(bad[:8])}"
    return _metric(value, 1.0, value >= 1.0, detail)


def relevance_rate(pack: dict, target: float) -> dict[str, Any]:
    cov = pack["coverage"]
    counts = cov.get("counts", {})
    kept, relevant = counts.get("kept", 0), counts.get("relevant", 0)
    value = round(relevant / kept, 3) if kept else 0.0
    detail = f"{relevant} relevant of {kept} kept posts"
    if value < target:
        weak = sorted(cov.get("sources_used", []), key=lambda s: s.get("relevant_share", 0))[:2]
        if weak:
            detail += ("; weakest kept sources: " + ", ".join(
                f"{s['source_unit']} ({_pct(s.get('relevant_share', 0))} of {s.get('kept', 0)})" for s in weak))
    return _metric(value, target, value >= target, detail)


def source_diversity(pack: dict, target: int, exempt: bool) -> dict[str, Any]:
    platforms = sorted({e["platform"] for e in pack.get("evidence", [])}
                       | {s["platform"] for s in pack["coverage"].get("sources_used", [])})
    n = len(platforms)
    detail = ", ".join(platforms) or "no platforms"
    if exempt:
        detail += " (this brief is exempt, PRD 14.3)"
    return _metric(n, target, None if exempt else n >= target, detail)


def schema_valid(pack: dict) -> dict[str, Any]:
    from pydantic import ValidationError

    from ctxpack.schemas.pack import SCHEMA_VERSION, ContextPack

    try:
        ContextPack.model_validate(pack)
        return _metric(1.0, 1.0, True, f"valid Context Pack {SCHEMA_VERSION}")
    except ValidationError as exc:
        return _metric(0.0, 1.0, False, f"{exc.error_count()} schema error(s): {str(exc).splitlines()[1][:120]}")


def loop_health(pack: dict, run: Any | None) -> dict[str, Any]:
    loop = pack["coverage"].get("loop", {})
    value = {"tool_calls": loop.get("tool_calls"), "finish_reason": loop.get("finish_reason"),
             "fallback_used": loop.get("fallback_used"), "top_up_used": loop.get("top_up_used")}
    if run is not None:
        value["max_tool_calls"] = mode_limits(str(run.mode))["max_tool_calls"]
    healthy = value["finish_reason"] == "finish" and not value["fallback_used"]
    detail = (f"{value['tool_calls']} tool calls, finished by '{value['finish_reason']}'"
              f"{', fallback used' if value['fallback_used'] else ''}{', top-up used' if value['top_up_used'] else ''}")
    if not healthy:
        detail += " - the agent did not finish on its own; the pack is still valid but collection was cut short"
    return _metric(value, "finish, no fallback", healthy, detail)


def _source_units_from_pack(pack: dict) -> set[str]:
    cov = pack["coverage"]
    units = {s["source_unit"] for s in cov.get("sources_used", []) + cov.get("sources_dropped", [])}
    for d in cov.get("decision_log", []):
        for u in (d.get("source_unit") or "").split(", "):
            if u:
                units.add(u)
    return {u.casefold() for u in units}


def source_units(pack: dict, run: Any | None) -> set[str]:
    """Planned + tried + used + dropped units (the run adds the plan's starting units)."""
    units = _source_units_from_pack(pack)
    if run is not None and run.plan:
        from ctxpack.orchestrator import source_units as run_units

        units |= run_units(run)
    return units


def plan_divergence(units_by_brief: dict[str, set[str]], max_shared: float) -> dict[str, Any]:
    from ctxpack.orchestrator import units_overlap

    sets = list(units_by_brief.values())
    ov = units_overlap(sets) if len(sets) > 1 else {"shared": 0, "total": 0, "share": 0.0, "max_pairwise": 0.0}
    pairs = {f"{a} / {b}": round(len(units_by_brief[a] & units_by_brief[b]) / len(units_by_brief[a] | units_by_brief[b]), 3)
             for a, b in combinations(units_by_brief, 2) if units_by_brief[a] | units_by_brief[b]}
    shared_units = sorted({u for a, b in combinations(sets, 2) for u in a & b})
    value = round(ov["share"], 3)
    detail = (f"{ov['shared']} of {ov['total']} distinct source units are used by more than one brief"
              + (f": {', '.join(shared_units[:6])}" if shared_units else ""))
    return {**_metric(value, max_shared, value < max_shared, detail), "pairwise_jaccard": pairs}


def unit_yields(decision_log: list[dict]) -> dict[str, dict[str, int]]:
    """unit -> collected items and (estimated) relevant posts, from the agent's own call results."""
    out: dict[str, dict[str, int]] = {}
    for d in decision_log:
        m = _YIELD.search(d.get("result_summary") or "")
        unit = d.get("source_unit") or ""
        if not m or not unit or ", " in unit:
            continue
        collected, kept, pct = (int(g) for g in m.groups())
        row = out.setdefault(unit, {"collected": 0, "relevant": 0})
        row["collected"] += collected
        row["relevant"] += round(kept * pct / 100)
    return out


def allocation_efficiency(pack: dict, collection_usd: float | None) -> dict[str, Any]:
    """SIMULATED: agent vs. an equal split of the same items over the same units at their observed yields."""
    yields = {u: y for u, y in unit_yields(pack["coverage"].get("decision_log", [])).items() if y["collected"]}
    base = {"simulated": True,
            "assumption": "Same total items spread equally over the units the agent tried, each unit keeping the "
                          "relevant-per-item rate it actually showed. Diminishing returns and units never tried are "
                          "not modelled."}
    if len(yields) < 2:
        return {**_metric(None, "agent >= equal split", None, "fewer than two units collected: nothing to compare"),
                **base}
    total = sum(y["collected"] for y in yields.values())
    agent = sum(y["relevant"] for y in yields.values())
    equal = sum(total / len(yields) * y["relevant"] / y["collected"] for y in yields.values())
    ratio = round(agent / equal, 2) if equal else None
    per_usd = {"agent": round(agent / collection_usd, 1), "equal_split": round(equal / collection_usd, 1)} \
        if collection_usd else None
    detail = (f"agent {agent} relevant posts vs. equal split ~{round(equal)} from {total} items over "
              f"{len(yields)} units" + (f"; per USD {per_usd['agent']} vs. {per_usd['equal_split']}" if per_usd else ""))
    return {**_metric(ratio, "agent >= equal split", ratio is not None and ratio >= 1.0, detail), **base,
            "relevant_per_usd": per_usd, "units": len(yields)}


def latency(pack: dict, mode: str) -> dict[str, Any]:
    """Minutes from the first to the last event saved with the pack (queue wait included).
    A long pause between two events means stages were re-run by hand later; it is named, not hidden."""
    events = sorted((datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")), e)
                    for e in pack.get("events", []) if e.get("created_at"))
    target = mode_limits(mode)["typical_minutes"]
    if len(events) < 2:
        return _metric(None, target, None, "no timed events in the pack")
    minutes = round((events[-1][0] - events[0][0]).total_seconds() / 60, 1)
    detail = f"{minutes} min end to end (NFR1: about {target} min)"
    gap, before, after = max(((b[0] - a[0]).total_seconds() / 60, a[1], b[1]) for a, b in zip(events, events[1:]))
    if gap > target:
        def name(e: dict) -> str:
            return (e.get("payload") or {}).get("stage") or e["type"]
        detail += (f"; includes a {round(gap)} min pause between '{name(before)}' and '{name(after)}' "
                   f"(stages re-run by hand later), so about {round(minutes - gap, 1)} min of work")
    return _metric(minutes, target, minutes <= target * 1.25, detail)


def cost(run: Any | None, mode: str) -> dict[str, Any]:
    lim = mode_limits(mode)
    cap = round(lim["apify_usd"] + lim["llm_usd"] + lim["analysis_llm_usd"], 2)
    lo, hi = lim["typical_usd"]
    if run is None:
        return _metric(None, cap, None, "run no longer in the database")
    total = round(run.cost_apify_usd + run.cost_llm_usd, 2)
    detail = (f"Apify ${run.cost_apify_usd:.2f} + Anthropic ${run.cost_llm_usd:.2f}; typical ${lo:.2f}-{hi:.2f}, "
              f"hard cap ${cap:.2f} (NFR2)")
    if total > cap:
        detail += "; over the cap because analysis stages were re-run on the saved corpus"
    return _metric(total, cap, total <= cap, detail)


def peak_memory(run: Any | None, mode: str, limit_mb: float) -> dict[str, Any]:
    mb = run.peak_mem_mb if run is not None else None
    if mb is None:
        return _metric(None, limit_mb, None, "not recorded")
    applies = mode == "standard"
    return _metric(mb, limit_mb, (mb < limit_mb) if applies else None,
                   f"{mb} MB peak (NFR9 applies to Standard runs)" + ("" if applies else "; Quick run, shown only"))


def plan_mix(plan: dict | None) -> dict[str, float]:
    """Share of the ENABLED starting units per platform (V6)."""
    units = [u for u in (plan or {}).get("starting_units", []) if u.get("enabled", True)]
    out: dict[str, float] = {}
    for u in units:
        out[u["platform"]] = out.get(u["platform"], 0) + 1 / len(units)
    return {k: round(v, 2) for k, v in sorted(out.items())}


def expectations(pack: dict, expect: dict, min_share: float, clarifying: dict | None,
                 plan: dict | None = None) -> list[dict[str, Any]]:
    """Brief-specific checks from F5: market, languages, compliance area, the clarifying question."""
    interp = pack["brief"]["interpreted"]
    mix = {m["language"]: m["share"] for m in pack["coverage"].get("language_mix", [])}
    out = []
    if "market" in expect:
        out.append({"check": f"market is {expect['market']}", "pass": interp["market"] == expect["market"],
                    "detail": f"interpreted market: {interp['market']}"})
    markets = interp.get("markets") or []
    if "markets_include" in expect:  # V2: several markets
        codes = {m["code"] for m in markets}
        out.append({"check": f"markets include {', '.join(expect['markets_include'])}",
                    "pass": set(expect["markets_include"]) <= codes, "detail": f"markets: {interp['market']}"})
    if "countries_include" in expect:
        found = {c for m in markets for c in m["countries"]}
        out.append({"check": f"countries include {', '.join(expect['countries_include'])}",
                    "pass": set(expect["countries_include"]) <= found,
                    "detail": f"{len(found)} countries in the markets"})
    if expect.get("languages"):
        missing = [lang for lang in expect["languages"] if lang not in interp["languages"]]
        out.append({"check": "brief languages chosen", "pass": not missing,
                    "detail": "chosen: " + ", ".join(interp["languages"]) + (
                        "; left out: " + "; ".join(f"{e['language']} ({e['reason']})"
                                                   for e in interp.get("languages_excluded", []))
                        if interp.get("languages_excluded") else "")})
    for lang in expect.get("languages", []):
        share = mix.get(lang, 0.0)
        out.append({"check": f"{lang} posts in the corpus", "pass": share >= min_share,
                    "detail": f"{_pct(share)} of kept posts"})
    if "compliance_category" in expect:
        got = interp.get("compliance_category")
        flags = pack.get("compliance_flags", [])
        out.append({"check": f"compliance area {expect['compliance_category']}",
                    "pass": got == expect["compliance_category"],
                    "detail": f"interpreted: {got}; {len(flags)} compliance flag(s) in the pack"})
    if "plans_platforms" in expect or "platform_share_max" in expect:  # V6: where the plan starts
        mix = plan_mix(plan)
        shown = ", ".join(f"{k} {_pct(v)}" for k, v in mix.items()) or "no plan saved"
        for p in expect.get("plans_platforms", []):
            out.append({"check": f"plans {p}", "pass": p in mix if plan else None, "detail": shown})
        for p, most in expect.get("platform_share_max", {}).items():
            out.append({"check": f"{p} at most {_pct(most)} of the plan",
                        "pass": mix.get(p, 0.0) <= most if plan else None, "detail": shown})
    asks = [k for k in ("questions_max", "questions_fill") if k in expect]
    if asks:  # V3: brief-specific clarifying questions
        qs = (clarifying or {}).get("questions")
        shown = "; ".join(f"{q['id']} [{q['fills']}] {q['question']}" for q in qs or []) or "no questions"
        if qs is None:
            out.append({"check": "clarifying questions", "pass": None, "detail": "not checked yet"})
        else:
            if "questions_max" in expect:
                out.append({"check": f"at most {expect['questions_max']} question(s)",
                            "pass": len(qs) <= expect["questions_max"], "detail": shown})
            if "questions_fill" in expect:
                fills = {q["fills"] for q in qs}
                out.append({"check": "asks about " + ", ".join(expect["questions_fill"]),
                            "pass": set(expect["questions_fill"]) <= fills, "detail": shown})
            from ctxpack.agent.markets import places_in

            places = places_in(pack["brief"]["text"])
            answered = [q["id"] for q in qs if q["fills"] == "market" and (places["regions"] or places["countries"])]
            out.append({"check": "never asks what the brief already says", "pass": not answered,
                        "detail": f"market asked although the brief names a place ({', '.join(answered)})"
                        if answered else "ok"})
    return out


# --------------------------------------------------------------------------
# Claim entailment (evaluator model)
# --------------------------------------------------------------------------


def entailment_sample(pack: dict, n: int) -> list[dict]:
    """A fixed sample per pack (seeded by pack_id), so re-runs check the same claims."""
    ev = {e["id"] for e in pack.get("evidence", [])}
    items = [it for it in claim_items(pack) if it.get("id") and [e for e in item_evidence_ids(it) if e in ev]]
    return random.Random(pack["pack_id"]).sample(items, min(n, len(items)))


async def recheck_claims(pack: dict, n: int) -> dict[str, Any]:
    """Re-check a sample of claims with the evaluator role. Entailed = supported, or partially supported
    on a claim the pack already marks as inferred (that is how the pipeline labels a partial match)."""
    from ctxpack.synthesis.verify import Report, check_claims

    sample = entailment_sample(pack, n)
    ev_text = {e["id"]: e["text"] for e in pack.get("evidence", [])}
    items = [{"id": it["id"].upper(), "claim": it["claim"], "evidence_ids": item_evidence_ids(it)} for it in sample]
    report = Report()
    verdicts = await check_claims(items, ev_text, report, role="evaluator")
    by_id = {it["id"].upper(): it for it in sample}
    rows, counts = [], {"supported": 0, "partially_supported": 0, "not_supported": 0, "unchecked": 0}
    entailed = 0
    for key, it in by_id.items():
        v = verdicts.get(key)
        verdict = v.verdict if v else "unchecked"
        counts[verdict] += 1
        ok = verdict == "supported" or (verdict == "partially_supported" and it.get("claim_type") == "inferred")
        entailed += ok
        rows.append({"id": it["id"], "verdict": verdict, "claim_type": it.get("claim_type"), "entailed": ok,
                     "reason": (v.reason if v else "")[:200]})
    checked = len(sample) - counts["unchecked"]
    return {"checked": checked, "sampled": len(sample), "counts": counts, "entailed": entailed,
            "rate": round(entailed / checked, 4) if checked else None,
            "strict_rate": round(counts["supported"] / checked, 4) if checked else None,
            "rows": rows, "usd": round(report.usd, 4)}


def entailment_metric(ent: dict | None, target: float) -> dict[str, Any]:
    if not ent or ent.get("rate") is None:
        return _metric(None, target, None, "not re-checked yet")
    detail = (f"{ent['entailed']} of {ent['checked']} sampled claims entailed (strictly supported: "
              f"{_pct(ent['strict_rate'])})")
    bad = [r["id"] for r in ent["rows"] if not r["entailed"] and r["verdict"] != "unchecked"]
    if bad:
        detail += f"; not entailed: {', '.join(bad[:8])}"
    return _metric(ent["rate"], target, ent["rate"] >= target, detail)


# --------------------------------------------------------------------------
# One brief, and the whole evaluation
# --------------------------------------------------------------------------


def score_brief(spec: dict, pack: dict, run: Any | None, targets: dict, *, entailment: dict | None,
                clarifying: dict | None, reused: bool) -> dict[str, Any]:
    mode = pack["mode"]
    lim = mode_limits(mode)
    collection_usd = None
    if run is not None:
        collection_usd = run.cost_apify_usd + run.cost_llm_usd - (run.cost_analysis_llm_usd or 0.0)
    m = {
        "quote_groundedness": groundedness(pack),
        "claim_entailment": entailment_metric(entailment, targets["claim_entailment"]),
        "claims_with_evidence": claims_with_evidence(pack),
        "relevance_rate": relevance_rate(pack, targets["relevance_rate"]),
        "source_diversity": source_diversity(pack, targets["source_diversity_platforms"],
                                             bool(spec.get("source_diversity_exempt"))),
        "allocation_efficiency": allocation_efficiency(pack, collection_usd),
        "loop_health": loop_health(pack, run),
        "cost_usd": cost(run, mode),
        "latency_min": latency(pack, mode),
        "peak_mem_mb": peak_memory(run, mode, targets["peak_mem_mb_standard"]),
        "schema_valid": schema_valid(pack),
    }
    thin = bool(pack["coverage"].get("thin_evidence"))
    return {
        "id": spec["id"], "brief": spec["brief"], "mode": mode, "pack_id": pack["pack_id"],
        "run_id": run.id if run is not None else None, "reused": reused, "note": spec.get("note", ""),
        "interpreted": {k: pack["brief"]["interpreted"].get(k) for k in ("topic", "market", "languages")},
        "coverage_grade": pack["snapshot"].get("coverage_grade"),
        "relevant_posts": pack["coverage"].get("counts", {}).get("relevant"),
        "thin_evidence": thin,
        "thin_evidence_note": ("below the content bar or the minimum relevant posts for "
                               f"{mode} ({lim['min_relevant']}); the pack says so instead of padding") if thin else "",
        "metrics": m,
        "expectations": expectations(pack, spec.get("expect", {}), targets.get("expected_language_min_share", 0.05),
                                     clarifying, run.plan if run is not None else None),
        "clarifying_question": clarifying,
        "entailment": entailment,
        "units": sorted(source_units(pack, run)),
    }


def headline(briefs: list[dict], divergence: dict, targets: dict) -> dict[str, Any]:
    """Pooled numbers over all briefs vs. the PRD 14.3 targets."""
    def pooled(name: str) -> dict[str, Any]:
        vals = [b["metrics"][name] for b in briefs if b["metrics"][name]["value"] is not None]
        fails = [b["id"] for b in briefs if b["metrics"][name]["pass"] is False]
        if not vals:
            return _metric(None, targets.get(name), None, "no data")
        low = min(v["value"] for v in vals)
        return _metric(low, vals[0]["target"], not fails,
                       "lowest of the briefs" + (f"; failing: {', '.join(fails)}" if fails else ""))

    ent_checked = sum((b["entailment"] or {}).get("checked", 0) for b in briefs)
    ent_ok = sum((b["entailment"] or {}).get("entailed", 0) for b in briefs)
    ent_rate = round(ent_ok / ent_checked, 4) if ent_checked else None
    ratios = [b["metrics"]["allocation_efficiency"]["value"] for b in briefs
              if b["metrics"]["allocation_efficiency"]["value"] is not None]
    diverse = [b for b in briefs if b["metrics"]["source_diversity"]["pass"] is not None]
    return {
        "quote_groundedness": pooled("quote_groundedness"),
        "claim_entailment": _metric(ent_rate, targets["claim_entailment"],
                                    None if ent_rate is None else ent_rate >= targets["claim_entailment"],
                                    f"{ent_ok} of {ent_checked} sampled claims, all briefs"),
        "claims_with_evidence": pooled("claims_with_evidence"),
        "relevance_rate": pooled("relevance_rate"),
        "source_diversity": _metric(sum(b["metrics"]["source_diversity"]["pass"] for b in diverse),
                                    len(diverse), all(b["metrics"]["source_diversity"]["pass"] for b in diverse),
                                    f"briefs with >= {targets['source_diversity_platforms']} platforms "
                                    "(the vague brief is exempt)"),
        "plan_divergence": {k: v for k, v in divergence.items() if k != "pairwise_jaccard"},
        "allocation_efficiency": {**_metric(round(statistics.median(ratios), 2) if ratios else None,
                                            "agent >= equal split",
                                            bool(ratios) and statistics.median(ratios) >= 1.0,
                                            "median ratio over briefs"), "simulated": True},
        "schema_valid": pooled("schema_valid"),
        "peak_mem_mb": pooled_max(briefs, "peak_mem_mb"),
    }


def pooled_max(briefs: list[dict], name: str) -> dict[str, Any]:
    vals = [b["metrics"][name] for b in briefs if b["metrics"][name]["value"] is not None]
    if not vals:
        return _metric(None, None, None, "no data")
    worst = max(v["value"] for v in vals)
    fails = [b["id"] for b in briefs if b["metrics"][name]["pass"] is False]
    return _metric(worst, vals[0]["target"], not fails, "highest of the briefs")


def previous(brief_id: str, pack_id: str) -> dict | None:
    """The newest saved result for this brief and pack (re-used: entailment, clarifying question)."""
    for path in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        data = json.loads(path.read_text(encoding="utf-8"))
        for b in data.get("briefs", []):
            if b["id"] == brief_id and b["pack_id"] == pack_id:
                return b
    return None


def save(result: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{result['date']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    shutil.copyfile(path, FEATURED_EVALS)
    return path


def build_result(scored: list[dict], targets: dict, eval_usd: float) -> dict[str, Any]:
    divergence = plan_divergence({b["id"]: set(b["units"]) for b in scored}, targets["plan_divergence_max_shared"])
    now = datetime.now(UTC)
    return {"status": "ok", "date": date.today().isoformat(), "generated_at": now.isoformat(timespec="seconds"),
            "targets": targets, "headline": headline(scored, divergence, targets), "plan_divergence": divergence,
            "briefs": scored, "eval_cost_usd": round(eval_usd, 4),
            "notes": ["Allocation efficiency is SIMULATED (see each brief's assumption).",
                      "Cost and latency come from the run record; a run whose analysis was redone later includes "
                      "that extra time and spend."]}


def latest() -> dict | None:
    """The newest saved results (an --only run merges its briefs into these)."""
    paths = sorted(RESULTS_DIR.glob("*.json"))
    return json.loads(paths[-1].read_text(encoding="utf-8")) if paths else None


def human_ratings() -> dict[str, Any]:
    """featured/evals_human.json, or an empty template when it is missing or unreadable."""
    try:
        return json.loads(HUMAN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"session": None, "briefs": {}}


def published() -> dict[str, Any]:
    """What GET /api/v1/evals returns: the latest results plus the human ratings."""
    try:
        data = json.loads(FEATURED_EVALS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "not_run_yet", "results": [], "briefs": [],
                "note": "Evaluations on the four test briefs have not been run yet."}
    data["human"] = human_ratings()
    for b in data.get("briefs", []):
        b.pop("units", None)
    return data
