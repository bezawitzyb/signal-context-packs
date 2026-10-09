"""Anthropic client wrapper: roles, forced structured output, caching, budgets (B7).

- Roles from models.yaml (reasoner, worker, evaluator, synth); prompts
  from llm/prompts/*.md; scraped text only via untrusted().
- structured(): one tool whose input schema comes from a Pydantic model,
  validated, one retry with the validation error.
- call(): a raw tool-use call for the agent loop (the caller runs tools).
- Prompt caching: the system block is always a cache breakpoint; call()
  also caches the growing conversation.
- Cost: every call is logged (tokens, cost, duration). Inside tracking()
  it is also added to the spend table and the run, a "cost" event is
  emitted, and the run budget and daily cap are checked BEFORE each call
  (BudgetExceeded / DailyCapReached).
- Retries with exponential backoff are done by the SDK (models.yaml
  client.max_retries).
- LLM_FAKE=true: no network, no cost; answers come from a `fake` function
  or tests/fixtures/llm/<name>.json.
"""

from __future__ import annotations

import asyncio
import weakref
import copy
import json
import re
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from ctxpack.config import BACKEND_DIR, get_settings, load_yaml, model_for
from ctxpack.guards import BudgetExceeded, DailyCapReached, check_daily_cap

__all__ = ["BudgetExceeded", "DailyCapReached", "LLMError", "CallResult", "RawResult", "Tracker",
           "structured", "call", "tracking", "batched", "untrusted", "load_prompt", "cost_usd"]

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
FAKE_DIR = BACKEND_DIR / "tests" / "fixtures" / "llm"

_OPEN = "<untrusted_user_content"
_CLOSE = "</untrusted_user_content>"
_TAG_LIKE = re.compile(r"<\s*/?\s*untrusted_user_content", re.IGNORECASE)

T = TypeVar("T")
R = TypeVar("R")


class LLMError(RuntimeError):
    """The model did not return a valid structured answer after one retry."""


@dataclass
class CallResult:
    data: BaseModel
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0
    blocks: list[Any] = field(default_factory=list)  # every content block (server-tool results)


@dataclass
class RawResult:
    message: Any                                      # anthropic.types.Message
    usd: float = 0.0


def _models() -> dict[str, Any]:
    return load_yaml("models")


def load_prompt(name: str) -> str:
    """Prompt text from llm/prompts/<name>.md."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def untrusted(item_id: str, text: str) -> str:
    """Wrap scraped text so the model treats it as data (DH9).

    Tag look-alikes inside the text are neutralised, so a post cannot
    close the wrapper early and smuggle instructions outside it.
    """
    safe = _TAG_LIKE.sub(lambda m: m.group(0) + "_", text)  # any case or spacing (audit): never closes the wrapper
    safe_id = "".join(ch for ch in item_id if ch.isalnum() or ch in "-_")
    return f'<untrusted_user_content id="{safe_id}">\n{safe}\n{_CLOSE}'


# --------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------


def cost_usd(model: str, input_tokens: int, output_tokens: int,
             cache_write_tokens: int = 0, cache_read_tokens: int = 0, web_searches: int = 0) -> float:
    """USD for one response. input_tokens excludes cached tokens (as the API reports it)."""
    p = _models()["prices_usd_per_mtok"][model]
    tokens = (input_tokens * p["input"] + output_tokens * p["output"]
              + cache_write_tokens * p["cache_write_5m"] + cache_read_tokens * p["cache_read"])
    search = web_searches * _models()["server_tools"]["web_search"]["usd_per_1000_uses"] / 1000
    return tokens / 1_000_000 + search


@dataclass
class Tracker:
    """Spend of one run (or of a CLI session when run_id is None)."""

    run_id: str | None = None
    llm_limit_usd: float | None = None
    analysis: bool = False                 # after collection: own budget (modes.yaml analysis_llm_usd)
    spent_usd: float = 0.0                 # starts from the run's saved cost (events, breakdown)
    budget_spent_usd: float = 0.0          # what counts against llm_limit_usd; also starts from the saved cost
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # "role/name" -> {calls, usd, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, web_searches}
    by_call: dict[str, dict[str, float]] = field(default_factory=dict)
    _last_event_usd: float = 0.0
    reserved_usd: float = 0.0              # calls in flight (audit: parallel calls see each other)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def check(self, reserve_usd: float = 0.0) -> None:
        """Refuse a call when the budget is spent, or when its reservation (with the calls already in flight)
        would not fit what is left. A call that fits alone is never refused just for being the first."""
        if self.llm_limit_usd is None:
            return
        part = "analysis" if self.analysis else "collection"
        if self.budget_spent_usd >= self.llm_limit_usd:
            raise BudgetExceeded(f"run {part} LLM budget of ${self.llm_limit_usd:.2f} spent")
        if self.budget_spent_usd + self.reserved_usd + reserve_usd > self.llm_limit_usd:
            raise BudgetExceeded(f"run {part} LLM budget of ${self.llm_limit_usd:.2f} would be exceeded by "
                                 f"this call (${reserve_usd:.2f} reserved)")


_tracker: ContextVar[Tracker | None] = ContextVar("llm_tracker", default=None)


@contextmanager
def tracking(run_id: str | None = None, llm_limit_usd: float | None = None,
             analysis: bool = False) -> Iterator[Tracker]:
    """Record every paid call inside this block to the database and enforce the limits.

    Collection and analysis have separate budgets: with analysis=True, only the
    run's analysis spend (runs.cost_analysis_llm_usd) counts against llm_limit_usd.

    Needs the database (spend table, runs, events). Calls outside any
    tracking() block are only logged (tests, one-off tools).
    """
    spent, budget_spent, by_call = 0.0, 0.0, {}
    if run_id:
        from ctxpack import db

        run = db.get_run(run_id)
        spent = run.cost_llm_usd if run else 0.0
        budget_spent = ((run.cost_analysis_llm_usd or 0.0) if analysis else spent) if run else 0.0
        by_call = copy.deepcopy(((run.cost_breakdown or {}) if run else {}).get("anthropic", {}))  # a resume adds on
    tracker = Tracker(run_id=run_id, llm_limit_usd=llm_limit_usd, analysis=analysis, spent_usd=spent,
                      budget_spent_usd=budget_spent, by_call=by_call, _last_event_usd=spent)
    token = _tracker.set(tracker)
    try:
        yield tracker
    finally:
        _tracker.reset(token)
        if run_id and tracker.spent_usd > tracker._last_event_usd:
            _emit_cost(tracker)  # the last few cents since the previous event
        if run_id and tracker.by_call:
            from ctxpack import db

            db.set_cost_breakdown(run_id, "anthropic", tracker.by_call)


def reservation_usd(model: str, kwargs: dict[str, Any]) -> float:
    """A call's likely cost before it is made: its input (from its size) plus a share of its maximum answer."""
    cfg = _models()["client"]
    size = len(json.dumps({k: kwargs.get(k) for k in ("system", "messages", "tools")}, default=str))
    return cost_usd(model, int(size / cfg["chars_per_token"]),
                    int(kwargs.get("max_tokens", 4096) * cfg["reserve_output_share"]))


async def _before_paid_call(reserve_usd: float = 0.0) -> None:
    tracker = _tracker.get()
    if tracker is None:
        return
    async with tracker._lock:  # check and reserve together: parallel calls cannot all pass the same check
        tracker.check(reserve_usd)
        tracker.reserved_usd += reserve_usd
    try:
        await asyncio.to_thread(check_daily_cap)
    except BaseException:
        async with tracker._lock:
            tracker.reserved_usd -= reserve_usd
        raise


async def _after_paid_call(role: str, name: str, model: str, usage: Any, seconds: float) -> float:
    inp = usage.input_tokens or 0
    out = usage.output_tokens or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    usd = cost_usd(model, inp, out, cw, cr, searches)
    log.info("llm %s/%s model=%s in=%d out=%d cache_write=%d cache_read=%d searches=%d usd=%.5f secs=%.1f",
             role, name, model, inp, out, cw, cr, searches, usd, seconds)

    tracker = _tracker.get()
    if tracker is None:
        return usd
    async with tracker._lock:  # one writer at a time: spend rows are read-modify-write
        tracker.calls += 1
        tracker.input_tokens += inp
        tracker.output_tokens += out
        tracker.cache_write_tokens += cw
        tracker.cache_read_tokens += cr
        tracker.spent_usd += usd
        tracker.budget_spent_usd += usd
        row = tracker.by_call.setdefault(f"{role}/{name}", {})
        for key, value in (("calls", 1), ("usd", usd), ("input_tokens", inp), ("output_tokens", out),
                           ("cache_read_tokens", cr), ("cache_write_tokens", cw), ("web_searches", searches)):
            row[key] = row.get(key, 0) + value
        await asyncio.to_thread(_record_spend, tracker, usd)
    return usd


def _record_spend(tracker: Tracker, usd: float) -> None:
    from ctxpack import db

    db.add_spend(llm_usd=usd, run_id=tracker.run_id, analysis=tracker.analysis)
    if tracker.run_id and tracker.spent_usd - tracker._last_event_usd >= _models()["client"]["cost_event_step_usd"]:
        _emit_cost(tracker)


def _emit_cost(tracker: Tracker) -> None:
    """'cost' event with the run's totals (B6)."""
    from ctxpack import db
    from ctxpack.schemas.enums import EventType

    run = db.get_run(tracker.run_id)
    if run is not None:
        db.append_event(tracker.run_id, EventType.cost, {
            "apify_usd": round(run.cost_apify_usd, 4), "llm_usd": round(run.cost_llm_usd, 4)})
    tracker._last_event_usd = tracker.spent_usd


# --------------------------------------------------------------------------
# The Anthropic client
# --------------------------------------------------------------------------


_CLIENTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = weakref.WeakKeyDictionary()


def _client():
    """One client per event loop: its connection pool belongs to the loop that made it (each research run has
    its own loop in a worker thread, the web app another)."""
    import anthropic

    loop = asyncio.get_running_loop()
    client = _CLIENTS.get(loop)
    if client is None:
        key = get_settings().anthropic_api_key
        cfg = _models()["client"]
        client = _CLIENTS[loop] = anthropic.AsyncAnthropic(api_key=key.get_secret_value() if key else None,
                                                           max_retries=cfg["max_retries"],
                                                           timeout=cfg["timeout_secs"])
    return client


def server_tool(name: str, model: str, **options: Any) -> dict[str, Any]:
    """web_search / web_fetch definition with the type this model supports (models.yaml)."""
    spec = _models()["server_tools"][name]
    return {"type": spec["type_by_model"][model], "name": spec["name"], **options}


def _cached_system(system: str) -> list[dict[str, Any]]:
    """System prompt as one cache breakpoint (prompts shorter than the model minimum are simply not cached)."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


async def _create(role: str, name: str, **kwargs: Any) -> tuple[Any, float]:
    """One paid request: limits first (with a reservation), then the call, then cost accounting."""
    reserve = reservation_usd(kwargs["model"], kwargs)
    await _before_paid_call(reserve)
    try:
        started = time.monotonic()
        resp = await _client().messages.create(**kwargs)
        usd = await _after_paid_call(role, name, kwargs["model"], resp.usage, time.monotonic() - started)
    finally:
        if (tracker := _tracker.get()) is not None:
            async with tracker._lock:
                tracker.reserved_usd -= reserve
    return resp, usd


def _tool(name: str, schema: type[BaseModel], description: str) -> dict[str, Any]:
    return {"name": name, "description": description, "input_schema": schema.model_json_schema()}


# --------------------------------------------------------------------------
# Structured output
# --------------------------------------------------------------------------


def _validate(schema: type[BaseModel], data: Any) -> BaseModel:
    """Validate a tool input. Large nested objects sometimes arrive as JSON strings
    (e.g. "plan": "{...}"); only if validation fails, those are parsed and tried once more."""
    try:
        return schema.model_validate(data)
    except ValidationError:
        if not isinstance(data, dict):
            raise
        fixed = dict(data)
        for key, value in data.items():
            if isinstance(value, str) and value.lstrip()[:1] in ("{", "["):
                try:
                    fixed[key] = json.loads(value)
                except ValueError:
                    pass
        if fixed == data:
            raise
        return schema.model_validate(fixed)


async def structured(
    role: str,
    system: str,
    user: str,
    schema: type[BaseModel],
    tool_name: str,
    *,
    description: str = "Return the answer.",
    max_tokens: int = 4096,
    fake: Callable[[str], dict[str, Any]] | None = None,
    server_tools: list[str] | None = None,
    server_tool_options: dict[str, dict[str, Any]] | None = None,
    no_tool_answer: Callable[[list[Any]], dict[str, Any] | None] | None = None,
) -> CallResult:
    """One call that must answer through the `tool_name` tool, validated against `schema`.

    LLM_FAKE=true: no network. `fake(user)` builds the answer, otherwise
    tests/fixtures/llm/<tool_name>.json is replayed.
    no_tool_answer(blocks): when the model answers without the tool, this may return the answer
    to use instead of a paid retry (e.g. the page could not be fetched, so there is nothing to read).
    """
    if get_settings().llm_fake:
        raw = fake(user) if fake else json.loads((FAKE_DIR / f"{tool_name}.json").read_text(encoding="utf-8"))
        return CallResult(data=schema.model_validate(raw))

    model = model_for(role)
    # A forced custom tool would stop the model from using web search/fetch first.
    forced = not server_tools and model in _models().get("forced_tool_choice_ok", [])
    tools = [server_tool(n, model, **(server_tool_options or {}).get(n, {})) for n in server_tools or []]
    tools.append(_tool(tool_name, schema, description))
    tool_choice = {"type": "tool", "name": tool_name} if forced else {"type": "auto"}
    if not forced:
        system += f"\n\nAnswer only by calling the {tool_name} tool exactly once."

    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    result = CallResult(data=None)  # type: ignore[arg-type]
    attempts, pauses = 0, 0
    while attempts < 2:  # first try + one retry with the validation error (B7)
        resp, usd = await _create(role, tool_name, model=model, max_tokens=max_tokens,
                                  system=_cached_system(system), messages=messages,
                                  tools=tools, tool_choice=tool_choice)
        result.input_tokens += resp.usage.input_tokens
        result.output_tokens += resp.usage.output_tokens
        result.usd += usd
        result.web_searches += getattr(getattr(resp.usage, "server_tool_use", None), "web_search_requests", 0) or 0
        result.blocks.extend(resp.content)
        if resp.stop_reason == "pause_turn" and pauses < 3:
            # Long server-tool turn: re-send it as is and the API resumes (no extra user message).
            pauses += 1
            messages.append({"role": "assistant", "content": resp.content})
            continue
        attempts += 1
        if resp.stop_reason == "max_tokens":  # cut off: the retry gets twice the room, or it fails the same way
            max_tokens = min(max_tokens * 2, _models()["client"]["max_tokens_cap"])

        block = next((b for b in resp.content if b.type == "tool_use" and b.name == tool_name), None)
        if block is None and no_tool_answer is not None and (answer := no_tool_answer(result.blocks)) is not None:
            result.data = schema.model_validate(answer)
            return result
        if block is None:
            error = f"No {tool_name} tool call in the answer (stop_reason={resp.stop_reason})."
            log.warning("llm %s/%s: %s", role, tool_name, error)
            messages += [{"role": "assistant", "content": resp.content},
                         {"role": "user", "content": f"{error} Call the {tool_name} tool now."}]
            continue
        try:
            result.data = _validate(schema, block.input)
            return result
        except ValidationError as exc:
            log.warning("llm %s/%s invalid answer (attempt %d): %s", role, tool_name, attempts,
                        "; ".join(e["msg"] for e in exc.errors(include_input=False))[:2000])
            messages += [
                {"role": "assistant", "content": resp.content},
                {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                    "content": f"Invalid input, fix and call {tool_name} again: {exc.errors(include_input=False)}",
                }]},
            ]
    raise LLMError(f"{tool_name}: no valid answer after one retry")


# --------------------------------------------------------------------------
# Raw tool-use call (agent loop)
# --------------------------------------------------------------------------


async def call(
    role: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    name: str = "agent",
    max_tokens: int = 8192,
    tool_choice: dict[str, Any] | None = None,
    fake: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
) -> RawResult:
    """One model turn with the caller's tool definitions. The caller runs the tools.

    Caching: system prompt + tool definitions, and the conversation so far
    (top-level automatic breakpoint), so each loop turn re-reads the
    history from the cache.
    LLM_FAKE=true: `fake(messages)` or tests/fixtures/llm/<name>.json gives
    {"content": [...], "stop_reason": "..."}.
    """
    if get_settings().llm_fake:
        raw = fake(messages) if fake else json.loads((FAKE_DIR / f"{name}.json").read_text(encoding="utf-8"))
        return RawResult(message=_fake_message(role, raw))

    kwargs: dict[str, Any] = dict(model=model_for(role), max_tokens=max_tokens, system=_cached_system(system),
                                  messages=messages, tools=tools, cache_control={"type": "ephemeral"})
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    resp, usd = await _create(role, name, **kwargs)
    return RawResult(message=resp, usd=usd)


def _fake_message(role: str, raw: dict[str, Any]) -> Any:
    from anthropic.types import Message

    content = [{**b, "id": b.get("id") or f"toolu_fake_{i}"} if b.get("type") == "tool_use" else b
               for i, b in enumerate(raw["content"])]
    return Message.model_validate({
        "id": "msg_fake", "type": "message", "role": "assistant", "model": model_for(role),
        "content": content, "stop_reason": raw.get("stop_reason", "end_turn"), "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    })


# --------------------------------------------------------------------------
# Bounded-parallel batches
# --------------------------------------------------------------------------


async def batched(items: Sequence[T], fn: Callable[[list[T]], Awaitable[R]], *,
                  size: int, parallel: int) -> list[R]:
    """Split `items` into batches of `size`, run `fn` on at most `parallel` at once; results in order."""
    gate = asyncio.Semaphore(parallel)
    chunks = [list(items[i:i + size]) for i in range(0, len(items), size)]

    async def run(chunk: list[T]) -> R:
        async with gate:
            return await fn(chunk)

    return list(await asyncio.gather(*(run(c) for c in chunks)))
