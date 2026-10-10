# V13 plan: RSS and Atom feeds as a source

Status: **approved 2026-10-10 and built.** Decisions: 1 `feedparser`; 2 server-side download with the URL
guard; 3 Google News search feeds feed the news hooks step; 4 one paid Quick test run. Estimates are working
hours with Claude Code, tests included. Paid calls are listed; everything else runs on fixtures (free).

Found while building: feedparser treats `str`/`bytes` input as a URL or a local file name first, so the code
always hands it an in-memory stream; some forums (Discourse) answer 404 when a page is asked for with RSS
first in `Accept`, so downloads send a browser-style `Accept`; a forum's home page often announces no feed
while its category pages do, and a page's own feed (closest path) is chosen before site-wide ones; link-only
paragraphs ("Read full topic") and `<small>` metadata are left out of post text.

## Goal of this step

Two gaps from user testing and the evals: thin evidence for B2B buyers and business owners (they talk in
niche forums more than on Reddit), and few dated posts (undated posts cap a finding at moderate). Feeds
help both at no Apify cost: many forums (Discourse, phpBB, vBulletin, XenForo), blogs with comments and
Q&A sites publish a feed of their newest threads, each with a date.

A feed is **a way to find recent threads**, not a new kind of evidence. Its items are forum posts like
the ones `fetch_and_segment` already reads, so they become `web_forum` documents and go through the same
cleaning chain, relevance check and verification.

Out of scope: news feeds as audience voice (articles are the publisher's voice, not the audience's),
feeds of social platforms that have their own tool (Reddit, YouTube, X; `web_skip_domains` already
routes them), feed subscriptions or scheduled re-reads (refreshes were dropped on 2026-10-09).

## Findings that shape the plan (current code)

1. **The server never downloads a web page itself.** `fetch_and_segment` (`collect/web.py`) asks a worker
   model to use Anthropic's server-side `web_fetch`, and code keeps only segments that are exact
   substrings of the fetched text. `httpx` is a dependency but is used only by `actor_check.py` and
   `demo_check.py` (fixed Apify and own-site URLs). A feed reader would be the **first place where
   Render downloads a URL that came from search results**, so it needs a URL guard (see Design 3).
2. Web search already returns forum pages with a `page_type` and an `estimated_date`
   (`tools.web_search`), and it nudges the agent towards recent forum, Q&A and review pages
   (`_recent_voice_page`). A feed is the natural next step from such a page.
3. Web documents are `Platform.web_forum` / `web_review` / `web_editorial`. All forum domains together
   are ONE platform (`schemas/enums.py`), so feed items need no new platform and no schema change.
4. Limits per unit (`_item_limit`, `unit_share_max`), duplicate-call keys, dropped units and the 24 h
   cache are generic in `collect/tools.py`; a new tool gets them by using the same helpers.
5. Authors are hashed in `cleaning.hash_author` (needs the salt); a feed's `<author>` / `<dc:creator>`
   must be hashed in the function that reads the feed, like every other mapper.
6. News hooks (`synthesis/news.py`) use one worker call with web search (`modes.yaml news`); an item is
   kept only when its URL came back from that search. Google News offers free search feeds per
   language and country, which could feed this step later (decision 3).

## Design

### 1. A new collection tool: `read_feed`
- Input: `site_or_feed_url` (a forum page or a feed URL) and `reason`. The site must be on a domain that
  **this run's web_search returned** (the same rule as Facebook groups found by a keyword search). Any
  other domain is refused with "use web_search first". No per-brief or per-market feed lists anywhere.
- Code finds the feed: if the URL is a page, it reads `<link rel="alternate" type="application/rss+xml">`
  or Atom from that page's HTML; it never guesses addresses beyond that one page.
- Code reads the feed, keeps items inside the run's time window (dates come with every item), maps each
  item to a `Draft` (platform `web_forum`, `source_unit = feed:<domain>`, permalink = item link, author
  hashed on the spot, HTML stripped to text) and runs `_finish_collection` - so the agent sees only the
  usual short summary ("read 30, in window 22, kept 14, 64% relevant").
- Items whose text is only a short summary (under `feeds.min_item_words`) are **not** stored as posts;
  their links are returned to the agent as `threads_to_read` for `fetch_and_segment`, which reads the
  full thread with its replies (where most of the audience's voice is) and keeps exact quotes as today.
- Every quote still links to its source page; text-fragment anchors come from the original text as now.

### 2. Limits in modes.yaml (both modes)
```yaml
feeds:
  feeds_per_call_max: 3          # Quick and Standard
  items_per_feed_max: 40         # counts towards item_budget and unit_share_max like any source
  min_item_words: 25             # shorter items become threads_to_read, not posts
  fetch_timeout_secs: 15
  max_bytes: 2000000             # a feed above this is skipped (memory stays below 400 MB)
```
`catalog.yaml` gets a `web_feeds` source (kind: web, platform: web_forum, tool: read_feed) with its
audience note, and `tool_latency.read_feed: "usually 2-10 s"`.

### 3. URL guard (new, security)
One function, used by `read_feed` only:
- `https` or `http` only, standard ports, no username or password in the URL;
- the host must resolve to public addresses only (no localhost, private, link-local or cloud metadata
  ranges), checked again after every redirect (at most 3);
- the response must look like HTML, RSS or Atom; at most `max_bytes`, with the timeout above;
- blocked sites (`web.blocked_sites()`) and `web_skip_domains` are refused as in `fetch_and_segment`.
Parsing never resolves external entities or DTDs (decision 1 picks the parser). Feed text is untrusted
data: it reaches a model only through the relevance check, inside `<untrusted_user_content>`.

### 4. Agent prompt
One short paragraph in the agent loop prompt: when web_search finds a recent forum or Q&A page, `read_feed`
on that site is a cheap way to see its newest dated threads; then read the best threads with
`fetch_and_segment`. No site names in the prompt.

### 5. Offline mode and tests
- `USE_FIXTURES`: a recorded feed fixture (`tests/fixtures/feeds/*.xml`, synthetic text, no real names).
- `--record` stores feeds already reduced to hashed, redacted drafts, never raw XML with author names.
- Tests: feed and Atom parsing; time window; author hashed and raw name never stored or logged; HTML
  stripped; short items become `threads_to_read`; domain-not-from-search refused; URL guard refuses
  private IPs, redirects to private IPs, oversize and wrong content type; item and unit limits; duplicate
  call; dropped unit never called again; cache holds only hashed, redacted items. No network in tests.

## Steps and estimates

| # | Step | Hours |
|---|---|---|
| 1 | URL guard + tests | 1.5 |
| 2 | Feed reading and parsing, feed discovery from one page, mapping to drafts (author hashing) + tests | 2.0 |
| 3 | `read_feed` tool: limits, domain rule, `threads_to_read`, cache, config + tests | 2.0 |
| 4 | Agent prompt paragraph, catalog entry, live log label, fixtures and recorded mode | 1.0 |
| 5 | README (sources list, data handling), PRD/guide notes, `export-schema` if anything changed | 0.5 |
| 6 | One paid Quick run on a B2B brief to compare with the earlier run (decision 4) | 0.5 |
| | **Total** | **about 7.5** |

## How we know it worked
- On the same B2B brief: more `web_forum` posts kept, a higher share of dated posts, and no drop in
  relevance rate compared with the run before V13.
- All tests pass offline; `demo-check --no-paid` passes; peak memory stays below 400 MB.

## Decisions for the owner
1. **Parser.** (a) `feedparser` - one small, widely used library that understands every feed variant
   (recommended); (b) `defusedxml` plus our own code for RSS and Atom (smaller, more code to maintain);
   (c) Python's built-in XML only (no new library, weakest against hostile files). Each new library
   needs your OK (CLAUDE.md).
2. **Server-side download.** Reading feeds from Render with the URL guard above (free, fast; recommended),
   or through Anthropic's `web_fetch` like web pages (no new download code, but every feed costs model
   tokens and the raw XML may not come back intact).
3. **Google News feeds for news hooks.** Add as a second, free candidate list for `news.py`, or
   leave out. Note: Google News links are Google redirect URLs, and Google's terms for these feeds are
   not clearly meant for commercial tools. **Owner: use (2026-10-10);** switch: `modes.yaml feeds.google_news`.
4. **One paid Quick test run** at the end. Expected maximum cost **$4.60** (Apify $1.80 + collection
   LLM $1.40 + analysis LLM $1.40, the hard caps in `modes.yaml`); typical $1.50-3.00.

## Results (2026-10-10, two paid Quick runs of "Heat pumps for homeowners in Germany")

| | Before V13 (featured pack) | Run 1 | Run 2 (with the feeds hint) |
|---|---|---|---|
| Cost | - | $2.31 | $2.46 (+ $0.39 to finish the pack) |
| Relevant / kept posts | 171 / 232 | 144 / 193 | 146 / 201 |
| Forum posts kept | 0 (pages too old) | 0 | 5 (hausbesitzer-forum.de, via fetch_and_segment) |
| read_feed calls | - | 0 | 0 |

- The agent never called read_feed in either run. In run 2 it read two forums' pages instead. A test by hand
  showed why that was reasonable: one forum has no feed, the other's site-wide feed was 10% relevant (newest
  posts on every subject). A category feed of a topic forum (discuss.python.org packaging) was 100% relevant.
  The hint, tool description and prompt now say: pass a sub-forum or category page about the topic, never a
  home page; skip feeds when there is none.
- Both runs ran out of Quick's analysis budget ($1.40) - not caused by V13 (the news candidates add < $0.001).
  Run 2's pack was finished with an owner-approved $1.00 extra (`pk_EhgXHmlWhKPm`, $0.39 used). Raising
  `analysis_llm_usd` for Quick is the owner's decision.
- Google News: the English category ("heat pump installation (heating)") found property ads in a German news
  search, so the search term is now the plan's core term in the market language (`news.core_term`:
  "wärmepumpe"). With the candidates first in the prompt, one check gave 4 hooks (3 from Google News); the
  prompt now also requires the model's own English line for a candidate, never the publisher's headline.
