"""Every enum in the pack, plan and documents. Values are lowercase snake_case.

Pydantic rejects any other spelling (e.g. "Strong" or "STRONG").
"""

from enum import StrEnum


class Mode(StrEnum):
    quick = "quick"
    standard = "standard"


class Platform(StrEnum):
    """Source family. All forum domains together are ONE platform (web_forum)."""

    reddit = "reddit"
    tiktok = "tiktok"
    youtube = "youtube"
    instagram = "instagram"
    web_forum = "web_forum"
    web_review = "web_review"
    web_editorial = "web_editorial"


class CollectionPlatform(StrEnum):
    """Where a starting source unit is searched (web covers forums, reviews, editorial)."""

    reddit = "reddit"
    tiktok = "tiktok"
    youtube = "youtube"
    instagram = "instagram"
    web = "web"


class SourceUnitKind(StrEnum):
    subreddit = "subreddit"
    hashtag = "hashtag"
    channel = "channel"
    domain = "domain"
    query = "query"


class ConfidenceLabel(StrEnum):
    strong = "strong"
    moderate = "moderate"
    emerging = "emerging"
    speculative = "speculative"


class ClaimType(StrEnum):
    observed = "observed"
    inferred = "inferred"
    external = "external"


class Trend(StrEnum):
    rising = "rising"
    stable = "stable"
    fading = "fading"
    insufficient_data = "insufficient_data"


class Emotion(StrEnum):
    frustration = "frustration"
    aspiration = "aspiration"
    skepticism = "skepticism"
    humour = "humour"
    anxiety = "anxiety"
    pride = "pride"
    nostalgia = "nostalgia"
    excitement = "excitement"
    guilt = "guilt"
    indifference = "indifference"


class ComplianceCategory(StrEnum):
    food_nutrition = "food_nutrition"
    health_supplements = "health_supplements"
    alcohol = "alcohol"
    children = "children"
    energy_environmental = "energy_environmental"
    finance = "finance"
    other = "other"


class Level(StrEnum):
    """Effort or impact."""

    low = "low"
    medium = "medium"
    high = "high"


class RelevanceReason(StrEnum):
    """Why the relevance worker (F4-5) judged a document as it did."""

    on_topic = "on_topic"
    partly_on_topic = "partly_on_topic"
    off_topic = "off_topic"
    promotional = "promotional"
    news_or_brand = "news_or_brand"
    wrong_market = "wrong_market"
    insufficient_evidence = "insufficient_evidence"


class DatePrecision(StrEnum):
    day = "day"
    month = "month"
    year = "year"
    unknown = "unknown"


class HypothesisStatus(StrEnum):
    supported = "supported"
    refuted = "refuted"
    inconclusive = "inconclusive"


class CoverageGrade(StrEnum):
    a = "a"
    b = "b"
    c = "c"
    d = "d"


class SourceVerdict(StrEnum):
    kept = "kept"
    dropped = "dropped"


class MotivationKind(StrEnum):
    need = "need"
    pain = "pain"
    job = "job"


class ObjectionKind(StrEnum):
    objection = "objection"
    myth = "myth"
    trust_marker = "trust_marker"


class CultureKind(StrEnum):
    format = "format"
    community = "community"
    creator = "creator"
    code = "code"


class WhiteSpaceKind(StrEnum):
    unmet_need = "unmet_need"
    unanswered_question = "unanswered_question"
    unserved_segment = "unserved_segment"


class TargetKind(StrEnum):
    community = "community"
    creator = "creator"


class FinishReason(StrEnum):
    finish = "finish"
    tool_call_limit = "tool_call_limit"
    time_limit = "time_limit"
    budget_limit = "budget_limit"
    no_tool_call = "no_tool_call"
    error = "error"
    stopped = "stopped"


class EventType(StrEnum):
    """Live events (guide B6)."""

    stage = "stage"
    agent_call = "agent_call"
    agent_result = "agent_result"
    coverage = "coverage"
    fallback = "fallback"
    queue = "queue"
    counters = "counters"
    cost = "cost"
    pack_ready = "pack_ready"
    error = "error"


class RunStatus(StrEnum):
    """Run lifecycle (guide B5). The pipeline step is in RunStage."""

    created = "created"
    needs_clarification = "needs_clarification"
    awaiting_approval = "awaiting_approval"
    queued = "queued"
    running = "running"
    interrupted = "interrupted"
    complete = "complete"
    partial = "partial"
    failed = "failed"
    stopped = "stopped"


class RunStage(StrEnum):
    planning = "planning"
    collecting = "collecting"
    extracting = "extracting"
    clustering = "clustering"
    writing = "writing"
    verifying = "verifying"
    packaging = "packaging"


class Requester(StrEnum):
    web = "web"
    api = "api"
    mcp = "mcp"
    cli = "cli"


class InterpretationField(StrEnum):
    """Interpretation fields that can be marked as assumed (inferred, not stated)."""

    topic = "topic"
    market = "market"
    languages = "languages"
    audience = "audience"
    category = "category"
    compliance_category = "compliance_category"
    competitors = "competitors"
    intent = "intent"
    time_window_days = "time_window_days"
