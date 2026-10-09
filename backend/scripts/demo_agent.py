"""Demo agent (guide Step 5.2, PRD FR-G3): three TikTok scripts with and without a Context Pack.

With the pack, the agent gets the pack's skill the way an installed skill works: the SKILL.md
body up front, reference files opened on demand (read_reference). Without the pack it gets
only the task. Both versions go through the same automatic checks (code, no model):

  lexicon       >= 3 of the pack's lexicon terms used (terms the pack also lists under
                never_claim do not count)
  not_this      0 guardrails.not_this or never_claim phrases
  safe facts    every fact stated comes from a safe_to_assert item
  ids exist     every cited id exists in the pack
  quotes        no real person's quote copied into a script (FR: no quotes in ads)

Output: examples/demo_agent.md (both versions side by side with the check results), after the
same privacy check as featured packs. The reasoner role writes; the cost is shown first.

Run from backend/: uv run python -m scripts.demo_agent [--pack PACK_ID] [--yes]
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import typer
from pydantic import BaseModel, Field

from ctxpack.config import REPO_DIR, get_settings, model_for
from ctxpack.exports.skill import references, skill_body
from ctxpack.llm.client import call, cost_usd, load_prompt, untrusted

NL_PACK = "pk_7KAp0R-njCpL"   # NL rerun 2026-10-09 (Quick, merge fix); examples/demo_agent.md was made with pk_wrvZBhDFsLR9
TASK = ("Write three TikTok scripts for a new snack brand launching in the Netherlands. "
        "The audience is Dutch snackers aged 18-40.")
OUT = REPO_DIR / "examples" / "demo_agent.md"
MAX_TURNS = 6
MAX_TOKENS = 6000
QUOTE_MIN_WORDS = 6   # a copied run of this many words from a post counts as a reused quote
_ID = re.compile(r"\b[A-Z]{2,4}-\d{2,4}\b")


# --------------------------------------------------------------------------
# The agent's tools
# --------------------------------------------------------------------------


class Fact(BaseModel):
    text: str = Field(description="The statement as it appears in the script.")
    about: Literal["audience", "brand"] = Field(
        description="audience: about the people or the category; brand: what our own brand or product does.")
    item_id: str = Field(description='The pack item it comes from, or "" if none.')


class Script(BaseModel):
    title: str
    hook: str = Field(description="First spoken line, in the audience's language.")
    beats: list[str] = Field(min_length=3, max_length=5)
    on_screen_text: list[str]
    caption: str
    hashtags: list[str]
    cited_ids: list[str] = Field(description="Ids of every item the script builds on; empty if none.")
    facts_stated: list[Fact] = Field(description="Every statement presented as fact, with its item_id.")


class Scripts(BaseModel):
    scripts: list[Script] = Field(min_length=3, max_length=3)


def tools(with_pack: bool, names: list[str]) -> list[dict[str, Any]]:
    out = [{"name": "submit_scripts", "description": "Submit the three finished scripts (once).",
            "input_schema": Scripts.model_json_schema()}]
    if with_pack:
        out.insert(0, {"name": "read_reference", "description": "Open one reference file of the installed skill.",
                       "input_schema": {"type": "object", "properties": {"file": {"type": "string", "enum": names}},
                                        "required": ["file"]}})
    return out


@dataclass
class AgentRun:
    with_pack: bool
    scripts: list[dict] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    turns: int = 0
    usd: float = 0.0
    error: str = ""


async def run_agent(pack: dict | None, fake: Any = None) -> AgentRun:
    """A plain tool-use loop: read_reference on demand, then submit_scripts."""
    refs = references(pack) if pack else {}
    run = AgentRun(with_pack=pack is not None)
    user = f"Task: {TASK}"
    if pack:
        user = ("Installed skill (SKILL.md):\n\n" + skill_body(pack) + f"\n\nReference files: {', '.join(refs)}\n\n"
                + user)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    system = load_prompt("demo_agent")
    for _ in range(MAX_TURNS):
        res = await call("reasoner", system, messages, tools(pack is not None, list(refs)), name="demo_agent",
                         max_tokens=MAX_TOKENS, fake=fake)
        run.turns += 1
        run.usd += res.usd
        msg = res.message
        messages.append({"role": "assistant", "content": msg.content})
        results = []
        for b in msg.content:
            if b.type != "tool_use":
                continue
            if b.name == "submit_scripts":
                try:
                    run.scripts = [s.model_dump() for s in Scripts.model_validate(b.input).scripts]
                    return run
                except ValueError as exc:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                    "content": f"Invalid scripts: {str(exc)[:500]}. Fix and submit again."})
            elif b.name == "read_reference" and b.input.get("file") in refs:
                name = b.input["file"]
                run.opened.append(name)
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": untrusted(f"references/{name}", refs[name])})
            else:
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                "content": "Unknown tool or file."})
        if not results:
            messages.append({"role": "user", "content": "Call submit_scripts with the three scripts."})
        else:
            messages.append({"role": "user", "content": results})
    run.error = f"no scripts after {MAX_TURNS} turns"
    return run


# --------------------------------------------------------------------------
# Automatic checks (code)
# --------------------------------------------------------------------------


def script_text(s: dict) -> str:
    return "\n".join([s["hook"], *s["beats"], *s["on_screen_text"], s["caption"], " ".join(s["hashtags"])])


def _has(text: str, phrase: str) -> bool:
    phrase = phrase.strip().casefold()
    return bool(phrase) and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text.casefold()) is not None


def pack_ids(pack: dict) -> set[str]:
    ids: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("id"), str):
                ids.add(x["id"].upper())
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(pack)
    return ids


def safe_ids(pack: dict) -> set[str]:
    ids: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if x.get("safe_to_assert") is True and isinstance(x.get("id"), str):
                ids.add(x["id"].upper())
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk({k: v for k, v in pack.items() if k != "evidence"})
    return ids


def _grams(t: str) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", t.casefold())
    return {tuple(words[i:i + QUOTE_MIN_WORDS]) for i in range(len(words) - QUOTE_MIN_WORDS + 1)}


def reusable_text(pack: dict) -> str:
    """What the pack itself offers for reuse: recurring phrases, say_this, hooks, do-first actions."""
    return "\n".join([p["text"] for p in pack["voice"]["phrases"]] + list(pack["guardrails"]["say_this"])
                     + [h["text"] for h in pack["playbook"]["hooks"]] + [d["action"] for d in pack["do_first"]])


def copied_quotes(text: str, pack: dict) -> list[str]:
    """Evidence ids whose post shares a run of QUOTE_MIN_WORDS words with the scripts, not counting
    runs the pack itself offers for reuse (a recurring phrase is the audience's language, not one person's quote)."""
    mine = _grams(text) - _grams(reusable_text(pack))
    return sorted(e["id"] for e in pack.get("evidence", []) if mine & _grams(e["text"]))


def check(scripts: list[dict], pack: dict) -> list[dict[str, Any]]:
    """The four Step 5.2 checks plus quote reuse. The pack is the yardstick for both versions."""
    text = "\n".join(script_text(s) for s in scripts)
    g = pack["guardrails"]
    banned = list(g["not_this"]) + list(g["never_claim"])
    lex = [x["term"] for x in pack["voice"]["lexicon"]]
    conflicted = [t for t in lex if any(_has(t, b) for b in g["never_claim"])]  # the whole banned phrase
    used = [t for t in lex if _has(text, t) and t not in conflicted]
    hits = [b for b in banned if _has(text, b)]
    known, safe = pack_ids(pack), safe_ids(pack)
    allfacts = [f for s in scripts for f in s["facts_stated"]]
    facts = [f for f in allfacts if f.get("about", "audience") == "audience"]
    brand = [f for f in allfacts if f.get("about") == "brand"]
    unsafe = [f"{f['item_id'] or 'no id'}: {f['text'][:60]}" for f in facts if f["item_id"].upper() not in safe]
    cited = sorted({i.upper() for s in scripts for i in s["cited_ids"]} | {f["item_id"].upper() for f in allfacts if f["item_id"]}
                   | set(_ID.findall(text)))
    missing = [i for i in cited if i not in known]
    quotes = copied_quotes(text, pack)
    return [
        {"check": ">= 3 lexicon terms", "pass": len(used) >= 3,
         "detail": f"{len(used)}: {', '.join(used) or 'none'}"
                   + (f" (not counted, also under never_claim: {', '.join(conflicted)})" if conflicted else "")},
        {"check": "0 not_this / never_claim phrases", "pass": not hits, "detail": "; ".join(hits) or "none"},
        {"check": "facts only from safe_to_assert items", "pass": not unsafe,
         "detail": f"{len(facts)} audience fact(s)" + (f"; not safe: {'; '.join(unsafe)}" if unsafe else "")
                   + (f"; {len(brand)} brand claim(s) to verify before use: "
                      + "; ".join(f["text"][:60] for f in brand) if brand else "")},
        {"check": "cited ids exist", "pass": bool(cited) and not missing,
         "detail": (f"{len(cited)} cited" + (f"; unknown: {', '.join(missing)}" if missing else "")) if cited
         else "no ids cited"},
        {"check": "no copied quotes", "pass": not quotes, "detail": ", ".join(quotes) or "none"},
    ]


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(pack: dict, without: AgentRun, with_: AgentRun, checks: dict[str, list[dict]]) -> str:
    def mark(ok: bool) -> str:
        return "✓ pass" if ok else "✗ fail"

    L = ["# Demo agent: three TikTok scripts, with and without a Context Pack", "",
         f"Task given to both: *{TASK}*", "",
         f"- Model: `{model_for('reasoner')}` (reasoner role), same system prompt for both versions.",
         f"- With pack: the skill of pack `{pack['pack_id']}` ({pack['brief']['text']}): SKILL.md body up front, "
         f"reference files on demand. Opened: {', '.join(with_.opened) or 'none'}.",
         "- Without pack: only the task.",
         f"- Generated {date.today().isoformat()} by `backend/scripts/demo_agent.py`. Checks are code, not a model; "
         "the pack's lexicon and guardrails are the yardstick for both versions.", "",
         "## Automatic checks", "", "| Check | Without pack | With pack |", "|---|---|---|"]
    for a, b in zip(checks["without"], checks["with"]):
        L.append(f"| {a['check']} | {mark(a['pass'])}: {_cell(a['detail'])} | {mark(b['pass'])}: {_cell(b['detail'])} |")
    for n in range(3):
        a = without.scripts[n] if n < len(without.scripts) else None
        b = with_.scripts[n] if n < len(with_.scripts) else None
        L += ["", f"## Script {n + 1}", "", "| | Without pack | With pack |", "|---|---|---|"]
        rows = [("Title", "title"), ("Hook", "hook")]
        for label, key in rows:
            L.append(f"| {label} | {_cell(a[key]) if a else '-'} | {_cell(b[key]) if b else '-'} |")
        L.append(f"| Beats | {'<br>'.join(f'{i + 1}. {_cell(x)}' for i, x in enumerate(a['beats'])) if a else '-'} | "
                 f"{'<br>'.join(f'{i + 1}. {_cell(x)}' for i, x in enumerate(b['beats'])) if b else '-'} |")
        for label, key, sep in (("On screen", "on_screen_text", " / "), ("Hashtags", "hashtags", " ")):
            L.append(f"| {label} | {_cell(sep.join(a[key])) if a else '-'} | {_cell(sep.join(b[key])) if b else '-'} |")
        L.append(f"| Caption | {_cell(a['caption']) if a else '-'} | {_cell(b['caption']) if b else '-'} |")
        L.append(f"| Cites | {', '.join(a['cited_ids']) or '-' if a else '-'} | {', '.join(b['cited_ids']) or '-' if b else '-'} |")
    L += ["", "Scripts are generated examples, not tested ads. Facts the pack does not mark safe to state need "
          "checking first; see the pack's guardrails and compliance flags.", ""]
    return "\n".join(L)


def load_pack(pack_id: str) -> dict:
    path = REPO_DIR / "featured" / f"{pack_id}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    from ctxpack import db

    db.init_engine()
    pack = db.get_pack(pack_id)
    if pack is None:
        raise typer.BadParameter(f"pack {pack_id} not found")
    return pack


def estimate_usd(pack: dict) -> float:
    """Generous upper bound: the skill and every reference opened, a few turns, two versions."""
    refs = sum(len(v) for k, v in references(pack).items() if k != "evidence.json")
    skill = len(skill_body(pack))
    with_pack = cost_usd(model_for("reasoner"), int((skill + refs) / 3 * 3), 3 * 3000)
    return round(2 * (with_pack + cost_usd(model_for("reasoner"), 2000, 3000)), 2)


def main(pack_id: str = typer.Option(NL_PACK, "--pack", help="Featured or saved pack id"),
         yes: bool = typer.Option(False, "--yes", help="Do not wait for Enter before the paid calls")) -> None:
    from rich.console import Console

    from ctxpack.exports.featured import privacy_problems

    console = Console()
    pack = load_pack(pack_id)
    console.print(f"demo agent on {pack_id} ({pack['brief']['text']}) | model {model_for('reasoner')} | "
                  f"estimated max cost ${estimate_usd(pack):.2f}", highlight=False)
    if not yes and not get_settings().llm_fake:
        typer.prompt("Press Enter to start (Ctrl-C to cancel)", default="", show_default=False)

    async def both() -> tuple[AgentRun, AgentRun]:
        return await asyncio.gather(run_agent(None), run_agent(pack))

    if get_settings().llm_fake:
        without, with_ = asyncio.run(both())
    else:
        from ctxpack import db
        from ctxpack.llm.client import tracking

        db.init_engine()
        with tracking(None):  # counts toward today's spend and the daily cap
            without, with_ = asyncio.run(both())
    for r in (without, with_):
        if r.error:
            console.print(f"[red]✘[/red] {'with' if r.with_pack else 'without'} pack: {r.error}")
            raise typer.Exit(1)
    checks = {"without": check(without.scripts, pack), "with": check(with_.scripts, pack)}
    text = render(pack, without, with_, checks)
    problems = privacy_problems({"demo": text, "evidence": []})
    if problems:
        console.print(f"[red]✘[/red] privacy check failed, nothing written: {'; '.join(problems[:5])}")
        raise typer.Exit(1)
    OUT.write_text(text, encoding="utf-8")
    for label, rows in checks.items():
        console.print(f"\n[bold]{label.upper()} PACK[/bold]")
        for c in rows:
            console.print(f"  {'[green]PASS[/green]' if c['pass'] else '[red]FAIL[/red]'} {c['check']}: {c['detail']}",
                          highlight=False)
    console.print(f"\nopened: {', '.join(with_.opened) or 'none'} | turns {without.turns} + {with_.turns} | "
                  f"cost ${without.usd + with_.usd:.3f} | saved {OUT.relative_to(REPO_DIR)}", highlight=False)


if __name__ == "__main__":
    typer.run(main)
