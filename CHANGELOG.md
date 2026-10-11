# Changelog

What changed in each version of SIGNAL - Context Packs, why, and the decisions behind it. Newest first.

- **App versions** (this file) follow the pack format where they can: app 1.1 to 1.3 brought pack format
  (schema) 1.1 to 1.3. The schema's own changelog is in [docs/SCHEMA.md](docs/SCHEMA.md).
- **V1-V13** are the change steps that came after the 7-day build. Most of them came from four moderated user
  tests ([docs/USER_RESEARCH.md](docs/USER_RESEARCH.md)).
- The detailed step plans (`docs/02` and `docs/04`-`07`) were merged into this file in 1.5.0. Their full
  text is still in the git history.

---

## 1.5.0 - 2026-10-11 - New look, API guide, tidy repo

**Web app**
- A new look: Loudio colours, shadows and display font, and section cards.
- Text roles are used everywhere: serif = their words, sans = our work, mono = machine data.
- The pack page has one Summary card, related findings in the side panel, and panels that fade in on scroll.
- "Act on it" is steadier, and the generic-AI check moved into "The research".
- The home page shows a looping "how it works" strip above the brief box, with the Gen Z pack first.
- In "Their words", badges and post links never break mid-word.

**Packs**
- Culture and phrase items describe the pattern their posts share.
- New featured Gen Z pack (`pk_-ACqqf-R8ubD`), scored in the evals.

**API**
- The developer page (`/docs`) groups the endpoints by what they do: Create a pack, Read packs, Use a
  pack, Reference, Status.
- A fold-out "How to use the API" guide at the top explains each endpoint, with copy-paste examples.

**Repo**
- The docs are merged into this changelog and [docs/USER_RESEARCH.md](docs/USER_RESEARCH.md).
- The README is up to date.
- MIT licence added.
- `index.html` (in the repo root) holds the 4-slide project presentation.

## 1.4.0 - 2026-10-10 - V13 Forum feeds

**Why.** Testing and the evals showed thin evidence for B2B buyers and business owners (who talk in niche
forums more than on Reddit), and too few dated posts (undated posts cap a finding at "moderate").

**Added**
- **`read_feed` tool.** It reads the RSS or Atom feed of a forum that this run's web search returned. Any
  other site is refused ("use web_search first"), and there are no per-brief feed lists.
- **Short items are not stored as posts.** Feed items under 25 words come back as `threads_to_read`, which
  `fetch_and_segment` then reads in full.
- **Feed items are ordinary posts.** They are `web_forum` posts and pass the full cleaning chain. Authors
  are hashed where they are read. No schema change.
- **URL guard.** This is the first place the server downloads a URL it found in search results, so the
  guard allows:
  - public addresses only, checked again after every redirect (at most 3);
  - standard ports;
  - HTML, RSS or Atom only;
  - at most 2 MB and 15 seconds.
- **Google News search feeds** add dated candidates for news hooks. The search term is the plan's core term
  in the market language.
- Limits are in `modes.yaml` under `feeds`. Fixtures and tests run without a network.

**Decisions (owner, 2026-10-10)**
- Use `feedparser`.
- Feeds are downloaded on the server, through the URL guard.
- Use Google News feeds (the switch is `modes.yaml feeds.google_news`).
- Run one paid Quick test.

**Results.** Two paid Quick runs of the German heat-pump brief, $2.31 and $2.46:
- The agent never called `read_feed`. It read forum pages instead.
- Tested by hand, a forum's site-wide feed was 10% relevant and a topic category feed was 100%. The agent
  is now told to pass only sub-forum or category pages.
- Both runs ran out of Quick's $1.40 analysis budget.

**Also in this release**
- New featured packs from Quick reruns:
  - Gen Z;
  - NL snacks;
  - DE heat pumps (`pk_n-QlY1xrqi0x`).
- The Summary fits one laptop screen.
- New packs save a spread-out quote order.
- UX audit:
  - cut-off text opens;
  - short pack titles;
  - a plainer pack page.

## 1.3.0 - 2026-10-09 - V12 A pack that follows your goals - schema 1.3

**Added**
- **The pack follows your goals.** `config/goals.yaml` decides the order of the pack's sections (main goal
  first). Sections are reordered, never dropped.
- **Summary and first moves per goal.** "For your goal" blocks (`snapshot.for_goals[]`), and each first
  move names the goal it serves (`do_first[].goal`).
- **Goals reach every analysis step.** Goals, offer and key question reach relevance, extraction,
  clustering and writing. Relevance stays about the topic: goals change emphasis, not what counts as
  on-topic.
- **Brand perception analysis** (`BRP-xx`):
  - Your brand and its parent brand are searched by name.
  - Code computes the numbers:
    - mentions;
    - unprompted mentions (an awareness signal);
    - share of voice;
    - stance mix;
    - praised and criticised aspects;
    - whether people tell the brand apart from its parent.
  - 2-5 verified findings, labelled "online mentions from vocal people, not a survey".
- **Exports, the MCP digest and `get_pack_view` follow `section_order`.**

**Decisions (owner, 2026-10-09)**
- Post briefs, drafts and the calendar stay in every pack.
- At most 3 goals per pack (Quick and Standard).
- A brand name is required for brand perception.
- Schema 1.3.
- One paid Quick run of a brand-perception brief.
- **Decided not to build:**
  - a customer-journey section;
  - brand-voice word lists;
  - AI-search visibility;
  - "refresh this brief" and scheduled refreshes.

**Also in this release (2026-10-09)**
- **Asking needs a key.** "Ask this pack" needs the run key. A tester's guest key has daily limits per pack
  and per visitor.
- **Facebook as a source.** Keyword search, and public groups only when that run's keyword search found
  them.
- **Author names are redacted from post text** on every platform.
- **`actor-check`.** A free weekly check of every Apify actor's health, prices and inputs.
- **Scoring.**
  - Opus re-checks claims in the evals.
  - Mostly-undated posts cap a finding at "moderate".
- **UI/UX audit.**
  - A clearer start screen, access key, plan and run screens, and pack header.
  - A signal when the pack is ready.

## 1.2.0 - 2026-10-09 - V11 Understand the brief - schema 1.2

**Why.** In testing, briefs were vague ("booking.com"), and the tool guessed the goal. "Launching" was read
as a goal.

**Added**
- **The planning call records the five things only the user knows.** They are:
  - goals;
  - offer;
  - who;
  - markets;
  - key question (and by when).

  Each is tied to the brief's exact words. Code checks that every quote really is in the brief. Nothing is
  filled from a guess.
- **Goals and offer are always asked when missing, and cannot be skipped.** "No offer of my own" is an
  answer. Other questions are asked only when the gap would change the research. At most 4 questions.
- **Goals come from a fixed list of 8, ranked, main first:**
  - understand_audience;
  - content_plan;
  - campaign_launch;
  - positioning;
  - product_validation;
  - market_entry;
  - brand_perception;
  - sales_enablement.
- **The offer has a stage:** idea, launching, selling or no_offer.
- **One editable "Here's what I understood" box** shows where each item came from: your brief, your answer,
  assumed, or chosen in code.
- **Agents (API, MCP) must pass `goals`.** Without them, no run is created and the error lists the
  allowed goals.
- **CLI:** `--goal` (repeatable), `--offer`, `--offer-stage`.
- **A "How to write a brief" guide and template** sit next to the brief box.

**Decisions (owner, 2026-10-09)**
- `clarifying.max_questions` is raised from 3 to 4.
- `goals` is required for agents.
- The goal list and its wording.
- Schema 1.2.

## 1.1.0 - 2026-10-07/08 - V1-V10 The user-value changes - schema 1.1

Ten changes chosen from the first user tests, built in dependency order.

| Change | What it does |
|---|---|
| **V1 Never lose a run** | **Root cause found:** a loop that ended by error or timeout skipped all analysis, so no pack was saved. Now any run with enough relevant posts ends with a pack, and a failure after collection gives a partial or evidence-only pack. Below the minimum, a thin-evidence screen says why and offers one-click re-runs. Every pack and run has "Run again with these inputs", and "My packs" lists packs made in this browser. |
| **V2 Markets and languages** | Several markets per brief, with weights (`markets[]` replaces `market`). Languages are chosen in code from the markets, plus English, and capped per mode (Quick 4, Standard 6). Left-out languages are shown with the reason. A fifth eval brief: B2B in several markets. |
| **V3 Smart clarifying questions** | 0-3 questions written for this brief, with answer chips. Answers are stored in `brief.intake`. Named competitors are always searched. Agents are never asked. Changed in part by V11. |
| **V4 Condensed content** | Each section has one job, and each finding appears once, in its best place, linked from elsewhere (`related_ids`). Pain points became their own section. Each section has a "so what" line. "What performs" leads with a takeaway. Empty sections say why. |
| **V5 Opportunities you can trust** | One `opportunities[]` list replaces "white space". An opportunity is "supported" only with enough people in 2 or more communities; otherwise it is an "early signal - check before acting". A web search looks for existing solutions, and the pack never says "nobody serves this". |
| **V6 LinkedIn as a source** | Keyword post search only: never a person or profile, and no login of ours. Posts that need a login to view are marked. Every platform has a backup actor, and X joined on 2026-10-08. |
| **V7 News hooks and timing** | "Ride this now": dated news and events, each with its source link (no link means it is dropped). Timing chips on channels come from posts or a cited source, never from model memory. |
| **V8 Post briefs, drafts, calendar** | 5-8 post briefs whose key points cite posts. Full drafts of the first 3, labelled "Draft - review before posting"; unsupported claims are removed in code. A 4-week calendar as a Notion CSV (formula-safe cells). API and MCP: `get_post_briefs`, `get_calendar`. |
| **V9 Revised pack page and hand-off** | The pack page has three parts (Summary, Understand your audience, Act on it) plus The research, folded. Strength labels are in plain words. Hand-off options are described by purpose and length. "Watch how this pack was made" replays the run. |
| **V10 Ask this pack** | A read-only chat over one pack. Answers cite real posts; invented references are removed; "no evidence" is said plainly. Limits are in `modes.yaml` under `ask`. |

**Decisions (owner, 2026-10-07)**
- The plan was approved.
- LinkedIn: go ahead.
- Notion: "Copy for Notion" and CSV import only, with no Notion integration.
- All schema changes went into one version, 1.1, with a migration for older packs.

**Also in this release**
- A guest run key for testers: set only on Render, and deleting it revokes it.
- An owner-only run-costs page (`/runs`).
- Commercial messaging.

## 1.0.0 - 2026-10-06 - The 7-day build

Built in five phases by one non-technical builder with Claude Code. It was deployed on Day 1 and stayed live
throughout, on free hosting (Render Free + Neon Free + GitHub Actions and Pages). Only Anthropic and Apify
cost money.

| Day | Phase | Delivered |
|---|---|---|
| 0 | Setup | Accounts and keys, a public repo, `.env` blocked for Claude Code, gitleaks before every commit |
| 1 | 1 Foundations, tools, deploy | **Schema 1.0** and SCHEMA.md; collection tools (Reddit, TikTok, YouTube, Instagram, web search and fetch, Trends) each running the cleaning chain (hash authors, redact, dates, de-duplicate, spam, relevance); `/ping` and a keep-alive |
| 2 | 2 The agent loop | Interpret + plan; runs as jobs in Postgres with a FIFO queue; the agent loop (Sonnet, plain tool use) with limits enforced in the tools, a reason per call, up to 3 calls at once, and fallbacks; recorded transcripts for offline mode |
| 3-4 | 3 The pack engine | Extract, cluster with a membership check, counts in code, write, verify (exact-substring quotes, claim check), confidence (PRD 5.4); playbook, compliance flags, exports (JSON, Markdown, prompt block, Claude skill); REST API, live events, MCP, run key, spend cap |
| 5 | 4 The web app | Ask and plan screens, a live research view, the pack page with the evidence drawer, hand-off, print stylesheet, end-to-end and accessibility tests |
| 6-7 | 5 Evaluation and polish | Eval harness on 4 briefs and `/evals`; the demo agent (with and without a pack); sharpened tensions, opportunities and lexicon; the read-only static mirror on GitHub Pages; README and examples |

**Rules set in this build that still hold**
- The agent decides where to look; the tools own the data and enforce every limit.
- No model writes a number.
- Every quote is an exact substring of its post.
- Scraped text is untrusted data.
- The cut order kept verification, the decision log, the evidence drawer, the prompt block, MCP, the skill
  export and the run queue.
