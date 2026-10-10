"""English under a Summary quote (2026-10-10): a translation of the QUOTED words, not of the whole post.

The post's own translation (evidence text_en) starts wherever the post starts, so under a quote taken from
later in the post it read as an unrelated sentence. One worker call per pack translates only the summary
findings' non-English quotes (at most 3); the answers are saved in the run's draft so a retry never pays again.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ctxpack.llm.client import load_prompt, structured, untrusted


class QuoteTranslation(BaseModel):
    id: str
    text_en: str = Field(min_length=1, description="Faithful English translation of exactly this quote.")


class QuoteTranslations(BaseModel):
    items: list[QuoteTranslation]


def wanted(findings: list[dict], evidence: dict[str, dict]) -> list[str]:
    """The findings' quotes that are not in English, each once."""
    return list(dict.fromkeys(
        q["text"] for f in findings if (q := f.get("quote") or {}).get("text")
        and (evidence.get(q.get("evidence_id")) or {}).get("language") not in (None, "en")))


async def translate(quotes: list[str]) -> tuple[dict[str, str], float]:
    """{quote: English} for the given quotes, and the cost. Missing answers are simply left out."""
    if not quotes:
        return {}, 0.0
    ids = {f"q{i}": q for i, q in enumerate(quotes, 1)}
    user = "Quotes:\n\n" + "\n\n".join(untrusted(i, q) for i, q in ids.items())
    res = await structured("worker", load_prompt("quote_en"), user, QuoteTranslations, "record_quote_en",
                           description="Record an English translation for every quote.", max_tokens=1024,
                           fake=lambda _: {"items": [{"id": i, "text_en": f"(English) {q}"} for i, q in ids.items()]})
    got = {ids[t.id]: t.text_en.strip() for t in res.data.items if t.id in ids and t.text_en.strip()}
    return got, res.usd


def apply(findings: list[dict], evidence: dict[str, dict], english: dict[str, str]) -> None:
    """Set quote_en on each non-English finding: the quote's own translation, else none (never the whole post's,
    unless the quote IS the whole post)."""
    for f in findings:
        q = f.get("quote") or {}
        ev = evidence.get(q.get("evidence_id")) or {}
        if not q.get("text") or ev.get("language") in (None, "en"):
            f["quote_en"] = None
        elif q["text"] in english:
            f["quote_en"] = english[q["text"]]
        else:
            f["quote_en"] = ev.get("text_en") if q["text"].strip() == (ev.get("text") or "").strip() else None
