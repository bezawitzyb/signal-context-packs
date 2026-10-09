"""Agent tools; they own the data and enforce every limit from modes.yaml (B8b-d).

Every collection tool: limits check -> run (or 24 h cache of cleaned
drafts) -> cleaning chain -> store -> SHORT summary. The agent never sees
raw corpora: only counts, new terms and at most 3 wrapped samples.
A tool past a limit returns {"status": "limit_reached", ...} and does nothing.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from ctxpack.collect import apify, web
from ctxpack.collect.cleaning import Deduper, Draft, clean, make_draft, name_like, words
from ctxpack.collect.mappers import MAPPERS, map_items, sanitize_for_fixture
from ctxpack.collect.relevance import BriefContext
from ctxpack.config import load_yaml
from ctxpack.guards import BudgetExceeded, StopRequested
from ctxpack.llm.client import untrusted
from ctxpack.schemas.document import Document
from ctxpack.schemas.enums import Platform


log = logging.getLogger(__name__)


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
    must_search: list[str] = field(default_factory=list)  # competitors the user named (V3): searched by name
    intake: dict = field(default_factory=dict)            # the user's roles, goal and channels (V3, used in V6)
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
    page_queries: dict[str, str] = field(default_factory=dict)          # url -> the web search that found it
    queries: list[str] = field(default_factory=list)
    dropped_units: set = field(default_factory=set)
    tried_units: set = field(default_factory=set)        # every unit a collection call was made for
    unit_platform: dict[str, Platform] = field(default_factory=dict)
    external_signals: list[dict] = field(default_factory=list)
    coverage_after_last_collection: bool = False
    finished: dict | None = None
    extra_secs: int = 0                                  # crash fallback after a timeout (modes.yaml agent)
    apify_unavailable: bool = False                      # Apify credit used up (or switched off): no actor calls
    apify_usd_cap: float | None = None                   # a lower Apify cap for this run than the mode's
    apify_recorded_usd: float = 0.0                      # Apify spend already written to the spend table
    blocked_domains: set = field(default_factory=set)    # sites that refused fetching (this run + remembered)
    site_failures: Counter = field(default_factory=Counter)  # domain -> pages that failed or showed no posts
    facebook_groups: dict[str, dict] = field(default_factory=dict)  # public groups search_facebook returned
    apify_by_actor: dict[str, dict[str, float]] = field(default_factory=dict)   # actor -> {runs, usd, items}
    source_failures: list[dict] = field(default_factory=list)  # actor + fallback gave nothing (V6 -> blind spot)
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
        return {"apify_usd": round(max(0.0, apify_cap(self) - self.apify_usd), 3),
                "llm_usd": round(max(0.0, lim["llm_usd"] - self.llm_usd), 3),
                "items": max(0, lim["item_budget"] - self.items)}

    def left(self) -> dict[str, Any]:
        return {"budget_left": self.budget_left(), "calls_left": self.calls_left(),
                "seconds_left": self.seconds_left()}


def _count_actor(ctx: RunContext, result: apify.ActorResult) -> None:
    """Apify spend per actor, for the run's cost breakdown."""
    row = ctx.apify_by_actor.setdefault(result.actor_id, {"runs": 0, "usd": 0.0, "items": 0})
    row["runs"] += 1
    row["usd"] += result.usd
    row["items"] += len(result.items)


def _probe_limit(ctx: RunContext, platform: Platform, unit: str, limit: int,
                 blind: bool = False) -> tuple[int, str | None]:
    """Explore small, exploit what works, per search: a new search (query, hashtag, subreddit, group) starts at
    probe_items unless its platform is already strongly relevant; a search that proved relevant gets full size.
    2026-10-09 NL rerun: a good TikTok query let an English hashtag in at full size (60 posts, 16% relevant)."""
    cfg = _modes()["collection"]
    probe, share_min = cfg["probe_items"], cfg["probe_min_relevant_share"]
    trusted, trusted_n = cfg["probe_trusted_platform_share"], cfg["probe_trusted_min_searches"]
    if limit <= probe:
        return limit, None
    if blind:
        return probe, (f"browsing a subreddit without a query returns its newest posts on every subject: limited "
                       f"to {probe} items; pass query to search inside it")
    st = ctx.unit_stats.get(unit)
    if st and st["kept"]:                        # this very search ran before: judge it on its own results
        share = st["relevant"] / st["kept"]
        if share >= share_min:
            return limit, None
        return probe, (f"this search was {share:.0%} relevant: it stays at {probe} items; sharpen it or move on")
    on_platform = [s for u, s in ctx.unit_stats.items() if ctx.unit_platform.get(u) == platform and s["kept"]]
    kept = sum(s["kept"] for s in on_platform)
    relevant = sum(s["relevant"] for s in on_platform)
    if len(on_platform) >= trusted_n and relevant / kept >= trusted:   # one good search is not enough
        return limit, None
    first = "first" if not kept else "new"
    return probe, (f"{first} {platform} search: limited to {probe} items to test it; repeat it for up to {limit} "
                   f"if at least {share_min:.0%} of its posts are relevant")


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


NO_APIFY_CREDIT = ("social sources are unavailable for this run: Reddit, TikTok, YouTube, Instagram, "
                   "LinkedIn, X, Facebook and Trends cannot run; use web_search and fetch_and_segment")


def apify_cap(ctx: RunContext) -> float:
    cap = ctx.limits["apify_usd"]
    return min(cap, ctx.apify_usd_cap) if ctx.apify_usd_cap is not None else cap


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
        "collected": s["collected"], "kept": s["kept"], "relevant": s["relevant"], "undated": s["undated"],
        "relevant_share": relevant_share,
        "dropped": {k: s[k] for k in ("out_of_window", "duplicate", "spam") if s[k]},
        "new_terms": _new_terms(ctx, result.documents),
        "samples": _samples(result.documents),
        **notes, **ctx.left(),
    }


def _drafts_from_raw(platform: Platform, unit: str, raw: list[dict], fetched_at: datetime) -> list[Draft]:
    """RawPost dicts -> Drafts. The author name is hashed inside make_draft and discarded. Names of the other
    authors in the batch are redacted from every text too (comments tag each other by name)."""
    names = name_like([p.get("author") for p in raw])
    return [make_draft(platform=platform, source_unit=unit, url=p.get("url") or "", text=p["text"],
                       author=p.get("author"), date_raw=p.get("date"), fetched_at=fetched_at,
                       permalink=p.get("permalink"), community=p.get("community"),
                       thread_id=p.get("thread_id"), engagement=p.get("engagement"), page_names=names)
            for p in raw]


# --------------------------------------------------------------------------
# Apify collection tools
# --------------------------------------------------------------------------

_TREND_FIELDS = ("keyword", "geo", "timeRange", "interestOverTime", "searchTerms", "searchTerm",
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


def _readable(result: apify.ActorResult, context: dict | None = None) -> bool:
    """At least one item our mapper (or the trends reader) can read."""
    if result.actor_id in MAPPERS:
        return bool(map_items(result.actor_id, result.items, context))
    return bool(trend_series(result.items)) if "trends" in result.actor_id else True


def _src(source: str) -> dict[str, Any]:
    """A catalog source; "facebook/groups" is the groups block of facebook (it shares facebook's comments)."""
    base, _, part = source.partition("/")
    src = _catalog()["sources"][base]
    return {**src[part], "comments": src.get("comments")} if part else src


async def _run_source(ctx: RunContext, source: str, inputs: Callable[[dict, int], dict | None], limit: int,
                      timeout: int | None = None,
                      limit_for: Callable[[dict], int] | None = None,
                      fallback_first: bool = False) -> apify.ActorResult:
    src = _src(source)
    attempts = []
    specs = (src.get("fallback"), src["actor"]) if fallback_first else (src["actor"], src.get("fallback"))
    for spec in specs:
        if spec:
            n = limit_for(spec) if limit_for else limit
            if (run_input := inputs(spec, n)) is not None:  # None: this actor cannot take this unit
                attempts.append((spec, run_input, n))
    result = await apify.run_with_fallback(attempts, limit, timeout, deadline=ctx.deadline(), usable=_readable)
    if not limit_for:
        result.items = result.items[:limit]
    ctx.apify_unavailable |= result.status == apify.NO_CREDIT
    ctx.apify_usd += result.usd
    _count_actor(ctx, result)
    _record(ctx, result)
    return result


async def _run_comments(ctx: RunContext, source: str, posts: list[dict], total: int) -> apify.ActorResult | None:
    """Chained comments: only posts that HAVE comments, highest first (call_rules.chain_comments)."""
    src = _src(source).get("comments")
    cfg = _modes()["collection"]
    parents = sorted((p for p in posts if (p.get("comments") or 0) > 0 and p.get("url")),
                     key=lambda p: p["comments"], reverse=True)[:cfg["chain_parent_posts_max"]]
    if not src or not parents or total <= 0 or ctx.apify_unavailable:
        return None
    urls = [p["url"] for p in parents]
    per_post = max(1, math.ceil(total / len(urls)))

    def inputs(spec: dict, limit: int) -> dict:
        n = max(per_post, spec.get("min_items", 0))
        return {
            "clockworks/tiktok-comments-scraper": {"postURLs": urls, "commentsPerPost": n},
            "scrapeforge/tiktok-comments-extractor": {"postURLs": urls, "commentsPerPost": n,  # 0 would mean ALL
                                                      "maxRepliesPerComment": 0},
            "streamers/youtube-comments-scraper": {"startUrls": [{"url": u} for u in urls], "maxComments": n},
            "solidcode/youtube-comments-scraper": {"startUrls": urls, "maxResults": n, "sortBy": "top",
                                                   "includeReplies": False},
            "apify/instagram-comment-scraper": {"directUrls": urls, "resultsLimit": n},
            "supreme_coder/instagram-comments-scraper": {"urls": urls, "limitPerSource": n,
                                                         "scrapeReplies": False},  # default is true
            "harvestapi/linkedin-post-comments": {"posts": urls, "maxItems": n, "scrapeReplies": False,
                                                  "profileScraperMode": "short"},
            "datadoping/linkedin-post-comments-scraper": {"posts": urls, "max_comments": n,
                                                          "sort_by": "Most relevant"},
            "xquik/x-tweet-scraper": {"mode": "replies", "replyTweetIds": [x_post_id(u) for u in urls],
                                      "maxItemsPerTarget": n, "maxItems": limit},
            "scraper_one/x-post-replies-scraper": {"postUrls": urls, "resultsLimit": n},
            # facebook: name-free post links; the date filter stays off (billed per comment), cleaning keeps
            # the window
            "apify/facebook-comments-scraper": {"startUrls": [{"url": u} for u in urls], "resultsLimit": n,
                                                "includeNestedComments": False, "viewOption": "RANKED_THREADED"},
            "thedoor/facebook-comment-scraper": {"postUrls": urls, "targetComments": n, "includeReplies": False,
                                                 "includeReactions": False},
        }[spec["id"]]

    attempts = [(spec, inputs(spec, total)) for spec in (src["actor"], src.get("fallback")) if spec]
    context = {"parent_urls": urls, "parent_by_id": {str(p.get("thread_id")): p["url"] for p in parents}}
    result = await apify.run_with_fallback(attempts, total, deadline=ctx.deadline(),
                                           usable=lambda r: _readable(r, context))
    ctx.apify_unavailable |= result.status == apify.NO_CREDIT
    result.items = result.items[:total]
    result.context = context
    ctx.apify_usd += result.usd
    _count_actor(ctx, result)
    _record(ctx, result)
    return result


async def _apify_tool(ctx: RunContext, tool: str, source: str, platform: Platform, unit: str, target: str,
                      limit: int, reason: str, search_inputs: Callable[[dict, int], dict | None],
                      with_comments: bool, fallback_first: bool = False, blind: bool = False) -> dict[str, Any]:
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
    limit, probe_note = _probe_limit(ctx, platform, unit, limit, blind)
    src = _src(source)
    expected = apify.expected_cost(src["actor"], limit)
    if ctx.apify_usd + ctx.pending_apify_usd + expected > apify_cap(ctx):
        return _limit_reached(ctx, "social-source budget for this run is used up")
    ctx.call_keys.add(key)
    ctx.calls += 1
    ctx.queries.append(target)
    ctx.tried_units.add(unit)
    ctx.pending_items += limit
    ctx.pending_unit_items[unit] += limit
    ctx.pending_apify_usd += expected
    try:
        drafts, notes = await _collect_apify(ctx, tool, source, platform, unit, target, limit, search_inputs,
                                             with_comments, fallback_first)
        for d in drafts:
            d.found_by = target
    finally:
        ctx.pending_items -= limit
        ctx.pending_unit_items[unit] -= limit
        ctx.pending_apify_usd -= expected
    if ctx.apify_unavailable and not drafts:
        return _limit_reached(ctx, NO_APIFY_CREDIT)
    if probe_note:
        notes["limited"] = probe_note
    return await _finish_collection(ctx, tool, unit, drafts, notes)


def _apify_limit(ctx: RunContext) -> str | None:
    return NO_APIFY_CREDIT if ctx.apify_unavailable else None


async def _collect_apify(ctx: RunContext, tool: str, source: str, platform: Platform, unit: str, target: str,
                         limit: int, search_inputs: Callable[[dict, int], dict | None],
                         with_comments: bool, fallback_first: bool = False) -> tuple[list[Draft], dict[str, Any]]:
    language = ",".join(ctx.brief.languages)
    extra = f"{limit}|{ctx.window_days}"   # actor date filters follow the window: never share across windows

    cached = apify.cache_get(tool, target, language, extra)
    notes: dict[str, Any] = {"cached": bool(cached)}
    groups: dict[str, dict] = {}
    if cached:
        drafts = [Draft.from_cache(d) for d in cached["drafts"]]
        groups = cached.get("groups") or {}
    else:
        fetched_at = datetime.now(timezone.utc)
        posts_n = limit if not with_comments else max(1, round(limit * _modes()["collection"]["chain_posts_share"]))
        res = await _run_source(ctx, source, search_inputs, posts_n, fallback_first=fallback_first)
        raw = map_items(res.actor_id, res.items)
        notes.update(actor=res.actor_id, fallback_used=res.used_fallback)
        if not raw:
            notes["actor_status"] = res.status
            if res.status in (apify.NO_RESULTS, "SUCCEEDED"):   # it worked and found nothing: not a blind spot
                notes["no_results"] = "this search found no posts; try other words or another place"
            elif res.status not in (apify.NO_CREDIT, apify.NO_TIME):
                ctx.source_failures.append({"source_unit": unit, "platform": str(platform), "status": res.status})
                notes["source_problem"] = (f"{platform} gave nothing ({res.status}) after its fallback; "
                                           "recorded as a blind spot - try another source")
        if with_comments:
            com = await _run_comments(ctx, source, [p for p in raw if p.get("kind") == "post"], limit - len(raw))
            if com is not None:
                raw += map_items(com.actor_id, com.items, com.context)
                notes["comments_actor"] = com.actor_id
        drafts = _drafts_from_raw(platform, unit, raw[:limit], fetched_at)
        groups = _public_groups(raw) if tool == "search_facebook" else {}
        apify.cache_put(tool, target, language, {"drafts": [d.to_cache() for d in drafts], "groups": groups}, extra)
    if groups:
        for gid, g in groups.items():
            ctx.facebook_groups.setdefault(gid, {"name": g["name"], "posts": 0})["posts"] += g["posts"]
        top = sorted(groups.items(), key=lambda kv: -kv[1]["posts"])[:_modes()["collection"]["groups_listed_max"]]
        notes["public_groups"] = [{"group": gid, "name": untrusted(f"group-{gid}", g["name"][:80]),
                                   "posts_here": g["posts"]} for gid, g in top]
    return drafts, notes


def _public_groups(raw: list[dict]) -> dict[str, dict]:
    """Public groups the search results were posted in: id -> {name, posts}."""
    out: dict[str, dict] = {}
    for p in raw:
        if (gid := p.get("group_id")):
            g = out.setdefault(gid, {"name": p.get("community") or "", "posts": 0})
            g["posts"] += 1
    return out


def _cutoff(ctx: RunContext) -> str:
    return (date.today() - timedelta(days=ctx.window_days)).isoformat()


def search_country(ctx: RunContext) -> str:
    """The brief's country for actors that search 'as in' a country - only when the brief has exactly one:
    pinning a multi-country brief to its first country would hide the others."""
    return ctx.brief.countries[0] if len(ctx.brief.countries) == 1 else ""


def search_language(ctx: RunContext) -> str:
    """The brief's main language when it is not English (YouTube relevanceLanguage); "" otherwise."""
    lang = ctx.brief.languages[0] if ctx.brief.languages else ""
    return "" if lang in ("", "en") else lang


def reddit_search_time(window_days: int) -> str:
    """The narrowest searchTime that still covers the window (harshmaur/reddit-scraper)."""
    for days, name in ((7, "week"), (31, "month"), (366, "year")):
        if window_days <= days:
            return name
    return "all"


_LOOKS_LIKE_SUB = re.compile(r"\s*(?:https?://(?:www\.)?reddit\.com)?/?r/\S", re.I)


def _sub(target: str) -> str | None:
    """The subreddit name in 'r/<name>' (letters, digits or _, up to 21), else None."""
    m = re.fullmatch(r"(?:https?://(?:www\.)?reddit\.com)?/?r/([A-Za-z0-9_]{1,21})/?", target.strip())
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


def linkedin_unit(query: str) -> str:
    return f"linkedin:search:{query.strip().casefold()}"


def x_unit(target: str) -> str:
    t = target.strip()
    return f"x:#{t.lstrip('#').casefold()}" if t.startswith("#") else f"x:search:{t.casefold()}"


def facebook_unit(query: str) -> str:
    return f"facebook:search:{query.strip().casefold()}"


def web_unit(url: str) -> str:
    return "web:" + (web.urlparse(url).netloc.removeprefix("www.") or "?")


def unit_for(tool: str, args: dict[str, Any]) -> str | None:
    """The source unit a collection call works on (None for web_search, trends, coverage, finish)."""
    return {"search_reddit": lambda: reddit_unit(args.get("target", "")),
            "search_tiktok": lambda: tiktok_unit(args.get("target", "")),
            "search_youtube": lambda: youtube_unit(args.get("query", "")),
            "search_instagram": lambda: instagram_unit(args.get("hashtag", "")),
            "search_linkedin": lambda: linkedin_unit(args.get("query", "")),
            "search_x": lambda: x_unit(args.get("target", "")),
            "search_facebook": lambda: facebook_unit(args.get("query", "")),
            "read_facebook_group": lambda: facebook_group_unit(str(args.get("group", ""))),
            }.get(tool, lambda: None)()


async def search_reddit(ctx: RunContext, target: str, limit: int = 0, reason: str = "",
                        query: str = "") -> dict[str, Any]:
    """target 'r/<name>' browses the subreddit; with `query` it searches INSIDE it (same unit);
    any other target is a Reddit-wide search."""
    sub = _sub(target)
    if not sub and _LOOKS_LIKE_SUB.match(target):  # e.g. r/wärmepumpe: was silently searched Reddit-wide
        return {"status": "refused", "error": f"'{target.strip()}' is not a valid subreddit name: Reddit names use "
                "only letters, digits and _ (up to 21 characters, e.g. r/waermepumpe). Fix the name, or search "
                "Reddit-wide with plain words", **ctx.left()}
    if not sub and query.strip():                  # a query with a Reddit-wide target: search both, never drop it
        target = f"{target.strip()} {query.strip()}"
    unit = reddit_unit(target)
    query = query.strip() if sub else ""

    def inputs(spec: dict, n: int) -> dict:
        posts = max(1, round(n * _modes()["collection"]["chain_posts_share"]))
        per_post = max(1, math.ceil((n - posts) / posts))
        if spec["id"] == "harshmaur/reddit-scraper":
            base = {"crawlCommentsPerPost": True, "maxPostsCount": posts, "maxCommentsPerPost": per_post,
                    "maxCommentsCount": n - posts, "aiAnalysis": False, "includeNSFW": False}
            # postedAfter switches searches to newest-first and ignores searchSort (actor docs, 2026-10-09).
            # Reddit-wide: relevance + searchTime (newest-first gave loosely matching posts). Inside a subreddit
            # the query and the community already keep posts on topic, and relevance + "past year" returned only
            # posts older than a 180-day window (r/de, 2026-10-09 rerun): newest-first there.
            search = {**base, "searchSort": "relevance", "searchTime": reddit_search_time(ctx.window_days)}
            if sub and query:
                return {**base, "searchTerms": [query], "withinCommunity": sub, "postedAfter": _cutoff(ctx)}
            return {**base, "subredditUrls": [f"r/{sub}"], "postedAfter": _cutoff(ctx)} if sub else \
                   {**search, "searchTerms": [target]}
        # fatihtahta: maxPosts per query, maxComments per post; extra analysis options stay off (billed)
        frame = "month" if ctx.window_days <= 31 else "year"
        base = {"maxPosts": posts, "scrapeComments": True, "maxComments": per_post, "dateFrom": _cutoff(ctx),
                "includeNsfw": False, "sentiment_analysis": False, "content_analysis": False,
                "maximize_coverage": False}
        if sub:
            return {**base, "subredditName": sub, "subredditKeywords": [query] if query else [],
                    "subredditSort": "relevance" if query else "new", "subredditTimeframe": frame}
        return {**base, "queries": [target], "sort": "relevance", "timeframe": frame}

    call_target = f"{target.strip()} {query}" if query else target   # call key, cache key, seen words
    return await _apify_tool(ctx, "search_reddit", "reddit", Platform.reddit, unit, call_target, limit, reason,
                             inputs, with_comments=False, blind=bool(sub and not query))


async def search_tiktok(ctx: RunContext, target: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    tag = target.strip().lstrip("#") if target.strip().startswith("#") else None
    unit = tiktok_unit(target)
    country = search_country(ctx)

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "clockworks/tiktok-scraper":
            # Hashtag pages return all-time top videos (2021 in the 2026-10-04 test) and ignore
            # oldestPostDateUnified, so hashtags go through video search with its date filter.
            period = ("PAST_MONTH" if ctx.window_days <= 30 else "LAST_3_MONTHS" if ctx.window_days <= 90
                      else "LAST_6_MONTHS")
            return {"searchQueries": [f"#{tag}" if tag else target], "resultsPerPage": n,
                    "searchSection": "/video", "videoSearchDateFilter": period,
                    **({"proxyCountryCode": country} if country else {})}   # billed per video
        # novi: video search for hashtags too, so publishTime applies; limit is soft (code counts items)
        period = ("MONTH" if ctx.window_days <= 30 else "THREE_MONTH" if ctx.window_days <= 90 else "SIX_MONTH")
        # region defaults to GB: always send one (the first market country for a multi-country brief)
        region = country or (ctx.brief.countries[0] if ctx.brief.countries else "")
        return {"type": "SEARCH", "keyword": f"#{tag}" if tag else target, "limit": n, "publishTime": period,
                "sortType": 0, **({"region": region} if region else {})}

    return await _apify_tool(ctx, "search_tiktok", "tiktok", Platform.tiktok, unit, target, limit, reason,
                             inputs, with_comments=True)


async def search_youtube(ctx: RunContext, query: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    channel = query.strip() if query.strip().startswith(("@", "https://www.youtube.com/")) else None
    unit = youtube_unit(query)
    country, language = search_country(ctx), search_language(ctx)
    # The primary has no region or language input (worldwide, mostly English results); for a non-English
    # single-country brief the fallback, which takes both, goes first. Channels: the primary only.
    local_first = bool(country and language and not channel)

    def inputs(spec: dict, n: int) -> dict | None:
        if spec["id"] == "streamers/youtube-scraper":
            base = {"maxResults": n, "maxResultsShorts": 0, "maxResultStreams": 0}
            url = channel if channel and channel.startswith("http") else f"https://www.youtube.com/{channel}"
            if channel:
                return {**base, "startUrls": [{"url": url}]}
            # Search mixes in videos from 2022-2025 (2026-10-04 test): use the upload-date filter.
            return {**base, "searchQueries": [query], "dateFilter": "month" if ctx.window_days <= 30 else "year"}
        if channel:  # grow_media searches only: a channel unit has no fallback
            return None
        return {"q": query, "maxResults": n, "useFilters": True, "order": "relevance",
                "publishedAfter": f"{_cutoff(ctx)}T00:00:00Z",
                **({"regionCode": country} if country else {}),
                **({"relevanceLanguage": language} if language else {})}

    return await _apify_tool(ctx, "search_youtube", "youtube", Platform.youtube, unit, query, limit, reason,
                             inputs, with_comments=True, fallback_first=local_first)


async def search_instagram(ctx: RunContext, hashtag: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    tag = hashtag.strip().lstrip("#")
    unit = instagram_unit(hashtag)

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "apify/instagram-hashtag-scraper":
            return {"hashtags": [tag], "resultsLimit": n, "resultsType": "posts"}
        # top posts: they have comments to chain (the primary's newest posts often have none)
        return {"hashtags": [tag], "feed_type": "top", "resultsLimit": n}

    return await _apify_tool(ctx, "search_instagram", "instagram", Platform.instagram, unit, f"#{tag}", limit,
                             reason, inputs, with_comments=True)


# Keyword search only (PRD DH1, DH8): never a person, profile, company page, group, event or message.
_LINKEDIN_PRIVATE = re.compile(r"linkedin\.com/|^\s*(?:https?://|www\.)|/(?:in|groups?|messaging|events)/", re.I)


def linkedin_period(window_days: int, actor_id: str) -> str:
    """The narrowest date filter that still covers the window (cleaning drops anything older)."""
    if actor_id == "datadoping/linkedin-posts-search-scraper":
        return "past-week" if window_days <= 7 else "past-month"   # no longer option: cleaning keeps the window
    for days, name in ((1, "24h"), (7, "week"), (31, "month"), (92, "3months"), (183, "6months")):
        if window_days <= days:
            return name
    return "year"


async def search_linkedin(ctx: RunContext, query: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    """LinkedIn posts for a keyword query, plus comments on posts that have some (V6).

    Content visible to any logged-in user; no session of ours. Evidence gets requires_login.
    """
    if _LINKEDIN_PRIVATE.search(query) or not query.strip():
        return {"status": "refused", "error": "search_linkedin takes keywords only - never a profile, person, "
                "company page, group, event or message link (private or personal content is never collected)",
                **ctx.left()}
    unit = linkedin_unit(query)

    def inputs(spec: dict, n: int) -> dict:
        period = linkedin_period(ctx.window_days, spec["id"])
        if spec["id"] == "harvestapi/linkedin-post-search":
            return {"searchQueries": [query], "maxPosts": n, "postedLimit": period, "sortBy": "relevance",
                    "scrapeComments": False, "scrapeReactions": False, "profileScraperMode": "short"}
        return {"keywords": [query], "max_posts": max(n, spec.get("min_items", 0)), "sort_by": "relevance",
                "date_filter": period}

    return await _apify_tool(ctx, "search_linkedin", "linkedin", Platform.linkedin, unit, query, limit, reason,
                             inputs, with_comments=True)


# Keywords or a hashtag only: never a person, profile, list, community or a search scoped to an account.
_X_PRIVATE = re.compile(r"(?:twitter|x)\.com/|^\s*(?:https?://|www\.)|(?<![\w])@\w|"
                        r"\b(?:from|to|list|filter:follows|conversation_id):", re.I)
_X_ID = re.compile(r"/status(?:es)?/(\d+)")


def x_post_id(url: str) -> str:
    m = _X_ID.search(url or "")
    return m.group(1) if m else ""


async def search_x(ctx: RunContext, target: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    """Public X (Twitter) posts for keywords or a '#hashtag', plus replies to posts that have some."""
    if _X_PRIVATE.search(target) or not target.strip():
        return {"status": "refused", "error": "search_x takes keywords or a #hashtag only - never a person, "
                "@handle, profile, list or community link", **ctx.left()}
    unit = x_unit(target)
    query = target.strip()

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "xquik/x-tweet-scraper":
            lang = ctx.brief.languages[0] if len(ctx.brief.languages) == 1 else None
            return {"searchTerms": [query], "maxItems": n, "queryType": "Top", "since": _cutoff(ctx),
                    **({"lang": lang} if lang else {})}
        return {"query": query, "searchType": "latest", "resultsCount": n, "timeWindow": ctx.window_days}

    return await _apify_tool(ctx, "search_x", "x", Platform.x, unit, query, limit, reason, inputs,
                             with_comments=True)


# Keywords only (2026-10-09): never a person, profile, page, named group, event or link.
_FB_PRIVATE = re.compile(r"(?:facebook|fb)\.(?:com|me)/|^\s*(?:https?://|www\.)|(?<![\w])@\w", re.I)


async def search_facebook(ctx: RunContext, query: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    """Public Facebook posts for a keyword query (mostly from PUBLIC groups), plus comments on posts that
    have some. No session of ours; links are rebuilt as facebook.com/<post id>."""
    if _FB_PRIVATE.search(query) or not query.strip():
        return {"status": "refused", "error": "search_facebook takes keywords only - never a person, profile, "
                "page, group, event or link (private or personal content is never collected)", **ctx.left()}
    unit = facebook_unit(query)
    q = query.strip()

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "scrapeforge/facebook-search-posts":
            return {"query": q, "search_type": "posts", "max_results": n, "start_date": _cutoff(ctx)}
        return {"query": q, "resultsCount": n, "searchType": "top", "startDate": _cutoff(ctx)}

    return await _apify_tool(ctx, "search_facebook", "facebook", Platform.facebook, unit, q, limit, reason,
                             inputs, with_comments=True)


def facebook_group_unit(group: str) -> str:
    return f"facebook:group:{group.strip()}"


async def read_facebook_group(ctx: RunContext, group: str, limit: int = 0, reason: str = "") -> dict[str, Any]:
    """Newest posts of a PUBLIC Facebook group, plus comments on posts that have some. Only a group that
    search_facebook returned in THIS run (owner's decision 2026-10-09): never a group named by the agent, a page
    or a profile."""
    gid = str(group).strip()
    if gid not in ctx.facebook_groups:
        return {"status": "refused", "error": "read_facebook_group only reads a public group that search_facebook "
                "listed under public_groups in this run - pass its group number exactly as listed",
                **({"groups_found": sorted(ctx.facebook_groups)} if ctx.facebook_groups else {}), **ctx.left()}
    url = f"https://www.facebook.com/groups/{gid}/"

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "apify/facebook-groups-scraper":   # its date filter is billed per post: newest first
            return {"startUrls": [{"url": url}], "resultsLimit": n, "viewOption": "CHRONOLOGICAL"}
        return {"startUrls": [{"url": url}], "maxItems": n, "viewOption": "CHRONOLOGICAL",
                "onlyPostsNewerThan": _cutoff(ctx), "includeComments": False, "fetchAllComments": False}

    return await _apify_tool(ctx, "read_facebook_group", "facebook/groups", Platform.facebook,
                             facebook_group_unit(gid), url, limit, reason, inputs, with_comments=True)


# --------------------------------------------------------------------------
# Google Trends (external signal, never Documents)
# --------------------------------------------------------------------------

def _timeframe(window_days: int) -> str:
    """timeRange for the brief's window (scrapesage's values; see _apify_time_range for apify's)."""
    if window_days <= 30:
        return "today 1-m"
    if window_days <= 90:
        return "today 3-m"
    return "today 12-m"


def _apify_time_range(time_range: str) -> str:
    """apify/google-trends-scraper has no 'today 12-m': its empty value means the past 12 months
    (input schema checked 2026-10-09; the API refuses any value outside its list)."""
    return "" if time_range == "today 12-m" else time_range


def trend_series(items: list[dict]) -> dict[str, list[float]]:
    """keyword -> values over time, from either actor's output."""
    series: dict[str, list[float]] = {}
    for it in items:
        for point in it.get("interestOverTime") or []:                        # scrapesage (one item per term)
            if isinstance(point.get("value"), (int, float)) and it.get("keyword"):
                series.setdefault(it["keyword"], []).append(float(point["value"]))
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
    if ctx.apify_usd + expected > apify_cap(ctx):
        return _limit_reached(ctx, "social-source budget for this run is used up")
    ctx.call_keys.add(key)
    ctx.calls += 1
    tf = tr = _timeframe(ctx.window_days)

    def inputs(spec: dict, n: int) -> dict:
        if spec["id"] == "scrapesage/google-trends-scraper":  # interest over time only: fewer types = cheaper
            return {"mode": "keywords", "searchTerms": terms, "geo": geo.upper(), "timeRange": tr,
                    "dataTypes": ["interestOverTime"], "maxItems": n}
        return {"searchTerms": terms, "geo": geo.upper(), "timeRange": _apify_time_range(tr), "isMultiple": len(terms) > 1,
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
    ctx.blocked_domains |= set(web.blocked_sites())
    skip = list(web.skip_domains())                          # platforms with their own tool, login walls
    blocked = (skip + sorted(ctx.blocked_domains - set(skip)))[:_modes()["collection"]["blocked_sites_max"]]
    res = await web.discover(query, country, language, blocked)
    ctx.llm_usd += res.usd
    pages, hidden = [], 0
    for p in res.pages:
        if web.domain_of(p.url) in ctx.blocked_domains or web.skipped(p.url):  # never offer one search returned
            hidden += 1
            continue
        ctx.page_types[p.url] = p.page_type
        ctx.page_queries.setdefault(p.url, query)
        pages.append({"url": p.url, "page_type": p.page_type, "language": p.language, "why": p.why[:160],
                      **({"estimated_date": p.estimated_date[:40]} if p.estimated_date else {}),
                      "already_fetched": p.url in ctx.fetched_urls})
    hint = {} if any(_recent_voice_page(p, ctx) for p in pages) else {"hint": (
        "no recent forum, Q&A or review page in these results: try ONE more web_search with other words - the "
        "local word for forum or experiences, or a known local forum or review site of this market (site:...) - "
        "before moving on")}
    return {"status": "ok", "tool": "web_search", "pages": pages, "searches": res.searches,
            "oldest_wanted": _cutoff(ctx), **hint,
            **({"blocked_sites_hidden": hidden} if hidden else {}),
            **({"unlisted_pages_dropped": res.unlisted} if res.unlisted else {}), **ctx.left()}


def _recent_voice_page(page: dict, ctx: RunContext) -> bool:
    """A forum / Q&A / review page not known to be older than the window (2026-10-09 NL rerun: one web search
    found only a 2011 thread and blog posts, and the agent never tried again)."""
    if page["page_type"] not in ("forum", "qa", "review") or page.get("already_fetched"):
        return False
    if not page.get("estimated_date"):
        return True
    from ctxpack.collect.cleaning import parse_date
    from ctxpack.schemas.enums import DatePrecision

    day, precision = parse_date(page["estimated_date"], datetime.now(timezone.utc))
    if day is None:
        return True
    if precision == DatePrecision.year:      # "2026": the page may be from any day of that year
        day = day.replace(month=12, day=31)
    elif precision == DatePrecision.month:
        day = day.replace(day=28)
    return day.isoformat() >= _cutoff(ctx)


async def fetch_and_segment(ctx: RunContext, urls: list[str], reason: str = "") -> dict[str, Any]:
    if why := _general_limit(ctx) or _time_limit(ctx, "fetch_and_segment"):
        return _limit_reached(ctx, why)
    max_pages = ctx.limits["web_pages_per_call_max"]
    ctx.blocked_domains |= set(web.blocked_sites())
    todo, skipped, blocked, platform = [], [], [], {}
    for url in dict.fromkeys(u.strip() for u in urls if u.strip()):
        unit = web_unit(url)
        if instead := web.skipped(url):
            platform[url] = f"use {instead}" if instead.startswith("search_") else instead
        elif web.domain_of(url) in ctx.blocked_domains:
            blocked.append(url)
        elif url in ctx.fetched_urls or unit in ctx.dropped_units or len(todo) >= max_pages:
            skipped.append(url)
        elif _item_limit(ctx, unit, 1)[1]:
            skipped.append(url)
        else:
            todo.append(url)
    note = {"blocked_sites": sorted({web.domain_of(u) for u in blocked}),
            "blocked_note": "these sites refuse fetching; choose other sites"} if blocked else {}
    if platform:
        note["not_read_here"] = platform                     # e.g. a reddit thread: search_reddit reads it
    if not todo:
        return {"status": "nothing_to_fetch", "skipped": skipped, **note, **ctx.left()}
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
            try:
                res = await web.fetch_and_segment(url, ctx.page_types.get(url, "forum"), fetched_at)
            except (BudgetExceeded, StopRequested):
                raise
            except Exception as exc:  # one page the model could not split never loses the other pages
                log.warning("fetch_and_segment %s failed: %s", web.domain_of(url), type(exc).__name__)
                return web.PageResult(url, error=web.SEGMENT_FAILED)
        if not res.error:
            apify.cache_put("fetch_and_segment", url, "", {"drafts": [d.to_cache() for d in res.drafts]})
        return res

    results = await asyncio.gather(*(one(u) for u in todo))
    newly_blocked = {web.domain_of(r.url) for r in results if r.error in web.BLOCKED_ERRORS}
    web.remember_blocked(newly_blocked)
    ctx.site_failures.update(web.domain_of(r.url) for r in results
                             if r.error in web.SOFT_ERRORS or (not r.error and not r.drafts))
    failing = {d for d, n in ctx.site_failures.items()
               if n >= _modes()["collection"]["site_failures_max"]} - ctx.blocked_domains
    if newly_blocked or failing:
        ctx.blocked_domains |= newly_blocked | failing
        note = {"blocked_sites": sorted(set(note.get("blocked_sites", [])) | newly_blocked | failing),
                "blocked_note": "these sites refuse fetching or show no readable posts; choose other sites"}
    drafts: list[Draft] = []
    pages = []
    for r in results:
        ctx.llm_usd += r.usd
        unit = web_unit(r.url)
        room, _ = _item_limit(ctx, unit, len(r.drafts) or 1)
        for d in r.drafts[:room]:
            d.found_by = ctx.page_queries.get(r.url)
        drafts += r.drafts[:room]
        pages.append({"url": r.url, "posts": len(r.drafts), "not_exact": r.segments_not_exact,
                      **({"error": r.error} if r.error else {})})
        if ctx.record and r._page_text:
            _record_page(r)
    units = sorted({d.source_unit for d in drafts}) or ["web"]
    summary = await _finish_collection(ctx, "fetch_and_segment", ", ".join(units), drafts, {"pages": pages, **note})
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
    unsearched = [c for c in ctx.must_search if not any(c.casefold() in q.casefold() for q in ctx.queries)]
    if unsearched and ctx.calls_left() > 0 and ctx.seconds_left() > 0:
        problems.append("search every competitor the user named, by name, before you finish: " + ", ".join(unsearched))
    if not (summary or "").strip():
        problems.append("summary must not be empty")
    if problems:
        return {"status": "refused", "problems": problems}
    ctx.dropped_units |= {u for u, v in named.items() if v == "dropped"}
    follow_ups = [{"source_unit": f.get("source_unit", ""), "query": (f.get("query") or "").strip()}
                  for f in follow_up_queries or [] if (f.get("query") or "").strip()]
    gaps = list(gaps or []) + [f"Not searched (limits reached): {c}, named by the user" for c in unsearched]
    ctx.finished = {"summary": summary.strip(), "source_verdicts": source_verdicts, "gaps": gaps,
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
        ("search_reddit", f"Reddit posts and comments: from one subreddit (target 'r/<name>'), searched inside "
                          f"that subreddit when you give a query, or from a Reddit-wide search (target = the "
                          f"query). Latency {_latency('search_reddit')}.",
         {"target": {"type": "string"}, "limit": limit, "reason": _reason(),
          "query": {"type": "string", "description": "With an 'r/<name>' target: search inside that subreddit. "
                    "Always use it for broad subreddits (country, city, general); without it you get the "
                    "newest posts on every subject."}},
         ["target", "reason"]),
        ("search_tiktok", f"TikTok videos for a hashtag ('#tag') or query, plus comments on the most-discussed "
                          f"videos. Latency {_latency('search_tiktok')}.",
         {"target": {"type": "string"}, "limit": limit, "reason": _reason()}, ["target", "reason"]),
        ("search_youtube", f"YouTube videos for a query or a channel ('@handle'), plus comments on the "
                           f"most-discussed videos. Latency {_latency('search_youtube')}.",
         {"query": {"type": "string"}, "limit": limit, "reason": _reason()}, ["query", "reason"]),
        ("web_search", f"Find 5-15 forum, Q&A and review pages in a country and language, each with its "
                       f"estimated date when one is visible. Stores nothing; follow with fetch_and_segment, and "
                       f"skip pages dated before oldest_wanted (their posts are dropped as out of window). "
                       f"Never returns social platforms that have their own tool (Reddit, TikTok, YouTube, "
                       f"Instagram, LinkedIn, X) or login-walled sites: use their tools instead. "
                       f"Latency {_latency('web_search')}.",
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
    if "facebook" in _catalog()["sources"]:
        defs.insert(3, ("search_facebook", f"Facebook public posts for a keyword query - mostly from public "
                                           f"groups (parents, homeowners, local and hobby communities, people "
                                           f"35+) - plus comments on posts that have some. Keywords only - never "
                                           f"a person, profile, page or group. Latency "
                                           f"{_latency('search_facebook')}.",
                        {"query": {"type": "string"}, "limit": limit, "reason": _reason()}, ["query", "reason"]))
        if _catalog()["sources"]["facebook"].get("groups"):
            defs.insert(4, ("read_facebook_group", f"Newest posts of ONE public Facebook group, plus comments on "
                                                   f"posts that have some. Only a group that search_facebook "
                                                   f"listed under public_groups in this run (pass its number); "
                                                   f"use it when a group holds a lot of relevant talk. Never a "
                                                   f"page, profile or any other group. Latency "
                                                   f"{_latency('read_facebook_group')}.",
                            {"group": {"type": "string", "description": "The group number from public_groups."},
                             "limit": limit, "reason": _reason()}, ["group", "reason"]))
    if "x" in _catalog()["sources"]:
        defs.insert(3, ("search_x", f"X (Twitter) posts for keywords or a '#hashtag' (real-time reactions, "
                                    f"complaints aimed at brands, news and fandom talk), plus replies to posts "
                                    f"that have some. Keywords only - never a person, @handle or profile. "
                                    f"Latency {_latency('search_x')}.",
                        {"target": {"type": "string"}, "limit": limit, "reason": _reason()},
                        ["target", "reason"]))
    if "linkedin" in _catalog()["sources"]:
        defs.insert(3, ("search_linkedin", f"LinkedIn posts for a keyword query (professional and B2B "
                                           f"discussion), plus comments on posts that have some. Keywords only - "
                                           f"never a person, profile, group or company page. Readers may need "
                                           f"to log in to open these posts. Latency {_latency('search_linkedin')}.",
                        {"query": {"type": "string"}, "limit": limit, "reason": _reason()}, ["query", "reason"]))
    if "instagram" in _catalog()["sources"]:
        defs.insert(3, ("search_instagram", f"Instagram posts for a hashtag, plus comments on posts that have "
                                            f"some. Latency {_latency('search_instagram')}.",
                        {"hashtag": {"type": "string"}, "limit": limit, "reason": _reason()},
                        ["hashtag", "reason"]))
    return [{"name": n, "description": d, "input_schema": {"type": "object", "properties": p, "required": r}}
            for n, d, p, r in defs]


TOOLS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "search_reddit": search_reddit, "search_tiktok": search_tiktok, "search_youtube": search_youtube,
    "search_instagram": search_instagram, "search_linkedin": search_linkedin, "search_x": search_x,
    "search_facebook": search_facebook, "read_facebook_group": read_facebook_group,
    "web_search": web_search, "fetch_and_segment": fetch_and_segment,
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
