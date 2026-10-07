"""Brief input, interpretation and research plan (PRD FR-A1..A4, prompt F4-1)."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ctxpack.config import load_yaml
from ctxpack.schemas.enums import (
    IntakeFill,
    CollectionPlatform,
    ComplianceCategory,
    InterpretationField,
    Mode,
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
    intent: str = Field(description="What the marketer wants to achieve.", examples=["launch a brand"])
    time_window_days: int = Field(description="Look-back window in days.", examples=[180])
    assumed: list[InterpretationField] = Field(
        default_factory=list, description="Fields that were inferred rather than stated in the brief."
    )

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
    """One of 0-3 questions that would most improve THIS research (change V3). Never asked of agents."""

    id: str = Field(default="Q1", pattern=r"^Q\d{1,2}$", description="Q1, Q2, Q3.", examples=["Q1"])
    question: str = Field(description="The question, in the user's terms and the brief's language.",
                          examples=["Who should this speak to?"])
    why_it_helps: str = Field(default="", description="One short line shown to the user: how the answer changes "
                              "the research.", examples=["Buyers and shop-floor users talk in different places."])
    fills: IntakeFill = Field(default=IntakeFill.other, description="Which intake field the answer fills.")
    options: list[str] = Field(min_length=3, max_length=5, description="3-5 answer chips written for THIS brief.")
    multi_select: bool = Field(default=False, description="True if more than one chip may be chosen.")
    allow_free_text: bool = Field(default=True, description="True if the user may answer in their own words.")


class QAnswer(Strict):
    question: str = Field(description="The question asked.")
    answer: str = Field(description="The answer given.")


class Intake(Strict):
    """What the user told us before planning (change V3; brief.intake in schema 1.1). Empty = agent decides."""

    audience_roles: list[str] = Field(default_factory=list, description="Who exactly to reach (e.g. plant managers "
                                      "who sign off budgets; operators on the shop floor).")
    goal: str | None = Field(default=None, description="What the research is for (content calendar, campaign, "
                             "positioning, product research, sales).")
    offer: str | None = Field(default=None, description="What the user offers.")
    channels_in_use: list[str] = Field(default_factory=list, description="Channels the user already uses.")
    competitors_user: list[str] = Field(default_factory=list, description="Competitors the user named; always "
                                        "searched.")
    timeframe: str | None = Field(default=None, description="When the user needs to act, in their words.")
    other_answers: list[QAnswer] = Field(default_factory=list, description="Answers that fill no field above.")
    questions_asked: list[ClarifyingQuestion] = Field(default_factory=list,
                                                      description="The questions shown to the user.")

    def empty(self) -> bool:
        return not (self.audience_roles or self.goal or self.offer or self.channels_in_use
                    or self.competitors_user or self.timeframe or self.other_answers)


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
