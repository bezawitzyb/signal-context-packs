"""Relevance screening (F4-5): worker batches of 30, at most 5 at once."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pydantic import BaseModel, Field

from ctxpack.config import load_yaml
from ctxpack.llm.client import batched, load_prompt, structured, untrusted
from ctxpack.schemas.enums import RelevanceReason


class RelevanceItem(BaseModel):
    id: str
    relevance: float = Field(ge=0, le=1)
    is_relevant: bool
    language: str = Field(description="ISO 639-1 code, e.g. en, nl, de.")
    market_match: bool | None = None
    is_promotional: bool = False
    research_question_ids: list[str] = Field(default_factory=list)
    reason: RelevanceReason


class RelevanceBatch(BaseModel):
    items: list[RelevanceItem]


@dataclass
class BriefContext:
    """What the relevance worker needs to know about the brief."""

    topic: str
    market: str = "global"
    languages: list[str] = field(default_factory=lambda: ["en"])
    audience: str = ""
    research_questions: dict[str, str] = field(default_factory=dict)  # id -> question
    goals: str = ""                                                     # V12: confirmed goals in plain words
    offer: str = ""                                                     # V12: the user's offer and its stage
    key_question: str = ""                                              # V12
    brands: list[str] = field(default_factory=list)                     # V12: the user's brand (aliases)
    parent_brands: list[str] = field(default_factory=list)              # V12


@dataclass
class RelevanceOutcome:
    verdicts: dict[str, RelevanceItem]
    usd: float = 0.0


def brief_block(ctx: BriefContext) -> str:
    rqs = "\n".join(f"- {rid}: {q}" for rid, q in ctx.research_questions.items()) or "- (none yet)"
    extra = "".join([
        f"\nThe user's goals (main first; they decide emphasis, never what is on-topic): {ctx.goals}" if ctx.goals
        else "",
        f"\nWhat the user offers: {ctx.offer}" if ctx.offer else "",
        f"\nTheir key question: {ctx.key_question}" if ctx.key_question else "",
        f"\nThe user's own brand: {', '.join(ctx.brands)}" if ctx.brands else "",
        f" (parent brand: {', '.join(ctx.parent_brands)})" if ctx.brands and ctx.parent_brands else ""])
    return (f"Topic: {ctx.topic}\nMarket: {ctx.market}\nLanguages: {', '.join(ctx.languages)}\n"
            f"Audience: {ctx.audience or 'not specified'}{extra}\nResearch questions:\n{rqs}")


def _fake_answer(ctx: BriefContext):
    """LLM_FAKE: deterministic keyword overlap with the topic. No network."""
    topic_words = {w for w in re.findall(r"\w+", ctx.topic.lower()) if len(w) > 2}

    def fake(user: str) -> dict:
        items = []
        for item_id, body in re.findall(r'<untrusted_user_content id="([^"]+)">\n(.*?)\n</untrusted_user_content>',
                                        user, flags=re.S):
            words = set(re.findall(r"\w+", body.lower()))
            hit = bool(topic_words & words)
            items.append({"id": item_id, "relevance": 0.8 if hit else 0.1, "is_relevant": hit,
                          "language": ctx.languages[0], "market_match": None, "is_promotional": False,
                          "research_question_ids": list(ctx.research_questions)[:1] if hit else [],
                          "reason": "on_topic" if hit else "off_topic"})
        return {"items": items}

    return fake


async def classify(texts: dict[str, str], ctx: BriefContext) -> RelevanceOutcome:
    """Screen {id: text}. Items the model skips get no verdict (treated as not relevant)."""
    cfg = load_yaml("modes")["cleaning"]
    system = load_prompt("relevance")

    async def run(batch: list[str]):
        user = brief_block(ctx) + "\n\nItems:\n\n" + "\n\n".join(untrusted(i, texts[i]) for i in batch)
        return await structured("worker", system, user, RelevanceBatch, "record_relevance",
                                description="Record a relevance verdict for every item.",
                                fake=_fake_answer(ctx))

    results = await batched(list(texts), run, size=cfg["relevance_batch_size"],
                            parallel=cfg["relevance_parallel_max"])
    outcome = RelevanceOutcome(verdicts={})
    for res in results:
        outcome.usd += res.usd
        for item in res.data.items:
            if item.id in texts:  # ignore ids the model invented
                outcome.verdicts[item.id] = item
    return outcome
