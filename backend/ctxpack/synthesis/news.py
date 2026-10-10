"""News hooks and timing (change V7, PRD 6.1d).

News hooks: after collection, ONE worker call with web search (modes.yaml news.searches_max) in the
brief's languages for news, regulation, trade fairs and events from the last lookback_days to the next
lookahead_days that connect to the top themes and pain points. Since V13 the call also gets dated
headlines from Google News search feeds (free; modes.yaml feeds). Code keeps an item only when its URL was
returned by the search or by such a feed, and its date is inside that span; at most max_hooks become news_hooks (NWS-xx).
Calendar facts (budget cycles, deadlines) are kept only with such a URL too; they become timing chips,
never hooks. Nothing comes from model memory alone.

Timing: chips on channel cards, built in code - observed ones from the pack's moments (with their
evidence), external ones from news hooks and calendar facts (with their URL).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ctxpack.config import get_settings, load_yaml
from ctxpack.llm.client import LLMError, load_prompt, structured, untrusted
from ctxpack.synthesis.opportunities import _search_urls

log = logging.getLogger(__name__)

KINDS = ("news", "regulation", "event", "calendar")


class NewsOut(BaseModel):
    kind: str = "news"
    headline: str = ""
    date: str = ""
    source_url: str = ""
    why_it_matters: str = ""
    related_ids: list[str] = Field(default_factory=list)


class NewsList(BaseModel):
    items: list[NewsOut] = Field(default_factory=list)


def _cfg() -> dict:
    return load_yaml("modes")["news"]


def _fake(user: str) -> dict:
    ids = [line.split(" | ")[0] for line in user.splitlines() if " | " in line and line[:3].isalpha()]
    soon = (date.today() + timedelta(days=12)).isoformat()
    later = (date.today() + timedelta(days=40)).isoformat()
    return {"items": [
        {"kind": "event", "headline": "Fake trade fair on the topic", "date": soon,
         "source_url": "https://example.com/fair", "why_it_matters": "Fake: the audience meets there.",
         "related_ids": ids[:1]},
        {"kind": "calendar", "headline": "Fake budget deadline", "date": later,
         "source_url": "https://example.com/deadline", "why_it_matters": "Fake: budgets are set before it.",
         "related_ids": []},
        {"kind": "news", "headline": "No source, so it is dropped", "date": soon, "source_url": "",
         "why_it_matters": "Fake.", "related_ids": []},
    ]}


def _findings(s: dict) -> list[dict]:
    """Top themes and pain points (verified), strongest first."""
    out = []
    for name in ("themes", "pain_points"):
        out += sorted(s.get(name, []), key=lambda it: -it.get("confidence", {}).get("score", 0))[:4]
    return out


def keep(items: list[NewsOut], found: set[str] | None, known: set[str], today: date) -> tuple[list[dict], list[dict]]:
    """(hooks, calendar facts): URL from the search, date in the span, at most max_hooks hooks."""
    cfg = _cfg()
    start, end = today - timedelta(days=cfg["lookback_days"]), today + timedelta(days=cfg["lookahead_days"])
    hooks, calendar, seen = [], [], set()
    for it in items:
        url = it.source_url.strip()
        if urlparse(url).scheme not in ("http", "https") or (found is not None and url not in found):
            continue  # no URL (or one the search did not return): dropped, never invented
        try:
            when = date.fromisoformat(it.date.strip()[:10])
        except ValueError:
            continue
        if not (start <= when <= end) or it.kind not in KINDS or not it.headline.strip() or url in seen:
            continue
        seen.add(url)
        entry = {"kind": it.kind, "headline": it.headline.strip(), "date": when.isoformat(), "source_url": url,
                 "why_it_matters": it.why_it_matters.strip(),
                 "related_ids": [i.strip().upper() for i in it.related_ids if i.strip().upper() in known]}
        (calendar if it.kind == "calendar" else hooks).append(entry)
    hooks = sorted(hooks, key=lambda h: (not h["related_ids"], h["date"]))[:cfg["max_hooks"]]
    for n, h in enumerate(hooks, 1):
        h.update(id=f"NWS-{n:02d}", type="news_hook", claim_type="external")
    return hooks, calendar[:cfg["max_hooks"]]


def core_term(plan: dict | None, language: str) -> str:
    """The brief's core term in the market language, from the plan's starting queries (code, no model): the
    word most queries share ("wärmepumpe"), or a two-word phrase when that word nearly always comes with the
    same next word ("meal prep"). 2026-10-10: the English category ("heat pump installation (heating)") found
    property ads in a German news search; "Wärmepumpe" found 100 dated headlines."""
    from collections import Counter

    from ctxpack.collect.cleaning import words
    from ctxpack.collect.tools import _STOP

    queries = [[w.casefold() for w in words(q.get("query", ""))]
               for u in (plan or {}).get("starting_units", []) for q in u.get("queries", [])
               if q.get("language") == language]
    counts = Counter(w for q in queries for w in set(q) if len(w) > 2 and w not in _STOP and not w.isdigit())
    if not counts:
        return ""
    first = {w: sum(q.index(w) for q in queries if w in q) / counts[w] for w in counts}   # mean position
    top = max(counts, key=lambda w: (counts[w], -first[w], len(w)))     # ties: the earlier word ("heat" pump)
    nxt = Counter(q[q.index(top) + 1] for q in queries if top in q and q.index(top) + 1 < len(q))
    if nxt:
        word, n = nxt.most_common(1)[0]
        if n >= 2 and n * 2 > counts[top] and word not in _STOP:
            return f"{top} {word}"
    return top


async def feed_candidates(interp: Any, plan: dict | None = None) -> list[dict]:
    """Dated headlines from Google News search feeds (change V13, modes.yaml feeds): the core term of the plan's
    queries in the main language, then (English only) the category. Free; [] when off, offline or failing."""
    cfg, look = load_yaml("modes")["feeds"], _cfg()["lookback_days"]
    if not cfg["google_news"]:
        return []
    from ctxpack.agent.markets import primary_country
    from ctxpack.collect import feeds

    country = primary_country([m.model_dump() for m in interp.markets]) or "US"
    language = interp.languages[0] if interp.languages else "en"
    terms = [core_term(plan, language), interp.category if language == "en" else ""]
    queries = list(dict.fromkeys(q.strip() for q in terms if q and q.strip()))
    found = await asyncio.gather(*(feeds.google_news(q, language, country, look)
                                   for q in queries[:cfg["google_news_queries_max"]]))
    seen, out = set(), []
    for h in sorted((h for hs in found for h in hs), key=lambda h: h["date"], reverse=True):
        if h["url"] not in seen:
            seen.add(h["url"])
            out.append(h)
    return out[:cfg["google_news_items_max"]]


async def find(s: dict, interp: Any, today: date | None = None,
               plan: dict | None = None) -> tuple[list[dict], list[dict], float]:
    """(news hooks, calendar facts, usd). A failed search gives none (the pack says so), never a crash."""
    today = today or date.today()
    cfg = _cfg()
    findings = _findings(s)
    if not findings:
        return [], [], 0.0
    lines = "\n".join(f"{it['id']} | {it.get('label') or ''} {it['claim']}".replace("  ", " ") for it in findings)
    candidates = await feed_candidates(interp, plan)
    user = (f"Today: {today.isoformat()}\nLook from {(today - timedelta(days=cfg['lookback_days'])).isoformat()} "
            f"to {(today + timedelta(days=cfg['lookahead_days'])).isoformat()}\nTopic: {interp.topic}\n"
            f"Markets: {interp.market}\nLanguages: {', '.join(interp.languages)}\nAudience: {interp.audience}\n\n"
            "Findings (id | text):\n" + untrusted("findings", lines))
    if candidates:
        user += ("\n\nCandidate headlines from news feeds (date | headline | publisher | url):\n" + untrusted(
            "news_feeds", "\n".join(f"{h['date']} | {h['headline']} | {h['source']} | {h['url']}" for h in candidates)))
    try:
        res = await structured("worker", load_prompt("news_hooks"), user, NewsList, "record_news",
                               description="Record the dated, cited news hooks.", max_tokens=2500,
                               server_tools=["web_search"],
                               server_tool_options={"web_search": {"max_uses": cfg["searches_max"]}}, fake=_fake)
    except LLMError as exc:
        log.warning("news search failed (%s)", type(exc).__name__)
        return [], [], 0.0
    found = None if get_settings().llm_fake else _search_urls(res.blocks) | {h["url"] for h in candidates}
    known = {it["id"] for name in ("themes", "pain_points", "motivations", "objections", "tensions")
             for it in s.get(name, [])}
    hooks, calendar = keep(res.data.items, found, known, today)
    return hooks, calendar, res.usd


# Time words people use (V7 observed timing). General calendar vocabulary, never per brief or market.
TIME_WORDS: dict[str, list[str]] = {
    "Mondays": ["monday", "maandag", "montag", "lundi", "lunes", "lunedì", "poniedziałek", "måndag", "mandag"],
    "Fridays": ["friday", "vrijdag", "freitag", "vendredi", "viernes", "venerdì", "piątek", "fredag"],
    "Sundays": ["sunday", "zondag", "sonntag", "dimanche", "domingo", "domenica", "niedziela", "söndag", "søndag"],
    "Weekends": ["weekend", "weekends", "wochenende", "fin de semana", "fine settimana", "helg", "helgen"],
    "Evenings": ["evening", "evenings", "tonight", "avond", "'s avonds", "abend", "abends", "soir", "noche",
                 "sera", "wieczór", "kväll"],
    "Mornings": ["morning", "mornings", "ochtend", "morgens", "matin", "mañana", "mattina", "rano"],
    "Lunch break": ["lunch", "lunchbreak", "lunchpauze", "mittagspause", "déjeuner", "almuerzo", "pranzo"],
    "Winter": ["winter", "hiver", "invierno", "inverno", "zima", "vinter"],
    "Summer": ["summer", "zomer", "sommer", "été", "verano", "lato", "sommar"],
    "Holidays": ["christmas", "kerst", "weihnachten", "noël", "navidad", "natale", "holidays", "feestdagen"],
    "Payday": ["payday", "salaris", "gehalt", "end of the month", "eind van de maand", "monatsende"],
}
_TIME_RE = {label: re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, words)) + r")(?!\w)", re.I)
            for label, words in TIME_WORDS.items()}


def time_mentions(evidence: list[dict], platform: str) -> list[dict]:
    """Observed chips from posts on this platform that name a time (at least time_mention_min_posts)."""
    least = _cfg()["time_mention_min_posts"]
    posts = [e for e in evidence if e["platform"] == platform and not e.get("short_form")]
    chips = []
    for label, pattern in _TIME_RE.items():
        hits = [e["id"] for e in posts if pattern.search(e.get("text", ""))]
        if len(hits) >= least:
            chips.append({"label": label, "when": f"named in {len(hits)} posts",
                          "why": f"People on {platform} bring up {label.lower()} when they talk about this.",
                          "evidence_ids": hits[:3], "claim_type": "observed", "source_url": None, "item_id": None,
                          "_n": len(hits)})
    return [{k: v for k, v in c.items() if k != "_n"} for c in sorted(chips, key=lambda c: -c["_n"])]


def channel_timing(channels: list[dict], moments: list[dict], evidence: list[dict], hooks: list[dict],
                   calendar: list[dict], today: date | None = None) -> list[dict]:
    """Timing chips per channel, in code. Observed: a moment goes to the channels whose platform its
    evidence comes from (else the first channel). External: upcoming news hooks and calendar facts go to
    the first channel. Times people name in posts (weekdays, seasons, times of day) become observed chips
    on the channel of that platform. Every chip carries its receipt (evidence ids or the URL)."""
    if not channels:
        return channels
    today = today or date.today()
    most = _cfg()["timing_per_channel_max"]
    platform_of = {e["id"]: e["platform"] for e in evidence}
    out = [{**c, "timing": []} for c in channels]
    for m in moments:
        if not m.get("evidence_ids"):
            continue
        chip = {"label": m["name"], "when": m["timing"], "why": m["claim"], "evidence_ids": m["evidence_ids"][:3],
                "claim_type": "observed", "source_url": None, "item_id": m["id"]}
        platforms = {platform_of.get(e) for e in m["evidence_ids"]}
        targets = [c for c in out if c["platform"] in platforms] or out[:1]
        for c in targets:
            c["timing"].append(chip)
    for c in out:  # times people name in the posts on that channel's platform
        c["timing"] += [t for t in time_mentions(evidence, c["platform"])
                        if t["label"].casefold() not in {x["label"].casefold() for x in c["timing"]}]
    upcoming = [h for h in hooks if h["date"] >= today.isoformat()]
    for h in upcoming:
        out[0]["timing"].append({"label": h["headline"], "when": h["date"], "why": h["why_it_matters"],
                                 "evidence_ids": [], "claim_type": "external", "source_url": h["source_url"],
                                 "item_id": h["id"]})
    for f in calendar:
        out[0]["timing"].append({"label": f["headline"], "when": f["date"], "why": f["why_it_matters"],
                                 "evidence_ids": [], "claim_type": "external", "source_url": f["source_url"],
                                 "item_id": None})
    for c in out:
        c["timing"] = c["timing"][:most]
    return out
