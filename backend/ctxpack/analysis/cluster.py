"""Clustering (F4-7) over extraction digests + membership check (F4-9, membership mode).

ONE reasoner call groups the relevant posts. The model sees short post ids
(D001...); code maps them back, drops ids it invented, and keeps short_form
posts only in lexicon clusters. The clusters are saved (CL-01...) before any
check runs, so a resumed run never repeats the paid clustering call.

Membership check: every (cluster, post) pair is confirmed. Lexicon and
competitor members are checked in code (the term or brand must appear in
the post); all others by batched worker yes/no calls, one cluster per call.
Only verified_member_ids count (metrics.py).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from ctxpack.analysis.extract import chunks
from ctxpack.collect.relevance import BriefContext, brief_block
from ctxpack.config import load_yaml
from ctxpack.llm.client import LLMError, batched, load_prompt, structured, untrusted
from ctxpack.schemas.enums import ClusterKind, MotivationKind, ObjectionKind, WhiteSpaceKind

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# The clusterer's answer (F4-7)
# --------------------------------------------------------------------------


class Group(BaseModel):
    label: str = Field(description="Audience-centred name.")
    point: str = Field(description="One sentence every member expresses.")
    member_ids: list[str] = Field(default_factory=list, description="Post ids (D001...) that clearly express it.")


class MotivationGroup(Group):
    kind: MotivationKind = MotivationKind.need


class TensionSideOut(BaseModel):
    text: str = Field(description='This side, e.g. "want to snack healthy".')
    member_ids: list[str] = Field(default_factory=list)


class TensionGroup(BaseModel):
    label: str
    want: TensionSideOut
    but: TensionSideOut


class ObjectionGroup(Group):
    kind: ObjectionKind = ObjectionKind.objection


class SegmentGroup(Group):
    description: str = Field(default="", description="Who they are and what sets them apart (evidence only).")


class LexiconCandidate(BaseModel):
    term: str = Field(description="The term exactly as written in the posts.")
    meaning: str = Field(description="What they mean by it, in English.")
    language: str = Field(default="en", description="ISO 639-1 code of the term.")
    member_ids: list[str] = Field(default_factory=list)


class MomentGroup(Group):
    timing: str = Field(default="", description="When it happens.")


class CompetitorGroup(BaseModel):
    name: str = Field(description="Normalised brand name.")
    aliases: list[str] = Field(default_factory=list, description="Spellings used in the posts.")
    member_ids: list[str] = Field(default_factory=list)


class WhiteSpaceGroup(Group):
    kind: WhiteSpaceKind = WhiteSpaceKind.unmet_need


class ClusterAnswer(BaseModel):
    themes: list[Group] = Field(default_factory=list, description="5-12 audience-centred themes.")
    motivations: list[MotivationGroup] = Field(default_factory=list)
    tensions: list[TensionGroup] = Field(default_factory=list)
    objections: list[ObjectionGroup] = Field(default_factory=list)
    segments: list[SegmentGroup] = Field(default_factory=list, description="2-4, from evidence only.")
    lexicon: list[LexiconCandidate] = Field(default_factory=list)
    moments: list[MomentGroup] = Field(default_factory=list)
    competitors: list[CompetitorGroup] = Field(default_factory=list)
    white_space: list[WhiteSpaceGroup] = Field(default_factory=list)


class MembershipItem(BaseModel):
    id: str
    member: bool


class MembershipBatch(BaseModel):
    items: list[MembershipItem]


def _cfg() -> dict:
    return load_yaml("modes")["clustering"]


# --------------------------------------------------------------------------
# Digests
# --------------------------------------------------------------------------


def _line(alias: str, d: Any, summary_chars: int) -> str:
    if d.short_form:
        return f"{alias} SHORT | {d.platform} | text: {d.text}".replace("\n", " ")
    ex = d.extraction or {}
    parts = [alias, str(d.platform), d.source_unit, f"stance {ex.get('stance', 'neutral')}"]
    if ex.get("emotion"):
        parts.append("emotion " + ",".join(ex["emotion"]))
    if summary_chars:
        parts.append("summary: " + (d.text_en or d.text)[:summary_chars])
    for key in ("needs", "pains", "objections", "questions"):
        if ex.get(key):
            parts.append(f"{key}: " + "; ".join(ex[key]))
    if ex.get("unanswered_question"):
        parts.append("unanswered: " + ex["unanswered_question"])
    if ex.get("brand_mentions"):
        parts.append("brands: " + ", ".join(f"{b['name']} ({b['stance']})" for b in ex["brand_mentions"]))
    if ex.get("verbatim_phrases"):
        parts.append("phrases: " + "; ".join(f'"{p}"' for p in ex["verbatim_phrases"]))
    if ex.get("time_occasion_cues"):
        parts.append("cues: " + "; ".join(ex["time_occasion_cues"]))
    return " | ".join(parts).replace("\n", " ")


def digests(docs: list[Any], max_chars: int, summary_chars: int) -> tuple[str, dict[str, str]]:
    """(digest text, alias -> doc id). Summaries shrink until everything fits in one call."""
    width = max(3, len(str(len(docs))))
    aliases = {f"D{i:0{width}d}": d.id for i, d in enumerate(docs, 1)}
    by_alias = dict(zip(aliases, docs))
    while True:
        lines = [_line(a, d, summary_chars) for a, d in by_alias.items()]
        text = "\n".join(lines)
        if len(text) <= max_chars or summary_chars == 0:
            break
        summary_chars = summary_chars // 2 if summary_chars > 20 else 0
    if len(text) > max_chars:  # still too big without summaries: the tail is left out (logged)
        log.warning("cluster digests: %d chars over the %d max even without summaries; cutting", len(text), max_chars)
        text = text[:max_chars].rsplit("\n", 1)[0]
    return text, aliases


# --------------------------------------------------------------------------
# Answer -> cluster rows
# --------------------------------------------------------------------------


@dataclass
class ClusterOutcome:
    clusters: int = 0
    invented_ids: int = 0          # ids the clusterer made up: dropped
    proposed: int = 0              # (cluster, post) pairs proposed
    verified: int = 0
    rejected: int = 0              # the check said no
    unchecked: int = 0             # no verdict even after the retry pass: not counted
    calls: int = 0
    usd: float = 0.0
    resumed: bool = False          # clusters were already saved: no clustering call
    by_cluster: dict[str, dict[str, int]] = field(default_factory=dict)


def to_rows(answer: ClusterAnswer, aliases: dict[str, str], short_ids: set[str],
            outcome: ClusterOutcome) -> list[Any]:
    """Cluster rows CL-01... with real doc ids. Empty clusters (and one-sided tensions) are left out."""
    from ctxpack.db import ClusterRow

    rows: list[ClusterRow] = []

    def ids(member_ids: list[str], lexicon: bool = False) -> list[str]:
        out: list[str] = []
        for alias in member_ids:
            doc_id = aliases.get(alias.strip().upper())
            if doc_id is None:
                outcome.invented_ids += 1
            elif (lexicon or doc_id not in short_ids) and doc_id not in out:
                out.append(doc_id)
        return out

    def add(cluster_kind: ClusterKind, label: str, members: list[str], **details: Any) -> str | None:
        if not members:
            return None
        cid = f"CL-{len(rows) + 1:02d}"
        rows.append(ClusterRow(run_id="", id=cid, kind=cluster_kind.value, label=label.strip(), member_ids=members,
                               details={k: (v.value if hasattr(v, "value") else v) for k, v in details.items()}))
        return cid

    for g in answer.themes:
        add(ClusterKind.theme, g.label, ids(g.member_ids), point=g.point)
    for g in answer.motivations:
        add(ClusterKind.motivation, g.label, ids(g.member_ids), point=g.point, kind=g.kind)
    for t in answer.tensions:
        want, but = ids(t.want.member_ids), ids(t.but.member_ids)
        if want and but:  # both sides need real members
            w = add(ClusterKind.tension_want, t.label, want, point=t.want.text, side=t.want.text)
            b = add(ClusterKind.tension_but, t.label, but, point=t.but.text, side=t.but.text, pair_id=w)
            rows[-2].details["pair_id"] = b
    for g in answer.objections:
        add(ClusterKind.objection, g.label, ids(g.member_ids), point=g.point, kind=g.kind)
    for g in answer.segments:
        add(ClusterKind.segment, g.label, ids(g.member_ids), point=g.point, description=g.description)
    for g in answer.lexicon:
        add(ClusterKind.lexicon, g.term, ids(g.member_ids, lexicon=True),
            point=f'uses "{g.term}" meaning {g.meaning}', term=g.term, meaning=g.meaning,
            language=g.language.lower()[:2])
    for g in answer.moments:
        add(ClusterKind.moment, g.label, ids(g.member_ids), point=g.point, timing=g.timing)
    for g in answer.competitors:
        add(ClusterKind.competitor, g.name, ids(g.member_ids), point=f"mentions {g.name}", name=g.name,
            aliases=g.aliases)
    for g in answer.white_space:
        add(ClusterKind.white_space, g.label, ids(g.member_ids), point=g.point, kind=g.kind)
    return rows


def _fake_clusters(user: str) -> dict:
    """LLM_FAKE: a small, valid answer built from the digest lines. No network."""
    lines = re.findall(r"^(D\d+)( SHORT)? \| (.*)$", user, flags=re.M)
    longs = [a for a, short, _ in lines if not short]
    shorts = [a for a, short, _ in lines if short]
    if not longs:
        return {}
    half = longs[:max(1, len(longs) // 2)]
    answer: dict[str, Any] = {
        "themes": [{"label": "Fake theme", "point": "Talks about the topic.", "member_ids": longs}],
        "motivations": [{"label": "Fake need", "point": "Wants a good snack.", "kind": "need", "member_ids": half}],
        "tensions": [{"label": "Fake tension", "want": {"text": "to snack", "member_ids": half[:2]},
                      "but": {"text": "it costs", "member_ids": longs[-2:]}}],
        "segments": [{"label": "Fake segment", "point": "Snacks a lot.", "description": "From the posts.",
                      "member_ids": half}],
        "white_space": [{"label": "Fake gap", "point": "Nobody answers this.", "kind": "unanswered_question",
                         "member_ids": longs[:2]}],
    }
    for alias, _, rest in lines:
        if m := re.search(r'phrases: "(\S+)', rest):
            term = m.group(1).strip('".,!?')
            answer["lexicon"] = [{"term": term, "meaning": "a fake meaning", "language": "nl",
                                  "member_ids": [alias] + shorts}]
            break
    for _alias, _, rest in lines:
        if m := re.search(r"brands: ([^(|]+) \(", rest):
            name = m.group(1).strip()
            answer["competitors"] = [{"name": name, "aliases": [], "member_ids": [
                a for a, _, r in lines if f"{name} (" in r]}]
            break
    return answer


async def cluster_documents(docs: list[Any], ctx: BriefContext, outcome: ClusterOutcome) -> list[Any]:
    """The ONE clustering call over all relevant docs' digests; returns unsaved rows."""
    cfg = _cfg()
    text, aliases = digests(docs, cfg["digest_max_chars"], cfg["digest_summary_chars"])
    user = brief_block(ctx) + "\n\nPost digests (one per line):\n\n" + untrusted("digests", text)
    res = await structured("reasoner", load_prompt("cluster"), user, ClusterAnswer, "record_clusters",
                           description="Record every cluster with its member post ids.",
                           max_tokens=cfg["max_tokens"], fake=_fake_clusters)
    outcome.calls += 1
    outcome.usd += res.usd
    return to_rows(res.data, aliases, {d.id for d in docs if d.short_form}, outcome)


def brand_key(name: str) -> str:
    """Spelling-proof brand key: "Lay's", "Lays", "LAYS" and "Calvé"/"Calve" are one key each."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9a-z]", "", plain.casefold())


def _brand_keys(name: str) -> list[str]:
    """Main key first, then keys of names in brackets: "AH (Albert Heijn)" -> ["ah", "albertheijn"]."""
    keys = [brand_key(re.sub(r"\(.*?\)", "", name))] + [brand_key(x) for x in re.findall(r"\((.*?)\)", name)]
    return [k for k in keys if k]


def add_brand_clusters(rows: list[Any], docs: list[Any]) -> int:
    """Competitor clusters for every brand the extraction found that no clusterer competitor covers.

    The clusterer's competitor list is only a normaliser (names + aliases); the extraction already
    recorded every brand each post names, so no brand depends on the clusterer remembering it.
    Spellings merge in code: accents and punctuation are ignored, a name in brackets is the same
    brand, and a product name folds into the brand it starts with ("Lay's paprika" -> Lay's).
    Clusters built here (details.source = "extraction") are rebuilt on every call: idempotent.
    Returns the number of clusters added.
    """
    from collections import Counter

    from ctxpack.db import ClusterRow

    rows[:] = [r for r in rows if (r.details or {}).get("source") != "extraction"]
    parent: dict[str, str] = {}

    def find(k: str) -> str:
        while parent.setdefault(k, k) != k:
            k = parent[k]
        return k

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb, key=lambda k: (len(k), k))] = min(ra, rb, key=lambda k: (len(k), k))

    covered_roots: set[str] = set()
    for r in rows:
        if r.kind == ClusterKind.competitor:
            keys = [k for n in [r.details["name"], *r.details.get("aliases", [])] for k in _brand_keys(n)]
            for k in keys[1:]:
                union(keys[0], k)
            covered_roots.update(keys)

    mentions: list[tuple[str, str, str]] = []  # (doc id, spelling, main key)
    for d in docs:
        if d.short_form:
            continue
        for b in (d.extraction or {}).get("brand_mentions", []):
            keys = _brand_keys(b.get("name", ""))
            if keys:
                find(keys[0])  # registers the key for the prefix fold below
                for k in keys[1:]:
                    union(keys[0], k)
                mentions.append((d.id, b["name"].strip(), keys[0]))
    keys = sorted(parent, key=lambda k: (len(k), k))
    for i, k in enumerate(keys):  # product names fold into the shortest brand key they start with
        if prefix := next((p for p in keys[:i] if len(p) >= 2 and k.startswith(p) and len(p) < len(k)), None):
            union(prefix, k)
    covered = {find(k) for k in covered_roots}

    spellings: dict[str, Counter] = {}
    members: dict[str, list[str]] = {}
    for doc_id, spelling, key in mentions:
        root = find(key)
        if root in covered:
            continue
        spellings.setdefault(root, Counter())[spelling] += 1
        if doc_id not in members.setdefault(root, []):
            members[root].append(doc_id)
    next_n = max((int(r.id.split("-")[1]) for r in rows), default=0) + 1
    for root in sorted(members, key=lambda k: (-len(members[k]), k)):
        # display name: the most used spelling whose own key is the root ("Lay's", not "Lay's paprika")
        names = spellings[root].most_common()
        name = next((n for n, _ in names if _brand_keys(n)[0] == root), names[0][0])
        rows.append(ClusterRow(run_id="", id=f"CL-{next_n:02d}", kind=ClusterKind.competitor.value, label=name,
                               member_ids=members[root],
                               details={"point": f"mentions {name}", "name": name,
                                        "aliases": sorted(set(spellings[root]) - {name}), "source": "extraction"}))
        next_n += 1
    return len(members)


# --------------------------------------------------------------------------
# Membership check
# --------------------------------------------------------------------------


@dataclass
class _Post:
    id: str
    text: str
    language: str | None = None


def code_check(row: Any, docs_by_id: dict[str, Any]) -> list[str] | None:
    """Lexicon: the term appears in the post. Competitor: the brand (or an alias) is named.
    None for kinds the worker checks."""
    members = [i for i in row.member_ids if i in docs_by_id]
    if row.kind == ClusterKind.lexicon:
        term = row.details["term"].casefold()
        return [i for i in members if term in docs_by_id[i].text.casefold()]
    if row.kind == ClusterKind.competitor:
        names = {n.casefold() for n in [row.details["name"], *row.details.get("aliases", [])] if n.strip()}

        def named(d: Any) -> bool:
            brands = {b["name"].casefold() for b in (d.extraction or {}).get("brand_mentions", [])}
            return bool(names & brands) or any(n in d.text.casefold() for n in names)

        return [i for i in members if named(docs_by_id[i])]
    return None


def _fake_membership(user: str) -> dict:
    ids = re.findall(r'<untrusted_user_content id="([^"]+)">', user)
    return {"items": [{"id": i, "member": True} for i in ids]}


async def verify_members(rows: list[Any], docs_by_id: dict[str, Any], outcome: ClusterOutcome) -> None:
    """Fill verified_member_ids on every row not checked yet (details.verified marks a checked row)."""
    cfg = _cfg()
    system = load_prompt("verify_membership")
    verdicts: dict[tuple[str, str], bool] = {}
    by_cluster = {r.id: r for r in rows}
    todo = [r for r in rows if not (r.details or {}).get("verified")]

    worker_rows = []
    for row in todo:
        checked = code_check(row, docs_by_id)
        if checked is not None:
            for doc_id in row.member_ids:
                verdicts[(row.id, doc_id)] = doc_id in checked
        else:
            worker_rows.append(row)

    async def run(job: list[tuple[str, list[_Post]]]) -> None:
        cluster_id, posts = job[0]
        point = by_cluster[cluster_id].details.get("point") or by_cluster[cluster_id].label
        user = f"Cluster point: {point}\n\nPosts:\n\n" + "\n\n".join(untrusted(p.id, p.text) for p in posts)
        try:
            res = await structured("worker", system, user, MembershipBatch, "record_membership",
                                   description="Record for every post whether it expresses the point.",
                                   fake=_fake_membership)
        except LLMError as exc:  # its pairs get the retry pass
            log.warning("membership batch for %s failed: %s", cluster_id, exc)
            return
        outcome.calls += 1
        outcome.usd += res.usd
        wanted = {p.id for p in posts}
        for item in res.data.items:
            if item.id in wanted:
                verdicts.setdefault((cluster_id, item.id), item.member)

    limit = cfg["membership_text_chars"]
    for _ in range(2):  # first pass + one pass for pairs without a verdict
        jobs = []
        for row in worker_rows:
            posts = [_Post(i, docs_by_id[i].text[:limit]) for i in row.member_ids
                     if i in docs_by_id and (row.id, i) not in verdicts]
            jobs += [(row.id, c) for c in chunks(posts, cfg["membership_batch_docs_max"],
                                                 cfg["membership_batch_chars_max"])]
        if not jobs:
            break
        await batched(jobs, run, size=1, parallel=cfg["membership_parallel_max"])

    todo_ids = {r.id for r in todo}
    for row in todo:
        row.verified_member_ids = [i for i in row.member_ids if verdicts.get((row.id, i))]
        row.details = {**(row.details or {}), "verified": True}
    for row in rows:
        yes = len(row.verified_member_ids)
        no = sum(1 for i in row.member_ids if verdicts.get((row.id, i)) is False)
        outcome.by_cluster[row.id] = {"proposed": len(row.member_ids), "verified": yes, "rejected": no}
        outcome.proposed += len(row.member_ids)
        outcome.verified += yes
        outcome.rejected += no
        if row.id in todo_ids:
            outcome.unchecked += len(row.member_ids) - yes - no


# --------------------------------------------------------------------------
# The stage
# --------------------------------------------------------------------------


async def cluster_run(run_id: str, ctx: BriefContext, *, redo: bool = False) -> ClusterOutcome:
    """Cluster a run's relevant docs (unless clusters are already saved) and check every member."""
    from ctxpack import db

    if redo:
        db.delete_clusters(run_id)
    docs = sorted(db.get_documents(run_id, relevant_only=True), key=lambda d: d.id)
    docs_by_id = {d.id: d for d in docs}
    outcome = ClusterOutcome()
    rows = db.get_clusters(run_id)
    if rows:
        outcome.resumed = True
    else:
        rows = await cluster_documents(docs, ctx, outcome)
    before = {r.id for r in rows}
    add_brand_clusters(rows, docs)
    if gone := before - {r.id for r in rows}:  # brand clusters from the extraction are rebuilt each time
        db.delete_clusters(run_id, ids=sorted(gone))
    db.save_clusters(run_id, rows)  # saved before the check: a resume never pays for the clustering call again
    await verify_members(rows, docs_by_id, outcome)
    db.save_clusters(run_id, rows)
    outcome.clusters = len(rows)
    log.info("run %s clustering: %d clusters, pairs proposed %d verified %d rejected %d unchecked %d, "
             "invented ids %d, %d calls, $%.4f", run_id, outcome.clusters, outcome.proposed, outcome.verified,
             outcome.rejected, outcome.unchecked, outcome.invented_ids, outcome.calls, outcome.usd)
    return outcome


def estimate_usd(docs: list[Any]) -> float:
    """Generous upper estimate for clustering + membership (the CLI shows it before a paid run)."""
    from ctxpack.config import model_for
    from ctxpack.llm.client import cost_usd

    cfg = _cfg()
    text, _ = digests(docs, cfg["digest_max_chars"], cfg["digest_summary_chars"])
    # Clustering: digests at ~3 chars per token + prompt; answer = ~4 memberships per post at ~4 tokens + labels.
    usd = cost_usd(model_for("reasoner"), len(text) // 3 + 2000, min(cfg["max_tokens"], len(docs) * 16 + 4000))
    # Membership: ~4 clusters per post, each post's text once per cluster, ~30 posts per call.
    pairs = 4 * len(docs)
    avg = sum(min(len(d.text), cfg["membership_text_chars"]) for d in docs) / max(1, len(docs))
    calls = pairs / cfg["membership_batch_docs_max"] + 1
    usd += cost_usd(model_for("worker"), int(pairs * avg / 3 + calls * 600), pairs * 15)
    return 2 * usd  # retries and the retry pass
