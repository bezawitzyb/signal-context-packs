"""Opportunities you can trust (change V5, PRD 6.1c).

White space and the scored opportunities (draft sections) become ONE list. Counts are code: distinct
authors and communities from the cluster's verified posts; "supported" needs scoring.yaml's minimums,
otherwise "signal" (confidence at most emerging). Before anything is called unserved, one web search per
opportunity (modes.yaml searches_max) looks for existing products, services or content: found ones are
listed (only URLs the search returned) and the opportunity is reworded as a gap in how it is served; none
-> "no existing solution found in our search". "Nobody serves this" is never kept (checked in code).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from ctxpack.analysis.metrics import author_key
from ctxpack.config import get_settings, load_yaml
from ctxpack.llm.client import LLMError, load_prompt, structured, untrusted
from ctxpack.schemas.migrate import cap_emerging

log = logging.getLogger(__name__)

NOT_FOUND = "no existing solution found in our search"
NOT_SEARCHED = "not searched (search limit for this pack)"
SEARCH_FAILED = "the search for existing solutions did not work this time"
_NOBODY = re.compile(r"\b(nobody|no one|no-one|no brand|no company)\b[^.;]*\b(serv|offer|provid|address|solv|answer|explain)",
                     re.I)
_KIND = {"unanswered_question": "content_idea", "unmet_need": "product_idea", "unserved_segment": "positioning"}


class Solution(BaseModel):
    name: str
    url: str


class CheckOut(BaseModel):
    existing_solutions: list[Solution] = Field(default_factory=list)
    opportunity: str = ""
    kind: str = "product_idea"


def no_nobody(text: str) -> str:
    """Drop any clause that claims nobody serves it (V5): the research cannot show that."""
    if not _NOBODY.search(text):
        return text
    parts = [p for p in re.split(r"(?<=[.;])\s+|;\s*", text) if p and not _NOBODY.search(p)]
    return " ".join(parts).strip() or ""


def _search_urls(blocks: list[Any]) -> set[str]:
    urls: set[str] = set()
    for b in blocks:
        content = getattr(b, "content", None)
        if getattr(b, "type", "") == "web_search_tool_result" and isinstance(content, list):
            urls |= {getattr(r, "url", "") for r in content if getattr(r, "url", "")}
    return urls


def _fake(user: str) -> dict:
    return {"existing_solutions": [{"name": "Example tool", "url": "https://example.com/tool"}]
            if "solved elsewhere" in user else [],
            "opportunity": "", "kind": "content_idea" if "?" in user else "product_idea"}


async def check(text: str, markets: str, languages: list[str]) -> tuple[CheckOut | None, float]:
    """One web search for what already addresses it. Only solutions whose URL the search returned stay."""
    cfg = load_yaml("modes")["opportunities"]
    user = (f"Markets: {markets}\nLanguages: {', '.join(languages)}\nOpportunity (from the research):\n"
            + untrusted("opportunity", text))
    try:
        res = await structured("worker", load_prompt("opportunity_check"), user, CheckOut, "record_check",
                               description="Record the existing solutions and the opportunity.", max_tokens=1500,
                               server_tools=["web_search"], server_tool_options={"web_search": {"max_uses": 1}},
                               fake=_fake)
    except LLMError as exc:
        log.warning("opportunity search failed (%s)", type(exc).__name__)
        return None, 0.0
    out = res.data
    if not get_settings().llm_fake:  # never a URL the search did not return
        found = _search_urls(res.blocks)
        out.existing_solutions = [s for s in out.existing_solutions if s.url in found]
    out.existing_solutions = out.existing_solutions[:cfg["solutions_max"]]
    return out, res.usd


async def build(s: dict, clusters: dict[str, Any], docs: list[Any], interp: Any) -> tuple[list[dict], dict[str, str], float]:
    """(opportunities, old id -> new id, usd) from the verified draft sections."""
    score_cfg = load_yaml("scoring")["opportunities"]
    searches = load_yaml("modes")["opportunities"]["searches_max"]
    docs_by_id = {d.id: d for d in docs if d.is_relevant and not d.short_form}
    items = {it["id"]: it for name in ("pain_points", "motivations", "white_space") for it in s.get(name, [])}

    def counts(cluster_id: str | None) -> tuple[int, list[str]]:
        c = clusters.get(cluster_id or "")
        members = [docs_by_id[m] for m in (c.verified_member_ids if c else []) if m in docs_by_id]
        return len({author_key(d) for d in members}), sorted({d.source_unit for d in members})

    candidates = []
    for o in s.get("opportunities", []):  # scored (PRD 5.5) first, best first
        base = next((items[b] for b in o.get("builds_on", []) if b in items), None)
        candidates.append({"old": o["id"], "text": f"{o['title'].strip()}: {o['description'].strip()}",
                           "kind": "product_idea", "cluster_id": o.get("cluster_id"),
                           "confidence": (base or {}).get("confidence") or {"score": 0.0, "label": "speculative"},
                           "evidence_ids": o.get("evidence_ids", [])[:5], "builds_on": o.get("builds_on", []),
                           "related_ids": [], "score": o.get("score"), "components": o.get("components")})
    for w in s.get("white_space", []):
        candidates.append({"old": w["id"], "text": w["claim"], "kind": _KIND.get(w.get("kind"), "content_idea"),
                           "cluster_id": w.get("cluster_id"), "confidence": w["confidence"],
                           "evidence_ids": w.get("evidence_ids", [])[:5], "builds_on": [],
                           "related_ids": w.get("related_ids", []), "score": None, "components": None})

    out, mapping, usd = [], {}, 0.0
    for n, c in enumerate(candidates, 1):
        authors, communities = counts(c["cluster_id"])
        supported = authors >= score_cfg["supported_min_authors"] and len(communities) >= score_cfg["supported_min_communities"]
        text, kind, solutions, note = no_nobody(c["text"]) or c["text"], c["kind"], [], NOT_SEARCHED
        if n <= searches:
            res, cost = await check(text, interp.market, interp.languages)
            usd += cost
            if res is None:
                note = SEARCH_FAILED
            else:
                solutions = [{"name": x.name.strip(), "url": x.url} for x in res.existing_solutions if x.name.strip()]
                reworded = no_nobody(res.opportunity.strip()) if solutions else ""
                text = reworded or text
                kind = res.kind if res.kind in ("content_idea", "product_idea", "positioning") else kind
                note = "" if solutions else NOT_FOUND
        new_id = f"OPP-{n:02d}"
        mapping[c["old"]] = new_id
        out.append({"id": new_id, "type": "opportunity", "opportunity": no_nobody(text) or text, "kind": kind,
                    "status": "supported" if supported else "signal",
                    "confidence": c["confidence"] if supported else cap_emerging(c["confidence"]),
                    "distinct_authors": authors, "communities": communities, "existing_solutions": solutions,
                    "search_note": note, "evidence_ids": c["evidence_ids"], "builds_on": c["builds_on"],
                    "related_ids": c["related_ids"], "cluster_id": c["cluster_id"], "score": c["score"],
                    "components": c["components"]})
    from ctxpack.schemas.migrate import rename_ids

    # links inside the list (a scored opportunity building on white space) use the new ids too; an
    # opportunity never builds on itself
    for o in out:  # only the references: renaming the new ids too would rename them twice (OPP-05 -> OPP-04)
        o["builds_on"], o["related_ids"] = rename_ids(o["builds_on"], mapping), rename_ids(o["related_ids"], mapping)
    for o in out:
        o["builds_on"] = [b for b in o["builds_on"] if b != o["id"]]
        o["related_ids"] = [r for r in o["related_ids"] if r != o["id"]]
    return out, mapping, usd
