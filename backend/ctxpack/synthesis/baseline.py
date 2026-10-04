"""Generic baseline answer (F4-8, PRD FR-D1): one reasoner call with NO evidence.

What a generic marketing answer would say about the audience and topic. Used
for non_obvious (write.py) and the generic-vs-found panel.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ctxpack.llm.client import load_prompt, structured
from ctxpack.schemas.plan import Interpretation


class Baseline(BaseModel):
    generic_points: list[str] = Field(description="8-12 one-sentence points a generic answer would make.")


def _brief(interp: Interpretation) -> str:
    return (f"Topic: {interp.topic}\nMarket: {interp.market}\nLanguages: {', '.join(interp.languages)}\n"
            f"Audience: {interp.audience}\nCategory: {interp.category}\nIntent: {interp.intent}")


def _fake(user: str) -> dict:
    return {"generic_points": ["People want healthy options.", "Price matters to shoppers.",
                               "Social media is the main channel.", "Convenience drives choice.",
                               "Taste is important.", "Sustainability is a growing trend.",
                               "Influencers shape opinions.", "Younger people are more open to new brands."]}


async def generic_points(interp: Interpretation) -> tuple[list[str], float]:
    """(8-12 generic points, cost). The brief only - no posts, no clusters."""
    res = await structured("reasoner", load_prompt("baseline"), _brief(interp), Baseline, "record_baseline",
                           description="Record the generic points.", max_tokens=2000, fake=_fake)
    points = [p.strip() for p in res.data.generic_points if p.strip()][:12]
    return points, res.usd
