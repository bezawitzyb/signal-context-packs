"""Interpret the brief and build the starting plan in one call (F4-1, PRD FR-A2/A3).

ONE reasoner call returns the interpretation and EITHER one clarifying
question (only if allowed: never for agents, never twice) OR the plan.
The cost/time estimate is computed here from modes.yaml, never by the
model. Unit kinds per platform come from catalog.yaml (unit_types).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self

from pydantic import Field, ValidationError, model_validator

from ctxpack.config import load_yaml, mode_limits
from ctxpack.llm.client import load_prompt, structured
from ctxpack.schemas.enums import CollectionPlatform, Mode
from ctxpack.schemas.plan import (
    ClarifyingQuestion,
    Interpretation,
    Plan,
    PlanHypothesis,
    PlanResult,
    ResearchQuestion,
    RunEstimate,
    StartingSourceUnit,
    Strict,
)

TOOL = "record_plan"
_MARKET = re.compile(r"^([A-Z]{2}|global)$")
_LANG = re.compile(r"^[a-z]{2}$")
# Target formats per unit kind. Reddit names are ASCII only (seen live: "r/Wärmepumpe").
_TARGET = {
    "subreddit": (re.compile(r"^r/[A-Za-z0-9_]{2,21}$"), '"r/name" with ASCII letters, digits or _'),
    "hashtag": (re.compile(r"^#[^\s#]+$"), '"#tag" without spaces'),
    "domain": (re.compile(r"^(?!https?:)[a-z0-9.-]+\.[a-z]{2,}$"), "a bare domain like forum.example.com"),
}


def unit_kinds() -> dict[CollectionPlatform, set[str]]:
    """Allowed unit kinds per collection platform, from catalog.yaml (web = all web sources)."""
    kinds: dict[CollectionPlatform, set[str]] = {}
    for src in load_yaml("catalog")["sources"].values():
        name = "web" if src["kind"] == "web" else src["platform"]
        if name in CollectionPlatform.__members__:
            kinds.setdefault(CollectionPlatform(name), set()).update(src["unit_types"])
    return kinds


def _check(interp: Interpretation, plan: Plan | None) -> None:
    """Rules the model must follow; a violation triggers the client's one retry with the error."""
    errors = []
    if not _MARKET.match(interp.market):
        errors.append(f'market must be an ISO alpha-2 code in capitals or "global", got {interp.market!r}')
    errors += [f"language {code!r} is not an ISO 639-1 code" for code in interp.languages if not _LANG.match(code)]
    options = load_yaml("modes")["time_window_days_options"]
    if interp.time_window_days not in options:
        errors.append(f"time_window_days must be one of {options}")
    if plan is not None:
        for label, ids in (("hypothesis", [h.id for h in plan.hypotheses]),
                           ("research question", [q.id for q in plan.research_questions])):
            if len(set(ids)) != len(ids):
                errors.append(f"duplicate {label} ids: {ids}")
        allowed = unit_kinds()
        seen = set()
        for unit in plan.starting_units:
            if unit.kind.value not in allowed.get(unit.platform, set()):
                errors.append(f"{unit.platform.value} cannot search a {unit.kind.value}; "
                              f"allowed: {sorted(allowed.get(unit.platform, set()))}")
            pattern, hint = _TARGET.get(unit.kind.value, (None, ""))
            if pattern and not pattern.match(unit.target):
                errors.append(f"{unit.source_unit}: a {unit.kind.value} target must be {hint}")
            if unit.source_unit.lower() in seen:
                errors.append(f"duplicate starting unit {unit.source_unit}")
            seen.add(unit.source_unit.lower())
            if not unit.queries:
                errors.append(f"{unit.source_unit}: give at least one query")
            errors += [f"{unit.source_unit}: query language {q.language!r} is not one of the brief languages"
                       for q in unit.queries if q.language not in interp.languages]
    if errors:
        raise ValueError("; ".join(errors))


def _build_plan(answer: "PlanOnlyAnswer | PlanAnswer") -> Plan:
    try:
        return Plan(hypotheses=answer.hypotheses, research_questions=answer.research_questions,
                    starting_units=answer.starting_units)
    except ValidationError as exc:
        raise ValueError("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                                   for e in exc.errors(include_input=False))) from None


# The tool input is kept flat (plan lists at the top level): with a nested "plan"
# object Sonnet sometimes sent it as a string or split it (seen live, Step 2.2).

class PlanOnlyAnswer(Strict):
    """What the model returns when no question is allowed (agents, or after the one answer)."""

    interpretation: Interpretation
    hypotheses: list[PlanHypothesis] = Field(description="3-5 testable hypotheses.")
    research_questions: list[ResearchQuestion] = Field(description="5-8 research questions.")
    starting_units: list[StartingSourceUnit] = Field(description="3-6 starting source units.")

    @model_validator(mode="after")
    def _valid(self) -> Self:
        _check(self.interpretation, _build_plan(self))
        return self

    def to_result(self) -> PlanResult:
        return PlanResult(interpretation=self.interpretation, plan=_build_plan(self))


class PlanAnswer(Strict):
    """What the model returns when a clarifying question is allowed: the question OR the plan lists."""

    interpretation: Interpretation
    clarifying_question: ClarifyingQuestion | None = Field(
        default=None, description="Only if market or audience truly cannot be inferred; then leave the lists empty.")
    hypotheses: list[PlanHypothesis] = Field(default_factory=list, description="3-5 testable hypotheses.")
    research_questions: list[ResearchQuestion] = Field(default_factory=list, description="5-8 research questions.")
    starting_units: list[StartingSourceUnit] = Field(default_factory=list, description="3-6 starting source units.")

    @model_validator(mode="after")
    def _valid(self) -> Self:
        has_plan = bool(self.hypotheses or self.research_questions or self.starting_units)
        if (self.clarifying_question is None) != has_plan:
            raise ValueError("give exactly one of: clarifying_question, or the plan "
                             "(hypotheses, research_questions, starting_units)")
        _check(self.interpretation, _build_plan(self) if has_plan else None)
        return self

    def to_result(self) -> PlanResult:
        if self.clarifying_question:
            return PlanResult(interpretation=self.interpretation, clarifying_question=self.clarifying_question)
        return PlanResult(interpretation=self.interpretation, plan=_build_plan(self))


@dataclass
class Interpreted:
    result: PlanResult
    estimate: RunEstimate
    usd: float = 0.0


def estimate(mode: Mode | str) -> RunEstimate:
    """Cost and time for the plan screen, from modes.yaml only."""
    m = Mode(mode)
    lim = mode_limits(m.value)
    low, high = lim["typical_usd"]
    return RunEstimate(mode=m, max_usd=round(lim["apify_usd"] + lim["llm_usd"], 2),
                       typical_usd_low=low, typical_usd_high=high, typical_minutes=lim["typical_minutes"],
                       collection_secs=lim["collection_secs"], max_tool_calls=lim["max_tool_calls"])


def _sources_block() -> str:
    """Kinds of source the tools can search, with general audience notes (no per-brief lists)."""
    lines = []
    for name, src in load_yaml("catalog")["sources"].items():
        if name == "google_trends":
            continue  # context signal for the agent, not a starting unit
        platform = "web" if src["kind"] == "web" else src["platform"]
        lines.append(f"- {platform} ({name}): units {', '.join(src['unit_types'])}. {src['audience'].strip()}")
    return "\n".join(lines)


def _user_message(brief: str, window_days: int, allow_question: bool,
                  clarification: tuple[str, str] | None) -> str:
    options = load_yaml("modes")["time_window_days_options"]
    parts = [f"<brief>\n{brief.strip()}\n</brief>"]
    if clarification:
        question, answer = clarification
        parts.append(f"You already asked: {question}\nThe answer: {answer}\n"
                     "Use this answer; fields it settles are no longer assumed.")
    parts.append(f"Default time_window_days: {window_days} (allowed: {options}).")
    parts.append("A clarifying question IS allowed (only if market or audience truly cannot be inferred)."
                 if allow_question else
                 "A clarifying question is NOT allowed: make your best assumption, list it in assumed, "
                 "and give the plan.")
    parts.append("Sources the tools can search:\n" + _sources_block())
    return "\n\n".join(parts)


async def interpret(brief: str, *, mode: Mode | str = Mode.quick, window_days: int | None = None,
                    allow_question: bool = True,
                    clarification: tuple[str, str] | None = None) -> Interpreted:
    """ONE reasoner call: interpretation + (question | plan), plus the estimate from config.

    allow_question=False for agents (API auto_approve / MCP). After a
    clarification (question, answer) no second question is possible.
    """
    window = window_days or load_yaml("modes")["default_time_window_days"]
    ask = allow_question and clarification is None
    schema = PlanAnswer if ask else PlanOnlyAnswer
    res = await structured("reasoner", load_prompt("interpret_plan"),
                           _user_message(brief, window, ask, clarification), schema, TOOL,
                           description="Record the interpretation and either one clarifying question or the plan.",
                           max_tokens=6000)
    return Interpreted(result=res.data.to_result(), estimate=estimate(mode), usd=res.usd)
