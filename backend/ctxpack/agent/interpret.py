"""Interpret the brief and build the starting plan in one call (F4-1, PRD FR-A2/A3, FR-A2d).

ONE reasoner call returns the interpretation (with its understanding of
the five inputs only the user knows) and EITHER clarifying questions
(only if allowed: never for agents) OR the plan. Code checks that every
understood input rests on the brief's own words, merges the user's
answers, and makes sure the goal and offer questions are asked when
missing (V11). The cost/time estimate is computed here from modes.yaml,
never by the model. Unit kinds per platform come from catalog.yaml.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Self

from pydantic import Field, ValidationError, model_validator

from ctxpack.config import load_yaml, mode_limits
from ctxpack.llm.client import load_prompt, structured
from ctxpack.schemas.enums import (CollectionPlatform, Goal, InputSource, InputStatus, IntakeFill,
                                   InterpretationField, Mode)
from ctxpack.schemas.plan import (
    ClarifyingQuestion,
    Intake,
    Interpretation,
    UnderstoodInput,
    Understanding,
    goals_text,
    Plan,
    PlanHypothesis,
    PlanResult,
    ResearchQuestion,
    RunEstimate,
    StartingSourceUnit,
    Strict,
)

TOOL = "record_plan"
REQUIRED = (IntakeFill.goal, IntakeFill.offer)  # V11: always asked when missing, never skipped
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


def _check(interp: Interpretation, plan: Plan | None, questions: list[ClarifyingQuestion] = ()) -> None:
    """Rules the model must follow; a violation triggers the client's one retry with the error."""
    errors = []
    clar = load_yaml("modes")["clarifying"]
    most = clar["max_questions"]
    if len(questions) > most:
        errors.append(f"ask at most {most} clarifying questions, not {len(questions)}")
    errors += [f"{q.id}: give {clar['options_min']}-{clar['options_max']} answer chips, not {len(q.options)}"
               for q in questions if q.fills not in REQUIRED + (IntakeFill.brand,)
               and not clar["options_min"] <= len(q.options) <= clar["options_max"]]
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        errors.append(f"duplicate question ids: {ids}")
    regions = set(load_yaml("markets")["regions"])
    for m in interp.markets:
        if not (_MARKET.match(m.code) or m.code in regions):
            errors.append(f'market code must be an ISO alpha-2 country in capitals, a region in {sorted(regions)} '
                          f'or "global", got {m.code!r}')
        errors += [f"country {c!r} is not an ISO alpha-2 code in capitals" for c in m.countries
                   if not re.fullmatch(r"[A-Z]{2}", c)]
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
                    starting_units=answer.starting_units,
                    source_balance_reason=answer.source_balance_reason)
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
    source_balance_reason: str = Field(default="", description="Only if one platform takes more than half of "
                                       "the starting units: why this audience really lives there.")

    @model_validator(mode="after")
    def _valid(self) -> Self:
        _check(self.interpretation, _build_plan(self))
        return self

    def to_result(self) -> PlanResult:
        return PlanResult(interpretation=self.interpretation, plan=_build_plan(self))


class PlanAnswer(Strict):
    """What the model returns when questions are allowed: 1-3 clarifying questions OR the plan lists (V3)."""

    interpretation: Interpretation
    clarifying_questions: list[ClarifyingQuestion] = Field(
        default_factory=list, description="0-3 questions that would most improve THIS research; then leave the "
        "lists empty. None if the brief is specific enough.")
    hypotheses: list[PlanHypothesis] = Field(default_factory=list, description="3-5 testable hypotheses.")
    research_questions: list[ResearchQuestion] = Field(default_factory=list, description="5-8 research questions.")
    starting_units: list[StartingSourceUnit] = Field(default_factory=list, description="3-6 starting source units.")
    source_balance_reason: str = Field(default="", description="Only if one platform takes more than half of "
                                       "the starting units: why this audience really lives there.")

    @model_validator(mode="after")
    def _valid(self) -> Self:
        has_plan = bool(self.hypotheses or self.research_questions or self.starting_units)
        if bool(self.clarifying_questions) == has_plan:
            raise ValueError("give exactly one of: clarifying_questions, or the plan "
                             "(hypotheses, research_questions, starting_units)")
        _check(self.interpretation, _build_plan(self) if has_plan else None, self.clarifying_questions)
        return self

    def to_result(self) -> PlanResult:
        if self.clarifying_questions:
            return PlanResult(interpretation=self.interpretation, clarifying_questions=self.clarifying_questions)
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
    return RunEstimate(mode=m, max_usd=round(lim["apify_usd"] + lim["llm_usd"] + lim["analysis_llm_usd"], 2),
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


def _user_message(brief: str, window_days: int, allow_question: bool, intake: Intake | None,
                  edits: dict | None) -> str:
    cfg = load_yaml("modes")
    options = cfg["time_window_days_options"]
    parts = [f"<brief>\n{brief.strip()}\n</brief>"]
    if intake is not None and not intake.empty():
        known = intake.model_dump(exclude={"questions_asked"}, exclude_defaults=True)
        parts.append("The user already told you (use it; fields it settles are no longer assumed; write research "
                     "questions and hypotheses per audience role when roles are given, and set their role):\n"
                     + json.dumps(known, ensure_ascii=False, indent=1))
    if edits:
        parts.append("The user edited your interpretation; keep these exactly and plan for them:\n"
                     + json.dumps(edits, ensure_ascii=False, indent=1))
    parts.append(f"Default time_window_days: {window_days} (allowed: {options}).")
    goals = load_yaml("goals")
    parts.append("Goal list (ids for understanding.goals): " + "; ".join(
        f"{gid} = {g['description']}" for gid, g in goals["goals"].items())
        + ". Offer stages: " + ", ".join(goals["offer_stages"]) + ".")
    parts.append(f"Clarifying questions ARE allowed: 0 to {cfg['clarifying']['max_questions']}. Ask about the goal "
                 "and the offer whenever the brief does not state them, then only the other gaps that would most "
                 "change this research; none if the brief states everything that matters."
                 if allow_question else
                 "Clarifying questions are NOT allowed: give the plan. Fill the understanding only from the "
                 "brief's own words and what the user told you; for the other interpretation fields make your "
                 "best assumptions and list them in assumed.")
    parts.append("Sources the tools can search:\n" + _sources_block())
    return "\n\n".join(parts)


def _fake_answer(brief: str, ask: bool) -> dict:
    """LLM_FAKE: the recorded plan; a one-word brief (e.g. "snacks") gets one clarifying question instead,
    so the question path can be tried for free. Real runs never use this."""
    import json

    from ctxpack.llm.client import FAKE_DIR

    recorded = json.loads((FAKE_DIR / f"{TOOL}.json").read_text(encoding="utf-8"))
    if not (ask and len(brief.split()) <= 1):
        return recorded
    interp = {**recorded["interpretation"], "topic": brief.strip(),
              "markets": [{"code": "global", "countries": [], "weight": 1.0, "assumed": True}],
              "assumed": ["market", "audience"]}
    return {"interpretation": interp, "hypotheses": [], "research_questions": [], "starting_units": [],
            "clarifying_questions": [
                {"id": "Q1", "question": "Which market should this cover?", "fills": "market",
                 "why_it_helps": "Each country snacks and talks about it in its own places and language.",
                 "options": ["Netherlands", "Germany", "United Kingdom", "Global"], "multi_select": False,
                 "allow_free_text": True},
                {"id": "Q2", "question": "Who should this speak to?", "fills": "audience_roles",
                 "why_it_helps": "Shoppers, parents and retailers talk about snacks in different places.",
                 "options": ["Young adults buying for themselves", "Parents buying for kids",
                             "Retail buyers", "Everyone"], "multi_select": True, "allow_free_text": True}]}


async def interpret(brief: str, *, mode: Mode | str = Mode.quick, window_days: int | None = None,
                    allow_question: bool = True, intake: Intake | None = None,
                    edits: dict | None = None) -> Interpreted:
    """ONE reasoner call: interpretation + (0-3 clarifying questions | plan), plus the estimate from config.

    allow_question=False for agents (API auto_approve / MCP). Questions are asked only while the user has
    told us nothing yet (no intake, no edits). A question the brief already answers is dropped in code; if
    none is left, one plan-only call follows. Edits (markets, languages, audience, competitors) win.
    """
    window = window_days or load_yaml("modes")["default_time_window_days"]
    told_required = (intake is not None and bool(intake.goals) and bool(intake.offer or intake.offer_stage)
                     and (Goal.brand_perception not in intake.goals or bool(intake.brand)))
    ask = allow_question and not edits and (intake is None or intake.empty() or not told_required)
    usd = 0.0
    for attempt in ((True, False) if ask else (False,)):
        schema = PlanAnswer if attempt else PlanOnlyAnswer
        res = await structured("reasoner", load_prompt("interpret_plan"),
                               _user_message(brief, window, attempt, intake, edits), schema, TOOL,
                               description="Record the interpretation and either the clarifying questions or the plan.",
                               max_tokens=6000, fake=lambda user, a=attempt: _fake_answer(brief, a))
        usd += res.usd
        result = res.data.to_result()
        if attempt:
            settle_understanding(result.interpretation, brief, intake, edits)
            asked = ensure_required(drop_answered(result.clarifying_questions, brief,
                                                  result.interpretation.understanding),
                                    result.interpretation.understanding)
            if asked:  # V11: the goal and offer are asked even if the model planned straight away
                result = PlanResult(interpretation=result.interpretation, clarifying_questions=asked)
                break
            if result.plan is None:
                continue  # every question was already answered by the brief: plan straight away
        break
    if window_days:  # a window the user chose wins over the model's reading (V1: inputs are never lost)
        result.interpretation.time_window_days = window_days
    settle_markets(result, brief, str(mode), edits)
    _apply_edits(result, intake, edits)
    settle_understanding(result.interpretation, brief, intake, edits)
    if result.plan is not None:
        balance_sources(result.plan)
    return Interpreted(result=result, estimate=estimate(mode), usd=usd)


def balance_sources(plan: Plan) -> list[str]:
    """V6: no platform above modes.yaml planning.source_share_max of the enabled starting units unless the
    plan says why. Extra units (the last ones of that platform) are switched off, never deleted: the user
    sees them on the plan screen and can switch them back on. Returns the units switched off."""
    if plan.source_balance_reason.strip():
        return []
    share = load_yaml("modes")["planning"]["source_share_max"]
    enabled = [u for u in plan.starting_units if u.enabled]
    cap = max(1, int(share * len(enabled)))
    off: list[str] = []
    for platform in {u.platform for u in enabled}:
        same = [u for u in enabled if u.platform == platform]
        for u in same[cap:]:
            u.enabled = False
            off.append(u.source_unit)
    return off


def drop_answered(questions: list[ClarifyingQuestion], brief: str,
                  understood: Understanding | None = None) -> list[ClarifyingQuestion]:
    """Never ask what the brief already says (V3, V11): a market question when the brief names a place (and
    it is not unclear), a goal, offer or key-question question when the brief states it."""
    from ctxpack.agent.markets import places_in

    u = understood or Understanding()
    places = places_in(brief)
    named = bool(places["regions"] or places["countries"]) and u.markets.status != InputStatus.unclear
    stated = {IntakeFill.goal: bool(u.goals) and u.goal.status == InputStatus.stated,
              IntakeFill.offer: u.offer.status == InputStatus.stated,
              IntakeFill.key_question: u.key_question.status == InputStatus.stated,
              IntakeFill.timeframe: u.key_question.status == InputStatus.stated,
              IntakeFill.brand: u.brand.status == InputStatus.stated}
    kept = [q for q in questions if not ((q.fills == IntakeFill.market and named) or stated.get(q.fills))]
    for n, q in enumerate(kept, 1):
        q.id = f"Q{n}"
    return kept


def missing_required(u: Understanding) -> list[IntakeFill]:
    """The goal and offer when neither the brief (stated, quote checked) nor the user gave them (V11); the brand
    when brand perception is a known goal and no brand is known (V12; the web goal card asks it too)."""
    out = []
    if not u.goals or u.goal.status != InputStatus.stated:
        out.append(IntakeFill.goal)
    if u.offer.status != InputStatus.stated:
        out.append(IntakeFill.offer)
    if Goal.brand_perception in u.goals and u.brand.status != InputStatus.stated:
        out.append(IntakeFill.brand)
    return out


def fixed_question(fill: IntakeFill, model_q: ClarifyingQuestion | None = None) -> ClarifyingQuestion:
    """The goal or offer question, built from config/goals.yaml (chips fixed so code can read the answer)."""
    cfg = load_yaml("goals")
    text = cfg["questions"][fill.value]
    if fill == IntakeFill.goal:
        return ClarifyingQuestion(question=text["question"], why_it_helps=text["why_it_helps"], fills=fill,
                                  options=[g["chip"] for g in cfg["goals"].values()], multi_select=True,
                                  allow_free_text=True, required=True,
                                  placeholder="Optional: the goal in your own words")
    if fill == IntakeFill.brand:
        return ClarifyingQuestion(question=text["question"], why_it_helps=text["why_it_helps"], fills=fill,
                                  options=[], allow_free_text=True, required=True, placeholder=text["placeholder"])
    placeholder = (model_q.placeholder if model_q and model_q.placeholder else "") or text["placeholder"]
    return ClarifyingQuestion(question=text["question"], why_it_helps=text["why_it_helps"], fills=fill,
                              options=[st["chip"] for st in cfg["offer_stages"].values()], multi_select=False,
                              allow_free_text=True, required=True, placeholder=placeholder)


def ensure_required(questions: list[ClarifyingQuestion], u: Understanding) -> list[ClarifyingQuestion]:
    """Goal first, then offer (fixed questions, required), then the model's other questions; at most
    clarifying.max_questions in all (V11). A goal or offer question the model wrote is replaced."""
    rest = list(questions)
    first: list[ClarifyingQuestion] = []
    for fill in missing_required(u):
        own = next((q for q in rest if q.fills == fill), None)
        rest = [q for q in rest if q.fills != fill]
        first.append(fixed_question(fill, own))
    rest = [q for q in rest if q.fills not in REQUIRED + (IntakeFill.brand,)]  # stated: never asked again
    out = (first + rest)[:load_yaml("modes")["clarifying"]["max_questions"]]
    for n, q in enumerate(out, 1):
        q.id = f"Q{n}"
    return out


def _norm(text: str) -> str:
    return " ".join(str(text).casefold().split())


def settle_understanding(interp: Interpretation, brief: str, intake: Intake | None = None,
                         edits: dict | None = None) -> None:
    """V11, in code: an understood input stays only if its quote is in the brief; the user's answers and
    edits win; who and markets may show the model's assumption, goals and offer never. Idempotent."""
    u = interp.understanding
    text = _norm(brief)
    for name in ("goal", "offer", "who", "markets", "key_question", "brand"):
        inp: UnderstoodInput = getattr(u, name)
        quote = _norm(inp.brief_quote)
        if inp.status != InputStatus.missing and quote and quote in text:
            inp.source = InputSource.brief
        else:
            setattr(u, name, UnderstoodInput())
    if u.goal.status == InputStatus.missing:
        u.goals = []
    elif not u.goals:
        u.goal.status = InputStatus.unclear  # words about a goal that is not in the list
    if u.offer.status == InputStatus.missing:
        u.offer_stage = None
    if intake is not None:
        if intake.goals:
            u.goals = list(intake.goals)
            u.goal = UnderstoodInput(value=goals_text(intake.goals, intake.goal_note), status=InputStatus.stated,
                                     source=InputSource.answer)
        if intake.offer or intake.offer_stage:
            u.offer = UnderstoodInput(value=intake.offer or u.offer.value, status=InputStatus.stated,
                                      source=InputSource.answer)
            u.offer_stage = intake.offer_stage or u.offer_stage
        if intake.audience_roles:
            u.who = UnderstoodInput(value="; ".join(intake.audience_roles), status=InputStatus.stated,
                                    source=InputSource.answer)
        if intake.brand:
            words = intake.brand + (f" (parent: {intake.parent_brand})" if intake.parent_brand else "")
            u.brand = UnderstoodInput(value=words, status=InputStatus.stated, source=InputSource.answer)
        if intake.key_question or intake.timeframe:
            words = "; ".join(x for x in (intake.key_question, f"by {intake.timeframe}" if intake.timeframe else "")
                              if x)
            u.key_question = UnderstoodInput(value=words, status=InputStatus.stated, source=InputSource.answer)
    edits = edits or {}
    if edits.get("markets"):
        u.markets = UnderstoodInput(value=interp.market, status=InputStatus.stated, source=InputSource.answer)
    if edits.get("audience") and not (intake and intake.audience_roles):
        u.who = UnderstoodInput(value=interp.audience, status=InputStatus.stated, source=InputSource.answer)
    if u.who.source == InputSource.none and interp.audience:
        u.who.value, u.who.source = interp.audience, InputSource.assumed
    if u.markets.source == InputSource.none and interp.market:
        u.markets.value, u.markets.source = interp.market, InputSource.assumed
    interp.intent = goals_text(u.goals, intake.goal_note if intake else None)  # never a model's guess
    interp.assumed = [a for a in interp.assumed if a != InterpretationField.intent]


def _apply_edits(result: PlanResult, intake: Intake | None, edits: dict | None) -> None:
    """The user's own words win: edited audience and topic, and competitors (user ones first, always kept)."""
    interp = result.interpretation
    if edits and edits.get("audience"):
        interp.audience = str(edits["audience"]).strip()
    if edits and edits.get("topic"):
        interp.topic = str(edits["topic"]).strip()
    names = list((intake.competitors_user if intake else []))
    if edits and "competitors" in edits:
        names += [str(c).strip() for c in edits["competitors"] if str(c).strip()]
    else:
        names += interp.competitors
    seen: set[str] = set()
    interp.competitors = [c for c in names if not (c.casefold() in seen or seen.add(c.casefold()))]


def settle_markets(result: PlanResult, brief: str, mode: str, edits: dict | None = None) -> None:
    """Code decides the final geography and languages (V2): regions expand, a place named in the brief
    is never "global", languages come from the markets plus English (capped per mode); queries in a
    left-out language are dropped, and a starting unit left without queries goes too."""
    from ctxpack.agent import markets as mk
    from ctxpack.schemas.plan import ExcludedLanguage, Market

    interp = result.interpretation
    edits = edits or {}
    chosen_markets = [{"code": c, "assumed": False} for c in edits.get("markets") or []]
    markets = mk.normalise(chosen_markets or [m.model_dump() for m in interp.markets], brief)
    langs, excluded = mk.choose_languages(markets, interp.languages, mode, mk.places_in(brief)["countries"])
    if edits.get("languages"):  # the user's own choice of languages (supported ones, any number up to the cap)
        supported = load_yaml("modes")["languages"]["supported"]
        mine = [lang for lang in dict.fromkeys(edits["languages"]) if lang in supported]
        cap = load_yaml("modes")["languages"]["max_per_mode"][mode]
        if mine:
            dropped = [lang for lang in langs if lang not in mine]
            excluded = [e for e in excluded if e["language"] not in mine]
            excluded += [{"language": lang, "reason": "removed by you"} for lang in dropped]
            excluded += [{"language": lang, "reason": f"over the {cap}-language limit for this mode"}
                         for lang in mine[cap:]]
            langs = mine[:cap]
    interp.markets = [Market(**m) for m in markets]
    interp.market = mk.label(markets)
    interp.languages = langs
    interp.languages_excluded = [ExcludedLanguage(**e) for e in excluded]
    if result.plan is not None:
        for unit in result.plan.starting_units:
            unit.queries = [q for q in unit.queries if q.language in langs]
        result.plan.starting_units = [u for u in result.plan.starting_units if u.queries]
