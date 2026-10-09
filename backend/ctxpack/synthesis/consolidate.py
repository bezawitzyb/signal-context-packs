"""Consolidation (change V4, PRD 6.1b): every insight once, in its best place, linked from elsewhere.

After writing, items in different sections that state the same finding are found - code similarity
first (claim words + shared evidence), then ONE small worker call only for the borderline pairs. The item
in the section whose job fits best stays and absorbs the other's evidence; the other is removed and its
section links to the kept one (see_also). Then every item gets typed links to connected items in other
sections from shared posts: an objection shows the pain behind it (comes_from) and the motivation it
blocks (blocks). Thresholds live in config/scoring.yaml (consolidation).
"""

from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from ctxpack.config import load_yaml
from ctxpack.llm.client import LLMError, load_prompt, structured

log = logging.getLogger(__name__)

SECTIONS = ["themes", "pain_points", "tensions", "motivations", "objections", "white_space"]
_STOP = set("the a an and or but to of in on for with is are be it its they them their i my me we our you your "
            "this that not no so as at by from about have has was were just very can do does more most than "
            "when what which who want wants people posters".split())


class PairVerdict(BaseModel):
    pair: str = Field(description="The pair id, e.g. P03.")
    same: bool = Field(description="True only if both state the same finding (not merely related).")
    keep: str = Field(default="a", description='"a" or "b": the item whose section fits the finding best.')


class PairBatch(BaseModel):
    items: list[PairVerdict]


@dataclass
class Report:
    merged: list[tuple[str, str]] = field(default_factory=list)  # (removed id, kept id)
    checked_by_model: int = 0
    calls: int = 0
    usd: float = 0.0


def _cfg() -> dict[str, Any]:
    return load_yaml("scoring")["consolidation"]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w']+", text.casefold().replace("-", "")) if len(w) > 2 and w not in _STOP}


def _docs(it: dict) -> set[str]:
    docs = set(it.get("evidence_docs", []))
    for side in ("want", "but"):
        if isinstance(it.get(side), dict):
            docs |= set(it[side].get("docs", []))
    return docs


def similarity(a: dict, b: dict) -> float:
    """0-1: claim-word overlap (Jaccard) and shared evidence (overlap coefficient); one cluster = 1."""
    if a.get("cluster_id") and a.get("cluster_id") == b.get("cluster_id"):
        return 1.0
    wa, wb = _words(a["claim"]), _words(b["claim"])
    text = len(wa & wb) / len(wa | wb) if wa | wb else 0.0
    da, db = _docs(a), _docs(b)
    ev = len(da & db) / min(len(da), len(db)) if da and db else 0.0
    w = _cfg()["text_weight"]
    return round(w * text + (1 - w) * ev, 3)


def _fake(user: str) -> dict:
    """LLM_FAKE: borderline pairs are kept apart (only code-certain repeats merge in tests)."""
    return {"items": [{"pair": p, "same": False, "keep": "a"} for p in re.findall(r"^(P\d+):", user, flags=re.M)]}


async def consolidate(sections: dict[str, list[dict]], meta: dict[str, dict], report: Report | None = None,
                      members: dict[str, set[str]] | None = None) -> Report:
    """Merge repeats across SECTIONS in place; record see_also in meta; add typed relations.
    members (cluster id -> verified member doc ids): the kept item absorbs only posts of its own cluster(s),
    so its evidence still belongs to it (without members, only posts of the same cluster move)."""
    report = report or Report()
    cfg = _cfg()
    home = {name: n for n, name in enumerate(cfg["home_order"])}
    pairs = []
    for (sa, a), (sb, b) in itertools.combinations([(s, it) for s in SECTIONS for it in sections.get(s, [])], 2):
        if sa != sb:
            score = similarity(a, b)
            if score >= cfg["borderline_from"]:
                pairs.append((score, sa, a, sb, b))
    pairs.sort(key=lambda p: -p[0])
    certain = [p for p in pairs if p[0] >= cfg["merge_at"]]
    borderline = [p for p in pairs if p[0] < cfg["merge_at"]][:cfg["borderline_max_pairs"]]

    decisions: list[tuple[str, dict, str, dict]] = []   # (keep section, keep item, drop section, drop item)
    for _, sa, a, sb, b in certain:
        decisions.append((sa, a, sb, b) if home.get(sa, 99) <= home.get(sb, 99) else (sb, b, sa, a))
    if borderline:
        lines = [f"P{n:02d}: A [{sa}] {a['claim']}\n     B [{sb}] {b['claim']}" for n, (_, sa, a, sb, b) in
                 enumerate(borderline, 1)]
        try:
            res = await structured("worker", load_prompt("consolidate"), "\n".join(lines), PairBatch,
                                   "record_pairs", description="Record a verdict for every pair.", fake=_fake)
            report.calls += 1
            report.usd += res.usd
            verdicts = {v.pair.strip().upper(): v for v in res.data.items}
        except LLMError as exc:  # no verdicts: nothing borderline is merged
            log.warning("consolidation call failed (%s): borderline pairs kept apart", type(exc).__name__)
            verdicts = {}
        report.checked_by_model = len(borderline)
        for n, (_, sa, a, sb, b) in enumerate(borderline, 1):
            v = verdicts.get(f"P{n:02d}")
            if v and v.same:
                decisions.append((sa, a, sb, b) if v.keep.strip().lower() != "b" else (sb, b, sa, a))

    gone: dict[str, str] = {}
    for keep_s, keep, drop_s, drop in decisions:
        keep_id = keep["id"]
        while keep_id in gone:  # the keeper was itself merged away: follow the whole chain (A -> B -> C)
            keep_id = gone[keep_id]
        if keep_id != keep["id"]:
            keep_s, keep = next((s, it) for s in SECTIONS for it in sections.get(s, []) if it["id"] == keep_id)
        if drop["id"] in gone or drop is keep:
            continue
        own = _own_docs(keep, drop, members)
        moved = [d for d in drop.get("evidence_docs", []) if d in own]
        keep["evidence_docs"] = list(dict.fromkeys(keep.get("evidence_docs", []) + moved))[:5]
        have = {q["text"] for q in keep.get("quotes", [])}
        keep["quotes"] = (keep.get("quotes", []) + [q for q in drop.get("quotes", [])
                                                    if q["text"] not in have and q.get("doc_id") in own])[:3]
        sections[drop_s] = [it for it in sections[drop_s] if it is not drop]
        meta.setdefault(drop_s, {}).setdefault("see_also", []).append(keep["id"])
        gone[drop["id"]] = keep["id"]
        report.merged.append((drop["id"], keep["id"]))
    _remap(sections, gone)
    add_relations(sections)
    return report


def _own_docs(keep: dict, drop: dict, members: dict[str, set[str]] | None) -> set[str]:
    """Posts of the dropped item that may move to the kept one: verified members of the kept item's cluster(s)
    (tensions: of their pair). The 2026-10-09 reruns showed merged posts from another cluster failing the CHECK."""
    ids = [c for c in (keep.get("cluster_id"), keep.get("but_cluster_id")) if c]
    if members is None:
        if drop.get("cluster_id") not in ids:
            return set()
        return _docs(drop) | {q.get("doc_id") for q in drop.get("quotes", [])}
    return set().union(*(members.get(c, set()) for c in ids))


def _remap(sections: dict[str, Any], gone: dict[str, str]) -> None:
    """References to a merged item point to the item that kept the finding."""
    if not gone:
        return
    for items in sections.values():
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            for key in ("builds_on", "item_ids", "related_ids", "segment_ids"):
                if key in it:
                    it[key] = list(dict.fromkeys(gone.get(x, x) for x in it[key]))


def add_relations(sections: dict[str, list[dict]]) -> None:
    """Typed links from shared posts: objection -> pain (comes_from), objection -> motivation (blocks),
    otherwise related. At most relations_max per item, the most shared posts first."""
    cfg = _cfg()
    items = [(s, it) for s in SECTIONS for it in sections.get(s, [])]
    for s, it in items:
        mine = _docs(it)
        scored = []
        for s2, other in items:
            if s2 == s:
                continue
            shared = len(mine & _docs(other))
            if shared >= cfg["relation_min_shared_docs"]:
                kind = ("comes_from" if s == "objections" and s2 == "pain_points" else
                        "blocks" if s == "objections" and s2 == "motivations" else "related")
                scored.append((-shared, kind != "related", other["id"], kind))
        scored.sort(key=lambda x: (x[0], not x[1], x[2]))
        it["relations"] = [{"id": i, "kind": k} for _, _, i, k in scored[:cfg["relations_max"]]]
