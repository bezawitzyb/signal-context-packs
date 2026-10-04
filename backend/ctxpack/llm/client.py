"""Anthropic client wrapper: roles, forced structured output, caching, budgets (B7).

Step 1.5 adds only what the relevance step needs: one structured call
(a tool whose input schema comes from a Pydantic model, validated, one
retry with the validation error), the untrusted-content wrapper, prompts
from llm/prompts/*.md, token cost from models.yaml, and LLM_FAKE.
Caching, budgets, the daily cap and call logging arrive in Step 2.1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ctxpack.config import BACKEND_DIR, get_settings, load_yaml, model_for

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
FAKE_DIR = BACKEND_DIR / "tests" / "fixtures" / "llm"

_OPEN = "<untrusted_user_content"
_CLOSE = "</untrusted_user_content>"


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


def load_prompt(name: str) -> str:
    """Prompt text from llm/prompts/<name>.md."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def untrusted(item_id: str, text: str) -> str:
    """Wrap scraped text so the model treats it as data (DH9).

    Tag look-alikes inside the text are neutralised, so a post cannot
    close the wrapper early and smuggle instructions outside it.
    """
    safe = text.replace(_CLOSE, "</untrusted_user_content_>").replace(_OPEN, "<untrusted_user_content_")
    safe_id = "".join(ch for ch in item_id if ch.isalnum() or ch in "-_")
    return f'<untrusted_user_content id="{safe_id}">\n{safe}\n{_CLOSE}'


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = load_yaml("models")["prices_usd_per_mtok"][model]
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


@lru_cache
def _client():
    import anthropic

    key = get_settings().anthropic_api_key
    return anthropic.AsyncAnthropic(api_key=key.get_secret_value() if key else None)


def server_tool(name: str, model: str, **options: Any) -> dict[str, Any]:
    """web_search / web_fetch definition with the type this model supports (models.yaml)."""
    spec = load_yaml("models")["server_tools"][name]
    return {"type": spec["type_by_model"][model], "name": spec["name"], **options}


def _search_usd(count: int) -> float:
    return count * load_yaml("models")["server_tools"]["web_search"]["usd_per_1000_uses"] / 1000


def _tool(name: str, schema: type[BaseModel], description: str) -> dict[str, Any]:
    return {"name": name, "description": description, "input_schema": schema.model_json_schema()}


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
) -> CallResult:
    """One call that must answer through the `tool_name` tool, validated against `schema`.

    LLM_FAKE=true: no network. `fake(user)` builds the answer, otherwise
    tests/fixtures/llm/<tool_name>.json is replayed.
    """
    if get_settings().llm_fake:
        raw = fake(user) if fake else json.loads((FAKE_DIR / f"{tool_name}.json").read_text(encoding="utf-8"))
        return CallResult(data=schema.model_validate(raw))

    model = model_for(role)
    # A forced custom tool would stop the model from using web search/fetch first.
    forced = not server_tools and model in load_yaml("models").get("forced_tool_choice_ok", [])
    tools = [server_tool(n, model, **(server_tool_options or {}).get(n, {})) for n in server_tools or []]
    tools.append(_tool(tool_name, schema, description))
    tool_choice = {"type": "tool", "name": tool_name} if forced else {"type": "auto"}
    if not forced:
        system += f"\n\nAnswer only by calling the {tool_name} tool exactly once."

    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    result = CallResult(data=None)  # type: ignore[arg-type]
    attempts, pauses = 0, 0
    while attempts < 2:  # first try + one retry with the validation error (B7)
        resp = await _client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        result.input_tokens += resp.usage.input_tokens
        result.output_tokens += resp.usage.output_tokens
        result.usd += cost_usd(model, resp.usage.input_tokens, resp.usage.output_tokens)
        searches = getattr(getattr(resp.usage, "server_tool_use", None), "web_search_requests", 0) or 0
        result.web_searches += searches
        result.usd += _search_usd(searches)
        result.blocks.extend(resp.content)
        if resp.stop_reason == "pause_turn" and pauses < 3:
            # Long server-tool turn: re-send it as is and the API resumes (no extra user message).
            pauses += 1
            messages.append({"role": "assistant", "content": resp.content})
            continue
        attempts += 1

        block = next((b for b in resp.content if b.type == "tool_use" and b.name == tool_name), None)
        if block is None:
            error = f"No {tool_name} tool call in the answer (stop_reason={resp.stop_reason})."
            messages += [{"role": "assistant", "content": resp.content},
                         {"role": "user", "content": f"{error} Call the {tool_name} tool now."}]
            continue
        try:
            result.data = schema.model_validate(block.input)
            return result
        except ValidationError as exc:
            messages += [
                {"role": "assistant", "content": resp.content},
                {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                    "content": f"Invalid input, fix and call {tool_name} again: {exc.errors(include_input=False)}",
                }]},
            ]
    raise LLMError(f"{tool_name}: no valid answer after one retry")
