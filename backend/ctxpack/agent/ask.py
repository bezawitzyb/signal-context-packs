"""Ask this pack (change V10, PRD 6.1g): a read-only tool loop over ONE pack.

The model reads the pack with three tools (the same service functions as REST and MCP, bound to
this pack) and answers with [ID] citations. Code then keeps only ids that exist in the pack and
turns them into numbered citations that open the source post. Limits come from modes.yaml ask:
reads per answer and USD per answer (no new turn starts once it is spent); every call counts
against DAILY_SPEND_CAP_USD. Posts reach the model only inside <untrusted_user_content> tags.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ctxpack.config import load_yaml
from ctxpack.guards import BudgetExceeded, DailyCapReached
from ctxpack.llm.client import call, load_prompt, tracking, untrusted

CITE = re.compile(r"\[((?:EV-\d{4,})|(?:[A-Z]{2,4}-\d{2,}))\]")
NO_EVIDENCE = "This pack has no evidence on that."
OUT_OF_READS = ("I ran out of reads for this answer before I could finish. Try a narrower question, e.g. about one "
                "finding or one word.")
DAILY_CAP_MESSAGE = "Today's allowance for questions is used up. The pack stays available; ask again tomorrow."


def cfg() -> dict:
    return load_yaml("modes")["ask"]


def tool_defs() -> list[dict[str, Any]]:
    return [
        {"name": "get_pack_view", "description": "Read this pack. view=digest gives the summary (five truths, do "
         "first, tensions, their words, guardrails); view=full with fields gives chosen top-level sections, e.g. "
         "[\"pain_points\", \"post_briefs\"].",
         "input_schema": {"type": "object", "properties": {
             "view": {"type": "string", "enum": ["digest", "full"]},
             "fields": {"type": "array", "items": {"type": "string"}}}, "required": ["view"]}},
        {"name": "get_insight", "description": "One item by id (e.g. PAIN-01, TEN-02, PST-01) with its confidence, "
         "counts and the posts behind it.",
         "input_schema": {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]}},
        {"name": "search_evidence", "description": "Posts in this pack that contain a word or phrase (original "
         "language or English translation).",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    ]


def _wrap_posts(value: Any) -> Any:
    """Every post's text goes inside untrusted tags before the model sees it (DH9)."""
    if isinstance(value, dict):
        if isinstance(value.get("id"), str) and value["id"].startswith("EV-") and "text" in value:
            keep = {k: v for k, v in value.items() if k in ("id", "platform", "language", "posted_at", "url",
                                                             "engagement_percentile", "role")}
            return {**keep, "text": untrusted(value["id"], value["text"]),
                    **({"text_en": untrusted(value["id"], value["text_en"])} if value.get("text_en") else {})}
        return {k: _wrap_posts(v) for k, v in value.items() if k not in ("events", "coverage")}
    if isinstance(value, list):
        return [_wrap_posts(v) for v in value]
    return value


def run_tool(pack_id: str, name: str, args: dict[str, Any]) -> Any:
    """The three read tools, bound to this pack only (no other pack, nothing written)."""
    from ctxpack.api import service

    n = cfg()["evidence_per_read"]
    try:
        if name == "get_pack_view":
            fields = [f for f in args.get("fields") or [] if isinstance(f, str)] or None
            out = service.pack_view(pack_id, "full" if args.get("view") == "full" else "digest", fields)
        elif name == "get_insight":
            out = service.insight(pack_id, str(args.get("item_id", "")), n)
        elif name == "search_evidence":
            out = service.search_evidence(pack_id, str(args.get("query", "")), limit=n)
        else:
            return {"error": f"unknown tool {name}"}
    except service.NotFound as exc:
        return {"error": str(exc)}
    return _wrap_posts(out)


# --------------------------------------------------------------------------
# Citations: only ids that exist in the pack; numbered links to the posts
# --------------------------------------------------------------------------


def citations(answer: str, pack: dict) -> tuple[str, list[dict], list[str]]:
    """(answer with [1], [2] markers, citations, stripped ids). An id that is not in the pack is removed."""
    from ctxpack.api.service import all_items

    evidence = {e["id"]: e for e in pack.get("evidence", [])}
    items = all_items(pack)
    order: dict[str, int] = {}
    stripped: list[str] = []
    cites: list[dict] = []

    def source(item_id: str) -> dict | None:
        if item_id in evidence:
            e = evidence[item_id]
            return {"kind": "post", "url": e.get("url"), "platform": e["platform"], "date": e.get("posted_at"),
                    "label": f"{e['platform']}, {e.get('posted_at') or 'undated'}"}
        it = items.get(item_id)
        if it is None:
            return None
        refs = list(it.get("evidence_ids") or []) + [q["evidence_id"] for q in it.get("quotes", [])]
        first = next((evidence[r] for r in refs if r in evidence), None)
        text = it.get("claim") or it.get("text") or it.get("headline") or it.get("angle") or it.get("action") or ""
        return {"kind": "finding", "url": (first or {}).get("url") or it.get("source_url"),
                "label": text[:90]}

    def repl(m: re.Match) -> str:
        item_id = m.group(1)
        if item_id not in order:
            src = source(item_id)
            if src is None:
                stripped.append(item_id)
                return ""
            order[item_id] = len(order) + 1
            cites.append({"n": order[item_id], "id": item_id, **src})
        return f"[{order[item_id]}]"

    text = CITE.sub(repl, answer)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip()
    return text, cites, stripped


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


@dataclass
class Answer:
    answer: str
    citations: list[dict] = field(default_factory=list)
    stripped: list[str] = field(default_factory=list)
    reads: int = 0
    usd: float = 0.0
    stopped_early: bool = False


def _fake(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """LLM_FAKE: one search with the question's longest word, then an answer citing the first post found
    (and one invented id, which code must strip) - or "no evidence" when the search found nothing."""
    results = [b for m in messages if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    if not results:
        question = messages[-1]["content"] if isinstance(messages[-1]["content"], str) else ""
        word = max(re.findall(r"\w+", question) or ["pack"], key=len)
        return {"content": [{"type": "tool_use", "name": "search_evidence", "input": {"query": word}}],
                "stop_reason": "tool_use"}
    found = json.loads(results[-1]["content"])
    ids = [e["id"] for e in found.get("evidence", [])]
    if not ids:
        return {"content": [{"type": "text", "text": f"{NO_EVIDENCE} It covers what the summary lists."}],
                "stop_reason": "end_turn"}
    return {"content": [{"type": "text", "text": f"People describe it in their own words [{ids[0]}]. "
                                                 f"One more source [TEN-99]."}], "stop_reason": "end_turn"}


async def ask(pack_id: str, question: str, history: list[dict] = ()) -> Answer:
    """Answer one question about one pack. Never raises for limits: it says so in the answer."""
    from ctxpack.api import service

    c = cfg()
    pack = service.pack(pack_id)
    i = pack["brief"]["interpreted"]
    head = (f"Pack {pack_id}: {i['topic']} - {i['audience']} ({i['market']}). "
            f"{pack['coverage']['counts']['relevant']} relevant posts.")
    messages: list[dict[str, Any]] = []
    for turn in list(history)[-c["history_max"]:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        if str(turn.get("text", "")).strip():
            messages.append({"role": role, "content": str(turn["text"])[:2000]})
    while messages and messages[0]["role"] != "user":      # the API wants a user turn first
        messages.pop(0)
    if messages and messages[-1]["role"] == "user":         # two user turns in a row are not allowed
        messages.pop()
    messages.append({"role": "user", "content": question.strip()[:c["question_max_chars"]]})
    out = Answer(answer="")
    system = f"{load_prompt('ask')}\n\nThe pack: {head}"
    tools = tool_defs()
    with tracking(None, llm_limit_usd=c["max_usd"]) as tracker:
        while True:
            final = out.reads >= c["max_tool_calls"]
            try:
                res = await call("reasoner", system, messages, tools, name="ask", max_tokens=c["max_tokens"],
                                 tool_choice={"type": "none"} if final else None, fake=_fake)
            except DailyCapReached:
                out.answer, out.stopped_early = DAILY_CAP_MESSAGE, True
                break
            except BudgetExceeded:
                out.stopped_early = True
                break
            msg = res.message
            uses = [b for b in msg.content if b.type == "tool_use"]
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            if not uses or final:
                out.answer = text
                break
            messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in msg.content]})
            results = []
            for b in uses:
                out.reads += 1
                result = run_tool(pack_id, b.name, b.input if isinstance(b.input, dict) else {})
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(result, ensure_ascii=False, default=str)[:30000]})
            if out.reads >= c["max_tool_calls"]:   # say it in words too: the next turn must answer
                results.append({"type": "text", "text": "You have used all your reads for this answer. Answer now "
                                "from what you have read, with citations; say what you could not check."})
            messages.append({"role": "user", "content": results})
        out.usd = round(tracker.spent_usd, 4)
    if not out.answer:   # never "no evidence" when the limit, not the pack, ended the answer
        out.answer = ("I stopped before finishing: this answer reached its cost limit. Try a narrower question."
                      if out.stopped_early else OUT_OF_READS if out.reads >= c["max_tool_calls"] else NO_EVIDENCE)
    out.answer, out.citations, out.stripped = citations(out.answer, pack)
    return out
