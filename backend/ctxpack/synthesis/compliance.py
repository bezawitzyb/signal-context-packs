"""Compliance flags by category (F4-12, PRD FR-D4): ONE reasoner call over hooks and claims.

Every flag names an item that exists (hooks, do-first actions, this-week posts,
opportunities), a category, the rule area, why, a safer wording and the note
"check with legal - not legal advice". Test texts (CLI --test-hook) are
reviewed in the same call but never enter the pack.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ctxpack.llm.client import load_prompt, structured
from ctxpack.schemas.enums import ComplianceCategory


class FlagOut(BaseModel):
    item_id: str
    risky_claim: str = Field(default="", description="The risky claim itself, in at most 8 words.")
    category: str = "other"
    rule_area: str = ""
    why: str = ""
    safer_wording: str = ""


class ComplianceOut(BaseModel):
    flags: list[FlagOut] = Field(default_factory=list)


def review_items(parts: dict, opportunities: list[dict]) -> dict[str, str]:
    """id -> text of everything that makes a claim to an audience."""
    items = {h["id"]: h["text"] for h in parts["playbook"]["hooks"]}
    items |= {d["id"]: d["action"] for d in parts["do_first"]}
    items |= {p["id"]: f"{p['format']}: {p['angle']}" for p in parts["playbook"]["this_week"]}
    items |= {o["id"]: f"{o['title']}: {o['description']}" for o in opportunities}
    items |= {b["id"]: f"{b['hook']} / {b['angle']} / {b['cta']}" for b in parts.get("post_briefs", [])}
    items |= {d["id"]: " ".join(f"{d.get('title') or ''} {d['body']}".split()) for d in parts.get("drafts", [])}
    return items


def _fake(user: str) -> dict:
    flags = []
    for item_id, text in re.findall(r"^(\w+-\d+): (.*)$", user, flags=re.M):
        low = text.lower()
        if "planet" in low or "save" in low:
            flags.append({"item_id": item_id, "category": "energy_environmental", "rule_area": "green claims",
                          "why": "Fake.", "safer_wording": "Fake."})
        elif "health" in low or "gezond" in low:
            flags.append({"item_id": item_id, "category": "food_nutrition", "rule_area": "EU Reg. (EC) No 1924/2006",
                          "why": "Fake.", "safer_wording": "Fake."})
    return {"flags": flags}


async def flag(items: dict[str, str], category: str, market: str,
               test_texts: list[str] = ()) -> tuple[list[dict], list[dict], float]:
    """(pack flags CMP-01.., flags on test texts, cost)."""
    tests = {f"TEST-{n:02d}": t for n, t in enumerate(test_texts, 1)}
    if not items and not tests:
        return [], [], 0.0
    user = (f"Compliance category of the brief: {category}\nMarket: {market}\n\nItems to review:\n"
            + "\n".join(f"{i}: {t}" for i, t in {**items, **tests}.items()))
    res = await structured("reasoner", load_prompt("compliance"), user, ComplianceOut, "record_flags",
                           description="Record a flag for every item that needs care.", max_tokens=6000, fake=_fake)
    pack_flags, test_flags = [], []
    for f in res.data.flags:
        item_id = f.item_id.strip().upper()
        row = {"item_id": item_id, "risky_claim": f.risky_claim.strip(),
               "category": f.category if f.category in ComplianceCategory.__members__ else "other",
               "rule_area": f.rule_area, "why": f.why, "safer_wording": f.safer_wording,
               "note": "check with legal - not legal advice"}
        if item_id in tests:
            test_flags.append({**row, "text": tests[item_id]})
        elif item_id in items:
            pack_flags.append({"id": f"CMP-{len(pack_flags) + 1:02d}", **row})
    return pack_flags, test_flags, res.usd
