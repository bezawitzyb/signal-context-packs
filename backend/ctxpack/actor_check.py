"""actor-check: is every Apify actor in catalog.yaml still healthy, priced as we think and
accepting the inputs we send? Free: the public Apify API (no key), and our own tools run offline.

Per actor (main, fallback, comments and their fallbacks):
- health: deprecated, 30-day success rate (and the drop since the catalog snapshot), runs and
  users in 30 days, last build, review rating;
- price: the pricing model, every catalog price still a live price, a price change announced;
- inputs: every input our tools send - captured by running the real tools offline for every time
  window and a single-country non-English brief - exists in the actor's input schema, with an
  allowed value and type.
Thresholds live in catalog.yaml (health_check). Actor texts are untrusted: only numbers, dates and
field names are read and shown, never their descriptions or notices.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Iterator

import httpx

from ctxpack.config import get_settings, load_yaml

API = "https://api.apify.com/v2/acts/"
TIMEOUT = 30
FAIL, WARN = "fail", "warn"
_TYPES = {"integer": int, "number": (int, float), "string": str, "boolean": bool, "array": list, "object": dict}


@dataclass
class Finding:
    level: str          # fail | warn
    text: str


@dataclass
class ActorReport:
    actor_id: str
    role: str           # e.g. "reddit main", "tiktok comments fallback"
    facts: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    inputs_checked: int = 0

    @property
    def level(self) -> str:
        levels = {f.level for f in self.findings}
        return FAIL if FAIL in levels else WARN if WARN in levels else "ok"


# --------------------------------------------------------------------------
# The catalog
# --------------------------------------------------------------------------

def catalog_actors() -> list[tuple[str, dict]]:
    """(role, spec) for every Apify actor in catalog.yaml."""
    out = []
    for name, src in load_yaml("catalog")["sources"].items():
        if src.get("kind") != "apify":
            continue
        comments = src.get("comments") or {}
        for role, spec in (("main", src.get("actor")), ("fallback", src.get("fallback")),
                           ("comments", comments.get("actor")), ("comments fallback", comments.get("fallback"))):
            if spec:
                out.append((f"{name} {role}", spec))
    return out


# --------------------------------------------------------------------------
# What our tools send (offline: fixture items, fake model, nothing stored, no network)
# --------------------------------------------------------------------------

@contextmanager
def _offline() -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in ("USE_FIXTURES", "LLM_FAKE")}
    os.environ["USE_FIXTURES"] = os.environ["LLM_FAKE"] = "true"
    get_settings.cache_clear()
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()


# One call per kind of unit each tool accepts; every catalogued actor must be reached by one of them.
_CALLS: list[tuple[str, dict]] = [
    ("search_reddit", {"target": "meal prep"}),
    ("search_reddit", {"target": "r/MealPrepSunday"}),
    ("search_reddit", {"target": "r/MealPrepSunday", "query": "budget"}),
    ("search_tiktok", {"target": "#mealprep"}),
    ("search_tiktok", {"target": "meal prep"}),
    ("search_youtube", {"query": "meal prep"}),
    ("search_youtube", {"query": "@somechannel"}),
    ("search_instagram", {"hashtag": "mealprep"}),
    ("search_linkedin", {"query": "meal prep"}),
    ("search_x", {"target": "meal prep"}),
    ("search_x", {"target": "#mealprep"}),
    ("search_facebook", {"query": "meal prep"}),
    ("get_trends", {"terms": ["meal prep"], "geo": "NL"}),
]
# (countries, languages): worldwide English, and a single-country non-English brief (country inputs)
_BRIEFS = [([], ["en"]), (["NL"], ["nl", "en"])]


def sent_inputs() -> dict[str, list[dict]]:
    """actor id -> every input our tools send it. Main actors 'return nothing', so every fallback and
    comment actor is reached too (fallbacks return their fixture items, which feed the comment chains)."""
    from ctxpack.collect import apify, tools
    from ctxpack.collect.relevance import BriefContext

    mains = {spec["id"] for role, spec in catalog_actors() if role.endswith(("main", " comments"))}
    seen: dict[str, list[dict]] = {}

    async def capture(spec: dict, run_input: dict, limit: int, timeout: int | None = None) -> apify.ActorResult:
        seen.setdefault(spec["id"], []).append(run_input)
        if spec["id"] in mains:
            return apify.ActorResult(spec["id"], [], 0.0, "SUCCEEDED")
        path = apify.fixture_path(spec["id"])
        items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return apify.ActorResult(spec["id"], items[:limit], 0.0, "SUCCEEDED")

    async def run_all() -> None:
        for window in load_yaml("modes")["time_window_days_options"]:
            for countries, languages in _BRIEFS:
                for name, args in _CALLS:
                    ctx = tools.RunContext(
                        run_id="actor-check", mode="standard", window_days=window, store=lambda d, r: None,
                        brief=BriefContext(topic="meal prep", market=countries[0] if countries else "global",
                                           countries=list(countries), languages=list(languages),
                                           research_questions={"RQ1": "Why?"}))
                    await tools.TOOLS[name](ctx, reason="actor-check", **args)

    original, quiet = apify.run_actor, logging.getLogger("ctxpack.collect.apify")
    level = quiet.level
    apify.run_actor = capture
    quiet.setLevel(logging.ERROR)  # "main actor gave 0 items" is the point here, not a problem
    try:
        with _offline():
            asyncio.run(run_all())
    finally:
        apify.run_actor = original
        quiet.setLevel(level)
    return seen


# --------------------------------------------------------------------------
# Checks (pure: the fetched data in, findings out)
# --------------------------------------------------------------------------

def input_schema(build: dict) -> dict:
    schema = build.get("inputSchema") or (build.get("actorDefinition") or {}).get("input") or {}
    return json.loads(schema) if isinstance(schema, str) else schema


def check_input(run_input: dict, schema: dict) -> list[str]:
    """Problems with one input we send: unknown field, value not allowed, wrong type, out of range."""
    props, problems = schema.get("properties") or {}, []
    for key, value in run_input.items():
        p = props.get(key)
        if p is None:
            problems.append(f"input '{key}' no longer exists")
            continue
        want = _TYPES.get(p.get("type", ""))
        if want and (not isinstance(value, want) or (isinstance(value, bool) and p.get("type") != "boolean")):
            problems.append(f"input '{key}' must be {p['type']}, we send {type(value).__name__}")
            continue
        allowed = p.get("enum") or (p.get("items") or {}).get("enum")
        values = value if isinstance(value, list) else [value]
        if allowed and (bad := [v for v in values if v not in allowed]):
            problems.append(f"input '{key}' value {bad[0]!r} is not allowed")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if p.get("minimum") is not None and value < p["minimum"]:
                problems.append(f"input '{key}' = {value} is below its minimum {p['minimum']}")
            if p.get("maximum") is not None and value > p["maximum"]:
                problems.append(f"input '{key}' = {value} is above its maximum {p['maximum']}")
    for key in schema.get("required") or []:
        if key not in run_input and "default" not in (props.get(key) or {}):
            problems.append(f"required input '{key}' is not sent")
    return problems


def _date(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _live_prices(act: dict, now: datetime) -> tuple[str | None, dict[str, float], list[str]]:
    """(pricing model, event -> price on the Free plan, dates of announced price changes)."""
    infos = sorted(act.get("pricingInfos") or [], key=lambda p: str(p.get("startedAt", "")))
    current = [p for p in infos if (_date(p.get("startedAt")) or now) <= now]
    future = [str(p.get("startedAt", ""))[:10] for p in infos if (_date(p.get("startedAt")) or now) > now]
    info = current[-1] if current else {}
    if info.get("pricingModel") == "PRICE_PER_DATASET_ITEM":
        return info["pricingModel"], {"dataset_item": float(info.get("pricePerUnitUsd") or 0)}, future
    events = ((info.get("pricingPerEvent") or {}).get("actorChargeEvents") or {})
    prices = {}
    for name, ev in events.items():
        tiered = ((ev.get("eventTieredPricingUsd") or {}).get("FREE") or {}).get("tieredEventPriceUsd")
        price = tiered if tiered is not None else ev.get("eventPriceUsd")
        if isinstance(price, (int, float)):
            prices[name] = float(price)
    return info.get("pricingModel"), prices, future


def evaluate(spec: dict, act: dict, build: dict, inputs: list[dict], cfg: dict,
             now: datetime | None = None) -> tuple[dict[str, Any], list[Finding], int]:
    """(facts, findings, inputs checked) for one actor."""
    now = now or datetime.now(UTC)
    findings: list[Finding] = []
    stats = act.get("stats") or {}
    runs = stats.get("publicActorRunStats30Days") or {}
    total = int(runs.get("TOTAL") or 0)
    success = (runs.get("SUCCEEDED") or 0) / total if total else None
    built = _date(((act.get("taggedBuilds") or {}).get("latest") or {}).get("finishedAt"))
    rating, reviews = act.get("stats", {}).get("actorReviewRating"), int(stats.get("actorReviewCount") or 0)
    facts = {"success_30d": success, "runs_30d": total, "users_30d": stats.get("totalUsers30Days"),
             "last_build": built.date().isoformat() if built else None,
             "rating": round(rating, 2) if isinstance(rating, (int, float)) else None, "reviews": reviews}

    if act.get("isDeprecated"):
        findings.append(Finding(FAIL, "deprecated by its author"))
    if success is None:
        findings.append(Finding(WARN, "no public runs in the last 30 days"))
    else:
        if success < cfg["min_success_30d"]:
            findings.append(Finding(WARN, f"success {success:.1%} is below {cfg['min_success_30d']:.0%}"))
        if spec.get("success_30d") is not None and success < spec["success_30d"] - cfg["max_success_drop"]:
            findings.append(Finding(WARN, f"success fell from {spec['success_30d']:.1%} (catalog) to {success:.1%}"))
        if total < cfg["min_runs_30d"]:
            findings.append(Finding(WARN, f"only {total} runs in 30 days"))
    if (stats.get("totalUsers30Days") or 0) < cfg["min_users_30d"]:
        findings.append(Finding(WARN, f"only {stats.get('totalUsers30Days') or 0} users in 30 days"))
    if built and (now - built).days > cfg["max_days_since_build"]:
        findings.append(Finding(WARN, f"no new build for {(now - built).days} days"))
    if facts["rating"] is not None and reviews >= cfg["min_reviews"] and facts["rating"] < cfg["min_rating"]:
        findings.append(Finding(WARN, f"rating {facts['rating']} from {reviews} reviews"))

    model, prices, future = _live_prices(act, now)
    if model not in ("PAY_PER_EVENT", "PRICE_PER_DATASET_ITEM"):
        findings.append(Finding(FAIL, f"pricing model is {model or 'unknown'} (rental or paid plan: not usable)"))
    ours = {**(spec.get("price_usd") or {}), **(spec.get("addons_per_item") or {})}
    for key, value in ours.items():
        if isinstance(value, (int, float)) and not any(abs(value - p) < 1e-9 for p in prices.values()):
            findings.append(Finding(WARN, f"catalog price {key} = {value} is not a live price now"))
    if future:
        findings.append(Finding(WARN, f"price change announced from {', '.join(future)}"))

    schema, checked = input_schema(build), 0
    if not schema:
        findings.append(Finding(WARN, "input schema not readable"))
    else:
        problems: dict[str, None] = {}
        for run_input in inputs:
            checked += 1
            problems.update(dict.fromkeys(check_input(run_input, schema)))
        findings += [Finding(FAIL, p) for p in problems]
    if not inputs:
        findings.append(Finding(WARN, "no tool call reached this actor: its inputs were not checked"))
    return facts, findings, checked


# --------------------------------------------------------------------------
# Fetch + run
# --------------------------------------------------------------------------

def fetch(http: httpx.Client, actor_id: str) -> tuple[dict, dict]:
    """(actor, default build) from the public Apify API. No token is ever sent."""
    path = API + actor_id.replace("/", "~")
    act = http.get(path, timeout=TIMEOUT)
    act.raise_for_status()
    build = http.get(path + "/builds/default", timeout=TIMEOUT)
    build.raise_for_status()
    return act.json().get("data") or {}, build.json().get("data") or {}


def run(get: Callable[[str], tuple[dict, dict]] | None = None) -> list[ActorReport]:
    cfg = load_yaml("catalog")["health_check"]
    inputs = sent_inputs()
    reports, fetched = [], {}
    with httpx.Client(headers={"User-Agent": "ctxpack-actor-check"}) as http:
        for role, spec in catalog_actors():
            report = ActorReport(spec["id"], role)
            try:
                if spec["id"] not in fetched:  # one actor can fill two roles (X posts and replies)
                    fetched[spec["id"]] = get(spec["id"]) if get else fetch(http, spec["id"])
                act, build = fetched[spec["id"]]
            except Exception as exc:  # network or HTTP error: say which, never a URL or message
                status = getattr(getattr(exc, "response", None), "status_code", None)
                report.findings.append(Finding(FAIL, f"could not read the actor ({type(exc).__name__}"
                                                     f"{f', HTTP {status}' if status else ''})"))
            else:
                report.facts, report.findings, report.inputs_checked = evaluate(
                    spec, act, build, inputs.get(spec["id"], []), cfg)
            reports.append(report)
    return reports
