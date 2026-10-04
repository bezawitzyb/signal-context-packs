"""Agent tools; they own the data and enforce every limit from modes.yaml (B8b-d).

Every collection tool: limits check -> run (or 24 h cache of cleaned
drafts) -> cleaning chain -> store -> SHORT summary. The agent never sees
raw corpora: only counts, new terms and at most 3 wrapped samples.
A tool past a limit returns {"status": "limit_reached", ...} and does nothing.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from ctxpack.collect import apify, web
from ctxpack.collect.cleaning import Deduper, Draft, clean, make_draft, words
from ctxpack.collect.mappers import MAPPERS, map_items, sanitize_for_fixture
from ctxpack.collect.relevance import BriefContext
from ctxpack.config import load_yaml
from ctxpack.llm.client import untrusted
from ctxpack.schemas.document import Document
from ctxpack.schemas.enums import Platform


def _modes() -> dict[str, Any]:
    return load_yaml("modes")


def _catalog() -> dict[str, Any]:
    return load_yaml("catalog")


# --------------------------------------------------------------------------
# Run state
# --------------------------------------------------------------------------

Store = Callable[[list[Document], list[str]], None]


def db_store(run_id: str) -> Store:
    def store(docs: list[Document], replaced: list[str]) -> None:
        from ctxpack import db

        if replaced:
            db.delete_documents(replaced)
        if docs:
            db.save_documents(docs)
    return store


@dataclass
class RunContext:
    run_id: str
    mode: str
    brief: BriefContext
    window_days: int
    store: Store
    record: bool = False                      # save sanitised fixtures (CLI --record)
    brief_text: str = ""                      # the brief as typed (fake mode finds its transcript by it)
    started: float = field(default_factory=time.monotonic)
    calls: int = 0
    items: int = 0
    apify_usd: float = 0.0
    llm_usd: float = 0.0
    unit_items: Counter = field(default_factory=Counter)
    unit_stats: dict[str, Counter] = field(default_factory=dict)
    rq_counts: Counter = field(default_factory=Counter)
    relevant_total: int = 0
    deduper: Deduper = field(default_factory=Deduper)
    templates: set = field(default_factory=set)
    platform_scores: dict[str, list[float]] = field(default_factory=dict)
    call_keys: set = field(default_factory=set)
    fetched_urls: set = field(default_factory=set)
    page_types: dict[str, str] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)
    dropped_units: set = field(default_factory=set)
    tried_units: set = field(default_factory=set)        # every unit a collection call was made for
    unit_platform: dict[str, Platform] = field(default_factory=dict)
    external_signals: list[dict] = field(default_factory=list)
    coverage_after_last_collection: bool = False
    finished: dict | None = None
    extra_secs: int = 0                                  # crash fallback after a timeout (modes.yaml agent)
    apify_unavailable: bool = False                      # Apify credit used up: no more actor calls this run
    # Reserved by calls still running, so concurrent calls cannot jointly overshoot a limit.
    pending_items: int = 0
    pending_unit_items: Counter = field(default_factory=Counter)
    pending_apify_usd: float = 0.0

    @property
    def limits(self) -> dict[str, Any]:
        return _modes()["modes"][self.mode]

    def seconds_left(self) -> int:
        return max(0, int(self.limits["collection_secs"] + self.extra_secs - (time.monotonic() - self.started)))

    def deadline(self) -> float:
        """time.monotonic() at which collection time is up."""
        return self.started + self.limits["collection_secs"] + self.extra_secs

    def calls_left(self) -> int:
        return max(0, self.limits["max_tool_calls"] - self.calls)

    def budget_left(self) -> dict[str, Any]:
        lim = self.limits
        return {"apify_usd": round(max(0.0, lim["apify_usd"] - self.apify_usd), 3),
                "llm_usd": round(max(0.0, lim["llm_usd"] - self.llm_usd), 3),
                "items": max(0, lim["item_budget"] - self.items)}

    def left(self) -> dict[str, Any]:
        return {"budget_left": self.budget_left(), "calls_left": self.calls_left(),
                "seconds_left": self.seconds_left()}


def _limit_reached(ctx: RunContext, why: str) -> dict[str, Any]:
    return {"status": "limit_reached", "reason": why, **ctx.left()}


def _general_limit(ctx: RunContext) -> str | None:
    if ctx.calls_left() <= 0:
        return "max_tool_calls reached"
    if ctx.seconds_left() <= 0:
        return "collection time is up"
    if ctx.llm_usd >= ctx.limits["llm_usd"]:
        return "llm budget spent"
    return None


NO_APIFY_CREDIT = ("apify credit for this month is used up: Reddit, TikTok, YouTube, Instagram and "
                   "Trends cannot run; use web_search and fetch_and_segment")


def min_secs(tool: str) -> int:
    """The low end of a tool's typical latency (catalog.yaml), e.g. 'usually 60-90 s' -> 60."""
    m = re.search(r"\d+", _catalog()["tool_latency"].get(tool, ""))
    return int(m.group()) if m else 0


def _time_limit(ctx: RunContext, tool: str) -> str | None:
    """A call that cannot finish in the time left is not started (it would overrun the cap)."""
    need, left = min_secs(tool), ctx.seconds_left()
    if left < need:
        return f"not enough time left for {tool} ({left} s left, it usually needs at least {need} s)"
    return None


def _item_limit(ctx: RunContext, unit: str, requested: int) -> tuple[int, str | None]:
    """Clamp a call's items to: items per call, the item budget and the unit's 30% share."""
    lim = ctx.limits
    unit_cap = int(lim["unit_share_max"] * lim["item_budget"]) - ctx.unit_items[unit] - ctx.pending_unit_items[unit]
    allowed = min(max(1, requested or lim["items_per_call_max"]), lim["items_per_call_max"],
                  lim["item_budget"] - ctx.items - ctx.pending_items, unit_cap)
    if allowed <= 0:
        return 0, "unit share reached" if unit_cap <= 0 else "item budget spent"
    return allowed, None


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

_STOP = set("""
a an and are as at be but by for from has have i if in is it its me my no not of on or our so that the
their them they this to was we were what when which who with you your just like get got can will would
de het een en van in is op te dat die niet met zijn voor er maar ook als bij aan om dan wel nog naar
ik je jij we wij ze zij hij heb hebben was waren wordt kan geen meer veel
der die das und ist nicht mit sich auf dem den des ein eine einen zu von im für es ich du wir sie er
auch aber wie bei noch nur oder so wenn man hat habe sind war
""".split())


def _new_terms(ctx: RunContext, docs: list[Document]) -> list[str]:
    seen_words = {w.casefold() for q in ctx.queries for w in words(q)}
    counts: Counter = Counter()
    for d in docs:
        if not d.is_relevant:
            continue
        toks = [w.casefold() for w in words(d.text) if not w.isdigit()]
        counts.update(t for t in toks if len(t) > 2 and t not in _STOP and t not in seen_words)
        counts.update(f"{a} {b}" for a, b in zip(toks, toks[1:])
                      if a not in _STOP and b not in _STOP and len(a) > 2 and len(b) > 2
                      and not {a, b} <= seen_words)
    n = _modes()["collection"]["new_terms_max"]
    return [t for t, c in counts.most_common(n * 3) if c >= 2][:n]


def _samples(docs: list[Document]) -> list[str]:
    cfg = _modes()["collection"]
    best = sorted((d for d in docs if d.is_relevant and not d.short_form),
                  key=lambda d: (d.relevance or 0, d.engagement_percentile or 0), reverse=True)
    return [untrusted(d.id, d.text[:cfg["sample_chars"]]) for d in best[:cfg["samples_max"]]]


def _record_docs(ctx: RunContext, docs: list[Document]) -> None:
    for d in docs:
        st = ctx.unit_stats.setdefault(d.source_unit, Counter())
        ctx.unit_platform[d.source_unit] = d.platform
        st["kept"] += 1
        if d.is_relevant:
            st["relevant"] += 1
            ctx.relevant_total += 1
            ctx.rq_counts.update(d.research_question_ids)


async def _finish_collection(ctx: RunContext, tool: str, unit_label: str, drafts: list[Draft],
                             notes: dict[str, Any]) -> dict[str, Any]:
    """Shared tail: clean -> store -> counters -> summary."""
    for d in drafts:
        ctx.unit_items[d.source_unit] += 1
        ctx.unit_stats.setdefault(d.source_unit, Counter())["collected"] += 1
    ctx.items += len(drafts)
    result = await clean(drafts, run_id=ctx.run_id, window_days=ctx.window_days, brief=ctx.brief,
                         deduper=ctx.deduper, templates=ctx.templates, platform_scores=ctx.platform_scores)
    ctx.llm_usd += result.usd
    ctx.store(result.documents, result.replaced_ids)
    _record_docs(ctx, result.documents)
    ctx.coverage_after_last_collection = False
    s = result.stats
    relevant_share = round(s["relevant"] / s["kept"], 2) if s["kept"] else 0.0
    return {
        "status": "ok", "tool": tool, "source_unit": unit_label,
        "collected": s["collected"], "kept": s["kept"], "relevant": s["relevant"],
        "relevant_share": relevant_share,
        "dropped": {k: s[k] for k in ("out_of_window", "duplicate", "spam") if s[k]},
        "new_terms": _new_terms(ctx, result.documents),
        "samples": _samples(result.documents),
        **notes, **ctx.left(),
    }


def _drafts_from_raw(platform: Platform, unit: str, raw: list[dict], fetched_at: datetime) -> list[Draft]:
    """RawPost dicts -> Drafts. The author name is hashed inside make_draft and discarded."""
    return [make_draft(platform=platform, source_unit=unit, url=p.get("url") or "", text=p["text"],
                       author=p.get("author"), date_raw=p.get("date"), fetched_at=fetched_at,
                       permalink=p.get("permalink"), community=p.get("community"),
                       thread_id=p.get("thread_id"), engagement=p.get("engagement"))
            for p in raw]


# --------------------------------------------------------------------------
# Apify collection tools
# --------------------------------------------------------------------------

_TREND_FIELDS = ("keyword", "date", "value", "geo", "type", "is_partial", "searchTerms", "searchTerm",
                 "inputUrlOrTerm", "interestOverTime_timelineData")


def _record(ctx: RunContext, result: apify.ActorResult) -> None:
    """Save a sanitised fixture (CLI --record). Trends data holds no people, only numbers."""
    if not (ctx.record and result.items):
        return
    if result.actor_id in MAPPERS:
        items = sanitize_for_fixture(result.actor_id, result.items)
    elif "trends" in result.actor_id:
        items = [{k: i[k] for k in _TREND_FIELDS if k in i} for i in result.items]
    else:
        return
    import json
    path = apify.fixture_path(result.actor_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


async def _run_source(ctx: RunContext, source: str, inputs: Callable[[dict, int], dict], limit: int,
                      timeout: int | None = None,
                      limit_for: Callable[[dict], int] | None = None) -> apify.ActorResult:
    src = _catalog()["sources"][source]
    attempts = []
    for spec in (src["actor"], src.get("fallback")):
        if spec:
            n = limit_for(spec) if limit_for else limit
            attempts.append((spec, inputs(spec, n), n))
    result = await apify.run_with_fallback(attempts, limit, timeout, deadline=ctx.deadline())
    if not limit_for:
        result.items = result.items[:limit]
    ctx.apify_unavailable |= result.status == apify.NO_CREDIT
    ctx.apify_usd += result.usd
    _record(ctx, result)
    return result


async def _run_comments(ctx: RunContext, source: str, posts: list[dict], total: int) -> apify.ActorResult | None:
    """Chained comments: only posts that HAVE comments, highest first (call_rules.chain_comments)."""
    src = _catalog()["sources"][source].get("comments")
    cfg = _modes()["collection"]
    parents = sorted((p for p in posts if (p.get("comments") or 0) > 0 and p.get("url")),
                     key=lambda p: p["comments"], reverse=True)[:cfg["chain_parent_posts_max"]]
    if not src or not parents or total <= 0 or ctx.apify_unavailable:
        return None
    urls = [p["url"] for p in parents]
    per_post = max(1, math.ceil(total / len(urls)))

    def inputs(spec: dict, limit: int) -> dict:
        return {
            "clockworks/tiktok-comments-scraper": {"postURLs": urls, "commentsPerPost": per_post},
            "apidojo/tiktok-comments-scraper": {"startUrls": urls, "maxItems": limit},
            "streamers/youtube-comments-scraper": {"startUrls": [{"url": u} for u in urls], "maxComments": per_post},
            "apidojo/youtube-comments-scraper": {"startUrls": urls, "maxItems": limit},
            "apify/instagram-comment-scraper": {"directUrls": urls, "resultsLimit": per_post},
        }[spec["id"]]

    attempts = [(spec, inputs(spec, total)) for spec in (src["actor"], src.get("fallback")) if spec]
    result = await apify.run_with_fallback(attempts, total, deadline=ctx.deadline())
    ctx.apify_unavailable |= result.status == apify.NO_CREDIT
    result.items = result.items[:total]
    result.context = {"parent_urls": urls, "parent_by_id": {str(p.get("thread_id")): p["url"] for p in parents}}
    ctx.apify_usd += result.usd
    _record(ctx, result)
    return result


async def _apify_tool(ctx: RunContext, tool: str, source: str, platform: Platform, unit: str, target: str,
                      limit: int, reason: str, search_inputs: Callable[[dict, int], dict],
                      with_comments: bool) -> dict[str, Any]:
    if why := _general_limit(ctx) or _apify_limit(ctx) or _time_limit(ctx, tool):
        return _limit_reached(ctx, why)
    if unit in ctx.dropped_units:
        return {"status": "unit_dropped", "source_unit": unit, **ctx.left()}
    key = (tool, target.casefold(), limit)
    if key in ctx.call_keys:
        return {"status": "duplicate_call", "source_unit": unit, **ctx.left()}
    limit, why = _item_limit(ctx, unit, limit)
    if why:
        return _limit_reached(ctx, why)
    src = _catalog()["sources"][source]
    expected = apify.expected_cost(src["actor"], limit)
    if ctx.apify_usd + ctx.pending_apify_usd + expected > ctx.limits["apify_usd"]:
        return _limit_reached(ctx, f"apify budget (this call ~{expected} USD)")
    ctx.call_keys.add(key)
    ctx.calls += 1
    ctx.queries.append(target)
    ctx.tried_units.add(unit)
    ctx.pending_items += limit
    ctx.pending_unit_items[unit] += limit
    ctx.pending_apify_usd += expected
    try:
        drafts, notes = await _collect_apify(ctx, tool, source, platform, unit, target, limit, search_inputs,
                                             with_comments)
    finally:
        ctx.pending_items -= limit
        ctx.pending_unit_items[unit] -= limit
        ctx.pending_apify_usd -= expected
    if ctx.apify_unavailable and not drafts:
        return _limit_reached(ctx, NO_APIFY_CREDIT)
    return await _finish_collection(ctx, tool, unit, drafts, notes)


def _apify_limit(ctx: RunContext) -> str | None:
    return NO_APIFY_CREDIT if ctx.apify_unavailable else None


async def _collect_apify(ctx: RunContext, tool: str, source: str, platform: Platform, unit: str, target: str,
                         limit: int, search_inputs: Callable[[dict, int], dict],
                         with_comments: bool) -> tuple[list[Draft], dict[str, Any]]:
    language = ",".join(ctx.brief.languages)

    cached = apify.cache_get(tool, target, language, str(limit))
    notes: dict[str, Any] = {"cached": bool(cached)}
    if cached:
        drafts = [Draft.from_cache(d) for d in cached["drafts"]]
    else:
        fetched_at = datetime.now(timezone.utc)
        posts_n = limit if not with_comments else max(1, round(limit * _modes()["collection"]["chain_posts_share"]))
        res = await _run_source(ctx, source, search_inputs, posts_n)
        raw = map_items(res.actor_id, res.items)
        notes.update(actor=res.actor_id, fallback_used=res.used_fallback)
        if not res.items:
            notes["actor_status"] = res.status
        if with_comments:
            com = await _run_comments(ctx, source, [p for p in raw if p.get("kind") == "post"], limit - len(raw))
            if com is not None:
                raw += map_items(com.actor_id, com.items, com.context)
                notes["comments_actor"] = com.actor_id
        drafts = _drafts_from_raw(platform, unit, raw[:limit], fetched_at)
        apify.cache_put(tool, target, language, {"drafts": [d.to_cache() for d in drafts]}, str(limit))
    return drafts, notes


def _cutoff(ctx: RunContext) -> str:
    return (date.today() - timedelta(days=ctx.window_days)).isoformat()


def _sub(target: str) -> str | None:
    m = re.fullmatch(r"(?:https?://(?:www\.)?reddit\.com)?/?r/([A-Za-z0-9_]+)/?", target.strip())
    return m.group(1) if m else None


# Source unit names: one function per tool, shared with the fallback (what was tried?).

def reddit_unit(target: str) -> str:
    sub = _sub(target)
    return f"reddit:r/{sub}" if sub else f"reddit:search:{target.strip().casefold()}"


def tiktok_unit(target: str) -> str:
    t = target.strip()
    return f"tiktok:#{t.lstrip('#').casefold()}" if t.startswith("#") else f"tiktok:search:{t.casefold()}"


def youtube_unit(query: str) -> str:
    q = query.strip()
    return f"youtube:{q.casefold()}" if q.startswith(("@", "https://www.youtube.com/")) else f"youtube:search:{q.casefold()}"


def instagram_unit(hashtag: str) -> str:
    return f"instagram:#{hashtag.strip().lstrip('#').casefold()}"


def web_unit(url: str) -> str:
    return "web:" + (web.urlparse(url).netloc.removeprefix("www.") or "?")


def unit_for(tool: str, args: dict[str, Any]) -> str | None:
    """The source unit a collection call works on (None for web_search, trends, coverage, finish)."""
    return {"search_reddit": lambda: reddit_unit(args.get("target", "")),
            "search_tiktok": lambda: tiktok_unit(args.get("target", "")),
            "search_youtube": lambda: youtube_unit(args.get("query", "")),
            "search_instagram": lambda: instagram_unit(args.get("hashtag", "")),
            }.get(tool, lambda: None)()


async def search_reddit(ctx: RunContext, target: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    sub = _sub(target)
    unit = reddit_unit(target)

    def inputs(spec: dict, n: int) -> dict:
        posts = max(1, round(n * _modes()["collection"]["chain_posts_share"]))
        per_post = max(1, math.ceil((n - posts) / posts))
        if spec["id"] == "harshmaur/reddit-scraper":
            base = {"crawlCommentsPerPost": True, "maxPostsCount": posts, "maxCommentsPerPost": per_post,
                    "maxCommentsCount": n - posts, "postedAfter": _cutoff(ctx), "aiAnalysis": False,
                    "includeNSFW": False}
            return {**base, "subredditUrls": [f"r/{sub}"]} if sub else \
                   {**base, "searchTerms": [target], "searchSort": "relevance"}
        base = {"maxItems": max(n, spec.get("min_items", 0)), "maxPostCount": posts, "maxComments": per_post,
                "skipComments": False, "skipUserPosts": True, "skipCommunity": True, "searchCommunities": False,
                "searchUsers": False, "includeNSFW": False, "proxy": {"useApifyProxy": True}}
        return {**base, "startUrls": [{"url": f"https://www.reddit.com/r/{sub}/"}]} if sub else \
               {**base, "searches": [target], "sort": "relevance"}

    return await _apify_tool(ctx, "search_reddit", "reddit", Platform.reddit, unit, target, limit, reason,
                             inputs, with_comments=False)


async def search_tiktok(ctx: RunContext, target: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    tag = target.strip().lstrip("#") if target.strip().startswith("#") else None
    unit = tiktok_unit(target)

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "clockworks/tiktok-scraper":
            # Hashtag pages return all-time top videos (2021 in the 2026-10-04 test) and ignore
            # oldestPostDateUnified, so hashtags go through video search with its date filter.
            period = ("PAST_MONTH" if ctx.window_days <= 30 else "LAST_3_MONTHS" if ctx.window_days <= 90
                      else "LAST_6_MONTHS")
            return {"searchQueries": [f"#{tag}" if tag else target], "resultsPerPage": n,
                    "searchSection": "/video", "videoSearchDateFilter": period}
        return {"startUrls": [f"https://www.tiktok.com/tag/{tag}"], "maxItems": n} if tag else \
               {"keywords": [target], "maxItems": n}

    return await _apify_tool(ctx, "search_tiktok", "tiktok", Platform.tiktok, unit, target, limit, reason,
                             inputs, with_comments=True)


async def search_youtube(ctx: RunContext, query: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    channel = query.strip() if query.strip().startswith(("@", "https://www.youtube.com/")) else None
    unit = youtube_unit(query)

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "streamers/youtube-scraper":
            base = {"maxResults": n, "maxResultsShorts": 0, "maxResultStreams": 0}
            url = channel if channel and channel.startswith("http") else f"https://www.youtube.com/{channel}"
            if channel:
                return {**base, "startUrls": [{"url": url}]}
            # Search mixes in videos from 2022-2025 (2026-10-04 test): use the upload-date filter.
            return {**base, "searchQueries": [query], "dateFilter": "month" if ctx.window_days <= 30 else "year"}
        return {"youtubeHandles": [channel], "maxItems": n} if channel else {"keywords": [query], "maxItems": n}

    return await _apify_tool(ctx, "search_youtube", "youtube", Platform.youtube, unit, query, limit, reason,
                             inputs, with_comments=True)


async def search_instagram(ctx: RunContext, hashtag: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    tag = hashtag.strip().lstrip("#")
    unit = instagram_unit(hashtag)

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "apify/instagram-hashtag-scraper":
            return {"hashtags": [tag], "resultsLimit": n, "resultsType": "posts"}
        return {"search": tag, "searchType": "hashtag", "resultsType": "posts", "resultsLimit": n, "searchLimit": 1}

    return await _apify_tool(ctx, "search_instagram", "instagram", Platform.instagram, unit, f"#{tag}", limit,
                             reason, inputs, with_comments=True)


# --------------------------------------------------------------------------
# Google Trends (external signal, never Documents)
# --------------------------------------------------------------------------

def _timeframe(window_days: int) -> tuple[str, str]:
    """(khadinakbar timeframe, apify timeRange) for the brief's window."""
    if window_days <= 30:
        return "today 1-m", "today 1-m"
    if window_days <= 90:
        return "today 3-m", "today 3-m"
    return "today 12-m", "today 12-m"


def trend_series(items: list[dict]) -> dict[str, list[float]]:
    """keyword -> values over time, from either actor's output."""
    series: dict[str, list[float]] = {}
    for it in items:
        if "keyword" in it and isinstance(it.get("value"), (int, float)):     # khadinakbar (flat)
            series.setdefault(it["keyword"], []).append(float(it["value"]))
        for point in it.get("interestOverTime_timelineData") or []:          # apify
            values = point.get("value") or []
            for i, term in enumerate(it.get("searchTerms") or [it.get("searchTerm") or it.get("inputUrlOrTerm", "term")]):
                if i < len(values):
                    series.setdefault(term, []).append(float(values[i]))
    return series


def trend_direction(values: list[float]) -> str:
    """rising / stable / fading: last third vs first third (code, never a model)."""
    if len(values) < 3:
        return "stable"
    k = max(1, len(values) // 3)
    first, last = sum(values[:k]) / k, sum(values[-k:]) / k
    if first == 0:
        return "rising" if last > 0 else "stable"
    change = (last - first) / first
    return "rising" if change > 0.2 else "fading" if change < -0.2 else "stable"


async def get_trends(ctx: RunContext, terms: list[str], geo: str = "", reason: str = "") -> dict[str, Any]:
    if why := _general_limit(ctx) or _apify_limit(ctx) or _time_limit(ctx, "get_trends"):
        return _limit_reached(ctx, why)
    terms = [t.strip() for t in terms if t.strip()][:5]
    key = ("get_trends", "|".join(sorted(t.casefold() for t in terms)), geo.upper())
    if not terms or key in ctx.call_keys:
        return {"status": "duplicate_call" if terms else "no_terms", **ctx.left()}
    points = _modes()["collection"]["trends_points_max"]
    src = _catalog()["sources"]["google_trends"]

    def limit_for(spec: dict) -> int:  # per-term actors bill one item per term, per-point actors per point
        return len(terms) if spec.get("bills_per") == "term" else points

    expected = apify.expected_cost(src["actor"], limit_for(src["actor"]))
    if ctx.apify_usd + expected > ctx.limits["apify_usd"]:
        return _limit_reached(ctx, f"apify budget (this call ~{expected} USD)")
    ctx.call_keys.add(key)
    ctx.calls += 1
    tf, tr = _timeframe(ctx.window_days)

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "khadinakbar/google-trends-scraper":
            return {"keywords": terms, "geo": geo.upper(), "timeframe": tf,
                    "dataTypes": ["interest_over_time"], "maxResults": n}
        return {"searchTerms": terms, "geo": geo.upper(), "timeRange": tr, "isMultiple": len(terms) > 1,
                "maxItems": n}

    res = await _run_source(ctx, "google_trends", inputs, points, _modes()["collection"]["trends_timeout_secs"],
                            limit_for)
    if res.status == apify.NO_CREDIT:
        return _limit_reached(ctx, NO_APIFY_CREDIT)
    series = trend_series(res.items)
    signal = {"terms": terms, "geo": geo.upper() or "global", "timeframe": tf,
              "series": {t: {"points": len(v), "mean": round(sum(v) / len(v), 1), "trend": trend_direction(v)}
                         for t, v in series.items() if v}}
    ctx.external_signals.append(signal)
    status = "ok" if signal["series"] else "no_data"
    return {"status": status, "tool": "get_trends", "signal": signal, "actor": res.actor_id,
            "fallback_used": res.used_fallback, **ctx.left()}


# --------------------------------------------------------------------------
# Open web
# --------------------------------------------------------------------------

async def web_search(ctx: RunContext, query: str, country: str, language: str, reason: str = "") -> dict[str, Any]:
    if why := _general_limit(ctx) or _time_limit(ctx, "web_search"):
        return _limit_reached(ctx, why)
    key = ("web_search", web.discover_key(query, country, language))
    if key in ctx.call_keys:
        return {"status": "duplicate_call", **ctx.left()}
    ctx.call_keys.add(key)
    ctx.calls += 1
    ctx.queries.append(query)
    res = await web.discover(query, country, language)
    ctx.llm_usd += res.usd
    pages = []
    for p in res.pages:
        ctx.page_types[p.url] = p.page_type
        pages.append({"url": p.url, "page_type": p.page_type, "language": p.language, "why": p.why[:160],
                      "already_fetched": p.url in ctx.fetched_urls})
    return {"status": "ok", "tool": "web_search", "pages": pages, "searches": res.searches, **ctx.left()}


async def fetch_and_segment(ctx: RunContext, urls: list[str], reason: str = "") -> dict[str, Any]:
    if why := _general_limit(ctx) or _time_limit(ctx, "fetch_and_segment"):
        return _limit_reached(ctx, why)
    max_pages = ctx.limits["web_pages_per_call_max"]
    todo, skipped = [], []
    for url in dict.fromkeys(u.strip() for u in urls if u.strip()):
        unit = web_unit(url)
        if url in ctx.fetched_urls or unit in ctx.dropped_units or len(todo) >= max_pages:
            skipped.append(url)
        elif _item_limit(ctx, unit, 1)[1]:
            skipped.append(url)
        else:
            todo.append(url)
    if not todo:
        return {"status": "nothing_to_fetch", "skipped": skipped, **ctx.left()}
    ctx.calls += 1
    ctx.fetched_urls.update(todo)
    ctx.tried_units.update(web_unit(u) for u in todo)
    gate = asyncio.Semaphore(_modes()["parallel_tool_calls_max"])
    fetched_at = datetime.now(timezone.utc)

    async def one(url: str) -> web.PageResult:
        cached = apify.cache_get("fetch_and_segment", url, "")
        if cached:
            return web.PageResult(url, [Draft.from_cache(d) for d in cached["drafts"]])
        async with gate:
            res = await web.fetch_and_segment(url, ctx.page_types.get(url, "forum"), fetched_at)
        if not res.error:
            apify.cache_put("fetch_and_segment", url, "", {"drafts": [d.to_cache() for d in res.drafts]})
        return res

    results = await asyncio.gather(*(one(u) for u in todo))
    drafts: list[Draft] = []
    pages = []
    for r in results:
        ctx.llm_usd += r.usd
        unit = web_unit(r.url)
        room, _ = _item_limit(ctx, unit, len(r.drafts) or 1)
        drafts += r.drafts[:room]
        pages.append({"url": r.url, "posts": len(r.drafts), "not_exact": r.segments_not_exact,
                      **({"error": r.error} if r.error else {})})
        if ctx.record and r._page_text:
            _record_page(r)
    units = sorted({d.source_unit for d in drafts}) or ["web"]
    summary = await _finish_collection(ctx, "fetch_and_segment", ", ".join(units), drafts, {"pages": pages})
    if skipped:
        summary["skipped"] = skipped
    return summary


def _record_page(r: web.PageResult) -> None:
    import json
    data = json.loads(web.PAGES_FIXTURE.read_text(encoding="utf-8")) if web.PAGES_FIXTURE.exists() else {}
    data[r.url] = web.sanitize_page_fixture(r)
    web.PAGES_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    web.PAGES_FIXTURE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------
# Coverage and finish (B8d)
# --------------------------------------------------------------------------

async def coverage_report(ctx: RunContext) -> dict[str, Any]:
    ctx.coverage_after_last_collection = True
    rqs = ctx.brief.research_questions
    thin = max(3, ctx.limits["min_relevant"] // max(1, len(rqs) * 4))
    per_rq = {rid: {"question": q[:120], "relevant_docs": ctx.rq_counts.get(rid, 0)} for rid, q in rqs.items()}
    units = {u: {"collected": st["collected"], "kept": st["kept"], "relevant": st["relevant"],
                 "relevant_share": round(st["relevant"] / st["kept"], 2) if st["kept"] else 0.0,
                 "share_of_item_budget": round(ctx.unit_items[u] / ctx.limits["item_budget"], 2)}
             for u, st in ctx.unit_stats.items()}
    return {"status": "ok", "relevant_total": ctx.relevant_total, "min_relevant": ctx.limits["min_relevant"],
            "research_questions": per_rq,
            "thin_research_questions": [rid for rid, v in per_rq.items() if v["relevant_docs"] < thin],
            "source_units": units, "dropped_units": sorted(ctx.dropped_units), **ctx.left()}


async def finish(ctx: RunContext, summary: str, source_verdicts: list[dict], gaps: list[str],
                 follow_up_queries: list[dict] | None = None) -> dict[str, Any]:
    problems = []
    if not ctx.coverage_after_last_collection:
        problems.append("call coverage_report after your last collection call, then finish")
    named = {}
    for v in source_verdicts or []:
        unit, verdict, why = v.get("source_unit", ""), v.get("verdict"), (v.get("reason") or "").strip()
        if verdict not in ("kept", "dropped"):
            problems.append(f"{unit}: verdict must be kept or dropped")
        if not why:
            problems.append(f"{unit}: reason must not be empty")
        named[unit] = verdict
    missing = sorted(set(ctx.unit_stats) - set(named))
    if missing:
        problems.append(f"give a verdict for every source unit used: {', '.join(missing)}")
    if not (summary or "").strip():
        problems.append("summary must not be empty")
    if problems:
        return {"status": "refused", "problems": problems}
    ctx.dropped_units |= {u for u, v in named.items() if v == "dropped"}
    follow_ups = [{"source_unit": f.get("source_unit", ""), "query": (f.get("query") or "").strip()}
                  for f in follow_up_queries or [] if (f.get("query") or "").strip()]
    ctx.finished = {"summary": summary.strip(), "source_verdicts": source_verdicts, "gaps": list(gaps or []),
                    "follow_up_queries": follow_ups}
    return {"status": "ok", "finished": True}


# --------------------------------------------------------------------------
# Definitions the agent sees, and the dispatcher
# --------------------------------------------------------------------------

def _latency(tool: str) -> str:
    return _catalog()["tool_latency"].get(tool, "")


def _reason() -> dict[str, Any]:
    return {"type": "string", "description": "One short, specific reason for this call."}


def tool_definitions() -> list[dict[str, Any]]:
    lim = _modes()["modes"]
    per_call = max(m["items_per_call_max"] for m in lim.values())
    limit = {"type": "integer", "description": f"Items wanted (posts + comments), at most {per_call}."}
    defs = [
        ("search_reddit", f"Reddit posts and comments from one subreddit (target 'r/<name>') or a search "
                          f"query. Latency {_latency('search_reddit')}.",
         {"target": {"type": "string"}, "limit": limit, "reason": _reason()}, ["target", "reason"]),
        ("search_tiktok", f"TikTok videos for a hashtag ('#tag') or query, plus comments on the most-discussed "
                          f"videos. Latency {_latency('search_tiktok')}.",
         {"target": {"type": "string"}, "limit": limit, "reason": _reason()}, ["target", "reason"]),
        ("search_youtube", f"YouTube videos for a query or a channel ('@handle'), plus comments on the "
                           f"most-discussed videos. Latency {_latency('search_youtube')}.",
         {"query": {"type": "string"}, "limit": limit, "reason": _reason()}, ["query", "reason"]),
        ("web_search", f"Find 5-15 forum, Q&A and review pages in a country and language. Stores nothing; "
                       f"follow with fetch_and_segment. Latency {_latency('web_search')}.",
         {"query": {"type": "string"}, "country": {"type": "string", "description": "ISO country code"},
          "language": {"type": "string", "description": "ISO 639-1"}, "reason": _reason()},
         ["query", "country", "language", "reason"]),
        ("fetch_and_segment", f"Read web pages and keep their visitor posts word for word. At most "
                              f"{max(m['web_pages_per_call_max'] for m in lim.values())} pages per call. "
                              f"Latency {_latency('fetch_and_segment')}.",
         {"urls": {"type": "array", "items": {"type": "string"}}, "reason": _reason()}, ["urls", "reason"]),
        ("get_trends", f"Google Trends interest over time for up to 5 terms in a country (external context, "
                       f"not audience voice). Latency {_latency('get_trends')}.",
         {"terms": {"type": "array", "items": {"type": "string"}}, "geo": {"type": "string"},
          "reason": _reason()}, ["terms", "reason"]),
        ("coverage_report", f"Relevant documents per research question and per source unit, plus budget, calls "
                            f"and time left. Call it before finish. Latency {_latency('coverage_report')}.",
         {}, []),
        ("finish", "End collection: a summary, a verdict (kept or dropped) with a reason for EVERY source unit "
                   "you used, and an honest list of gaps. Optionally propose follow-up queries inside kept "
                   "units; code uses them only if evidence is short.",
         {"summary": {"type": "string"},
          "source_verdicts": {"type": "array", "items": {"type": "object", "properties": {
              "source_unit": {"type": "string"}, "verdict": {"type": "string", "enum": ["kept", "dropped"]},
              "reason": {"type": "string"}}, "required": ["source_unit", "verdict", "reason"]}},
          "gaps": {"type": "array", "items": {"type": "string"}},
          "follow_up_queries": {"type": "array", "items": {"type": "object", "properties": {
              "source_unit": {"type": "string", "description": "A unit you marked kept."},
              "query": {"type": "string"}}, "required": ["source_unit", "query"]}}},
         ["summary", "source_verdicts", "gaps"]),
    ]
    if "instagram" in _catalog()["sources"]:
        defs.insert(3, ("search_instagram", f"Instagram posts for a hashtag, plus comments on posts that have "
                                            f"some. Latency {_latency('search_instagram')}.",
                        {"hashtag": {"type": "string"}, "limit": limit, "reason": _reason()},
                        ["hashtag", "reason"]))
    return [{"name": n, "description": d, "input_schema": {"type": "object", "properties": p, "required": r}}
            for n, d, p, r in defs]


TOOLS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "search_reddit": search_reddit, "search_tiktok": search_tiktok, "search_youtube": search_youtube,
    "search_instagram": search_instagram, "web_search": web_search, "fetch_and_segment": fetch_and_segment,
    "get_trends": get_trends, "coverage_report": coverage_report, "finish": finish,
}


async def call_tool(ctx: RunContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool by name. Unknown tools and bad arguments come back as errors, never exceptions."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"status": "error", "error": f"unknown tool {name}"}
    try:
        return await fn(ctx, **args)
    except TypeError as exc:
        return {"status": "error", "error": f"bad arguments for {name}: {exc}"}
