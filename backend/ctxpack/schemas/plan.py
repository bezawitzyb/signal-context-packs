"""Brief input, interpretation and research plan (PRD FR-A1..A4, prompt F4-1)."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ctxpack.config import load_yaml
from ctxpack.schemas.enums import (
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


class Interpretation(Strict):
    """How the brief was understood. Inferred fields are listed in `assumed`."""

    topic: str = Field(description="What the conversation is about.", examples=["meal prep"])
    market: str = Field(description='ISO 3166-1 alpha-2 country code, or "global".', examples=["NL"])
    languages: list[str] = Field(min_length=1, description="ISO 639-1 codes, most important first.",
                                 examples=[["nl", "en"]])
    audience: str = Field(description="Who we listen to.", examples=["students aged 18-25"])
    category: str = Field(description="Product or service category.", examples=["snacks"])
    compliance_category: ComplianceCategory = Field(description="Regulated area that drives compliance checks.")
    competitors: list[str] = Field(default_factory=list, description="Brands named in or implied by the brief.")
    intent: str = Field(description="What the marketer wants to achieve.", examples=["launch a brand"])
    time_window_days: int = Field(description="Look-back window in days.", examples=[180])
    assumed: list[InterpretationField] = Field(
        default_factory=list, description="Fields that were inferred rather than stated in the brief."
    )


class ClarifyingQuestion(Strict):
    """At most one, only if market or audience truly cannot be inferred. Never asked of agents."""

    question: str = Field(description="The question.", examples=["Which country is the launch in?"])
    options: list[str] = Field(min_length=3, max_length=5, description="3-5 suggested answers.")


class PlanHypothesis(Strict):
    id: str = Field(pattern=r"^HYP-\d{2,}$", description="Hypothesis id.", examples=["HYP-01"])
    statement: str = Field(description="A testable statement.",
                           examples=["Students see meal prep as a money saver first."])


class ResearchQuestion(Strict):
    id: str = Field(pattern=r"^RQ-\d{2,}$", description="Research question id.", examples=["RQ-01"])
    text: str = Field(description="What collection should answer.",
                      examples=["What stops students from meal prepping?"])


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
    """Output of the interpret + plan call: EITHER a clarifying question OR a plan."""

    interpretation: Interpretation
    clarifying_question: ClarifyingQuestion | None = None
    plan: Plan | None = None

    @model_validator(mode="after")
    def _one_of(self) -> Self:
        if (self.clarifying_question is None) == (self.plan is None):
            raise ValueError("give exactly one of clarifying_question or plan")
        return self
