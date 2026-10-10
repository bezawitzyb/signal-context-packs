"""RSS and Atom feeds (change V13, docs/07_RSS_Feeds_Plan.md).

read(): one site or feed URL -> the feed's newest items. A page URL is read once to find the feed it
announces (<link rel="alternate" type="application/rss+xml">) on the same site; no address is guessed.
Every download goes through safe_fetch (the URL guard). Item authors leave this module only inside
FeedItem.author, which the read_feed tool passes straight to make_draft (hashed there, never stored).
google_news(): Google News search feed -> dated headline candidates for the news hooks step.
USE_FIXTURES=true replays tests/fixtures/tools/web_feeds.json (no network).
"""

from __future__ import annotations

import calendar
import io
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlsplit

import feedparser

from ctxpack.collect import safe_fetch
from ctxpack.collect.apify import FIXTURE_DIR
from ctxpack.collect.cleaning import redact
from ctxpack.collect.web import domain_of
from ctxpack.config import get_settings, load_yaml

log = logging.getLogger(__name__)

FEEDS_FIXTURE = FIXTURE_DIR / "web_feeds.json"
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml")
_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "section",
          "article", "pre", "hr"}
_SKIP = {"script", "style", "blockquote", "noscript", "template", "small"}  # blockquote: ANOTHER person's words


@dataclass
class FeedItem:
    link: str
    title: str
    text: str
    author: str | None = None      # raw name: only for make_draft, which hashes it; never logged or stored
    date: str | None = None        # ISO 8601 (UTC) when the feed gives one


@dataclass
class FeedResult:
    url: str                       # what was asked for
    feed_url: str = ""
    items: list[FeedItem] = field(default_factory=list)
    error: str | None = None


def _cfg() -> dict:
    return load_yaml("modes")["feeds"]


# --------------------------------------------------------------------------
# HTML: text of an item, feed links of a page
# --------------------------------------------------------------------------

class _Text(HTMLParser):
    """Blocks of visible text. A block whose only text is a link ("Read full topic", "Continue reading") and
    <small> metadata ("12 posts - 5 participants") are feed furniture, not the person's words: left out."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[list[tuple[str, bool]]] = [[]]
        self.skip = 0
        self.link = 0

    def _break(self) -> None:
        if self.blocks[-1]:
            self.blocks.append([])

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP:
            self.skip += 1
        elif tag == "a":
            self.link += 1
        elif tag in _BLOCK:
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "a":
            self.link = max(0, self.link - 1)
        elif tag in _BLOCK:
            self._break()

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.blocks[-1].append((data, self.link > 0))

    def text(self) -> str:
        out = []
        for block in self.blocks:
            if not any(t.strip() and not in_link for t, in_link in block):
                continue                                     # empty, or nothing but a link
            line = " ".join("".join(t for t, _ in block).split())
            out.append(line)
        return "\n\n".join(out)


def html_to_text(html: str) -> str:
    """Visible text of an item's HTML, one paragraph per block; quoted replies (blockquote), link-only
    paragraphs and <small> metadata left out."""
    p = _Text()
    p.feed(html or "")
    p.close()
    return p.text().strip()


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.feeds: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower().split()
        if tag == "link" and "alternate" in rel and a.get("type", "").lower() in FEED_TYPES and a.get("href"):
            self.feeds.append(a["href"].strip())


def same_site(url: str, site: str) -> bool:
    """url is on the site, a subdomain of it, or its parent (forum.example.org <-> example.org)."""
    a, b = domain_of(url), domain_of(site)
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def _closeness(feed_url: str, page_url: str) -> int:
    """Path segments the feed shares with the page: a category page's own feed beats the site-wide ones."""
    a = [x for x in urlsplit(feed_url).path.removesuffix(".rss").removesuffix(".atom").split("/") if x]
    b = [x for x in urlsplit(page_url).path.split("/") if x]
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def feed_links(html: bytes, page_url: str) -> list[str]:
    """Feeds a page announces, on the same site, closest to the page first (then in page order)."""
    p = _Links()
    try:
        p.feed(html.decode("utf-8", errors="replace"))
    except Exception:  # broken markup: no feed found, never a crash
        return []
    out = []
    for href in p.feeds:
        url = urljoin(page_url, href)
        if url.startswith(("http://", "https://")) and same_site(url, page_url) and url not in out:
            out.append(url)
    return sorted(out, key=lambda u: -_closeness(u, page_url))


# --------------------------------------------------------------------------
# Feeds
# --------------------------------------------------------------------------

def _iso(parsed) -> str | None:
    if not parsed:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def parse(body: bytes) -> list[FeedItem]:
    """RSS or Atom bytes -> items, newest first. Never fetches or opens anything: feedparser gets a stream
    (given a str or bytes it would try it as a URL or a local FILE NAME first)."""
    d = feedparser.parse(io.BytesIO(body))
    items = []
    for e in d.entries:
        link = (e.get("link") or "").strip()
        if not link.startswith(("http://", "https://")):
            continue
        content = e.get("content") or []
        raw = content[0].get("value", "") if content else e.get("summary", "")
        author = e.get("author") or (e.get("author_detail") or {}).get("name")
        items.append(FeedItem(link=link, title=html_to_text(e.get("title", "")), text=html_to_text(raw),
                              author=author or None,
                              date=_iso(e.get("published_parsed") or e.get("updated_parsed"))))
    return sorted(items, key=lambda it: it.date or "", reverse=True)


def is_feed(fetched: safe_fetch.Fetched) -> bool:
    if fetched.content_type in FEED_TYPES:
        return True
    head = fetched.body[:600].lstrip().lower()
    return fetched.content_type in ("application/xml", "text/xml") or head.startswith(b"<?xml") and (
        b"<rss" in head or b"<feed" in head or b"<rdf" in head)


async def read(url: str, **fetch_kw) -> FeedResult:
    """One site or feed URL -> its feed's items (fixtures offline). Errors come back as text, never raised."""
    if get_settings().use_fixtures:
        entry = json.loads(FEEDS_FIXTURE.read_text(encoding="utf-8")).get(url) if FEEDS_FIXTURE.exists() else None
        if not entry:
            return FeedResult(url, error="no_fixture")
        return FeedResult(url, entry["feed_url"], [FeedItem(**it) for it in entry["items"]])
    try:
        first = await safe_fetch.fetch(url, **fetch_kw)
        if is_feed(first):
            return FeedResult(url, first.url, parse(first.body))
        if first.content_type not in ("text/html", "application/xhtml+xml"):
            return FeedResult(url, error="not a web page or feed")
        links = feed_links(first.body, first.url)
        if not links:
            return FeedResult(url, error="this page announces no feed")
        feed = await safe_fetch.fetch(links[0], **fetch_kw)
        if not same_site(feed.url, url) or not is_feed(feed):
            return FeedResult(url, links[0], error="the announced feed could not be read")
        return FeedResult(url, feed.url, parse(feed.body))
    except safe_fetch.FetchRefused as exc:
        return FeedResult(url, error=str(exc))
    except Exception as exc:  # one broken site never stops the run
        log.warning("read_feed %s failed: %s", domain_of(url), type(exc).__name__)
        return FeedResult(url, error="the feed could not be read")


def sanitize_fixture(result: FeedResult) -> dict:
    """Items safe for a PUBLIC repo: author names -> user_N everywhere, PII redacted."""
    names: dict[str, str] = {}
    for it in result.items:
        if it.author:
            names.setdefault(it.author, f"user_{len(names) + 1}")
    items = []
    for it in result.items:
        title, text = it.title, it.text
        for real, alias in sorted(names.items(), key=lambda kv: -len(kv[0])):
            title, text = title.replace(real, alias), text.replace(real, alias)
        items.append({**asdict(it), "title": redact(title)[0], "text": redact(text)[0],
                      "author": names.get(it.author) if it.author else None})
    return {"feed_url": result.feed_url, "items": items}


def record(result: FeedResult) -> None:
    data = json.loads(FEEDS_FIXTURE.read_text(encoding="utf-8")) if FEEDS_FIXTURE.exists() else {}
    data[result.url] = sanitize_fixture(result)
    FEEDS_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FEEDS_FIXTURE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------
# Google News search feeds (news hooks)
# --------------------------------------------------------------------------

def google_news_url(query: str, language: str, country: str, days: int) -> str:
    lang, cc = (language or "en").lower(), (country or "US").upper()
    return (f"https://news.google.com/rss/search?q={quote_plus(f'{query} when:{days}d')}"
            f"&hl={lang}-{cc}&gl={cc}&ceid={cc}:{lang}")


async def google_news(query: str, language: str, country: str, days: int, **fetch_kw) -> list[dict]:
    """Dated headlines for one query: [{headline, date, url, source}], newest first. [] offline or on error.
    Headlines are publishers' words: they go to the model as untrusted data, never into the pack."""
    if get_settings().use_fixtures or not query.strip():
        return []
    try:
        fetched = await safe_fetch.fetch(google_news_url(query, language, country, days), **fetch_kw)
    except Exception as exc:  # news hooks still come from web search
        log.warning("google news feed failed: %s", type(exc).__name__)
        return []
    d = feedparser.parse(io.BytesIO(fetched.body))
    out = []
    for e in d.entries:
        url, when = (e.get("link") or "").strip(), _iso(e.get("published_parsed"))
        if url.startswith("https://") and when:
            out.append({"headline": html_to_text(e.get("title", ""))[:200], "date": when[:10], "url": url,
                        "source": html_to_text((e.get("source") or {}).get("title", ""))[:80]})
    return sorted(out, key=lambda h: h["date"], reverse=True)
