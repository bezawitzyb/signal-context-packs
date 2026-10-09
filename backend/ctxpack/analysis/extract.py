"""Per-document extraction (F4-6, PRD FR-C3): worker batches of relevant docs, at most 5 at once.

Each batch is saved to documents.extraction (and documents.text_en) as soon
as it returns, so a resumed run only pays for documents not yet extracted.
Verbatim phrases that are not exact substrings of the document's text are
discarded here, in code. Counts are never made here: clustering and the
metrics count verified members later.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

from pydantic import BaseModel, Field, field_validator

from ctxpack.collect.relevance import BriefContext, brief_block
from ctxpack.config import load_yaml
from ctxpack.llm.client import LLMError, batched, load_prompt, structured, untrusted
from ctxpack.schemas.enums import BrandRelation, EvidenceRole, Emotion, Stance

log = logging.getLogger(__name__)


def _stance(value: object) -> object:
    """An unknown stance becomes neutral instead of failing the whole batch (a paid retry)."""
    return value if value in Stance.__members__.values() else Stance.neutral


class BrandMention(BaseModel):
    name: str = Field(description="Brand, shop or product as written.")
    stance: Stance = Field(default=Stance.neutral, description="The person's stance toward it.")
    aspect: str | None = Field(default=None, description="V12, only for the user's own brand or its parent: what "
                               "about it the item talks about (price, service, app, quality...), 1-3 English "
                               "words. Null otherwise.")
    relation: BrandRelation | None = Field(default=None, description="V12, only for the user's own brand when the "
                                           "item also names or asks about its parent brand: same_as_parent, "
                                           "part_of_parent, distinct or unclear. Null otherwise.")

    _known_stance = field_validator("stance", mode="before")(_stance)

    @field_validator("relation", mode="before")
    @classmethod
    def _known_relation(cls, value: object) -> object:
        return value if value in BrandRelation.__members__.values() or value is None else "unclear"


class ExtractionItem(BaseModel):
    id: str
    text_en: str | None = Field(
        default=None, description="REQUIRED for every item not in English: faithful English translation. "
                                  "Null only if the item is already English.")
    needs: list[str] = Field(default_factory=list)
    pains: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    unanswered_question: str | None = None
    brand_mentions: list[BrandMention] = Field(default_factory=list)
    verbatim_phrases: list[str] = Field(
        default_factory=list, description="Exact substrings of the item's text, original language.")
    stance: Stance = Stance.neutral
    emotion: list[Emotion] = Field(default_factory=list, description="0-3 emotions the text clearly shows.")
    humour_or_irony: bool = False
    code_switching: bool = False
    time_occasion_cues: list[str] = Field(default_factory=list)
    role: EvidenceRole = Field(default=EvidenceRole.unknown, description="Who the author is, only when the text "
                               "shows it: buyer, influencer, user, consumer, other; unknown otherwise.")

    _known_stance = field_validator("stance", mode="before")(_stance)

    @field_validator("role", mode="before")
    @classmethod
    def _known_role(cls, value: object) -> object:
        """An unknown role word is "unknown" instead of failing the whole batch (a paid retry)."""
        v = str(value or "").strip().lower()
        return v if v in EvidenceRole.__members__ else EvidenceRole.unknown

    @field_validator("emotion", mode="before")
    @classmethod
    def _known_emotions(cls, value: object) -> object:
        """Emotions outside the list are dropped instead of failing the whole batch (a paid retry)."""
        known = set(Emotion.__members__.values())
        return [e for e in value if e in known] if isinstance(value, list) else value


class ExtractionBatch(BaseModel):
    items: list[ExtractionItem]


class Doc(Protocol):
    id: str
    text: str
    language: str | None


Saver = Callable[[dict[str, tuple[dict, str | None]]], int]


@dataclass
class ExtractOutcome:
    extracted: int = 0
    missing: list[str] = field(default_factory=list)  # no answer even after the retry pass
    phrases_kept: int = 0
    phrases_dropped: int = 0                          # not exact substrings: discarded
    untranslated: int = 0                             # not English, still no text_en after the retry pass
    calls: int = 0
    usd: float = 0.0


def _cfg() -> dict:
    return load_yaml("modes")["extraction"]


def needs_translation(doc: Doc) -> bool:
    return (doc.language or "").lower() != "en"


def _item(doc: Doc) -> str:
    """One item for the prompt: its language (from the relevance step) outside the untrusted wrapper."""
    return f"Item language: {doc.language or 'unknown'}\n" + untrusted(doc.id, doc.text)


def chunks(docs: list[Doc], max_docs: int, max_chars: int) -> list[list[Doc]]:
    """Greedy batches: at most max_docs per batch and about max_chars of text (a longer doc goes alone)."""
    out: list[list[Doc]] = []
    current: list[Doc] = []
    chars = 0
    for doc in docs:
        if current and (len(current) >= max_docs or chars + len(doc.text) > max_chars):
            out.append(current)
            current, chars = [], 0
        current.append(doc)
        chars += len(doc.text)
    if current:
        out.append(current)
    return out


def clean_item(item: ExtractionItem, doc: Doc, phrases_max: int) -> tuple[dict, str | None, int]:
    """(extraction, text_en, phrases dropped). Keeps only phrases found word for word in doc.text."""
    phrases: list[str] = []
    dropped = 0
    for phrase in item.verbatim_phrases:
        phrase = phrase.strip()
        if not phrase or phrase not in doc.text:
            dropped += 1
        elif phrase not in phrases and len(phrases) < phrases_max:
            phrases.append(phrase)
    extraction = item.model_dump(mode="json", exclude={"id", "text_en"})
    extraction["verbatim_phrases"] = phrases
    extraction["emotion"] = list(dict.fromkeys(extraction["emotion"]))[:3]
    text_en = None if not needs_translation(doc) or not (item.text_en or "").strip() else item.text_en.strip()
    return extraction, text_en, dropped


_NEGATIVE = {"niet", "not", "geen", "duur", "expensive", "hate", "jammer", "vies", "nooit", "never", "teuer"}


def _fake_brands(user: str, body: str, negative: bool) -> list[dict]:
    """LLM_FAKE (V12): the user's brand and its parent when the item names them (from the brief block)."""
    own = re.search(r"^The user's own brand: (.+?)(?: \(parent brand: (.+)\))?$", user, flags=re.M)
    if not own:
        return []
    low = body.lower()
    brand = next((b.strip() for b in own.group(1).split(",") if b.strip().lower() in low), None)
    parent = next((p.strip() for p in (own.group(2) or "").split(",") if p.strip() and p.strip().lower() in
                   low.replace((brand or "\0").lower(), "")), None)
    stance = "negative" if negative else "positive"
    out = [{"name": brand, "stance": stance, "aspect": "price" if "price" in low or "prijs" in low else "quality",
            "relation": ("part_of_parent" if parent else None)}] if brand else []
    return out + ([{"name": parent, "stance": "neutral", "aspect": None, "relation": None}] if parent else [])


def _fake_answer(user: str) -> dict:
    """LLM_FAKE: deterministic fields from the text itself. No network."""
    items = []
    for item_id, body in re.findall(r'<untrusted_user_content id="([^"]+)">\n(.*?)\n</untrusted_user_content>',
                                    user, flags=re.S):
        words = set(re.findall(r"\w+", body.lower()))
        negative = bool(_NEGATIVE & words)
        first = re.match(r"\S+(?:\s+\S+){0,3}", body.strip())
        items.append({
            "id": item_id,
            "needs": [], "pains": ["fake pain"] if negative else [], "objections": [],
            "questions": [body.strip()] if body.strip().endswith("?") else [],
            "unanswered_question": None, "brand_mentions": _fake_brands(user, body, negative),
            "verbatim_phrases": [first.group(0)] if first else [],
            "stance": "negative" if negative else "neutral",
            "emotion": ["frustration"] if negative else [],
            "humour_or_irony": False, "code_switching": False, "time_occasion_cues": [],
            "text_en": f"[en] {body.strip()}",
        })
    return {"items": items}


async def extract_documents(docs: list[Doc], ctx: BriefContext, save: Saver | None = None) -> ExtractOutcome:
    """Extract every doc in worker batches; docs the model skips or leaves untranslated get one more pass."""
    cfg = _cfg()
    system = load_prompt("extract")
    by_id = {d.id: d for d in docs}
    outcome = ExtractOutcome()
    done: set[str] = set()

    last_pass = False

    async def run(batch: list[list[Doc]]) -> None:
        chunk = batch[0]
        user = brief_block(ctx) + "\n\nItems:\n\n" + "\n\n".join(_item(d) for d in chunk)
        try:
            res = await structured("worker", system, user, ExtractionBatch, "record_extractions",
                                   description="Record the extraction for every item.",
                                   max_tokens=cfg["max_tokens"], fake=_fake_answer)
        except LLMError as exc:  # one bad batch must not sink the run: its docs get the retry pass
            log.warning("extraction batch of %d docs failed: %s", len(chunk), exc)
            return
        outcome.calls += 1
        outcome.usd += res.usd
        wanted = {d.id for d in chunk}
        results: dict[str, tuple[dict, str | None]] = {}
        for item in res.data.items:
            if item.id not in wanted or item.id in results or item.id in done:  # invented or repeated ids
                continue
            extraction, text_en, dropped = clean_item(item, by_id[item.id], cfg["phrases_max"])
            if text_en is None and needs_translation(by_id[item.id]):
                if not last_pass:
                    continue  # no translation: this doc goes into the retry pass
                outcome.untranslated += 1
            results[item.id] = (extraction, text_en)
            outcome.phrases_kept += len(extraction["verbatim_phrases"])
            outcome.phrases_dropped += dropped
        if save is not None and results:
            await asyncio.to_thread(save, results)
        done.update(results)
        outcome.extracted += len(results)

    pending = list(docs)
    for pass_no in range(2):  # first pass + one pass for skipped or untranslated docs
        if not pending:
            break
        last_pass = pass_no == 1
        # batched() over ready-made chunks (size 1) keeps the shared parallel limit
        await batched(chunks(pending, cfg["batch_docs_max"], cfg["batch_chars_max"]), run,
                      size=1, parallel=cfg["parallel_max"])
        pending = [d for d in pending if d.id not in done]
    outcome.missing = [d.id for d in pending]
    return outcome


def pending(run_id: str, *, redo: bool = False, limit: int | None = None) -> list:
    """Relevant docs of a run with no extraction (or no translation) yet - all of them with redo - by id."""
    from ctxpack import db

    docs = [d for d in db.get_documents(run_id, relevant_only=True)
            if redo or d.extraction is None or (needs_translation(d) and not d.text_en)]
    docs.sort(key=lambda d: d.id)
    return docs[:limit] if limit else docs


async def extract_run(run_id: str, ctx: BriefContext, *, redo: bool = False,
                      limit: int | None = None) -> ExtractOutcome:
    """The extracting stage: extracts pending() docs, saved batch by batch."""
    from ctxpack import db

    docs = pending(run_id, redo=redo, limit=limit)
    outcome = await extract_documents(docs, ctx, save=db.save_extractions)
    log.info("run %s extraction: %d docs, %d missing, %d untranslated, phrases kept %d dropped %d, %d calls, $%.4f",
             run_id, outcome.extracted, len(outcome.missing), outcome.untranslated, outcome.phrases_kept, outcome.phrases_dropped,
             outcome.calls, outcome.usd)
    return outcome


def estimate_usd(docs: list[Doc]) -> float:
    """Generous upper estimate for extracting docs (the CLI shows it before a paid run)."""
    from ctxpack.config import model_for
    from ctxpack.llm.client import cost_usd

    cfg = _cfg()
    chars = sum(len(d.text) for d in docs)
    batches = len(chunks(docs, cfg["batch_docs_max"], cfg["batch_chars_max"])) or 0
    # ~3 chars per token (Dutch/German run longer than English); system prompt + brief ~1,500 tokens a call;
    # answer = translation (~same length) + ~250 tokens of fields per doc. Doubled for retries and the retry pass.
    input_tokens = chars / 3 + batches * 1500
    output_tokens = chars / 3 + len(docs) * 250
    return 2 * cost_usd(model_for("worker"), int(input_tokens), int(output_tokens))
