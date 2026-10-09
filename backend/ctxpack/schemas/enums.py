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
    linkedin = "linkedin"
    x = "x"
    facebook = "facebook"
    web_forum = "web_forum"
    web_review = "web_review"
    web_editorial = "web_editorial"


class CollectionPlatform(StrEnum):
    """Where a starting source unit is searched (web covers forums, reviews, editorial)."""

    reddit = "reddit"
    tiktok = "tiktok"
    youtube = "youtube"
    instagram = "instagram"
    linkedin = "linkedin"
    x = "x"
    facebook = "facebook"
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


class ClusterKind(StrEnum):
    """What a cluster (CL-xx) groups (F4-7). Tension sides are two paired clusters."""

    theme = "theme"
    motivation = "motivation"
    tension_want = "tension_want"
    tension_but = "tension_but"
    objection = "objection"
    segment = "segment"
    lexicon = "lexicon"
    moment = "moment"
    competitor = "competitor"
    white_space = "white_space"


class Stance(StrEnum):
    """A document's stance toward the topic or a brand (extraction, F4-6; PRD 5.5 uses it)."""

    positive = "positive"
    negative = "negative"
    mixed = "mixed"
    neutral = "neutral"


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


class OpportunityKind(StrEnum):
    """What kind of opportunity (change V5)."""

    content_idea = "content_idea"
    product_idea = "product_idea"
    positioning = "positioning"


class OpportunityStatus(StrEnum):
    """supported: enough authors across communities; signal: an early signal - check before acting (V5)."""

    supported = "supported"
    signal = "signal"


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


class IntakeFill(StrEnum):
    """What a clarifying question fills in brief.intake (change V3)."""

    audience_roles = "audience_roles"
    goal = "goal"
    offer = "offer"
    channels_in_use = "channels_in_use"
    market = "market"
    competitors = "competitors"
    timeframe = "timeframe"
    key_question = "key_question"
    brand = "brand"
    other = "other"


class Goal(StrEnum):
    """What the research is for (change V11; chips and descriptions in config/goals.yaml)."""

    content_plan = "content_plan"
    campaign_launch = "campaign_launch"
    positioning = "positioning"
    product_validation = "product_validation"
    market_entry = "market_entry"
    brand_perception = "brand_perception"
    sales_enablement = "sales_enablement"
    understand_audience = "understand_audience"


class OfferStage(StrEnum):
    """How far the user's offer is (change V11)."""

    idea = "idea"
    launching = "launching"
    selling = "selling"
    no_offer = "no_offer"


class BrandRelation(StrEnum):
    """How a post treats the user's brand next to its parent brand (change V12)."""

    same_as_parent = "same_as_parent"
    part_of_parent = "part_of_parent"
    distinct = "distinct"
    unclear = "unclear"


class BrandFindingKind(StrEnum):
    """What a brand-perception finding is about (change V12)."""

    perception = "perception"
    praise = "praise"
    criticism = "criticism"
    differentiation = "differentiation"
    awareness = "awareness"


class InputStatus(StrEnum):
    """How clearly the brief states one of the five inputs (change V11)."""

    stated = "stated"
    unclear = "unclear"
    missing = "missing"


class InputSource(StrEnum):
    """Where an understood input came from (change V11). Goals and offer are never assumed."""

    brief = "brief"
    answer = "answer"
    assumed = "assumed"
    none = "none"


class EvidenceRole(StrEnum):
    """Who the post's author is, when the post shows it (change V3)."""

    buyer = "buyer"
    influencer = "influencer"
    user = "user"
    consumer = "consumer"
    other = "other"
    unknown = "unknown"


class PostChannel(StrEnum):
    """Where a post brief is published (change V8): the social platforms plus owned channels."""

    reddit = "reddit"
    tiktok = "tiktok"
    youtube = "youtube"
    instagram = "instagram"
    linkedin = "linkedin"
    x = "x"
    facebook = "facebook"
    web_forum = "web_forum"
    blog = "blog"
    newsletter = "newsletter"


class PostFormat(StrEnum):
    text_post = "text_post"
    carousel = "carousel"
    short_video = "short_video"
    blog_article = "blog_article"
    newsletter = "newsletter"


class TimingKind(StrEnum):
    """Why a calendar entry sits where it does (change V8)."""

    news_hook = "news_hook"
    channel_timing = "channel_timing"
    spread = "spread"


class RelationKind(StrEnum):
    """How one item connects to an item in another section (change V4)."""

    comes_from = "comes_from"   # e.g. an objection comes from a pain point
    blocks = "blocks"           # e.g. an objection blocks a motivation
    related = "related"


class InterpretationField(StrEnum):
    """Interpretation fields that can be marked as assumed (inferred, not stated)."""

    topic = "topic"
    market = "market"
    markets = "markets"
    languages = "languages"
    audience = "audience"
    category = "category"
    compliance_category = "compliance_category"
    competitors = "competitors"
    intent = "intent"
    time_window_days = "time_window_days"
