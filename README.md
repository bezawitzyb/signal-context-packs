# SIGNAL - Context Packs

**Evidence-linked audience research for marketers and AI agents.** Give SIGNAL a brief ("Launching a snack
brand in the Netherlands"). An agent decides where the audience really talks, collects real public
posts in the right market and language, and returns a **Context Pack**: their words, pain points,
tensions, objections, opportunities, post briefs with drafts, a 4-week content calendar and a
playbook. Every claim is tied to the posts behind it and carries a confidence label in plain words.
The pack works for people (web page, Notion, print) and for agents (JSON, prompt block, a Claude
skill, MCP) - and you can ask it questions.

| | |
|---|---|
| **Live app** | https://signal-l2w5.onrender.com |
| **Read-only mirror** (works even if the live service is down) | https://bezawitzyb.github.io/signal-context-packs/ |
| **Code** | https://github.com/bezawitzyb/signal-context-packs |
| **Presentation** (4 slides; press N for speaker notes) | https://bezawitzyb.github.io/signal-context-packs/presentation.html |
| **Evaluations** | https://signal-l2w5.onrender.com/evals |
| **API for developers** | https://signal-l2w5.onrender.com/docs (open "How to use the API" at the top) |
| **Pack format** | [docs/SCHEMA.md](docs/SCHEMA.md) - JSON schema in [docs/schema/](docs/schema/) |
| **Version** | 1.5.0 (2026-10-11) - what changed: [CHANGELOG.md](CHANGELOG.md) |

## Try it

1. Open the live app and pick a **featured pack**: Gen Z and meal prep (global), launching a snack brand
   in the Netherlands, or heat pumps for homeowners in Germany. The **Summary** fits one screen: what we
   heard most clearly (with real quotes and how strong each finding is), the recommended position and
   your first moves. Open any finding to see the real posts behind it.
2. **Ask this pack** (side panel): "How do they describe their biggest pain point?" or "Turn the first
   post brief into a LinkedIn carousel outline". Answers come only from the pack, with numbered links
   to the real posts. Asking needs the access key (the run key), typed on the start page or in the Ask panel.
3. **Share & export** the pack: a half-page quick brief for ChatGPT or Claude, a brief for your AI writer, the
   full report for Notion or Docs, the content calendar as a CSV for Notion, or a Claude skill.
   **Developer view** shows the JSON an agent reads; **Watch how this pack was made** replays the
   agent's decisions.
4. **Run your own brief.** Live runs need an access key (the run key); it is never shown on screen.
   "How to write a brief" next to the box explains the five things only you know. Whatever your brief
   leaves out gets up to 4 quick questions first: always your goal and your offer, then only gaps that
   change the research (who exactly, which countries, by when).
   A Quick run takes about 7-17 minutes; one run at a time, later ones queue.
5. If the live app is slow to answer, the free server is waking up (about a minute). The
   [read-only mirror](https://bezawitzyb.github.io/signal-context-packs/) has every featured pack, the
   evidence drawer and all downloads.

## What "context" means

> Everything a smart person who just spent two weeks immersed in this audience's conversations would
> know - and that a newcomer, human or agent, would need to act credibly - packaged so it can be
> checked and reused.

Seven layers: **landscape** (themes, platform lens), **language** (lexicon, phrases, say this / not this),
**pain points, tensions and motivations** ("I want X, but Y"), **beliefs and objections**, **culture and
codes**, **moments** (with news hooks and timing per channel), and **implications** (recommended position,
do first, channel plan, opportunities, post briefs, drafts, content calendar, playbook). Plus coverage,
risks, guardrails and instructions for agents. Each finding appears once, in the section where it fits
best, with links to related findings elsewhere.

## Features

- **Never lose a run.** Any run with enough relevant posts ends with a pack, whatever fails later. Too few
  posts ends on a screen that says why, with one-click re-runs. Runs survive server restarts.
- **Understands your brief.** It reads the brief for the five things only you know (goals, offer, who,
  markets, key question). It never guesses your goal or offer: when the brief leaves them out it asks,
  then only about gaps that change the research (at most 4 questions). One editable "Here's what I understood" box shows where each item came from.
- **A pack that follows your goals.** Up to 3 goals, main first, from 8 (content plan, positioning, market
  entry, brand perception, ...). The Summary, first moves and section order follow them.
- **Brand perception.** Your brand and its parent are searched by name. Code counts mentions, unprompted
  mentions, share of voice, stance and whether people tell the two apart. Labelled "online mentions, not a survey".
- **Markets and languages.** Several markets per brief, with weights. Languages are chosen in code from those
  markets, plus English; left-out languages are shown with the reason.
- **Many sources, no login of ours.** Reddit, TikTok, YouTube, Instagram, LinkedIn, X and Facebook (keyword
  search only, never a person or profile), the open web, forum feeds and Google Trends.
- **Every finding once, with proof.** Each finding sits in its best section, linked from the others. Every
  quote is an exact copy of its post, and every claim is re-checked against its posts.
- **Opportunities you can trust.** "Supported" (enough people in enough communities) or "early signal - check
  before acting", with existing solutions found by web search.
- **Ready to act.** News hooks with source links, 5-8 post briefs, full drafts of the first 3, and a 4-week
  content calendar for Notion.
- **Ask this pack.** A chat that answers only from the pack, with numbered links to the real posts (needs the
  access key).

How each feature came about, version by version: [CHANGELOG.md](CHANGELOG.md).

## How the agent chooses sources and stays within limits

- One planning call reads the brief, records what it understood of the five inputs only the user knows
  (each tied to the brief's exact words, checked in code - never a guess), and proposes hypotheses,
  research questions and 3-6 starting sources with reasons and queries per language. A missing goal or
  offer is always asked (up to 4 questions in all); no platform may take more than half of the starting
  sources unless the plan says why.
- The **agent loop** (Claude Sonnet, plain tool use) then picks the next call itself, with a reason:
  Reddit, TikTok, YouTube, Instagram, LinkedIn, X and Facebook (keyword search only, no login of ours; on
  Facebook also public groups that a keyword search found in the same run) through
  Apify, the open web through web search and fetch, the feeds of forums that web search found
  (V13), and Google Trends. It sees only short summaries
  ("collected 50, kept 43, 84% relevant"), never raw posts. Every Apify source has a tested backup actor
  ([`catalog.yaml`](backend/ctxpack/config/catalog.yaml)); if both fail, the pack says so as a blind spot.
  A free weekly `actor-check` watches every actor's health, prices and inputs.
- **New searches start small.** The first call of a new search takes 20 posts (Quick) or 40 (Standard) and
  gets full size only once it proves on topic, so off-topic searches cost little. For a one-country brief,
  TikTok (and YouTube in non-English markets) looks for local results; English joins every brief (the
  Dutch, for example, discuss snacks in English too).
- **Tools own the data and the limits.** Every limit lives in
  [`backend/ctxpack/config/modes.yaml`](backend/ctxpack/config/modes.yaml) and is enforced in code, never
  only in a prompt. Quick allows 15 tool calls, 8 minutes and $1.80 of Apify; Standard allows 30 calls,
  10 minutes and $4.00. On top of that there is a daily spend cap.
- Inside every collection tool, before the agent hears back: normalise → hash authors → redact
  personal details → dates and time window → de-duplicate → spam → relevance check → store.
- If the loop crashes, code runs the untried starting sources. If evidence is thin, it tops up from
  sources already kept. A dropped source is never called again. An agent that finishes in the very turn
  its time runs out keeps its own source verdicts.
- Then: extraction, clustering with a membership check, **counts computed in code** (no model writes a
  number), writing, verification (every quote must be an exact substring of its post; every claim is
  re-checked against its own evidence), confidence scoring, opportunities, news hooks, playbook with
  post briefs and drafts, compliance flags, and a content calendar built in code. When two sections state
  the same finding, it stays once and keeps only posts that belong to it (checked in code on every run).

## What the output means

- [docs/SCHEMA.md](docs/SCHEMA.md) explains every field. Confidence is **strong / moderate / emerging /
  speculative** from evidence count, authors, platforms, sources, recency and the verifier; a finding whose posts are mostly undated is at most moderate. Only strong,
  observed claims confirmed by the claim check are `safe_to_assert`.
- [examples/](examples/) has the three featured packs as JSON and Markdown, each with its exported skill
  folder, and [examples/demo_agent.md](examples/demo_agent.md): an agent writing TikTok scripts with and
  without a pack, with automatic checks.
- **Skill export:** every pack downloads as a Claude skill (`SKILL.md` + `references/`), so an agent
  loads it only when the task needs it.
- **Exports:** quick brief (half a page), brief for your AI writer, full report (`brief.md`, same order as
  the page; prints with the Summary as page 1), content calendar (`content_calendar.csv`, UTF-8 for
  Notion, formula-safe cells), JSON.

## API and MCP

- **REST API** at `/api/v1`. The interactive docs at
  [signal-l2w5.onrender.com/docs](https://signal-l2w5.onrender.com/docs) group the endpoints by what they do
  (Create a pack, Read packs, Use a pack, Reference, Status). **How to use the API** at the top explains each
  endpoint with copy-paste examples. Reading packs is public; creating a pack and Ask need the run key in the
  `X-API-Key` header.
- **MCP** (read tools need no key): `claude mcp add --transport http signal https://signal-l2w5.onrender.com/mcp`.
  Tools: `list_packs`, `get_pack_view`, `get_insight`, `search_evidence`, `get_post_briefs`, `get_calendar`;
  with the run key also `create_context_pack` (agents are never asked questions, so `goals` is required,
  main goal first, e.g. `["positioning", "content_plan"]`), `get_pack_status` and `ask_pack`.
- Same data everywhere: the web page, API, MCP and every export read one `context_pack.json`, with the same
  item IDs.

## Data handling and privacy

- Only public posts. Packs carry per-pack author ids, so the same person cannot be linked across packs.
- Facebook: keyword search of public posts, and reading a **public** group only when that same run's keyword
  search found posts in it - never a group, page or profile chosen by name, never a private group, never a
  login of ours. Links are rebuilt as `facebook.com/<post number>`, so they carry no names.
- Forum feeds (V13): only feeds of sites the same run's web search returned. The server downloads them
  itself through a guard: public websites only (never local or private network addresses, checked again
  after every redirect), standard ports, web pages and feeds only, at most 2 MB and 15 seconds.
- Author names written inside a post (signatures, people tagged in comments) are redacted too.
- Author names are hashed (salted) in the function that receives them and are
  never stored, logged or sent to a model. Emails, phone numbers, handles and profile links are redacted.
- Scraped text is treated as untrusted data and is wrapped as such in every prompt.
- Collected posts expire after 30 days (checked every hour while the service runs, and at every start); a finished run's working draft and the 24 h cache go with them. Packs keep at most short excerpts (280 characters) with links.
- Quoted excerpts are for internal research and briefs only, **not for ads or other public material** -
  every pack says so. Exports note that the analysis is AI-assisted and that compliance flags are not legal advice.
- The repo is public and contains no keys: gitleaks runs on every commit, and `demo-check` also
  searches the files, the git history and the web builds for the real run key.

## Evaluation results

Five test briefs, scored on the current featured packs (details and reasons on
[/evals](https://signal-l2w5.onrender.com/evals); last scored 2026-10-11): Gen Z meal prep, snack brand NL and heat
pumps DE (all three Quick runs), a vague "snacks" brief and a brand-perception brief (Lidl Deluxe, UK, Quick). A sixth
brief (B2B, several markets) is in [`backend/evals/briefs.yaml`](backend/evals/briefs.yaml) and needs a paid
Standard run.

| Metric | Result | Target |
|---|---|---|
| Quote groundedness | **100%** | 100% |
| Claims with evidence | **100%** | 100% |
| Schema valid | **100%** | 100% |
| Source diversity | **3 of 4** briefs with ≥ 3 platforms (UK brand brief: 2) | all (vague brief exempt) |
| Plan divergence | **1.3%** of source units shared | < 50% |
| Allocation efficiency (SIMULATED) | **1.08×** an equal split | ≥ 1× |
| Peak memory | **201 MB** | < 400 MB |
| Claim entailment (Opus re-check of 30 claims per pack) | **91%** (Gen Z 100%, heat pumps 100%, NL 93%, UK 83%, vague 80%) | ≥ 95% - not met |
| Relevance rate | **34-80%** (Gen Z 80%, heat pumps 74%, NL 51%, vague 50%, UK 34%) | ≥ 60% - met by 2 of 5 |

Earlier scores: 2026-10-10 claim entailment 88%, relevance 34-78%; 2026-10-06 (older packs, Sonnet re-check)
81% and 33-54%. Cost and latency come from the run record, so the Gen Z and heat-pump packs, whose analysis was
redone by hand, show more time and spend than a single run takes.

## Run locally without keys

Needs Python 3.12 with [uv](https://docs.astral.sh/uv/) and Node.js 20+. No accounts, no `.env`:

```sh
git clone https://github.com/bezawitzyb/signal-context-packs.git
cd signal-context-packs
USE_FIXTURES=true LLM_FAKE=true ./start.sh      # then open http://localhost:7860
```

This uses recorded data and recorded agent runs: nothing is paid for and nothing leaves your machine.
The featured packs open as on the live app, and a new run (type any word as the run key) replays a
recorded research run end to end. Tests: `cd backend && uv run pytest` (they never spend money).

**With your own keys:** copy `.env.example` to `.env`, fill it in (Anthropic and Apify keys, a Neon
Postgres URL, a random salt and run key), then `./start.sh`. `cd backend && uv run python -m ctxpack.cli doctor`
checks the setup without showing any secret.

## Hosting

One **Render Free** web service (Docker, one worker, 512 MB) plus **Neon Free** Postgres, with no payment
card anywhere. Runs are jobs in the database: no work happens inside an HTTP request, every stage
saves to Neon, and live updates stream from the events table, so a restart loses nothing. A GitHub
Actions job pings `/ping` to keep the service awake, the static mirror is published to GitHub Pages, and a
weekly job checks every Apify actor (free, no key).
CI runs the lint, all tests, the build with the end-to-end tests and a secrets scan on every push (no secrets
needed: tests use recorded data). Each research run works on its own thread, so the site stays responsive.
Only Anthropic and Apify cost money; a daily spend cap stops new runs when it is reached.
More in [docs/DEPLOY.md](docs/DEPLOY.md).

## Known limitations

- **Claim entailment is 91%, not 95%.** The re-check model (Opus) still finds some claims slightly broader
  than their posts (most in the vague and UK brand packs). Such claims are labelled "inferred", not "safe to state".
- **Relevance is below 60%** for three of five briefs (NL 51%, vague 50%, UK 34%; Gen Z 80%, heat pumps 74%;
  single runs vary a lot with the searches the agent picks). Relevance is checked per post, so off-topic
  posts never become evidence, but they cost collection time.
- **Two of the three featured packs are marked "thin evidence"** (Gen Z and NL): a section falls short of the
  content bar, for example fewer than 2 tensions backed by 3 posts from 2 sources. The NL pack is a Quick run with
  71 relevant posts, so most of its findings are "emerging" or "speculative". Each pack says so instead of padding.
- **Quick runs often run out of analysis budget** ($1.40 in `modes.yaml`): three Quick runs on 2026-10-10/11 did,
  and ended as an evidence-only pack that the owner finished with a one-off extra budget. Richer runs (more
  relevant posts) need more extraction and writing.
- **Forum feeds (V13) are new and not yet proven in a full run.** In two paid heat-pump runs the agent preferred
  social searches and reading forum pages; a site-wide forum feed tested at 10% relevant, a topic category feed
  at 100%, so the agent is told to use only sub-forum or category feeds.
- **Standard runs take 15-20 minutes**, not 12. Quick runs take 7-17 minutes, not 7 (2026-10-10/11: 14-17).
- **The free server can sleep.** GitHub runs the keep-alive less often than scheduled, so the first visit
  after a quiet hour can take about a minute. The mirror is the backup.
- One live run at a time (later runs queue, up to 3 waiting).
- **Apify runs on the free plan ($5 a month).** When it is used up, runs continue with web search only and
  the pack says which platforms are missing.
- **Ask this pack** answers only from the pack; it cannot fill gaps with outside knowledge, by design.

## Architecture

```
 Browser (marketer)                        AI agents (Claude, MCP clients)
           |                                            |
           v                                            v
 +---------------------------------------------------------------------+
 | ONE Render Free web service (Docker, 1 worker)                      |
 |  /  web app (React)   /api/v1  REST + live events   /mcp  MCP       |
 |  /health  /ping                                                     |
 |                                                                     |
 |  brief -> interpret + plan -> [review] -> queue (runs table)        |
 |  worker: AGENT LOOP -> extract -> cluster + check -> metrics (code) |
 |          -> write -> verify -> opportunities + news -> playbook,    |
 |             post briefs + drafts -> compliance -> calendar -> pack  |
 |  ask:    one pack, read-only tools, citations checked in code       |
 |                                                                     |
 |  AGENT LOOP (Sonnet) -> TOOLS (own data + limits) -> Apify, web     |
 |  guards: run key, daily spend cap, one live run + FIFO queue        |
 +---------------------------------+-----------------------------------+
                                   v
                 Neon Postgres (runs, events, documents, packs)

 GitHub Actions: CI (lint, tests, e2e, secrets scan), keep-alive ping, static mirror -> GitHub Pages,
                 weekly Apify actor-check (no secrets)
```

## Folder map

```
backend/ctxpack/      Python package
  config/             modes.yaml (limits), scoring.yaml, models.yaml, catalog.yaml (actors)
  agent/              interpret + plan, markets, ask (Ask this pack)
  collect/            agent loop, tools, Apify, web, feeds + URL guard, cleaning chain, fallback
  analysis/           extraction, clustering, metrics (code)
  synthesis/          writing, verification, confidence, opportunities, news, playbook, posts (briefs,
                      drafts, calendar), compliance, finalise
  exports/            Markdown, prompt block, quick brief, calendar CSV, hand-off, skill, views, featured
  llm/                client + prompts/*.md
  api/  mcp_server.py  orchestrator.py  worker.py  guards.py  evaluation.py  cli.py
backend/tests/        tests (fixtures; never spend money)
backend/evals/        eval briefs and results
backend/scripts/      demo agent, static mirror builder
frontend/             React + TypeScript + Tailwind web app
featured/             featured packs (loaded at startup) and eval results
examples/             packs as JSON + Markdown, skills, demo agent output
docs/                 product requirements, implementation guide, user research, SCHEMA.md, DEPLOY.md
index.html            the 4-slide project presentation (published as presentation.html on the mirror)
CHANGELOG.md          what changed in each version, and why
```

## Documentation

| Document | What it is for |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | Every version (1.0.0 - 1.5.0): what changed, why, and the owner's decisions |
| [docs/01_Product_Requirements_Document.txt](docs/01_Product_Requirements_Document.txt) | What the product does: requirements, content model, scoring formulas |
| [docs/03_Technical_Implementation_Guide.txt](docs/03_Technical_Implementation_Guide.txt) | How it is built: architecture, build steps, prompts |
| [docs/SCHEMA.md](docs/SCHEMA.md) | Every field of a pack (generated from the code; do not edit by hand) |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Hosting on Render + Neon, environment variables, guest keys |
| [docs/USER_RESEARCH.md](docs/USER_RESEARCH.md) | Four user tests and the marketing use cases behind the changes |
| [CLAUDE.md](CLAUDE.md) | The rules Claude Code follows in this repo (security, stack, commands) |

Limits, budgets and scoring weights live only in `backend/ctxpack/config/*.yaml`; where a document and the
config disagree, the config is right.

## License

[MIT](LICENSE) - free to use, change and share, with credit.
