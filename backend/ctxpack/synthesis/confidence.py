"""Confidence score and label (PRD 5.4), weights and gates from scoring.yaml. Code only.

    score = 0.30 volume + 0.25 authors + 0.20 cross_platform
          + 0.10 engagement + 0.10 recency + 0.05 verifier
    label = the highest level whose score threshold AND gates all pass
    caps  : one author > 50% of members -> at most emerging
            thin-evidence run            -> at most emerging
            partially supported          -> one level down, claim_type inferred
            unverified inference         -> speculative
    safe_to_assert = strong AND observed AND verified as supported
"""

from __future__ import annotations

from dataclasses import dataclass

from ctxpack.config import load_yaml

LEVELS = ["speculative", "emerging", "moderate", "strong"]  # low -> high


@dataclass
class Evidence:
    """What the score needs about one claim's verified members (short_form excluded)."""

    members: int
    authors: int
    platforms: int
    sources: int
    engagement_median: float | None   # 0-100, None if no member has engagement data
    recency: float                    # share of dated members in the newer half of the window (0.5 undated)
    verifier: str | None              # supported | partially_supported | not_supported | None (unchecked)
    claim_type: str                   # observed | inferred
    top_author_share: float = 0.0     # share of members from the most frequent author
    thin_evidence: bool = False


@dataclass
class Result:
    score: float
    label: str
    claim_type: str
    safe_to_assert: bool
    components: dict[str, float]


def _cfg() -> dict:
    return load_yaml("scoring")["confidence"]


def components(e: Evidence) -> dict[str, float]:
    c = _cfg()
    sat = c["saturation"]
    eng = c["engagement_if_unknown"] if e.engagement_median is None else e.engagement_median / 100
    return {"volume": min(1.0, e.members / sat["volume_members"]),
            "authors": min(1.0, e.authors / sat["authors"]),
            "cross_platform": min(1.0, max(0, e.platforms - 1) / sat["cross_platform_extra"]),
            "engagement": eng,
            "recency": e.recency,
            "verifier": c["verifier_values"].get(e.verifier or "", 0.0)}


def score(e: Evidence) -> tuple[float, dict[str, float]]:
    comp = components(e)
    weights = _cfg()["weights"]
    return round(sum(weights[k] * v for k, v in comp.items()), 2), comp


def _gates_pass(level: str, e: Evidence, s: float) -> bool:
    g = _cfg()["labels"][level]
    return (s >= g["min_score"] and e.members >= g.get("min_members", 0) and e.authors >= g.get("min_authors", 0)
            and e.platforms >= g.get("min_platforms", 0) and e.sources >= g.get("min_sources", 0)
            and (not g.get("require_supported") or e.verifier == "supported"))


def _cap(label: str, cap: str) -> str:
    return LEVELS[min(LEVELS.index(label), LEVELS.index(cap))]


def assess(e: Evidence) -> Result:
    c = _cfg()
    s, comp = score(e)
    label = next(level for level in reversed(LEVELS) if _gates_pass(level, e, s))
    claim_type = e.claim_type
    if e.verifier == "partially_supported":
        label = LEVELS[max(0, LEVELS.index(label) - c["caps"]["partially_supported_levels_down"])]
        claim_type = "inferred"
    if e.top_author_share > c["caps"]["single_author_share_max"]:
        label = _cap(label, c["caps"]["single_author_cap_label"])
    if e.thin_evidence:
        label = _cap(label, c["caps"]["thin_evidence_cap_label"])
    if claim_type == "inferred" and e.verifier is None:
        label = "speculative"  # all unverified inferences (never checked; not_supported claims are dropped)
    safe = label == "strong" and claim_type == "observed" and e.verifier == "supported"
    return Result(score=s, label=label, claim_type=claim_type, safe_to_assert=safe, components=comp)
