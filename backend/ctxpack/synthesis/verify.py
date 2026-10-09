"""Verification (Step 3.4): exact quotes (code), claim checks (worker, F4-9 claim mode), confidence (PRD 5.4).

Stage 1 (code): every quote must be an exact substring of its evidence text. A
quote that matches only with different whitespace is replaced by the exact text
from the evidence; anything else is removed. A phrase whose own text is not
found is dropped, and so is any item left without evidence.
Stage 2 (worker, batched): each claim against its own evidence: supported /
partially_supported / not_supported. not_supported claims are dropped;
partially supported ones go one level down and become "inferred".
Then confidence.py scores and labels every claim and sets safe_to_assert.

runs.draft["sections"] stays as written; the result is runs.draft["verified"]
(sections, evidence, report), so verification can be redone without rewriting.
"""

from __future__ import annotations

import copy
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ctxpack.analysis.metrics import author_key, undated_share
from ctxpack.config import load_yaml
from ctxpack.llm.client import LLMError, batched, load_prompt, structured, untrusted
from ctxpack.synthesis import confidence as conf
from ctxpack.synthesis.write import INSIGHT_SECTIONS, SECTION_ORDER

log = logging.getLogger(__name__)

VERDICTS = ("supported", "partially_supported", "not_supported")


class Verdict(BaseModel):
    id: str
    verdict: str | None = Field(description="supported, partially_supported or not_supported.")
    reason: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _known(cls, value: object) -> str | None:
        """Close spellings are accepted; anything else counts as unchecked (no paid retry)."""
        v = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
        v = {"partial": "partially_supported", "partially": "partially_supported",
             "unsupported": "not_supported"}.get(v, v)
        return v if v in VERDICTS else None


class VerdictBatch(BaseModel):
    items: list[Verdict]


@dataclass
class Report:
    quotes_checked: int = 0
    quotes_whitespace_fixed: int = 0
    quotes_removed: int = 0
    items_dropped_no_evidence: int = 0
    phrases_dropped: int = 0
    supported: int = 0
    partially_supported: int = 0     # downgraded one level, claim_type inferred
    not_supported: int = 0           # dropped
    unchecked: int = 0               # no verdict even after the retry pass
    labels: dict[str, int] = field(default_factory=dict)
    safe_to_assert: int = 0
    groundedness: float = 1.0        # share of kept quotes that are exact substrings
    thin_evidence: bool = False
    dropped_items: list[str] = field(default_factory=list)
    calls: int = 0
    usd: float = 0.0
    resumed: bool = False


def _cfg() -> dict:
    return load_yaml("modes")["verification"]


# --------------------------------------------------------------------------
# Stage 1: exact quotes (code)
# --------------------------------------------------------------------------


def exact_quote(quote: str, text: str) -> str | None:
    """The exact text of `quote` inside `text`, allowing only different whitespace; None if absent."""
    quote = quote.strip()
    if not quote:
        return None
    if quote in text:
        return quote
    match = re.search(r"\s+".join(re.escape(t) for t in quote.split()), text)
    return match.group(0) if match else None


def check_quotes(sections: dict, ev_text: dict[str, str], report: Report) -> None:
    """Fix or remove every quote; drop phrases whose own text is not found and items left without evidence."""
    for name in INSIGHT_SECTIONS:
        kept_items = []
        for it in sections[name]:
            kept_quotes = []
            for q in it.get("quotes", []):
                report.quotes_checked += 1
                exact = exact_quote(q["text"], ev_text.get(q["evidence_id"], ""))
                if exact is None:
                    report.quotes_removed += 1
                    continue
                if exact != q["text"]:
                    report.quotes_whitespace_fixed += 1
                kept_quotes.append({"evidence_id": q["evidence_id"], "text": exact})
            it["quotes"] = kept_quotes
            if name == "phrases":
                found = next(filter(None, (exact_quote(it["text"], ev_text.get(e, "")) for e in it["evidence_ids"])),
                             None)
                if found is None:
                    report.phrases_dropped += 1
                    report.dropped_items.append(it["id"])
                    continue
                it["text"] = found
            it["evidence_ids"] = [e for e in it["evidence_ids"] if e in ev_text]
            sides_ok = all(side not in it or [e for e in it[side]["evidence_ids"] if e in ev_text]
                           for side in ("want", "but"))
            if not it["evidence_ids"] or not sides_ok:
                report.items_dropped_no_evidence += 1
                report.dropped_items.append(it["id"])
                continue
            kept_items.append(it)
        sections[name] = kept_items


# --------------------------------------------------------------------------
# Stage 2: claim checks (worker)
# --------------------------------------------------------------------------


def _fake_verdicts(user: str) -> dict:
    return {"items": [{"id": i, "verdict": "supported", "reason": "Fake."}
                      for i in re.findall(r"^Claim (\w+-\d+):", user, flags=re.M)]}


async def check_claims(items: list[dict], ev_text: dict[str, str], report: Report,
                       role: str = "worker") -> dict[str, Verdict]:
    """One verdict per claim (batched, one retry pass for claims without a verdict).
    The eval re-check uses role="evaluator" (PRD 14.3: not the pipeline's verifier model)."""
    cfg = _cfg()
    system = load_prompt("verify_claim")
    verdicts: dict[str, Verdict] = {}

    async def run(batch: list[dict]) -> None:
        blocks = []
        for it in batch:
            evs = it["evidence_ids"] + [e for side in ("want", "but") if side in it
                                        for e in it[side]["evidence_ids"] if e not in it["evidence_ids"]]
            blocks.append(f"Claim {it['id']}: {it['claim']}\nEvidence:\n"
                          + "\n".join(untrusted(e, ev_text[e]) for e in evs[:6] if e in ev_text))
        try:
            res = await structured(role, system, "\n\n".join(blocks), VerdictBatch, "record_verdicts",
                                   description="Record a verdict for every claim.", fake=_fake_verdicts)
        except LLMError as exc:  # its claims get the retry pass
            log.warning("claim batch of %d failed: %s", len(batch), exc)
            return
        report.calls += 1
        report.usd += res.usd
        wanted = {it["id"] for it in batch}
        for v in res.data.items:
            key = v.id.strip().upper()
            if key in wanted and v.verdict and key not in verdicts:
                verdicts[key] = v

    pending = items
    for _ in range(2):
        if not pending:
            break
        await batched(pending, run, size=cfg["claim_batch_items"], parallel=cfg["claim_parallel_max"])
        pending = [it for it in items if it["id"] not in verdicts]
    return verdicts


# --------------------------------------------------------------------------
# Confidence and references
# --------------------------------------------------------------------------


def top_author_share(member_ids: list[str], docs_by_id: dict[str, Any]) -> float:
    keys = [author_key(docs_by_id[m]) for m in member_ids if m in docs_by_id and not docs_by_id[m].short_form]
    return max(Counter(keys).values()) / len(keys) if keys else 0.0


def score_item(it: dict, verdict: Verdict | None, members: list[str], docs_by_id: dict, thin: bool) -> None:
    st = it["strength"]
    result = conf.assess(conf.Evidence(
        members=it["counts"]["matching"], authors=st["distinct_authors"], platforms=len(st["platforms"]),
        sources=it.get("distinct_sources", 0), engagement_median=st.get("engagement_percentile_median"),
        recency=it.get("recency_share", 0.5), verifier=verdict.verdict if verdict else None,
        claim_type=it["claim_type"], top_author_share=top_author_share(members, docs_by_id), thin_evidence=thin,
        undated_share=undated_share([docs_by_id[m] for m in members
                                     if m in docs_by_id and not docs_by_id[m].short_form])))
    it["confidence"] = {"score": result.score, "label": result.label}
    it["confidence_components"] = result.components
    it["claim_type"] = result.claim_type
    it["safe_to_assert"] = result.safe_to_assert
    it["verification"] = {"verdict": verdict.verdict if verdict else "unchecked",
                          "reason": verdict.reason if verdict else ""}


def prune_references(s: dict, evidence: list[dict]) -> list[dict]:
    """After drops: no reference to a dropped item; only evidence that is still cited."""
    alive = {it["id"] for name in SECTION_ORDER + ["risks"] for it in s.get(name, [])}
    for name in INSIGHT_SECTIONS:
        for it in s[name]:
            it["segment_ids"] = [x for x in it.get("segment_ids", []) if x in alive]
            it["related_ids"] = [x for x in it.get("related_ids", []) if x in alive]
            it["relations"] = [r for r in it.get("relations", []) if r["id"] in alive]
    for o in s["opportunities"]:
        o["builds_on"] = [b for b in o["builds_on"] if b in alive]
    s["opportunities"] = [o for o in s["opportunities"] if o["builds_on"]]
    for r in s["risks"]:
        r["item_ids"] = [x for x in r["item_ids"] if x in alive]
    for lens in s["platform_lens"]:
        lens["theme_shares"] = [t for t in lens["theme_shares"] if t["theme_id"] in alive]

    used: set[str] = set()
    for name in SECTION_ORDER:
        for it in s[name]:
            used.update(it.get("evidence_ids", []))
            used.update(q["evidence_id"] for q in it.get("quotes", []))
            for side in ("want", "but"):
                if side in it:
                    used.update(it[side]["evidence_ids"])
            if it.get("evidence_id"):
                used.add(it["evidence_id"])
    return [e for e in evidence if e["id"] in used]


# --------------------------------------------------------------------------
# The stage
# --------------------------------------------------------------------------


async def verify_run(run_id: str, *, redo: bool = False) -> Report:
    """Verify the run's draft; saves runs.draft["verified"]. A saved result is reused unless redo."""
    from ctxpack import db
    from ctxpack.config import mode_limits

    report = Report()
    run = db.get_run(run_id)
    draft = dict(run.draft or {})
    if not draft.get("sections"):
        raise ValueError(f"run {run_id} has no draft yet (Step 3.3)")
    if draft.get("verified") and not redo:
        report.resumed = True
        return Report(**{**draft["verified"]["report"], "resumed": True, "calls": 0, "usd": 0.0})

    sections = copy.deepcopy(draft["sections"])
    evidence = copy.deepcopy(draft["evidence"])
    ev_text = {e["id"]: e["text"] for e in evidence}
    docs_by_id = {d.id: d for d in db.get_documents(run_id, relevant_only=True)}
    members = {c.id: c.verified_member_ids for c in db.get_clusters(run_id)}
    report.thin_evidence = (run.analysis or {}).get("relevant_counted", 0) < mode_limits(run.mode)["min_relevant"]

    check_quotes(sections, ev_text, report)
    claims = [it for name in INSIGHT_SECTIONS for it in sections[name]]
    verdicts = await check_claims(claims, ev_text, report)
    for name in INSIGHT_SECTIONS:
        kept = []
        for it in sections[name]:
            v = verdicts.get(it["id"])
            if v and v.verdict == "not_supported":
                report.not_supported += 1
                report.dropped_items.append(it["id"])
                continue
            if v is None:
                report.unchecked += 1
            elif v.verdict == "supported":
                report.supported += 1
            else:
                report.partially_supported += 1
            item_members = members.get(it["cluster_id"], []) + members.get(it.get("but_cluster_id") or "", [])
            score_item(it, v, item_members, docs_by_id, report.thin_evidence)
            kept.append(it)
        sections[name] = kept
    evidence = prune_references(sections, evidence)

    labels = Counter(it["confidence"]["label"] for name in INSIGHT_SECTIONS for it in sections[name])
    report.labels = {level: labels.get(level, 0) for level in reversed(conf.LEVELS)}
    report.safe_to_assert = sum(it["safe_to_assert"] for name in INSIGHT_SECTIONS for it in sections[name])
    kept_ev = {e["id"]: e["text"] for e in evidence}
    quotes = [q for name in INSIGHT_SECTIONS for it in sections[name] for q in it["quotes"]]
    report.groundedness = (sum(q["text"] in kept_ev.get(q["evidence_id"], "") for q in quotes) / len(quotes)
                           if quotes else 1.0)
    draft["verified"] = {"sections": sections, "evidence": evidence,
                         "report": {k: v for k, v in report.__dict__.items() if k not in ("calls", "usd", "resumed")}}
    db.update_run(run_id, draft=draft)
    log.info("run %s verification: %s", run_id, draft["verified"]["report"])
    return report


def estimate_usd(draft: dict) -> float:
    """Generous upper estimate for the claim checks (the CLI shows it before a paid run)."""
    from ctxpack.config import model_for
    from ctxpack.llm.client import cost_usd

    items = sum(len(draft["sections"].get(n, [])) for n in INSIGHT_SECTIONS)  # drafts from before V4 lack some
    calls = items / _cfg()["claim_batch_items"] + 1
    return 2 * cost_usd(model_for("worker"), int(items * 5 * 110 + calls * 700), items * 45)
