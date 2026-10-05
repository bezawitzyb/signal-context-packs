"""Pack views for agents (PRD 11.2): digest and full; fields select sections.

Guardrails and instructions_for_agents are ALWAYS included, in every view.
"""

from __future__ import annotations

import json
import re
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


def _first_sentence(text: str, max_chars: int = 120) -> str:
    first = re.split(r"(?<=[.;:!?])\s", text.strip(), maxsplit=1)[0]
    return first if len(first) <= max_chars else first[:max_chars - 1].rsplit(" ", 1)[0] + "…"


def compact_guardrails(g: dict) -> dict:
    """Digest guardrails: say_this, not_this, never_claim and the quote note in full (never cut a rule);
    sensitivities as their first sentence. The full view keeps everything."""
    return {**g, "sensitivities": [_first_sentence(x) for x in g.get("sensitivities", [])]}


def digest_view(pack: dict) -> dict[str, Any]:
    """~1,100 tokens (modes.yaml digest_view_max_tokens): five truths, do first, top tensions, top lexicon,
    guardrails, agent instructions.
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
            "five_truths": [{"text": _first_sentence(t["text"], 140), "item_ids": t["item_ids"]}
                            for t in pack["snapshot"]["five_truths"][:sizes["truths"]]],
            "do_first": [{"id": d["id"], "action": _first_sentence(d["action"], 140)}
                         for d in pack["do_first"][:sizes["do_first"]]],
            "top_tensions": [{"id": t["id"], "claim": _first_sentence(t["claim"], 140),
                              "confidence": t["confidence"]["label"]} for t in pack["tensions"][:sizes["tensions"]]],
            "top_lexicon": [{"term": x["term"], "meaning": _first_sentence(x["meaning"], 60)}
                            for x in pack["voice"]["lexicon"][:sizes["lexicon"]]],
            "guardrails": compact_guardrails(pack["guardrails"]),
            "instructions_for_agents": pack["instructions_for_agents"],
            "more": "Shortened texts: open any id with get_insight / items endpoint. Full guardrails and every "
                    "section: view=full (fields=guardrails,...).",
        }

    view = build()
    limit = cfg()["digest_view_max_tokens"]
    # shrink the least important list first: words, then tensions, then actions, truths last
    for key in ["lexicon"] * 5 + ["tensions"] + ["lexicon", "do_first", "tensions", "truths"] * 4:
        if tokens(json.dumps(view, ensure_ascii=False)) <= limit:
            break
        sizes[key] = max(1, sizes[key] - 1)
        view = build()
    return view
