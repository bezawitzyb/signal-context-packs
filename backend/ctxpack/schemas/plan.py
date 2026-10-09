"""Brief input, interpretation and research plan (PRD FR-A1..A4, prompt F4-1)."""

import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ctxpack.config import load_yaml
from ctxpack.schemas.enums import (
    IntakeFill,
    CollectionPlatform,
    ComplianceCategory,
    Goal,
    InputSource,
    InputStatus,
    InterpretationField,
    Mode,
    OfferStage,
    SourceUnitKind,
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class BriefInput(Strict):
    """What a person or agent submits to start a run."""

    brief: str = Field(min_length=3, max_length=2000, description="The brief in plain words.",
                       examples=["Gen Z and meal prep"])
    mode: Mode = Field(default=Mode.quick, description="quick or standard.")
    time_window_days: int = Field(
        default_factory=lambda: load_yaml("modes")["default_time_window_days"],
        description="Look-back window in days (options in modes.yaml).", examples=[180])
    brand_voice: str | None = Field(default=None, max_length=200,
                                    description="Optional one-line brand voice; used ONLY by the playbook call.",
                                    examples=["Warm, cheeky, never preachy"])
    auto_approve: bool = Field(default=False, description="Skip plan review (agents always auto-approve).")

    @model_validator(mode="after")
    def _window(self) -> Self:
        options = load_yaml("modes")["time_window_days_options"]
        if self.time_window_days not in options:
            raise ValueError(f"time_window_days must be one of {options}")
        return self


class Market(Strict):
    """One market of the brief (schema 1.1, change V2)."""

    code: str = Field(description='ISO 3166-1 alpha-2 country in capitals (NL), a region in lower case '
                                  '(eu, dach, benelux, nordics, cee), or "global".', examples=["NL", "eu"])
    countries: list[str] = Field(default_factory=list, description="ISO alpha-2 countries in this market, "
                                 "the ones the brief names first. Empty for global.", examples=[["DE", "PL", "SE"]])
    weight: float = Field(default=1.0, ge=0, description="Share of the research for this market (weights sum to 1).")
    assumed: bool = Field(default=False, description="True if the brief does not state this market.")


class ExcludedLanguage(Strict):
    language: str = Field(description="ISO 639-1 code.")
    reason: str = Field(description="Why it was left out, in plain words.")


def goal_from_text(text: str) -> Goal | None:
    """A goal id or its chip text (config/goals.yaml), any case -> the Goal; anything else -> None."""
    key = str(text).strip().casefold()
    for gid, g in load_yaml("goals")["goals"].items():
        if key in (gid, gid.replace("_", " "), str(g["chip"]).casefold()):
            return Goal(gid)
    return None


def stage_from_text(text: str) -> OfferStage | None:
    """An offer-stage id or its chip text -> the OfferStage; anything else -> None."""
    key = str(text).strip().casefold()
    for sid, st in load_yaml("goals")["offer_stages"].items():
        if key in (sid, sid.replace("_", " "), str(st["chip"]).casefold()):
            return OfferStage(sid)
    return None


def goals_text(goals: list, note: str | None = None) -> str:
    """Ranked goals in plain words ("Positioning, then Content plan"), with the user's own words."""
    chips = load_yaml("goals")["goals"]
    words = ", then ".join(chips[getattr(g, "value", g)]["chip"] for g in goals)
    if note and note.strip():
        words = f"{words} ({note.strip()})" if words else note.strip()
    return words


def confirmed_goal(intake: dict | None) -> str:
    """The user's confirmed goals in plain words, from brief.intake (V11); "" when none were given."""
    i = intake or {}
    return goals_text(i.get("goals") or [], i.get("goal_note"))


def section_order(goals: list, has_brand: bool = False) -> list[str]:
    """Pack sections in the order the ranked goals need them (V12): the main goal's lead sections, then the next
    goal's, then the rest in config/goals.yaml default_order. "brand" only when the pack has brand perception."""
    cfg = load_yaml("goals")
    order: list[str] = []
    for g in goals:
        order += [x for x in cfg["goals"][getattr(g, "value", g)].get("lead", []) if x not in order]
    order += [x for x in cfg["default_order"] if x not in order]
    return [x for x in order if x != "brand" or has_brand]


def offer_text(intake: dict | None) -> str:
    """The user's offer and its stage in plain words, from brief.intake (V11); "" when not given."""
    i = intake or {}
    stage = load_yaml("goals")["offer_stages"].get(i.get("offer_stage") or "", {}).get("chip", "")
    return "; ".join(x for x in (i.get("offer") or "", stage) if x)


def brand_names(intake: dict | None, interpretation: dict | None = None) -> tuple[list[str], list[str]]:
    """(brand aliases, parent aliases) for brand perception (V12): the user's answer, else the brand the brief
    states (quote checked). Aliases are split on commas and slashes; empty lists when not given."""
    i = intake or {}
    u = ((interpretation or {}).get("understanding") or {}).get("brand") or {}
    brand = i.get("brand") or (u.get("value") if u.get("status") == "stated" else "") or ""

    def split(text: str) -> list[str]:
        return list(dict.fromkeys(p.strip() for p in re.split(r"[,/]", text or "") if p.strip()))
    return split(brand), split(i.get("parent_brand") or "")


class UnderstoodInput(Strict):
    """One of the five inputs only the user knows, as read from the brief (change V11). Never a guess."""

    value: str = Field(default="", description="What you understood, in plain words. Empty when missing.")
    brief_quote: str = Field(default="", description="The exact words of the brief it rests on, copied character "
                             "for character. Empty when missing.")
    status: InputStatus = Field(default=InputStatus.missing, description="stated (the brief says it clearly), "
                                "unclear (named but too vague to research well) or missing.")
    source: InputSource = Field(default=InputSource.none, description="Filled in code: brief, answer, assumed or "
                                "none. Leave it as none.")


class Understanding(Strict):
    """The five inputs only the user knows (change V11, schema 1.2): goals, offer, who, markets, key question.
    Each rests on the brief's own words or on the user's answer; code checks every quote is in the brief."""

    goal: UnderstoodInput = Field(default_factory=UnderstoodInput, description="What the research is for.")
    goals: list[Goal] = Field(default_factory=list, description="Goal ids the brief or the user states, main "
                              "first (ids in the goal list). Empty unless stated - never guessed.")
    offer: UnderstoodInput = Field(default_factory=UnderstoodInput, description="What the user sells or plans to "
                                   "sell.")
    offer_stage: OfferStage | None = Field(default=None, description="idea, launching, selling or no_offer - only "
                                           "when stated.")
    who: UnderstoodInput = Field(default_factory=UnderstoodInput, description="Whose conversations to listen to, "
                                 "and their roles (buyer, influencer, user).")
    markets: UnderstoodInput = Field(default_factory=UnderstoodInput, description="Where these people are.")
    key_question: UnderstoodInput = Field(default_factory=UnderstoodInput, description="The decision or question "
                                          "the research must help with, and by when.")
    brand: UnderstoodInput = Field(default_factory=UnderstoodInput, description="The user's own brand name, as "
                                   "people write it (V12; only matters for the brand_perception goal).")

    @model_validator(mode="before")
    @classmethod
    def _known_goals(cls, data: object) -> object:
        """Goals outside the list are dropped; if none is left, a stated goal becomes unclear."""
        if isinstance(data, dict) and data.get("goals"):
            known = [g for g in (goal_from_text(x) for x in data["goals"]) if g is not None]
            data = {**data, "goals": list(dict.fromkeys(known))}
            if not known and isinstance(data.get("goal"), dict) and data["goal"].get("status") == "stated":
                data["goal"] = {**data["goal"], "status": "unclear"}
        return data


class Interpretation(Strict):
    """How the brief was understood. Inferred fields are listed in `assumed`."""

    topic: str = Field(description="What the conversation is about.", examples=["meal prep"])
    markets: list[Market] = Field(min_length=1, description="Markets of the brief (1.1). A brief naming a "
                                  'country or region is never "global".')
    market: str = Field(default="", description="Short market label made in code from markets (e.g. NL, "
                        '"EU (DE, PL, SE, +3)", global). Leave it empty.', examples=["NL"])
    languages: list[str] = Field(min_length=1, description="ISO 639-1 codes, most important first.",
                                 examples=[["nl", "en"]])
    languages_excluded: list[ExcludedLanguage] = Field(
        default_factory=list, description="Languages left out, with the reason (1.1; filled in code). Leave it empty.")
    audience: str = Field(description="Who we listen to.", examples=["students aged 18-25"])
    category: str = Field(description="Product or service category.", examples=["snacks"])
    compliance_category: ComplianceCategory = Field(description="Regulated area that drives compliance checks.")
    competitors: list[str] = Field(default_factory=list, description="Brands named in or implied by the brief.")
    intent: str = Field(default="", description="Filled in code from the confirmed goals (V11). Leave it empty.",
                        examples=["Positioning, then content plan"])
    time_window_days: int = Field(description="Look-back window in days.", examples=[180])
    assumed: list[InterpretationField] = Field(
        default_factory=list, description="Fields that were inferred rather than stated in the brief."
    )
    understanding: Understanding = Field(default_factory=Understanding, description="The five inputs only the "
                                         "user knows, each with the brief's own words and a status (V11, 1.2).")

    @model_validator(mode="before")
    @classmethod
    def _from_1_0(cls, data: object) -> object:
        """Schema 1.0 had one `market` (ISO code or "global"): it becomes markets[] (migration 1.0 -> 1.1)."""
        if isinstance(data, dict) and "markets" not in data and data.get("market"):
            code = str(data["market"])
            data = {**data, "markets": [{"code": code, "countries": [] if code == "global" else [code.upper()],
                                         "weight": 1.0, "assumed": "market" in (data.get("assumed") or [])}]}
        return data

    @model_validator(mode="after")
    def _label(self) -> Self:
        from ctxpack.agent.markets import label

        self.market = label([m.model_dump() for m in self.markets])
        return self


class ClarifyingQuestion(Strict):
    """One of 0-4 questions that would most improve THIS research (change V3, V11). Never asked of agents."""

    id: str = Field(default="Q1", pattern=r"^Q\d{1,2}$", description="Q1, Q2, Q3, Q4.", examples=["Q1"])
    question: str = Field(description="The question, in the user's terms and the brief's language.",
                          examples=["Who should this speak to?"])
    why_it_helps: str = Field(default="", description="One short line shown to the user: how the answer changes "
                              "the research.", examples=["Buyers and shop-floor users talk in different places."])
    fills: IntakeFill = Field(default=IntakeFill.other, description="Which intake field the answer fills.")
    options: list[str] = Field(default_factory=list, max_length=8, description="3-5 answer chips written for THIS "
                               "brief (the goal and offer chips are set in code; the brand question has none).")
    multi_select: bool = Field(default=False, description="True if more than one chip may be chosen.")
    allow_free_text: bool = Field(default=True, description="True if the user may answer in their own words.")
    placeholder: str = Field(default="", max_length=120, description="A short example answer for the own-words box, "
                             "written for THIS brief (e.g. 'e.g. booking software for venues').")
    required: bool = Field(default=False, description="Set in code: the goal and offer questions cannot be "
                           "skipped. Leave it false.")


class GoalLeftOut(Strict):
    goal: Goal = Field(description="The goal left out.")
    reason: str = Field(description="Why, in plain words.")


class QAnswer(Strict):
    question: str = Field(description="The question asked.")
    answer: str = Field(description="The answer given.")


class Intake(Strict):
    """What the user told us before planning (change V3, V11; brief.intake in schema 1.2). Empty = not told."""

    audience_roles: list[str] = Field(default_factory=list, description="Who exactly to reach (e.g. plant managers "
                                      "who sign off budgets; operators on the shop floor).")
    goals: list[Goal] = Field(default_factory=list, description="What the research is for, main goal first "
                              "(ids in config/goals.yaml).", examples=[["positioning", "content_plan"]])
    goal_note: str | None = Field(default=None, description="The goal in the user's own words.")
    offer: str | None = Field(default=None, description="What the user offers.")
    offer_stage: OfferStage | None = Field(default=None, description="idea, launching, selling or no_offer.")
    key_question: str | None = Field(default=None, description="The decision or question the research must help "
                                     "with, in the user's words.")
    brand: str | None = Field(default=None, max_length=120, description="The user's brand as people write it "
                              "(V12; required with the brand_perception goal). Aliases separated by commas.")
    parent_brand: str | None = Field(default=None, max_length=120, description="The parent brand, if any (V12).")
    goals_left_out: list[GoalLeftOut] = Field(default_factory=list, description="Goals beyond the cap, with the "
                                              "reason (V12; filled in code).")
    channels_in_use: list[str] = Field(default_factory=list, description="Channels the user already uses.")
    competitors_user: list[str] = Field(default_factory=list, description="Competitors the user named; always "
                                        "searched.")
    timeframe: str | None = Field(default=None, description="When the user needs to act, in their words.")
    other_answers: list[QAnswer] = Field(default_factory=list, description="Answers that fill no field above.")
    questions_asked: list[ClarifyingQuestion] = Field(default_factory=list,
                                                      description="The questions shown to the user.")

    @model_validator(mode="before")
    @classmethod
    def _from_1_1(cls, data: object) -> object:
        """Schema 1.1 had one free-text `goal`: goal ids or chips become goals, other words the goal note."""
        if isinstance(data, dict) and "goal" in data:
            data = dict(data)
            old = data.pop("goal")
            if old:
                parts = [p.strip() for p in str(old).replace(";", ",").split(",") if p.strip()]
                found = [goal_from_text(p) for p in parts]
                if parts and all(found):
                    data.setdefault("goals", list(dict.fromkeys(g.value for g in found)))
                else:
                    data.setdefault("goal_note", str(old))
        if isinstance(data, dict) and data.get("goals"):
            goals = []
            for g in data["goals"]:
                found = goal_from_text(g.value if isinstance(g, Goal) else g)
                if found is None:
                    raise ValueError(f"unknown goal {g!r}: use one of {', '.join(load_yaml('goals')['goals'])}")
                goals.append(found)
            data = {**data, "goals": list(dict.fromkeys(goals))}
            most = load_yaml("modes")["goals"]["max"]
            if len(data["goals"]) > most:  # V12: the first ones are kept, the rest listed with the reason
                data["goals_left_out"] = [{"goal": g, "reason": f"at most {most} goals per pack - this one came "
                                           f"after the first {most}"} for g in data["goals"][most:]]
                data["goals"] = data["goals"][:most]
        if isinstance(data, dict) and data.get("offer_stage") and not isinstance(data["offer_stage"], OfferStage):
            stage = stage_from_text(data["offer_stage"])
            if stage is None:
                raise ValueError(f"unknown offer_stage {data['offer_stage']!r}: use one of "
                                 f"{', '.join(load_yaml('goals')['offer_stages'])}")
            data = {**data, "offer_stage": stage}
        return data

    def empty(self) -> bool:
        return not (self.audience_roles or self.goals or self.goal_note or self.offer or self.offer_stage
                    or self.key_question or self.brand or self.channels_in_use or self.competitors_user
                    or self.timeframe or self.other_answers)


class PlanHypothesis(Strict):
    id: str = Field(pattern=r"^HYP-\d{2,}$", description="Hypothesis id.", examples=["HYP-01"])
    statement: str = Field(description="A testable statement.",
                           examples=["Students see meal prep as a money saver first."])
    role: str | None = Field(default=None, description="The audience role it is about, if the user chose roles.")


class ResearchQuestion(Strict):
    id: str = Field(pattern=r"^RQ-\d{2,}$", description="Research question id.", examples=["RQ-01"])
    text: str = Field(description="What collection should answer.",
                      examples=["What stops students from meal prepping?"])
    role: str | None = Field(default=None, description="The audience role it is about, if the user chose roles.")


class SourceQuery(Strict):
    language: str = Field(description="ISO 639-1 code.", examples=["nl"])
    query: str = Field(description="Query in that language, incl. slang and local terms.",
                       examples=["mealprep studenten goedkoop"])


class StartingSourceUnit(Strict):
    """A place the agent starts looking. Chosen by reasoning, never from a fixed list."""

    platform: CollectionPlatform = Field(description="Where to search.")
    kind: SourceUnitKind = Field(description="subreddit, hashtag, channel, domain or query.")
    target: str = Field(description="The subreddit / hashtag / channel / domain / query.",
                        examples=["r/studenten"])
    reason: str = Field(min_length=1, description="One specific reason for starting here.")
    queries: list[SourceQuery] = Field(default_factory=list, description="Queries per language.")
    enabled: bool = Field(default=True, description="Plan review toggle; disabled units are not used.")

    @property
    def source_unit(self) -> str:
        return f"{self.platform.value}:{self.target}"


class Plan(Strict):
    hypotheses: list[PlanHypothesis] = Field(min_length=3, max_length=5, description="3-5 hypotheses.")
    research_questions: list[ResearchQuestion] = Field(min_length=5, max_length=8,
                                                       description="5-8 research questions.")
    starting_units: list[StartingSourceUnit] = Field(min_length=3, max_length=6,
                                                     description="3-6 starting source units.")
    source_balance_reason: str = Field(default="", description="Why one platform takes more than the allowed "
                                       "share of starting units (V6); empty when the mix is balanced.")


class PlanResult(Strict):
    """Output of the interpret + plan call: EITHER clarifying questions OR a plan."""

    interpretation: Interpretation
    clarifying_questions: list[ClarifyingQuestion] = Field(default_factory=list)
    plan: Plan | None = None

    @model_validator(mode="after")
    def _one_of(self) -> Self:
        if bool(self.clarifying_questions) == (self.plan is not None):
            raise ValueError("give exactly one of clarifying_questions or plan")
        return self


class RunEstimate(Strict):
    """Cost and time shown with the plan. Computed in code from modes.yaml, never by a model."""

    mode: Mode
    max_usd: float = Field(description="Hard cap: Apify + collection LLM + analysis LLM budgets for the mode.",
                           examples=[4.2])
    typical_usd_low: float = Field(examples=[1.5])
    typical_usd_high: float = Field(examples=[3.0])
    typical_minutes: int = Field(description="Typical end-to-end time.", examples=[7])
    collection_secs: int = Field(description="Hard cap on agent collection time.", examples=[300])
    max_tool_calls: int = Field(description="Hard cap on agent tool calls.", examples=[15])
