"""Open-web collection with Anthropic's server tools (guide Step 1.6, F4-3, F4-4).

discover(): worker + web_search -> 5-15 URLs with page type. Nothing stored.
fetch_and_segment(): worker + web_fetch per page -> segments. Code reads the
fetched text from the tool-result block and keeps ONLY segments that are
exact substrings of it. Authors are hashed in the same function that
receives them (make_draft). Quote anchors come from the ORIGINAL text,
before redaction, and never contain PII (PRD DH12).
USE_FIXTURES=true replays tests/fixtures/tools/web_*.json (no network).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote, urlparse

from pydantic import BaseModel, Field

from ctxpack.collect.apify import FIXTURE_DIR
from ctxpack.collect.cleaning import Draft, make_draft, redact
from ctxpack.config import get_settings, load_yaml
from ctxpack.llm.client import load_prompt, structured, untrusted
from ctxpack.schemas.enums import Platform

BLOCKED_ERRORS = {"url_not_allowed"}   # the site refuses Anthropic's fetcher: retrying never helps
# Bot walls, rate limits and JavaScript-only pages: maybe temporary, so the site is skipped for the
# rest of the run only (after modes.yaml site_failures_max), never remembered across runs.
SOFT_ERRORS = {"url_not_accessible", "too_many_requests", "unavailable", "not_text", "unsupported_content_type"}
DISCOVER_FIXTURE = FIXTURE_DIR / "web_discover.json"
PAGES_FIXTURE = FIXTURE_DIR / "web_pages.json"

PAGE_PLATFORM = {"forum": Platform.web_forum, "qa": Platform.web_forum,
                 "review": Platform.web_review, "article": Platform.web_editorial}


class FoundPage(BaseModel):
    url: str
    page_type: Literal["forum", "qa", "review", "article"]
    language: str
    why: str
    estimated_date: str | None = None


class Discovery(BaseModel):
    pages: list[FoundPage] = Field(default_factory=list)


class Segment(BaseModel):
    """One visitor post. Short posts come as `text`; long ones as `start` + `end` words, and
    code cuts the exact text out of the page (fewer output tokens, quotes always exact)."""
    text: str | None = Field(default=None, description="The whole post, exactly as on the page (short posts).")
    start: str | None = Field(default=None, description="Long posts: the first words, exactly as on the page.")
    end: str | None = Field(default=None, description="Long posts: the last words, exactly as on the page.")
    author: str | None = None
    date: str | None = None
    likes: float | None = None
    rating: float | None = None
    position: int = 0


class Segmentation(BaseModel):
    segments: list[Segment] = Field(default_factory=list)


@dataclass
class DiscoverResult:
    pages: list[FoundPage]
    usd: float = 0.0
    searches: int = 0
    unlisted: int = 0          # pages the model named that no search returned (dropped, never fetched)


@dataclass
class PageResult:
    url: str
    drafts: list[Draft] = field(default_factory=list)
    usd: float = 0.0
    segments_returned: int = 0
    segments_not_exact: int = 0
    error: str | None = None
    # only for recording a sanitised fixture; never stored or logged
    _page_text: str | None = field(default=None, repr=False)
    _segments: list[Segment] = field(default_factory=list, repr=False)


def _load(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# --------------------------------------------------------------------------
# Sites that refuse fetching (remembered in DATA_DIR, never committed)
# --------------------------------------------------------------------------

def domain_of(url: str) -> str:
    return urlparse(url if "//" in url else f"https://{url}").netloc.removeprefix("www.").casefold()


def _blocked_file():
    return get_settings().data_path / "blocked_sites.json"


def blocked_sites() -> dict[str, str]:
    """domain -> date first refused, for the last blocked_site_days. Empty in fixture mode."""
    if get_settings().use_fixtures or not _blocked_file().exists():
        return {}
    days = load_yaml("modes")["collection"]["blocked_site_days"]
    cutoff = (datetime.now().date().toordinal()) - days
    try:
        data = json.loads(_blocked_file().read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {d: day for d, day in data.items() if datetime.fromisoformat(day).date().toordinal() >= cutoff}


def remember_blocked(domains: set[str]) -> None:
    if get_settings().use_fixtures or not domains:
        return
    data = blocked_sites()
    today = datetime.now().date().isoformat()
    for d in domains:
        data.setdefault(d, today)
    _blocked_file().parent.mkdir(parents=True, exist_ok=True)
    _blocked_file().write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")


def discover_key(query: str, country: str, language: str) -> str:
    return f"{query.casefold()}|{country.upper()}|{language.lower()}"


async def discover(query: str, country: str, language: str, blocked: list[str] | None = None) -> DiscoverResult:
    """blocked: domains web search must not return (sites that refuse fetching)."""
    if get_settings().use_fixtures:
        data = _load(DISCOVER_FIXTURE).get(discover_key(query, country, language), {"pages": []})
        return DiscoverResult(Discovery.model_validate(data).pages)
    user = f"Query: {query}\nCountry: {country}\nLanguage: {language}\nKind of pages: forum, Q&A and review pages"
    res = await structured(
        "worker", load_prompt("web_discover"), user, Discovery, "record_pages",
        description="Record the pages found.", max_tokens=4096, server_tools=["web_search"],
        server_tool_options={"web_search": {"max_uses": load_yaml("modes")["collection"]["web_search_max_uses"],
                                            **({"blocked_domains": blocked} if blocked else {})}},
    )
    found = search_results(res.blocks)
    pages, seen, unlisted = [], set(), 0
    for p in res.data.pages:  # http(s) only, no duplicates, only pages a search really returned
        if urlparse(p.url).scheme not in ("http", "https") or p.url in seen:
            continue
        if (key := _url_key(p.url)) not in found and not get_settings().llm_fake:  # fake answers have no blocks
            unlisted += 1
            continue
        seen.add(p.url)
        pages.append(p if p.estimated_date or not found.get(key) else p.model_copy(update={"estimated_date": found[key]}))
    return DiscoverResult(pages, res.usd, res.web_searches, unlisted)


def _url_key(url: str) -> str:
    """The same page whatever its scheme, www., fragment or trailing slash."""
    u = urlparse(url.strip())
    return f"{u.netloc.removeprefix('www.').casefold()}{u.path.rstrip('/')}" + (f"?{u.query}" if u.query else "")


def search_results(blocks: list[Any]) -> dict[str, str | None]:
    """url key -> page_age for every result in the web_search_tool_result blocks."""
    found: dict[str, str | None] = {}
    for block in blocks:
        data = block.model_dump() if hasattr(block, "model_dump") else block
        if data.get("type") != "web_search_tool_result" or not isinstance(data.get("content"), list):
            continue
        for r in data["content"]:
            if isinstance(r, dict) and r.get("url"):
                found.setdefault(_url_key(r["url"]), r.get("page_age"))
    return found


# --------------------------------------------------------------------------
# Exact substrings and quote anchors
# --------------------------------------------------------------------------

def locate(segment: str, page: str) -> str | None:
    """The segment as it appears in the page (exact, or whitespace-tolerant). None if absent."""
    segment = segment.strip()
    if not segment:
        return None
    if segment in page:
        return segment
    parts = segment.split()
    match = re.search(r"\s+".join(map(re.escape, parts)), page)
    return match.group(0) if match else None


_MARKUP = re.compile(r"[\[\]()*_#>|`<]|https?:|www\.")
_TOKEN = re.compile(r"\S+")


def _anchor_ok(window: str, page: str, names: list[str]) -> bool:
    low = window.casefold()
    return (redact(window, names)[1] is False
            and not _MARKUP.search(window)
            and not any(n and n in low for n in names)
            and page.casefold().count(low) == 1)


def choose_anchors(original: str, page: str, authors: list[str | None], n_words: int) -> tuple[str | None, str | None]:
    """Start/end words for a #:~:text= link: from the original text, unique on the page, no PII.

    Windows that redaction would change (emails, phones, handles), that
    contain an author name or markup, or that are not unique are skipped.
    """
    names = [a.casefold().lstrip("@") for a in authors if a]
    toks = [m for m in _TOKEN.finditer(original)]
    if not toks:
        return None, None

    def window(i: int, j: int) -> str:
        return original[toks[i].start():toks[j - 1].end()]

    start = end = None
    for size in range(n_words, n_words + 5):
        for i in range(0, max(1, len(toks) - size + 1)):
            if i + size > len(toks):
                break
            w = window(i, i + size)
            if _anchor_ok(w, page, names):
                start, start_end_tok = w, i + size
                break
        if start:
            break
    if not start:
        return None, None
    for size in range(n_words, n_words + 5):
        for j in range(len(toks), start_end_tok + size - 1, -1):
            w = window(j - size, j)
            if j - size >= start_end_tok and _anchor_ok(w, page, names):
                end = w
                break
        if end:
            break
    return start, end


def text_fragment_url(url: str, start: str | None, end: str | None) -> str:
    """https://page#:~:text=start,end (Chrome scrolls to and highlights the post)."""
    def enc(s: str) -> str:
        return quote(" ".join(s.split()), safe="").replace("-", "%2D")

    base = url.split("#")[0]
    if not start:
        return base
    return f"{base}#:~:text={enc(start)}" + (f",{enc(end)}" if end else "")


# --------------------------------------------------------------------------
# Pointer segments: start/end words -> the exact post
# --------------------------------------------------------------------------

def _phrase_matches(phrase: str, page: str) -> list[re.Match]:
    parts = phrase.split()
    return list(re.finditer(r"\s+".join(map(re.escape, parts)), page)) if parts else []


def resolve_pointer(seg: Segment, page: str) -> str | None:
    """The post from its start words to its end words - only if BOTH appear exactly once on
    the page, in that order, within segment_max_chars. Otherwise None (copied in full instead)."""
    starts, ends = _phrase_matches(seg.start or "", page), _phrase_matches(seg.end or "", page)
    if len(starts) != 1 or len(ends) != 1:
        return None
    a, b = starts[0], ends[0]
    if b.start() < a.start() or b.end() - a.start() > load_yaml("modes")["collection"]["segment_max_chars"]:
        return None
    return page[a.start():b.end()]


async def _copy_in_full(page_text: str, segs: list[Segment]) -> tuple[list[Segment], float]:
    """Posts whose start/end words were not unique: one worker call copies them in full from
    the text we already have (no second fetch). Metadata stays from the first answer."""
    wanted = "\n".join(f"- position {s.position}: starts with \"{s.start}\", ends with \"{s.end}\"" for s in segs)
    user = (f"Posts to copy:\n{wanted}\n\nThe page:\n" + untrusted("page", page_text))
    res = await structured("worker", load_prompt("web_segment_copy"), user, Segmentation, "record_segments",
                           description="Record the listed posts in full.", max_tokens=8000)
    by_position = {s.position: s for s in res.data.segments if s.text}
    return [s.model_copy(update={"text": by_position[s.position].text}) for s in segs
            if s.position in by_position], res.usd


async def resolve_segments(page_text: str, segs: list[Segment]) -> tuple[list[Segment], float, int]:
    """Every segment with its text: short posts as given, pointers cut from the page, and the
    ones that could not be cut safely copied in full. Returns (segments, usd, copied)."""
    done, missing = [], []
    for s in segs:
        if s.text:
            done.append(s)
        elif s.start and s.end and (span := resolve_pointer(s, page_text)):
            done.append(s.model_copy(update={"text": span}))
        else:
            missing.append(s)
    usd = 0.0
    if missing:
        copied, usd = await _copy_in_full(page_text, missing)
        done += copied
    return sorted(done, key=lambda s: s.position), usd, len(missing)


# --------------------------------------------------------------------------
# Fetch + segment
# --------------------------------------------------------------------------

def _fetched_text(blocks: list[Any]) -> tuple[str | None, str | None]:
    """(page text, error code) from the web_fetch_tool_result block."""
    for block in blocks:
        data = block.model_dump() if hasattr(block, "model_dump") else block
        if data.get("type") != "web_fetch_tool_result":
            continue
        content = data.get("content") or {}
        if content.get("type") == "web_fetch_tool_error" or "error_code" in content:
            return None, content.get("error_code", "fetch_error")
        source = ((content.get("content") or {}).get("source") or {})
        if source.get("type") == "text" or isinstance(source.get("data"), str) and source.get("media_type", "").startswith("text"):
            return source.get("data"), None
        return None, "not_text"
    return None, "no_fetch_result"


def build_drafts(url: str, page_type: str, page_text: str, segments: list[Segment],
                 fetched_at: datetime, salt: str | None = None) -> tuple[list[Draft], int]:
    """Exact segments -> Drafts. Author names are hashed here and go no further."""
    n_words = load_yaml("modes")["collection"]["anchor_words"]
    authors = [s.author for s in segments]
    domain = urlparse(url).netloc.removeprefix("www.")
    drafts, not_exact = [], 0
    for seg in segments:
        original = locate(seg.text or "", page_text)
        if original is None:
            not_exact += 1
            continue
        start, end = choose_anchors(original, page_text, authors, n_words)
        drafts.append(make_draft(
            platform=PAGE_PLATFORM.get(page_type, Platform.web_forum), source_unit=f"web:{domain}",
            url=url, text=original, author=seg.author, date_raw=seg.date, fetched_at=fetched_at, salt=salt,
            community=domain, thread_id=url.split("#")[0],
            engagement={k: v for k, v in (("likes", seg.likes), ("rating", seg.rating)) if v is not None},
            fragment_anchor_start=start, fragment_anchor_end=end,
            page_names=[a for a in authors if a],  # quoted names of other posters are redacted too
        ))
    return drafts, not_exact


async def fetch_and_segment(url: str, page_type: str, fetched_at: datetime) -> PageResult:
    """One worker call: web_fetch the page, then record its posts as exact substrings."""
    if get_settings().use_fixtures:
        page = _load(PAGES_FIXTURE).get(url)
        if not page:
            return PageResult(url, error="no_fixture")
        segs = Segmentation.model_validate({"segments": page["segments"]}).segments
        drafts, not_exact = build_drafts(url, page_type, page["page_text"], segs, fetched_at)
        return PageResult(url, drafts, 0.0, len(segs), not_exact)

    res = await structured(
        "worker", load_prompt("web_segment"), f"Page to fetch and split: {url}", Segmentation,
        "record_segments", description="Record every visitor post on the page.", max_tokens=16000,
        # the fetch failed: nothing to split, so no retry (the model tends to explain in text instead)
        no_tool_answer=lambda blocks: {"segments": []} if _fetched_text(blocks)[0] is None else None,
        server_tools=["web_fetch"], server_tool_options={"web_fetch": {
            "max_uses": 1,
            "max_content_tokens": load_yaml("modes")["collection"]["web_fetch_max_content_tokens"]}},
    )
    page_text, error = _fetched_text(res.blocks)
    if page_text is None:
        return PageResult(url, usd=res.usd, error=error)
    returned = len(res.data.segments)
    segs, copy_usd, _ = await resolve_segments(page_text, res.data.segments)
    drafts, not_exact = build_drafts(url, page_type, page_text, segs, fetched_at)
    not_exact += returned - len(segs)              # pointers that could not be resolved or copied
    return PageResult(url, drafts, res.usd + copy_usd, returned, not_exact, _page_text=page_text, _segments=segs)


def sanitize_page_fixture(result: PageResult) -> dict:
    """Page text + segments safe for a PUBLIC repo: names -> pseudonyms, PII redacted, same in both."""
    text = result._page_text or ""
    segs = [s.model_dump() for s in result._segments]
    names: dict[str, str] = {}
    for s in segs:
        if s["author"]:
            names.setdefault(s["author"], f"user_{len(names) + 1}")
    for real, alias in sorted(names.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(real, alias)
        for s in segs:
            s["text"] = s["text"].replace(real, alias)
    for s in segs:
        s["author"] = names.get(s["author"]) if s["author"] else None
        s["text"] = redact(s["text"])[0]
    return {"page_text": posts_only(text, segs), "segments": segs}


def posts_only(page_text: str, segs: list[dict]) -> str:
    """Keep only the posts (exact substrings) - menus, sidebars and 'who is online' lists can
    hold usernames no rule recognises, so they never go into a public fixture."""
    kept = [loc for s in segs if (loc := locate(s["text"], page_text))]
    return redact("\n\n".join(kept))[0]
