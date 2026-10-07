"""Synthesis by layer group (F4-10, PRD FR-D2): two writer calls in parallel, then non_obvious (F4-9).

Call A writes the landscape and the voice, call B motivations, tensions,
objections, competition and implications. Each call sees only its verified
clusters and up to ~60 numbered evidence items (E01..) from them, wrapped as
untrusted content. Code then:
  - keeps an item only if its cluster belongs to that section and at least one
    cited evidence item is a verified member of that cluster (tension sides:
    of their own side's cluster);
  - adds counts, strength, emotion, trend and recency from the cluster's
    metrics (writers never output numbers);
  - gives deterministic ids by rank (biggest cluster first) and numbers the
    evidence EV-0001.. by first use;
  - marks non_obvious with one worker pass against the generic baseline.
Quotes are checked word for word in Step 3.4 (verify.py). The draft is saved
to runs.draft; confidence and safe_to_assert are added in Step 3.4.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ctxpack.analysis import metrics as met
from ctxpack.collect.relevance import BriefContext, brief_block
from ctxpack.config import load_yaml
from ctxpack.llm.client import batched, load_prompt, structured, untrusted
from ctxpack.schemas.enums import ClusterKind, CultureKind, HypothesisStatus

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# The writers' answers (F4-10)
# --------------------------------------------------------------------------


def _honest(value: object) -> str:
    """observed or inferred: no outside facts, so never "external"."""
    return "observed" if value == "observed" else "inferred"


class QuoteOut(BaseModel):
    evidence: str = Field(description="Evidence id, e.g. E03.")
    text: str = Field(description="Exact copy from that evidence text.")


class ItemOut(BaseModel):
    cluster_id: str
    claim: str
    summary_for_humans: str = ""
    claim_type: str = Field(default="observed", description="observed or inferred.")
    evidence: list[str] = Field(default_factory=list, description="1-5 evidence ids from the cluster.")
    quotes: list[QuoteOut] = Field(default_factory=list)
    segment_cluster_ids: list[str] = Field(default_factory=list)

    _claim_type = field_validator("claim_type", mode="before")(_honest)


class ThemeOut(ItemOut):
    label: str


class LensOut(BaseModel):
    platform: str
    tone: str = ""
    what_is_unique: str = ""
    evidence: list[str] = Field(default_factory=list)


class LexiconOut(ItemOut):
    term: str
    meaning: str
    language: str = "en"


class PhraseOut(ItemOut):
    text: str = Field(description="The phrase, copied exactly from cited evidence.")
    language: str = "en"


class SegmentOut(ItemOut):
    name: str
    description: str = ""


class CultureOut(ItemOut):
    kind: str = Field(description="format, community, creator or code.")
    name: str
    platform: str | None = None
    url: str | None = None


class MomentOut(ItemOut):
    name: str
    timing: str = ""


class VoiceOut(BaseModel):
    tone: str = ""
    code_switching: str | None = None
    category_words_they_use: list[str] = Field(default_factory=list)
    say_this: list[str] = Field(default_factory=list)
    not_this: list[str] = Field(default_factory=list)


class AnswerA(BaseModel):
    themes: list[ThemeOut] = Field(default_factory=list)
    platform_lens: list[LensOut] = Field(default_factory=list)
    lexicon: list[LexiconOut] = Field(default_factory=list)
    phrases: list[PhraseOut] = Field(default_factory=list)
    segments: list[SegmentOut] = Field(default_factory=list)
    culture: list[CultureOut] = Field(default_factory=list)
    moments: list[MomentOut] = Field(default_factory=list)
    voice: VoiceOut = Field(default_factory=VoiceOut)


class TensionOut(BaseModel):
    cluster_id: str = Field(description="The want cluster of the pair.")
    claim: str
    summary_for_humans: str = ""
    claim_type: str = "observed"
    want_text: str
    want_evidence: list[str] = Field(default_factory=list)
    but_text: str
    but_evidence: list[str] = Field(default_factory=list)
    quotes: list[QuoteOut] = Field(default_factory=list)
    segment_cluster_ids: list[str] = Field(default_factory=list)

    _claim_type = field_validator("claim_type", mode="before")(_honest)


class CompetitorOut(BaseModel):
    cluster_id: str
    tone: str = ""
    praised: list[str] = Field(default_factory=list)
    mocked: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class OpportunityOut(BaseModel):
    cluster_id: str
    title: str
    description: str


class HypothesisOut(BaseModel):
    id: str
    status: HypothesisStatus = HypothesisStatus.inconclusive
    why: str = ""
    evidence: list[str] = Field(default_factory=list)


class RiskOut(BaseModel):
    text: str
    cluster_ids: list[str] = Field(default_factory=list)


class PerformOut(BaseModel):
    evidence: str
    format: str
    why_it_worked: str


class AnswerB(BaseModel):
    tensions: list[TensionOut] = Field(default_factory=list)
    motivations: list[ItemOut] = Field(default_factory=list)
    objections: list[ItemOut] = Field(default_factory=list)
    competitors: list[CompetitorOut] = Field(default_factory=list)
    white_space: list[ItemOut] = Field(default_factory=list)
    opportunities: list[OpportunityOut] = Field(default_factory=list)
    hypotheses: list[HypothesisOut] = Field(default_factory=list)
    risks: list[RiskOut] = Field(default_factory=list)
    what_performs: list[PerformOut] = Field(default_factory=list)


class Coverage(BaseModel):
    id: str
    covered: bool


class CoverageBatch(BaseModel):
    items: list[Coverage]


CALL_A_KINDS = {ClusterKind.theme, ClusterKind.lexicon, ClusterKind.segment, ClusterKind.moment}
CALL_B_KINDS = {ClusterKind.motivation, ClusterKind.tension_want, ClusterKind.tension_but, ClusterKind.objection,
                ClusterKind.competitor, ClusterKind.white_space}


def _cfg() -> dict:
    return load_yaml("modes")["synthesis"]


# --------------------------------------------------------------------------
# Evidence for a call
# --------------------------------------------------------------------------


def excerpt(doc: Any, n: int) -> str:
    """At most n chars of the post, as an exact substring: around its first verbatim phrase, cut at words."""
    text = doc.text.strip()
    if len(text) <= n:
        return text
    start = 0
    for phrase in (doc.extraction or {}).get("verbatim_phrases", []):
        if (i := text.find(phrase)) >= 0:
            start = i
            break
    if start:
        start = max(0, start - 40)
        start = text.rfind(" ", 0, start) + 1 if start else 0
    chunk = text[start:start + n]
    if start + n < len(text) and (cut := chunk.rfind(" ")) > n // 2:
        chunk = chunk[:cut]
    return chunk.strip()


@dataclass
class Pool:
    """The numbered evidence of one call."""

    local: dict[str, str] = field(default_factory=dict)          # E01 -> doc id
    clusters_of: dict[str, list[str]] = field(default_factory=dict)  # doc id -> this call's clusters

    def doc(self, local_id: str) -> str | None:
        return self.local.get(local_id.strip().upper())


def select_pool(clusters: list[Any], extra_docs: list[str], docs_by_id: dict, cfg: dict) -> Pool:
    """Round-robin over the clusters (biggest first): one post each, then a second... until the cap.
    Within a cluster, posts with a verbatim phrase and of quotable length (~200 chars) come first."""
    def rank(doc_id: str) -> tuple:
        d = docs_by_id[doc_id]
        return (not (d.extraction or {}).get("verbatim_phrases"), abs(len(d.text) - 200), doc_id)

    chosen: list[str] = list(dict.fromkeys(extra_docs))
    order = sorted(clusters, key=lambda c: (-len(c.verified_member_ids), c.id))
    queues = {c.id: sorted((m for m in c.verified_member_ids if m in docs_by_id), key=rank) for c in order}
    for _ in range(cfg["evidence_per_cluster_max"]):
        for c in order:
            if len(chosen) >= cfg["evidence_per_call_max"]:
                break
            q = queues[c.id]
            while q and q[0] in chosen:
                q.pop(0)
            if q:
                chosen.append(q.pop(0))
    pool = Pool()
    width = max(2, len(str(len(chosen))))
    for i, doc_id in enumerate(chosen, 1):
        pool.local[f"E{i:0{width}d}"] = doc_id
        pool.clusters_of[doc_id] = [c.id for c in order if doc_id in c.verified_member_ids]
    return pool


def _cluster_line(c: Any) -> str:
    d = c.details or {}
    n = len(c.verified_member_ids)
    extra = {"lexicon": f" | term: {d.get('term')} = {d.get('meaning')}",
             "moment": f" | timing: {d.get('timing', '')}",
             "competitor": f" | spellings: {', '.join([d.get('name', c.label), *d.get('aliases', [])])}"}.get(c.kind, "")
    point = "" if c.kind in ("lexicon", "competitor") else f" | point: {d.get('point', '')}"
    return f"{c.id} | {c.kind} | {n} verified posts | {c.label}{point}{extra}"


def _evidence_block(pool: Pool, docs_by_id: dict, chars: int) -> str:
    parts = []
    for local_id, doc_id in pool.local.items():
        d = docs_by_id[doc_id]
        parts.append(f"{local_id} | clusters {', '.join(pool.clusters_of[doc_id]) or '-'} | {d.platform} | "
                     f"{d.language or '?'}\n" + untrusted(local_id, excerpt(d, chars)))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# Fake writers (LLM_FAKE): one valid item per cluster, quoting its first evidence
# --------------------------------------------------------------------------


def _parse_prompt(user: str) -> tuple[list[tuple[str, str, str]], dict[str, list[str]], dict[str, str]]:
    clusters = re.findall(r"^(CL-\d+) \| (\w+) \| \d+ verified posts \| ([^|\n]*)", user, flags=re.M)
    ev_clusters = {e: [c.strip() for c in cs.split(",")] for e, cs in
                   re.findall(r"^(E\d+) \| clusters ([^|]+) \|", user, flags=re.M)}
    texts = dict(re.findall(r'<untrusted_user_content id="(E\d+)">\n(.*?)\n</untrusted_user_content>', user,
                            flags=re.S))
    return clusters, ev_clusters, texts


def _fake_item(cid: str, ev_clusters: dict, texts: dict) -> dict | None:
    ev = next((e for e, cs in ev_clusters.items() if cid in cs), None)
    if ev is None:
        return None
    words = re.match(r"\S+(?:\s+\S+){0,2}", texts.get(ev, "").strip())
    return {"cluster_id": cid, "claim": f"Fake claim for {cid}.", "evidence": [ev],
            "quotes": [{"evidence": ev, "text": words.group(0)}] if words else []}


def _fake_a(user: str) -> dict:
    clusters, ev_clusters, texts = _parse_prompt(user)
    out: dict[str, list] = {"themes": [], "lexicon": [], "segments": [], "moments": [], "phrases": []}
    for cid, kind, label in clusters:
        if (item := _fake_item(cid, ev_clusters, texts)) is None:
            continue
        if kind == "theme":
            out["themes"].append({**item, "label": label.strip()})
            if item["quotes"]:
                out["phrases"].append({**item, "text": item["quotes"][0]["text"], "language": "nl"})
        elif kind == "lexicon":
            out["lexicon"].append({**item, "term": label.strip(), "meaning": "fake meaning", "language": "nl"})
        elif kind == "segment":
            out["segments"].append({**item, "name": label.strip(), "description": "From the posts."})
        elif kind == "moment":
            out["moments"].append({**item, "name": label.strip(), "timing": "weekends"})
    platforms = re.findall(r"^Platform (\w+):", user, flags=re.M)
    return {**out, "platform_lens": [{"platform": p, "tone": "fake tone", "what_is_unique": "fake"}
                                     for p in platforms],
            "voice": {"tone": "casual", "say_this": ["lekker"], "not_this": ["superfood"]}}


def _fake_b(user: str) -> dict:
    clusters, ev_clusters, texts = _parse_prompt(user)
    out: dict[str, list] = {k: [] for k in ("tensions", "motivations", "objections", "competitors", "white_space",
                                            "opportunities", "hypotheses", "risks")}
    kinds = {cid: kind for cid, kind, _ in clusters}
    for cid, kind, label in clusters:
        item = _fake_item(cid, ev_clusters, texts)
        if item is None:
            continue
        if kind in ("motivation", "objection", "white_space"):
            out[{"motivation": "motivations", "objection": "objections", "white_space": "white_space"}[kind]].append(item)
        elif kind == "competitor":
            out["competitors"].append({"cluster_id": cid, "tone": "mixed", "evidence": item["evidence"]})
        elif kind == "tension_want":
            but = re.search(rf"want {cid} / but (CL-\d+)", user)
            but_item = _fake_item(but.group(1), ev_clusters, texts) if but else None
            if but_item and kinds.get(but.group(1)) == "tension_but":
                out["tensions"].append({"cluster_id": cid, "claim": f"Fake tension {cid}.", "want_text": "want x",
                                        "want_evidence": item["evidence"], "but_text": "but y",
                                        "but_evidence": but_item["evidence"], "quotes": item["quotes"]})
    for cid in re.findall(r"^Opportunity (CL-\d+)", user, flags=re.M):
        out["opportunities"].append({"cluster_id": cid, "title": f"Fake opportunity {cid}", "description": "Do it."})
    for hid in re.findall(r"^(HYP-\d+):", user, flags=re.M):
        out["hypotheses"].append({"id": hid, "status": "inconclusive", "why": "Fake."})
    if clusters:
        out["risks"].append({"text": "Fake risk.", "cluster_ids": [clusters[0][0]]})
    return out


def _fake_coverage(user: str) -> dict:
    return {"items": [{"id": i, "covered": False} for i in re.findall(r"^(\w+-\d+): ", user, flags=re.M)]}


# --------------------------------------------------------------------------
# Building the draft (code)
# --------------------------------------------------------------------------


@dataclass
class WriteOutcome:
    calls: int = 0
    usd: float = 0.0
    written: dict[str, int] = field(default_factory=dict)       # section -> items kept
    dropped: dict[str, int] = field(default_factory=dict)       # reason -> count
    evidence: int = 0
    resumed: bool = False

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1


@dataclass
class Builder:
    clusters: dict[str, Any]
    docs_by_id: dict[str, Any]
    total: int
    today: Any
    window_days: int
    corpus_dates: list
    trends: str | None
    outcome: WriteOutcome

    def members(self, *cluster_ids: str) -> set[str]:
        return {m for cid in cluster_ids for m in self.clusters[cid].verified_member_ids}

    def docs(self, pool: Pool, local_ids: list[str], allowed: set[str], limit: int = 5) -> list[str]:
        out: list[str] = []
        for local_id in local_ids:
            doc_id = pool.doc(local_id)
            if doc_id is None or doc_id not in allowed:
                self.outcome.drop("evidence_not_in_cluster")
            elif doc_id not in out and len(out) < limit:
                out.append(doc_id)
        return out

    def quotes(self, pool: Pool, quotes: list[QuoteOut], allowed: set[str]) -> list[dict]:
        out = []
        for q in quotes:
            doc_id = pool.doc(q.evidence)
            if doc_id in allowed and q.text.strip():
                out.append({"doc_id": doc_id, "text": q.text.strip()})
            else:
                self.outcome.drop("quote_not_in_cluster")
        return out

    def numbers(self, cluster_ids: list[str]) -> dict[str, Any]:
        """Counts, strength, emotion, trend, recency - code only, from verified members."""
        from ctxpack.db import ClusterRow

        row = ClusterRow(run_id="", id="CL-00", kind="theme", label="", member_ids=[],
                         verified_member_ids=sorted(self.members(*cluster_ids)))
        m = met.cluster_metrics(row, self.docs_by_id, self.total, self.today, self.window_days,
                                self.corpus_dates, self.trends)
        min_share = load_yaml("scoring")["metrics"]["item_emotion_min_share"]
        strength = {k: v for k, v in m["strength"].items() if k != "distinct_sources"}
        return {"counts": m["counts"], "strength": strength, "trend": m["trend"], "recency": m["recency"],
                "emotion": [e["emotion"] for e in m["emotion_mix"] if e["share"] >= min_share][:3],
                "recency_share": m["recency_share"], "distinct_sources": m["strength"]["distinct_sources"]}

    def item(self, section: str, out: Any, kinds: set[str], pool: Pool, **fields: Any) -> dict | None:
        cluster = self.clusters.get(out.cluster_id.strip().upper())
        if cluster is None or cluster.kind not in kinds:
            self.outcome.drop("wrong_or_unknown_cluster")
            return None
        allowed = self.members(cluster.id)
        quotes = self.quotes(pool, out.quotes, allowed)
        evidence = self.docs(pool, out.evidence, allowed)
        for q in quotes:  # a quoted post is a receipt too
            if q["doc_id"] not in evidence and len(evidence) < 5:
                evidence.append(q["doc_id"])
        if not evidence:
            self.outcome.drop("no_evidence_left")
            return None
        segs = [s for s in out.segment_cluster_ids if (c := self.clusters.get(s)) and c.kind == ClusterKind.segment]
        return {"cluster_id": cluster.id, "claim": out.claim.strip(),
                "summary_for_humans": out.summary_for_humans.strip(), "claim_type": out.claim_type,
                "evidence_docs": evidence, "quotes": quotes, "segment_cluster_ids": segs,
                **fields, **self.numbers([cluster.id])}


def _rank(items: list[dict], prefix: str) -> list[dict]:
    """Deterministic ids by rank: most verified members first, then cluster id; one item per cluster."""
    seen: set[str] = set()
    kept = []
    for it in sorted(items, key=lambda i: (-i["counts"]["matching"], i["cluster_id"])):
        if it["cluster_id"] in seen and prefix not in ("PHR", "CUL"):
            continue
        seen.add(it["cluster_id"])
        kept.append(it)
    for n, it in enumerate(kept, 1):
        it["id"] = f"{prefix}-{n:02d}"
    return kept


# --------------------------------------------------------------------------
# The stage
# --------------------------------------------------------------------------


async def _write_calls(ctx: BriefContext, clusters: list[Any], docs_by_id: dict, analysis: dict, plan: Any,
                       outcome: WriteOutcome) -> tuple[AnswerA, Pool, AnswerB, Pool]:
    cfg = _cfg()
    system = load_prompt("write")
    seg_lines = "\n".join(f"{c.id} {c.label}" for c in clusters if c.kind == ClusterKind.segment) or "(none)"

    a_clusters = [c for c in clusters if c.kind in CALL_A_KINDS]
    a_pool = select_pool(a_clusters, [], docs_by_id, cfg)
    lens_lines = "\n".join(
        f"Platform {lens['platform']}: {lens['kept_posts']} posts; theme shares: "
        + ", ".join(f"{s['cluster_id']} {s['share']:.0%}" for s in lens["theme_shares"][:6])
        for lens in analysis.get("platform_lens", [])) or "(no platform with enough posts)"
    user_a = (brief_block(ctx) + "\n\nClusters:\n" + "\n".join(map(_cluster_line, a_clusters))
              + f"\n\nSegments:\n{seg_lines}\n\nPlatforms:\n{lens_lines}\n\nEvidence:\n\n"
              + _evidence_block(a_pool, docs_by_id, cfg["evidence_chars"]))

    competitors = {c["cluster_id"] for c in analysis.get("competitors", [])}
    b_clusters = [c for c in clusters if c.kind in CALL_B_KINDS
                  and (c.kind != ClusterKind.competitor or c.id in competitors)]
    perf_docs = [p["doc_id"] for p in analysis.get("what_performs", [])]
    b_pool = select_pool(b_clusters, perf_docs, docs_by_id, cfg)
    by_id = {c.id: c for c in clusters}
    pairs = "\n".join(f"Tension pair: want {c.id} / but {c.details['pair_id']} - {c.label}"
                      for c in b_clusters if c.kind == ClusterKind.tension_want and c.details.get("pair_id") in by_id)
    opps = "\n".join(f"Opportunity {o['cluster_id']}: {o['label']}"
                     for o in analysis.get("opportunities", [])[:cfg["opportunities_max"]]) or "(none)"
    hyps = "\n".join(f"{h.id}: {h.statement}" for h in plan.hypotheses)
    local_of = {v: k for k, v in b_pool.local.items()}
    perf = "\n".join(f"Performing post {local_of[d]}" for d in perf_docs if d in local_of) or "(none)"
    user_b = (brief_block(ctx) + "\n\nClusters:\n" + "\n".join(map(_cluster_line, b_clusters))
              + f"\n\n{pairs or 'Tension pairs: (none)'}\n\nSegments:\n{seg_lines}\n\nOpportunities:\n{opps}"
              + f"\n\nPlan hypotheses:\n{hyps}\n\nWhat performs:\n{perf}\n\nEvidence:\n\n"
              + _evidence_block(b_pool, docs_by_id, cfg["evidence_chars"]))

    res_a, res_b = await asyncio.gather(
        structured("synth", system + "\n\n" + load_prompt("write_a"), user_a, AnswerA, "record_sections_a",
                   description="Record the landscape and voice sections.", max_tokens=cfg["max_tokens"],
                   fake=_fake_a),
        structured("synth", system + "\n\n" + load_prompt("write_b"), user_b, AnswerB, "record_sections_b",
                   description="Record the motivation, tension, objection and implication sections.",
                   max_tokens=cfg["max_tokens"], fake=_fake_b))
    outcome.calls += 2
    outcome.usd += res_a.usd + res_b.usd
    return res_a.data, a_pool, res_b.data, b_pool


def build_sections(a: AnswerA, a_pool: Pool, b: AnswerB, b_pool: Pool, bld: Builder, analysis: dict,
                   plan: Any) -> dict[str, Any]:
    """Validated, numbered draft sections with code-computed numbers (evidence still as doc ids)."""
    k = ClusterKind
    s: dict[str, Any] = {}
    s["themes"] = _rank([i for o in a.themes
                         if (i := bld.item("themes", o, {k.theme}, a_pool, label=o.label.strip()))], "THM")
    s["lexicon"] = _rank([i for o in a.lexicon if (i := bld.item(
        "lexicon", o, {k.lexicon}, a_pool, term=o.term.strip(), meaning=o.meaning.strip(),
        language=o.language.lower()[:2]))], "LEX")
    phrases = []
    for o in a.phrases:
        if (i := bld.item("phrases", o, set(k), a_pool, text=o.text.strip(), language=o.language.lower()[:2])):
            i["quotes"].append({"doc_id": i["evidence_docs"][0], "text": o.text.strip()})  # checked in Step 3.4
            phrases.append(i)
    s["phrases"] = _rank(phrases, "PHR")
    s["segments"] = _rank([i for o in a.segments if (i := bld.item(
        "segments", o, {k.segment}, a_pool, name=o.name.strip(), description=o.description.strip()))], "SEG")
    culture = [i for o in a.culture if o.kind in CultureKind.__members__ and (i := bld.item(
        "culture", o, set(k), a_pool, kind=o.kind, name=o.name.strip(), platform=o.platform, url=o.url))]
    s["culture"] = _rank(culture, "CUL")
    s["moments"] = _rank([i for o in a.moments if (i := bld.item(
        "moments", o, {k.moment}, a_pool, name=o.name.strip(), timing=o.timing.strip()))], "MOM")

    tensions = []
    for o in b.tensions:
        want = bld.clusters.get(o.cluster_id.strip().upper())
        but = bld.clusters.get((want.details or {}).get("pair_id", "")) if want else None
        if not want or want.kind != k.tension_want or not but:
            bld.outcome.drop("wrong_or_unknown_cluster")
            continue
        want_docs = bld.docs(b_pool, o.want_evidence, bld.members(want.id))
        but_docs = bld.docs(b_pool, o.but_evidence, bld.members(but.id))
        if not want_docs or not but_docs:
            bld.outcome.drop("no_evidence_left")
            continue
        tensions.append({"cluster_id": want.id, "but_cluster_id": but.id, "claim": o.claim.strip(),
                         "summary_for_humans": o.summary_for_humans.strip(), "claim_type": o.claim_type,
                         "want": {"text": o.want_text.strip(), "docs": want_docs},
                         "but": {"text": o.but_text.strip(), "docs": but_docs},
                         "evidence_docs": (want_docs[:3] + but_docs[:2])[:5],
                         "quotes": bld.quotes(b_pool, o.quotes, bld.members(want.id, but.id)),
                         "segment_cluster_ids": [x for x in o.segment_cluster_ids if x in bld.clusters],
                         **bld.numbers([want.id, but.id])})
    s["tensions"] = _rank(tensions, "TEN")
    def kind_of(o: ItemOut, default: str) -> str:
        """need / pain / job, objection / myth / trust_marker...: from the cluster, not the writer."""
        c = bld.clusters.get(o.cluster_id.strip().upper())
        return (c.details or {}).get("kind", default) if c else default

    s["motivations"] = _rank([i for o in b.motivations if (i := bld.item(
        "motivations", o, {k.motivation}, b_pool, kind=kind_of(o, "need")))], "MOT")
    s["objections"] = _rank([i for o in b.objections if (i := bld.item(
        "objections", o, {k.objection}, b_pool, kind=kind_of(o, "objection")))], "OBJ")
    s["white_space"] = _rank([i for o in b.white_space if (i := bld.item(
        "white_space", o, {k.white_space}, b_pool, kind=kind_of(o, "unmet_need")))], "WSP")

    # Competitors: every brand with enough mentions (analysis), writer text where given.
    texts = {o.cluster_id.strip().upper(): o for o in b.competitors}
    comps = []
    for n, c in enumerate(analysis.get("competitors", []), 1):
        o = texts.get(c["cluster_id"])
        allowed = bld.members(c["cluster_id"])
        docs = bld.docs(b_pool, o.evidence, allowed, limit=3) if o else []
        docs = docs or sorted(allowed)[:2]  # verified brand mentions as receipts
        comps.append({"id": f"BRD-{n:02d}", "cluster_id": c["cluster_id"], "name": c["name"],
                      "mentions": c["mentions"], "share_of_mentions": c["share"], "tone": o.tone if o else "",
                      "praised": o.praised if o else [], "mocked": o.mocked if o else [], "evidence_docs": docs})
    s["competitors"] = comps

    # Platform lens: shares from code, words from the writer.
    lens_text = {o.platform: o for o in a.platform_lens}
    thm = {t["cluster_id"]: t["id"] for t in s["themes"]}
    s["platform_lens"] = []
    for n, lens in enumerate(analysis.get("platform_lens", []), 1):
        o = lens_text.get(lens["platform"])
        on_platform = {d for d in a_pool.local.values() if str(bld.docs_by_id[d].platform) == lens["platform"]}
        s["platform_lens"].append({
            "id": f"PLT-{n:02d}", "platform": lens["platform"], "kept_posts": lens["kept_posts"],
            "theme_shares": [{"theme_id": thm[x["cluster_id"]], "share": x["share"]}
                             for x in lens["theme_shares"] if x["cluster_id"] in thm],
            "emotion_mix": [{"emotion": e["emotion"], "share": e["share"]} for e in lens["emotion_mix"]],
            "tone": o.tone if o else "", "what_is_unique": o.what_is_unique if o else "",
            "evidence_docs": bld.docs(a_pool, o.evidence, on_platform) if o else []})

    # What performs: posts from code, format and "why" from the writer (always inferred).
    perf_text = {b_pool.doc(o.evidence): o for o in b.what_performs}
    s["what_performs"] = [
        {"id": f"PERF-{n:02d}", "evidence_docs": [p["doc_id"]], "url": p["url"], "platform": p["platform"],
         "engagement_percentile": p["engagement_percentile"], "format": perf_text[p["doc_id"]].format,
         "why_it_worked": perf_text[p["doc_id"]].why_it_worked, "claim_type": "inferred"}
        for n, p in enumerate((p for p in analysis.get("what_performs", []) if p["doc_id"] in perf_text), 1)]

    # Hypotheses from the plan; evidence from any of call B's posts.
    hyp_text = {o.id.strip().upper(): o for o in b.hypotheses}
    pool_b_docs = set(b_pool.local.values())
    s["hypotheses"] = []
    for h in plan.hypotheses:
        o = hyp_text.get(h.id)
        s["hypotheses"].append({"id": h.id, "statement": h.statement,
                                "status": o.status.value if o else "inconclusive",
                                "why": o.why if o else "Not addressed by the evidence.",
                                "evidence_docs": bld.docs(b_pool, o.evidence, pool_b_docs) if o else []})

    s["voice"] = a.voice.model_dump()
    s["_opportunities_text"] = {o.cluster_id.strip().upper(): o.model_dump() for o in b.opportunities}
    s["_risks"] = [r.model_dump() for r in b.risks]
    return s


INSIGHT_SECTIONS = ["themes", "lexicon", "phrases", "segments", "tensions", "motivations", "objections",
                    "culture", "moments", "white_space"]


async def mark_non_obvious(sections: dict, generic: list[str], outcome: WriteOutcome) -> None:
    """One worker pass (batched): is each finding already covered by the generic points?"""
    items = [it for name in INSIGHT_SECTIONS for it in sections[name]]
    system = load_prompt("verify_non_obvious")
    head = "Generic points:\n" + "\n".join(f"- {g}" for g in generic) + "\n\nFindings:\n"
    verdicts: dict[str, bool] = {}

    async def run(batch: list[dict]) -> None:
        user = head + "\n".join(f"{it['id']}: {it['claim']}" for it in batch)
        res = await structured("worker", system, user, CoverageBatch, "record_non_obvious",
                               description="Record for every finding whether the generic points cover it.",
                               fake=_fake_coverage)
        outcome.calls += 1
        outcome.usd += res.usd
        for v in res.data.items:
            verdicts.setdefault(v.id.strip().upper(), not v.covered)

    await batched(items, run, size=_cfg()["non_obvious_batch"], parallel=3)
    for it in items:
        it["non_obvious"] = verdicts.get(it["id"], False)  # no verdict: not claimed as non-obvious


def finish_sections(s: dict, analysis: dict) -> None:
    """Opportunities (scored in code), segment ids, risks, guardrail drafts."""
    seg_ids = {it["cluster_id"]: it["id"] for it in s["segments"]}
    for name in INSIGHT_SECTIONS:
        for it in s[name]:
            it["segment_ids"] = [seg_ids[c] for c in it.pop("segment_cluster_ids", []) if c in seg_ids]
            it.setdefault("related_ids", [])

    by_cluster: dict[str, list[dict]] = {}
    for name in ("motivations", "white_space"):
        for it in s[name]:
            by_cluster.setdefault(it["cluster_id"], []).append(it)
    texts = s.pop("_opportunities_text")
    opps = []
    for o in analysis.get("opportunities", [])[:_cfg()["opportunities_max"]]:
        builds_on = by_cluster.get(o["cluster_id"], [])
        if not builds_on:
            continue
        score, novelty = met.opportunity_score(o["components"], any(i["non_obvious"] for i in builds_on))
        t = texts.get(o["cluster_id"], {})
        opps.append({"cluster_id": o["cluster_id"], "title": t.get("title") or o["label"],
                     "description": t.get("description") or o["label"], "builds_on": [i["id"] for i in builds_on],
                     "score": score, "components": {**o["components"], "novelty": novelty},
                     "evidence_docs": builds_on[0]["evidence_docs"][:3]})
    opps.sort(key=lambda o: (-o["score"], o["cluster_id"]))
    for n, o in enumerate(opps, 1):
        o["id"] = f"OPP-{n:02d}"
    s["opportunities"] = opps

    items_by_cluster: dict[str, list[str]] = {}
    for name in INSIGHT_SECTIONS + ["competitors"]:
        for it in s[name]:
            for cid in (it["cluster_id"], it.get("but_cluster_id")):
                if cid:
                    items_by_cluster.setdefault(cid, []).append(it["id"])
    s["risks"] = [{"id": f"RSK-{n:02d}", "text": r["text"],
                   "item_ids": list(dict.fromkeys(i for c in r["cluster_ids"] for i in items_by_cluster.get(c, [])))}
                  for n, r in enumerate(s.pop("_risks"), 1)]
    voice = s["voice"]
    s["guardrails_draft"] = {"say_this": voice.pop("say_this", []), "not_this": voice.pop("not_this", [])}


SECTION_ORDER = ["themes", "platform_lens", "lexicon", "phrases", "segments", "tensions", "motivations",
                 "objections", "competitors", "culture", "what_performs", "moments", "white_space", "opportunities",
                 "hypotheses"]


def number_evidence(s: dict, docs_by_id: dict, chars: int) -> list[dict]:
    """EV-0001.. by first use in pack order; doc ids in items become evidence ids."""

    ev_of: dict[str, str] = {}

    def ev(doc_id: str) -> str:
        if doc_id not in ev_of:
            ev_of[doc_id] = f"EV-{len(ev_of) + 1:04d}"
        return ev_of[doc_id]

    for name in SECTION_ORDER:
        for it in s[name]:
            it["evidence_ids"] = [ev(d) for d in it.pop("evidence_docs", [])]
            for side in ("want", "but"):
                if side in it:
                    it[side] = {"text": it[side]["text"], "evidence_ids": [ev(d) for d in it[side]["docs"]]}
            if "quotes" in it:
                it["quotes"] = [{"evidence_id": ev(q["doc_id"]), "text": q["text"]} for q in it["quotes"]]
            if name == "what_performs":
                it["evidence_id"] = it["evidence_ids"][0]
    return [evidence_entry(docs_by_id[doc_id], ev_id, chars) for doc_id, ev_id in ev_of.items()]


def evidence_entry(d: Any, ev_id: str, chars: int) -> dict:
    """One pack evidence item from a stored document (excerpt, links, no raw author)."""
    from ctxpack.collect.web import text_fragment_url

    frag = text_fragment_url(d.url, d.fragment_anchor_start, d.fragment_anchor_end) \
        if d.fragment_anchor_start else None
    return {"id": ev_id, "doc_id": d.id, "platform": str(d.platform), "source_unit": d.source_unit,
            "url": d.permalink or d.url, "text_fragment_url": frag,
            "posted_at": d.posted_at.isoformat() if d.posted_at else None,
            "date_precision": str(d.date_precision), "language": d.language or "und",
            "text": excerpt(d, chars), "text_en": d.text_en, "redacted": d.redacted, "short_form": d.short_form,
            "engagement_percentile": d.engagement_percentile, "author_hash": d.author_hash,
            "emotion": list(dict.fromkeys((d.extraction or {}).get("emotion", [])))}


async def write_run(run_id: str, ctx: BriefContext, *, redo: bool = False) -> WriteOutcome:
    """Baseline + both writer calls + non_obvious; saves runs.draft. A saved draft is reused unless redo."""
    from ctxpack import db
    from ctxpack.schemas.plan import Interpretation, Plan
    from ctxpack.synthesis.baseline import generic_points

    outcome = WriteOutcome()
    run = db.get_run(run_id)
    draft = {} if redo else dict(run.draft or {})
    if draft.get("sections"):
        outcome.resumed = True
        return outcome
    interp = Interpretation.model_validate(run.interpretation)
    plan = Plan.model_validate(run.plan)
    analysis = run.analysis or {}
    clusters = db.get_clusters(run_id)
    docs = db.get_documents(run_id, relevant_only=True)
    docs_by_id = {d.id: d for d in docs}

    if not draft.get("generic_points"):
        draft["generic_points"], usd = await generic_points(interp)
        outcome.calls += 1
        outcome.usd += usd
        db.update_run(run_id, draft=draft)  # saved first: a resume never pays for it again

    a, a_pool, b, b_pool = await _write_calls(ctx, clusters, docs_by_id, analysis, plan, outcome)
    counted = [d for d in docs if not d.short_form]
    bld = Builder(clusters={c.id: c for c in clusters}, docs_by_id=docs_by_id, total=len(counted),
                  today=run.created_at.date(), window_days=interp.time_window_days,
                  corpus_dates=sorted(d.posted_at for d in counted if d.posted_at),
                  trends=met.trends_direction(run.collection), outcome=outcome)
    sections = build_sections(a, a_pool, b, b_pool, bld, analysis, plan)
    await mark_non_obvious(sections, draft["generic_points"], outcome)
    finish_sections(sections, analysis)
    evidence = number_evidence(sections, docs_by_id, _cfg()["evidence_chars"])
    outcome.written = {name: len(sections[name]) for name in SECTION_ORDER + ["risks"]}
    outcome.evidence = len(evidence)
    draft.update(sections=sections, evidence=evidence,
                 stats={"written": outcome.written, "dropped": outcome.dropped, "evidence": len(evidence)})
    db.update_run(run_id, draft=draft)
    log.info("run %s writing: %s, dropped %s, %d evidence, %d calls, $%.4f", run_id, outcome.written,
             outcome.dropped, len(evidence), outcome.calls, outcome.usd)
    return outcome


def check_draft(draft: dict, clusters: list[Any]) -> list[str]:
    """Problems with a draft: evidence ids that do not resolve, or that are not verified members of
    the item's cluster (tensions: of their pair). Empty list = all good (Step 3.3 CHECK)."""
    members = {c.id: set(c.verified_member_ids) for c in clusters}
    doc_of = {e["id"]: e["doc_id"] for e in draft.get("evidence", [])}
    problems = []
    s = draft.get("sections", {})
    for name in INSIGHT_SECTIONS + ["competitors"]:
        for it in s.get(name, []):
            allowed = members.get(it["cluster_id"], set()) | members.get(it.get("but_cluster_id", ""), set())
            refs = it.get("evidence_ids", []) + [q["evidence_id"] for q in it.get("quotes", [])]
            refs += [e for side in ("want", "but") if side in it for e in it[side]["evidence_ids"]]
            for ev in refs:
                if ev not in doc_of:
                    problems.append(f"{it['id']}: {ev} does not resolve")
                elif doc_of[ev] not in allowed:
                    problems.append(f"{it['id']}: {ev} is not in {it['cluster_id']}")
    return problems


def estimate_usd(clusters: list[Any]) -> float:
    """Generous upper estimate: baseline + two writer calls + non_obvious (the CLI shows it first)."""
    from ctxpack.config import model_for
    from ctxpack.llm.client import cost_usd

    cfg = _cfg()
    per_call_in = 2500 + len(clusters) * 40 + cfg["evidence_per_call_max"] * 110
    usd = cost_usd(model_for("reasoner"), 600, 800)
    usd += 2 * cost_usd(model_for("synth"), per_call_in, cfg["max_tokens"] // 2)
    usd += cost_usd(model_for("worker"), 4000, 3000)
    return 2 * usd  # retries
