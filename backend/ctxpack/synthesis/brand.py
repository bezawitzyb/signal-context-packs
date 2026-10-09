"""Brand perception (change V12): numbers in code, then ONE writer call for 2-5 findings, verified like every claim.

Only for packs whose confirmed goals include brand_perception. The writer sees the numbers (analysis/brand.py),
the groups of the brand's posts a finding may rest on ("bases", each with its size) and the brand's posts as
untrusted data. It picks a basis per finding; counts, strength and confidence come from that basis in code.
Quotes must be exact substrings of the evidence excerpt; every claim goes through the claim check, and a
not-supported claim is dropped. Below the minimum number of mentions there is no call and no finding.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from ctxpack.analysis import brand as an
from ctxpack.analysis.metrics import author_key, recency_share
from ctxpack.config import load_yaml
from ctxpack.llm.client import LLMError, load_prompt, structured, untrusted
from ctxpack.schemas.plan import brand_names
from ctxpack.synthesis import confidence as conf
from ctxpack.synthesis.verify import Report, check_claims, exact_quote, top_author_share
from ctxpack.synthesis.write import evidence_entry

log = logging.getLogger(__name__)

FRAMING = ("Online mentions from vocal people, not a survey: use these as signals, not as awareness or "
           "satisfaction numbers.")


class QuoteOut(BaseModel):
    doc_id: str
    text: str


class FindingOut(BaseModel):
    kind: str = Field(description="perception, praise, criticism, differentiation or awareness.")
    claim: str = Field(description="One sentence a person could say out loud, no numbers.")
    summary_for_humans: str = ""
    basis: str = Field(description="The basis id the claim rests on, exactly as listed.")
    doc_ids: list[str] = Field(default_factory=list, description="1-5 posts from that basis that show it.")
    quotes: list[QuoteOut] = Field(default_factory=list, description="0-2 exact quotes from those posts.")


class BrandOut(BaseModel):
    findings: list[FindingOut] = Field(default_factory=list)


def wanted(intake: dict | None) -> bool:
    return "brand_perception" in ((intake or {}).get("goals") or [])


def _fake(user: str) -> dict:
    """LLM_FAKE: one perception finding on the largest basis, citing its first post with a short quote."""
    basis = re.search(r"^- (all) \((\d+) posts\)", user, flags=re.M)
    doc = re.search(r'<untrusted_user_content id="([^"]+)">\n(.*?)\n</untrusted_user_content>', user, flags=re.S)
    if not (basis and doc):
        return {"findings": []}
    words = doc.group(2).split()[:4]
    return {"findings": [{"kind": "perception", "claim": "Fake: people talk about the brand mostly in passing.",
                          "basis": "all", "doc_ids": [doc.group(1)],
                          "quotes": [{"doc_id": doc.group(1), "text": " ".join(words)}] if words else []}]}


def _window(text: str, quote: str, n: int) -> str:
    """At most n chars of text around the quote, cut at spaces; always an exact substring of text."""
    i = text.find(quote)
    if len(text) <= n or i < 0:
        return text[:n]
    start = max(0, i - (n - len(quote)) // 2)
    start = text.rfind(" ", 0, start) + 1 if start else 0
    end = min(len(text), start + n)
    if end < len(text) and " " in text[start:end]:
        end = text.rfind(" ", start, end)
    piece = text[start:end]
    return piece if quote in piece else quote[:n]


def _user(rows: list[dict], groups: dict[str, list[Any]], members: list[Any], chars: int) -> str:
    lines = ["Numbers (computed in code; do not restate them as findings):"]
    for r in rows:
        lines.append(f"- {r['name']}{' (parent)' if r['is_parent'] else ''}: {r['mentions']} posts, {r['unprompted']} "
                     f"unprompted, share of voice {r['share_of_voice']}, stance {r['stance_mix']}, relation "
                     f"{r['relation_mix']}, praised {r['aspects_praised']}, criticised {r['aspects_criticised']}")
    lines.append("\nBases (a finding rests on exactly one; pick the one that fits the claim):")
    lines += [f"- {k} ({len(v)} posts)" for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]
    lines.append("\nThe brand's posts:")
    for d in members:
        lines.append(untrusted(d.id, (d.text_en and d.text_en != d.text and f"{d.text[:chars * 2]}\n[en] "
                                      f"{d.text_en[:chars * 2]}") or d.text[:chars * 2]))
    return "\n".join(lines)


async def build(run: Any, interp: Any, docs: list[Any], evidence: list[dict], thin: bool = False
                ) -> tuple[dict | None, list[dict], float]:
    """(brand_perception section or None, new evidence entries, usd). None when the goal is not chosen."""
    intake = run.intake or {}
    if not wanted(intake):
        return None, [], 0.0
    cfg = load_yaml("scoring")["brand"]
    chars = load_yaml("modes")["synthesis"]["evidence_chars"]
    brands, parents = brand_names(intake, run.interpretation)
    if not brands:
        return {"brands": [], "findings": [], "note": "No brand name was given, so nothing could be measured."}, [], 0.0
    own, members = an.stats(docs, brands, brands[0], parent=parents)
    rows = [own]
    if parents:
        rows.append(an.stats(docs, parents, parents[0], exclude=brands, is_parent=True)[0])
    notes = [FRAMING]
    if own["unprompted"] < cfg["min_unprompted"]:
        notes.append(f"Only {own['unprompted']} post(s) named {brands[0]} without being searched for by name: "
                     "few people bring it up unasked, a sign of low awareness in these communities.")
    if own["mentions"] < cfg["min_mentions"]:
        notes.append(f"{own['mentions']} post(s) named {brands[0]}: too few mentions to judge how people see it.")
        return {"brands": rows, "findings": [], "note": " ".join(notes)}, [], 0.0

    groups = an.bases(members, brands)
    ranked = sorted(members, key=lambda d: -(d.engagement_percentile or 0))[:cfg["member_texts_max"]]
    try:
        res = await structured("reasoner", load_prompt("brand_perception"), _user(rows, groups, ranked, chars),
                               BrandOut, "record_brand_findings", description="Record the brand-perception findings.",
                               max_tokens=4000, fake=_fake)
    except LLMError as exc:  # never sinks the pack: the numbers stand on their own
        log.warning("brand findings call failed: %s", exc)
        return {"brands": rows, "findings": [], "note": " ".join(notes)}, [], 0.0
    usd = res.usd

    ev_of = {e["doc_id"]: e["id"] for e in evidence}
    ev_text = {e["id"]: e["text"] for e in evidence}
    next_n = max([int(e["id"].split("-")[1]) for e in evidence] or [0]) + 1
    docs_by_id = {d.id: d for d in docs}
    new_ev: list[dict] = []
    drafts: list[dict] = []
    for f in res.data.findings[:cfg["findings_max"]]:
        group = groups.get(f.basis.strip())
        kind = f.kind.strip().lower()
        if not group or kind not in ("perception", "praise", "criticism", "differentiation", "awareness"):
            continue
        in_group = {d.id for d in group}
        cited = [i for i in dict.fromkeys(f.doc_ids) if i in in_group][:5]
        if not cited:
            continue
        if not an.basis_fits(kind, f.basis.strip()):  # counts never borrow from a wider group (seen live: BRP-01)
            group = [docs_by_id[i] for i in cited]
        quotes = []
        for q in f.quotes[:2]:
            d = docs_by_id.get(q.doc_id)
            if d is None or q.doc_id not in cited or exact_quote(q.text, d.text) is None:
                continue
            exact = exact_quote(q.text, d.text)
            if q.doc_id not in ev_of:
                entry = evidence_entry(d, f"EV-{next_n:04d}", chars)
                entry["text"] = _window(d.text.strip(), exact, chars)
                next_n += 1
                ev_of[d.id], ev_text[entry["id"]] = entry["id"], entry["text"]
                new_ev.append(entry)
            if exact_quote(exact, ev_text[ev_of[d.id]]):
                quotes.append({"evidence_id": ev_of[d.id], "text": exact_quote(exact, ev_text[ev_of[d.id]])})
        for i in cited:
            if i not in ev_of:
                entry = evidence_entry(docs_by_id[i], f"EV-{next_n:04d}", chars)
                next_n += 1
                ev_of[i], ev_text[entry["id"]] = entry["id"], entry["text"]
                new_ev.append(entry)
        drafts.append({"id": f"BRP-{len(drafts) + 1:02d}", "kind": kind, "brand": brands[0], "claim": f.claim.strip(),
                       "summary_for_humans": f.summary_for_humans.strip(), "group": group,
                       "evidence_ids": [ev_of[i] for i in cited], "quotes": quotes})

    report = Report()
    verdicts = await check_claims(drafts, ev_text, report) if drafts else {}
    usd += report.usd
    counted = len([d for d in docs if d.is_relevant and not d.short_form])
    findings = []
    for it in drafts:
        v = verdicts.get(it["id"])
        if v is not None and v.verdict == "not_supported":
            continue
        group = it.pop("group")
        engaged = sorted(d.engagement_percentile for d in group if d.engagement_percentile is not None)
        result = conf.assess(conf.Evidence(
            members=len(group), authors=len({author_key(d) for d in group}),
            platforms=len({str(d.platform) for d in group}), sources=len({d.source_unit for d in group}),
            engagement_median=engaged[len(engaged) // 2] if engaged else None,
            recency=recency_share(group, datetime.now(timezone.utc).date(), interp.time_window_days), verifier=v.verdict if v else None,
            claim_type="observed", top_author_share=top_author_share([d.id for d in group], docs_by_id),
            thin_evidence=thin))
        findings.append({**it, "id": f"BRP-{len(findings) + 1:02d}", "type": "brand_finding",
                         "counts": {"matching": len(group), "of_total": counted},
                         "confidence": {"score": result.score, "label": result.label},
                         "claim_type": result.claim_type, "safe_to_assert": result.safe_to_assert,
                         "non_obvious": False,
                         "strength": {"evidence_count": len(group),
                                      "distinct_authors": len({author_key(d) for d in group}),
                                      "platforms": sorted({str(d.platform) for d in group}),
                                      "engagement_percentile_median": engaged[len(engaged) // 2] if engaged else None}})
    used = {e for it in findings for e in it["evidence_ids"] + [q["evidence_id"] for q in it["quotes"]]}
    return {"brands": rows, "findings": findings, "note": " ".join(notes)}, [e for e in new_ev if e["id"] in used], usd
