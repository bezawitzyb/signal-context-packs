"""Pack views for agents (PRD 11.2): digest and full; fields select sections.

Guardrails and instructions_for_agents are ALWAYS included, in every view.
"""

from __future__ import annotations

import json
from typing import Any

from ctxpack.exports.common import cfg, tokens

ALWAYS = ("schema_version", "pack_id", "generated_at", "guardrails", "instructions_for_agents")


def full_view(pack: dict, fields: list[str] | None = None) -> dict[str, Any]:
    """Everything, or only the named top-level sections (plus ALWAYS). Unknown names raise ValueError."""
    if not fields:
        return pack
    unknown = [f for f in fields if f not in pack]
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")
    return {k: v for k, v in pack.items() if k in fields or k in ALWAYS}


def digest_view(pack: dict) -> dict[str, Any]:
    """<= ~500 tokens: five truths, do first, top tensions, top lexicon, guardrails, agent instructions.
    Lists shrink until it fits; guardrails and instructions are never trimmed."""
    interp = pack["brief"]["interpreted"]
    sizes = {"truths": 5, "do_first": 3, "tensions": 3, "lexicon": 8}

    def build() -> dict[str, Any]:
        return {
            "schema_version": pack["schema_version"], "pack_id": pack["pack_id"],
            "generated_at": pack["generated_at"],
            "brief": {k: interp[k] for k in ("topic", "market", "languages", "audience")},
            "coverage_grade": pack["snapshot"]["coverage_grade"],
            "thin_evidence": pack["coverage"]["thin_evidence"],
            "five_truths": [{"text": t["text"], "item_ids": t["item_ids"]}
                            for t in pack["snapshot"]["five_truths"][:sizes["truths"]]],
            "do_first": [{"id": d["id"], "action": d["action"]} for d in pack["do_first"][:sizes["do_first"]]],
            "top_tensions": [{"id": t["id"], "claim": t["claim"], "confidence": t["confidence"]["label"]}
                             for t in pack["tensions"][:sizes["tensions"]]],
            "top_lexicon": [{"term": x["term"], "meaning": x["meaning"]}
                            for x in pack["voice"]["lexicon"][:sizes["lexicon"]]],
            "guardrails": pack["guardrails"],
            "instructions_for_agents": pack["instructions_for_agents"],
        }

    view = build()
    limit = cfg()["digest_view_max_tokens"]
    for key in ("lexicon", "truths", "tensions", "do_first") * 8:
        if tokens(json.dumps(view, ensure_ascii=False)) <= limit:
            break
        sizes[key] = max(1, sizes[key] - 1)
        view = build()
    return view
