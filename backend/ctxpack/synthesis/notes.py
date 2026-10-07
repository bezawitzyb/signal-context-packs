"""Section notes (change V4, PRD 6.1b): one so_what line per section, tied to the user's goal, and 1-3
"what performs" takeaways (a concrete recommendation and why) from the performing posts.
One reasoner call after consolidation; empty sections get their reason in code (finalize.py)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ctxpack.llm.client import LLMError, load_prompt, structured, untrusted

NOTE_SECTIONS = ["themes", "pain_points", "tensions", "motivations", "objections", "segments", "culture",
                 "white_space", "what_performs", "platform_lens"]


class SoWhat(BaseModel):
    section: str
    so_what: str = Field(description="One line: what this section means for the user's goal.")


class TakeawayOut(BaseModel):
    takeaway: str = Field(description="A concrete recommendation.")
    why: str = Field(description="Why, from the performing posts.")
    post_ids: list[str] = Field(default_factory=list, description="PERF ids it rests on.")


class NotesAnswer(BaseModel):
    so_what: list[SoWhat] = Field(default_factory=list)
    takeaways: list[TakeawayOut] = Field(default_factory=list, max_length=3)


def _fake(user: str) -> dict:
    sections = re.findall(r"^## (\w+)", user, flags=re.M)
    posts = re.findall(r"\b(PERF-\d{2})\b", user)
    return {"so_what": [{"section": s, "so_what": f"What {s.replace('_', ' ')} means for your goal."}
                        for s in sections],
            "takeaways": [{"takeaway": "Lead with the format that performed best.", "why": "Fake.",
                           "post_ids": posts[:2]}] if posts else []}


def _user(sections: dict[str, Any], goal: str) -> str:
    parts = [f"Goal: {goal}"]
    for name in NOTE_SECTIONS:
        items = sections.get(name) or []
        if not items:
            continue
        if name == "what_performs":
            lines = [f"- {p['id']} ({p['platform']}, {p['format']}): {p['why_it_worked']}" for p in items]
        elif name == "platform_lens":
            lines = [f"- {p['platform']}: {p.get('tone', '')} {p.get('what_is_unique', '')}" for p in items]
        else:
            lines = [f"- {it['id']}: {it['claim']}" for it in items[:4]]
        parts.append(f"## {name}\n" + "\n".join(lines))
    return untrusted("sections", "\n\n".join(parts))


async def section_notes(sections: dict[str, Any], goal: str) -> tuple[dict[str, str], list[dict], float]:
    """({section: so_what}, takeaways with TKW ids, usd). A failed call leaves both empty (never blocks)."""
    try:
        res = await structured("reasoner", load_prompt("section_notes"), _user(sections, goal), NotesAnswer,
                               "record_notes", description="Record the so-what lines and the takeaways.",
                               max_tokens=2000, fake=_fake)
    except LLMError:
        return {}, [], 0.0
    known = {p["id"] for p in sections.get("what_performs", [])}
    so_what = {s.section: s.so_what.strip() for s in res.data.so_what
               if s.section in NOTE_SECTIONS and sections.get(s.section) and s.so_what.strip()}
    takeaways = [{"id": f"TKW-{n:02d}", "takeaway": t.takeaway.strip(), "why": t.why.strip(),
                  "post_ids": [p for p in t.post_ids if p in known]}
                 for n, t in enumerate(res.data.takeaways[:3], 1) if t.takeaway.strip()]
    return so_what, takeaways, res.usd
