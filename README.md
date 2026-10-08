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
| **Evaluations** | https://signal-l2w5.onrender.com/evals |
| **Pack format** | [docs/SCHEMA.md](docs/SCHEMA.md) - JSON schema in [docs/schema/](docs/schema/) |

## Try it

1. Open the live app and pick a **featured pack**: Gen Z and meal prep (global), launching a snack brand
   in the Netherlands, or heat pumps for homeowners in Germany. The **Summary** fits one screen: what we
   heard most clearly (with real quotes and how strong each finding is), the recommended position and
   your first moves. Open any finding to see the real posts behind it.
2. **Ask this pack** (side panel): "How do they describe their biggest pain point?" or "Turn the first
   post brief into a LinkedIn carousel outline". Answers come only from the pack, with numbered links
   to the real posts.
3. **Hand off** the pack: a half-page quick brief for ChatGPT or Claude, a brief for your AI writer, the
   full report for Notion or Docs, the content calendar as a CSV for Notion, or a Claude skill.
   **View as agent** shows the JSON an agent reads; **Watch how this pack was made** replays the
   agent's decisions.
4. **Run your own brief.** Live runs need an access key (the run key); it is never shown on screen.
   A vague brief gets up to 3 quick questions first (who exactly, which goal, which channels).
   A Quick run takes about 7-11 minutes; one run at a time, later ones queue.
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

## What is new (changes V1-V10)

| Change | What you get |
|---|---|
| **V1 Never lose a run** | Any run with enough relevant posts ends with a pack, whatever fails later; a step that fails twice still gives an evidence-only pack. Too few posts ends on a screen that says why, with one-click re-runs. Runs survive server restarts. |
| **V2 Markets and languages** | Several markets per brief, with weights; languages chosen in code from those markets (plus English), with the left-out ones and the reason shown. |
| **V3 Smart clarifying questions** | 0-3 brief-specific questions with answer chips (audience roles, goal, offer, channels, competitors); named competitors are always searched. |
| **V4 Condensed content** | Every finding once, in its best place; a "so what" line per section; pain points as their own section. |
| **V5 Opportunities you can trust** | One list: "supported" (enough people in enough communities) or "early signal - check before acting", with existing solutions found by web search. |
| **V6 LinkedIn as a source** (and **X**, 2026-10-07) | Keyword search only - never a person or profile - with no login of ours. |
| **V7 News hooks and timing** | "Ride this now": dated news and events, each with its source link; timing chips on channels (from posts or a cited source, never from memory). |
| **V8 Post briefs, drafts, calendar** | 5-8 post briefs whose key points cite real posts; full drafts for the first 3 (labelled "Draft - review before posting"; unsupported numbers and guardrail phrases are removed in code); a 4-week calendar as a Notion CSV. |
| **V9 Revised pack page and hand-off** | Summary / Understand your audience / Act on it / The research; plain-language strength labels ("good enough to: test a post / brief creative / commit budget"); a generic AI answer checked point by point against the posts; hand-off options described by purpose and length. |
| **V10 Ask this pack** | A read-only chat over one pack: answers cite real posts, invented references are removed, and "no evidence" is said plainly. Limited per pack per day without a run key. |

## How the agent chooses sources and stays within limits

- One planning call reads the brief and proposes hypotheses, research questions and 3-6 starting
  sources with reasons and queries per language. A vague brief gets up to 3 clarifying questions; no
  platform may take more than half of the starting sources unless the plan says why.
- The **agent loop** (Claude Sonnet, plain tool use) then picks the next call itself, with a reason:
  Reddit, TikTok, YouTube, Instagram, LinkedIn and X (keyword search only, no login of ours) through
  Apify, the open web through web search and fetch, and Google Trends. It sees only short summaries
  ("collected 50, kept 43, 84% relevant"), never raw posts. Every Apify source has a tested backup actor
  ([`catalog.yaml`](backend/ctxpack/config/catalog.yaml)); if both fail, the pack says so as a blind spot.
- **Tools own the data and the limits.** Every limit lives in
  [`backend/ctxpack/config/modes.yaml`](backend/ctxpack/config/modes.yaml) and is enforced in code, never
  only in a prompt. Quick allows 15 tool calls, 5 minutes and $1.80 of Apify; Standard allows 30 calls,
  10 minutes and $4.00. On top of that there is a daily spend cap.
- Inside every collection tool, before the agent hears back: normalise → hash authors → redact
  personal details → dates and time window → de-duplicate → spam → relevance check → store.
- If the loop crashes, code runs the untried starting sources. If evidence is thin, it tops up from
  sources already kept. A dropped source is never called again.
- Then: extraction, clustering with a membership check, **counts computed in code** (no model writes a
  number), writing, verification (every quote must be an exact substring of its post; every claim is
  re-checked against its own evidence), confidence scoring, opportunities, news hooks, playbook with
  post briefs and drafts, compliance flags, and a content calendar built in code.

## What the output means

- [docs/SCHEMA.md](docs/SCHEMA.md) explains every field. Confidence is **strong / moderate / emerging /
  speculative** from evidence count, authors, platforms, sources, recency and the verifier. Only strong,
  observed claims confirmed by the claim check are `safe_to_assert`.
- [examples/](examples/) has the three featured packs as JSON and Markdown, each with its exported skill
  folder, and [examples/demo_agent.md](examples/demo_agent.md): an agent writing TikTok scripts with and
  without a pack, with automatic checks.
- **Skill export:** every pack downloads as a Claude skill (`SKILL.md` + `references/`), so an agent
  loads it only when the task needs it.
- **Exports:** quick brief (half a page), brief for your AI writer, full report (`brief.md`, same order as
  the page; prints with the Summary as page 1), content calendar (`content_calendar.csv`, UTF-8 for
  Notion, formula-safe cells), JSON.
- **MCP** (read-only, no key): `claude mcp add --transport http signal https://signal-l2w5.onrender.com/mcp`.
  Tools: `list_packs`, `get_pack_view`, `get_insight`, `search_evidence`, `get_post_briefs`, `get_calendar`;
  with the run key also `create_context_pack`, `get_pack_status` and `ask_pack`.

## Data handling and privacy

- Only public posts. Author names are hashed (salted) in the function that receives them and are
  never stored, logged or sent to a model. Emails, phone numbers, handles and profile links are redacted.
- Scraped text is treated as untrusted data and is wrapped as such in every prompt.
- Collected posts expire after 30 days. Packs keep at most short excerpts (280 characters) with links.
- Quoted excerpts are for internal research and briefs only, **not for ads or other public material** -
  every pack says so. Exports note that the analysis is AI-assisted and that compliance flags are not legal advice.
- The repo is public and contains no keys: gitleaks runs on every commit, and `demo-check` also
  searches the files, the git history and the web builds for the real run key.

## Evaluation results

Four test briefs, run on 2026-10-06 before changes V1-V10 (details and reasons on
[/evals](https://signal-l2w5.onrender.com/evals)). A fifth brief (B2B, several markets) is added in
[`backend/evals/briefs.yaml`](backend/evals/briefs.yaml) and needs a paid Standard run.

| Metric | Result | Target |
|---|---|---|
| Quote groundedness | **100%** | 100% |
| Claims with evidence | **100%** | 100% |
| Schema valid | **100%** | 100% |
| Source diversity | **3 of 3** briefs with ≥ 3 platforms | ≥ 3 (vague brief exempt) |
| Plan divergence | **4%** of source units shared | < 50% |
| Allocation efficiency (SIMULATED) | **1.36×** an equal split | ≥ 1× |
| Peak memory | **196 MB** | < 400 MB |
| Claim entailment (Sonnet re-check) | **81%** (NL pack 93%) | ≥ 95% - not met |
| Relevance rate | **33-54%** | ≥ 60% - not met |

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
Actions job pings `/ping` to keep the service awake, and the static mirror is published to GitHub Pages.
Only Anthropic and Apify cost money; a daily spend cap stops new runs when it is reached.
More in [docs/DEPLOY.md](docs/DEPLOY.md).

## Known limitations

- **Claim entailment is 81%, not 95%.** The re-check model often finds a claim slightly broader than
  its posts. Such claims are labelled "inferred", not "safe to state". Prompt sharpening raised the
  score from 70%; the heat-pump pack (63%) could not be rebuilt within its own budget.
- **Relevance is below 60%.** The agent keeps some sources that are only a third on topic. Relevance is
  checked per post, so off-topic posts never become evidence, but they cost collection time.
- **Every featured pack is marked "thin evidence"** when a section falls short of the content bar (for
  example, the NL pack has one verified tension). It says so instead of padding.
- **Standard runs take 15-20 minutes**, not 12. Quick runs take about 11.
- **The free server can sleep.** GitHub runs the keep-alive less often than scheduled, so the first visit
  after a quiet hour can take about a minute. The mirror is the backup.
- One live run at a time (later runs queue, up to 3 waiting).
- **Apify runs on the free plan ($5 a month).** When it is used up, runs continue with web search only and
  the pack says which platforms are missing.
- **The featured packs were made before V8-V10.** They show the new page and summary, but post briefs,
  the recommended position, success measures and the generic-answer statuses appear only in packs made
  (or rebuilt) after those changes.
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

 GitHub Actions: keep-alive ping, static mirror -> GitHub Pages
```

## Folder map

```
backend/ctxpack/      Python package
  config/             modes.yaml (limits), scoring.yaml, models.yaml, catalog.yaml (actors)
  agent/              interpret + plan, markets, ask (Ask this pack)
  collect/            agent loop, tools, Apify, web, cleaning chain, fallback
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
docs/                 product requirements, phases, implementation guide, changes plan, SCHEMA.md, DEPLOY.md
```
