# V0 plan for the ten user-value changes (docs/04_Changes.txt)

Status: **approved 2026-10-07; V1-V10 built 2026-10-07/08** (V11 and V12 followed: files 05 and 06). Decisions: plan approved; Apify key replaced (new $5 budget);
LinkedIn (V6) go ahead; Notion = "Copy for Notion" + CSV import only (no Notion integration).
Estimates are working hours with
Claude Code, tests included. Paid calls are listed per step; everything else runs on fixtures (free).

## Findings that shape the plan

1. **V1 root cause (to confirm with a test in V1).** When the agent loop ends by *error* or *time
   limit*, `orchestrator.run_pipeline` treats the run as "partial" and **skips extraction, clustering,
   writing and verifying**. Packaging then finds no verified draft, saves no pack, and the run still
   ends as `partial`. The run screen says "stopped early - the pack uses what was collected" although
   no pack exists. Any other exception after collection fails the whole run with no pack either.
2. **Already done (V1.4):** runs and packs are saved in Neon with permanent `/runs/{id}` and
   `/packs/{id}` links, and the live run page resumes from the last event after a refresh (SSE
   `Last-Event-ID`). There is **no "not persistent" warning** in the app today (searched).
3. **The pack already has two overlapping sections:** `white_space[]` (unmet needs, WSP-xx) and
   `opportunities[]` (scored per PRD 5.5, OPP-xx, `builds_on`). V5's "opportunities replaces
   white_space" therefore means merging them.
4. **There is no "Pain points" section.** Pains are extracted per post (`extraction.pains`) and
   feed motivations of kind "need". V4 and V9 make it a section of its own.
5. `related_ids[]` already exists on every insight item (V4 builds on it).
6. `exports/safe_cells.py` is empty (docstring only): V8's CSV needs the formula-safe cell code.
7. `/runs` (without an id) is now the owner-only cost page; run pages stay at `/runs/{id}`.

## Conflicts with current docs and rules (to resolve in each step's "docs first")

| Step | Conflict | Proposal |
|---|---|---|
| V1 | "minimum relevant docs (scoring.yaml)" | The minimum lives in `modes.yaml` (`min_relevant` per mode, `worker.thin_evidence_floor` 20). Keep it there; the thin screen uses `thin_evidence_floor`. |
| V3 | PRD FR-A2 and D2: at most one clarifying question | Replace with 0-3 brief-specific questions (as the change file says). |
| V5 | `opportunities` (scored) and `white_space` both exist | One `opportunities[]` in 1.1 that absorbs both; the PRD 5.5 score is kept as a field. |
| V6 | PRD DH1: no login-walled content; CLAUDE.md lists LinkedIn nowhere | Update DH1 as the file says. Owner's decision noted (terms and privacy risk, see Risks). |
| V8 | CLAUDE.md: "brand voice only in the playbook call" | Drafts are written inside the playbook stage (same rule, one more call there). |
| V9 | "Send to Notion" needs a Notion integration token: a new service | Proposal: ship "Copy for Notion" (exists) + Notion CSV import now; "Send to Notion" only if you add a Notion integration (I would tell you the variable name). |
| V6/V9 | CLAUDE.md "No new paid services" | LinkedIn runs on Apify (allowed). A LinkedIn session account would be a new secret (you add it). |

## Schema 1.1 (one version for all steps)

The first step that changes the schema (V2) bumps `schema_version` to `"1.1"`, adds a CHANGELOG in
`docs/SCHEMA.md` (generated part stays generated; the changelog is a hand-written header file the
generator includes) and `schemas/migrate.py` with `migrate_1_0_to_1_1(pack)`. Every later step
extends both. `featured/` and `examples/` are migrated in each step and must validate.

| Field (1.1) | Step | Migration from 1.0 |
|---|---|---|
| `brief.interpreted.markets[] {code, countries[], weight, assumed}` (replaces `market`) | V2 | `market` -> one entry, weight 1 |
| `brief.interpreted.languages_excluded[] {language, reason}` | V2 | empty |
| `brief.intake {audience_roles[], goal, offer, channels_in_use[], competitors_user[], timeframe, other_answers[], questions_asked[]}` | V3 | empty intake |
| `evidence[].role` (buyer, influencer, user, consumer, other, unknown) | V3 | "unknown" |
| `pain_points[]` (new section, InsightItem) | V4 | empty, `empty_reason` set |
| `sections_meta {section: {so_what, empty_reason, next_steps[]}}` | V4 | empty |
| `what_performs[].takeaway` | V4 | "" |
| moments -> `channel_plan[].timing[]`; hypotheses -> Method table; whats_new -> landscape | V4/V7 | moved, ids kept |
| `opportunities[] {id, opportunity, kind, evidence_ids, distinct_authors, communities, existing_solutions[], status, confidence, related_ids[], score}` (replaces `white_space[]` + old `opportunities[]`) | V5 | white_space -> status "signal"; old scored opportunities -> kept with score |
| `evidence[].requires_login` | V6 | false |
| `news_hooks[] {id NWS-xx, headline, date, source_url, why_it_matters, related_ids[], claim_type external}` | V7 | empty |
| `channel_plan[].timing[] {label, when, why, evidence_ids, claim_type, source_url}` | V7 | from moments |
| `post_briefs[]`, `drafts[]`, `content_calendar[]` | V8 | empty |

## Steps

### V1 Never lose a run - about 4 h
- **Files:** `orchestrator.py` (analysis always runs when the corpus has >= `thin_evidence_floor`
  relevant docs, whatever ended collection; each analysis stage failure falls back to a partial pack
  from what exists; the failure goes into blind_spots and Method), `synthesis/finalize.py` (partial
  pack from a partial draft), `worker.py`, `api/service.py` (`rerun_inputs`), frontend `RunPage.tsx`
  (honest end states; thin-evidence screen with reasons and one-click re-plans), `Ask.tsx` (form
  kept in sessionStorage; prefill from "Run again"), `Home.tsx` ("My packs" from localStorage),
  `PackPage.tsx` ("Run again with these inputs").
- **Schema:** none. **Config:** none new (`thin_evidence_floor`, `min_relevant` exist).
- **Tests:** loop error / timeout / exception in extract, cluster, write, verify -> partial pack each
  time; below the floor -> thin screen state with reason codes; "run again" payload restores every
  input; refresh mid-run (already covered) stays green.
- **Paid:** none.

### V2 Correct markets and languages - about 4 h
- **Files:** `schemas/plan.py`, `schemas/pack.py` (1.1 bump), `schemas/migrate.py` (new),
  `agent/interpret.py` + `prompts/interpret_plan.md`, `collect/tools.py` (Trends and locale per
  country), `collect/cleaning.py` (cheap relative dates for the new languages), frontend plan screen
  (chosen and excluded languages with reasons), `evals/briefs.yaml` (brief 5).
- **Config:** new `config/markets.yaml` (regions -> countries: eu, dach, benelux, nordics, cee;
  country -> official languages) and in `modes.yaml`: `languages.supported` (en de nl fr it es pl sv
  da nb fi pt), `languages.max_per_mode {quick: 4, standard: 6}`. Geography only - no sources.
- **Tests:** "...in Europe" never gives global; a Poland brief includes pl; excluded languages carry
  a reason; migration of every featured pack validates.
- **Paid:** a few interpret calls on real briefs to check (about $0.10).

### V3 Smart clarifying questions - about 5 h
- **Files:** `schemas/plan.py` (questions list, intake), `agent/interpret.py` + prompt (gap-first
  rules from the change file), `api/routes.py` + `service.py` (answer several questions, skip,
  edit chips and re-plan), `mcp_server.py` (agents may pass intake; never asked), extraction prompt
  (evidence role), frontend `Ask.tsx` (question cards, chips, free text, skip / skip all; editable
  interpretation chips), `evaluation.py` + `briefs.yaml` (question checks).
- **Config:** `modes.yaml` `clarifying: {max_questions: 3, options_min: 3, options_max: 5}`.
- **Tests:** specific brief -> 0-1 questions; "snacks" -> market and audience; manufacturing ->
  role question; no question repeats what the brief says; answers change research questions;
  skip-all works; run-again restores answers.
- **Paid:** interpret calls on the 5 eval briefs (about $0.15).

### V4 Condensed content - about 6 h
- **Files:** `prompts/write*.md` (one job per section, so_what lines, takeaways), `synthesis/write.py`
  (pain points section), new `synthesis/consolidate.py` (code similarity first, then one worker call
  for borderline pairs; keeps the best home, merges evidence, adds `related_ids`), `finalize.py`
  (merge small sections; empty reasons), exports (Markdown, skill, prompt block), frontend cards
  (linked chips "comes from / blocks").
- **Config:** `scoring.yaml` `consolidation: {merge_similarity: 0.85, borderline_low: 0.6}`;
  `modes.yaml` item caps unchanged or lower.
- **Tests:** fixture pack: no two sections state the same finding; tensions, motivations,
  objections and pain points all present with distinct jobs; chips link real ids; empty sections
  show a reason and next steps.
- **Paid:** rebuild the 2 flagship packs from saved corpora to check quality (about $1-2 Anthropic,
  $0 Apify).

### V5 Opportunities you can trust - about 3 h
- **Files:** `schemas/pack.py` (merged opportunities), `analysis/metrics.py` (distinct authors and
  communities in code), new `synthesis/opportunities.py` (one web search per opportunity for existing
  solutions; rewording as a gap in how it is served), prompts, UI and exports rename White space ->
  Opportunities.
- **Config:** `scoring.yaml` `opportunities: {supported_min_authors: 3, supported_min_communities: 2}`;
  `modes.yaml` `opportunities.searches_max: 4`.
- **Tests:** one-post opportunity -> "early signal"; a search hit -> listed, never "nobody serves".
- **Paid:** web searches when rebuilding (about $0.05 per pack).

### V6 LinkedIn as a source - about 4 h
- **Files:** `config/catalog.yaml` (actor + fallback after live verification), `collect/tools.py`
  (`search_linkedin` with the full cleaning chain, `requires_login`, refuses private targets),
  `collect/mappers.py`, `collect/loop.py` + `prompts/collector.md` (general B2B guidance, source
  balance), PRD DH1/DH8/DH12/risks, evidence drawer note, fixture file for tests.
- **Config:** `modes.yaml` `source_share_max: 0.5`; catalog entry with price, latency, needs_session.
- **Tests:** tool on its fixture (no raw names or handles anywhere); budget and share limits; brief 5
  plans LinkedIn; the Gen Z brief does not lean on it.
- **Paid:** finding actors is free (Apify store API); **one small verification call** - I will tell
  you the exact cost first (expected under $0.50 of Apify).

### V7 News hooks and timing - about 3 h
- **Files:** new `synthesis/news.py` (web search in the brief's languages; up to 5 hooks; no URL ->
  dropped), `finalize.py` (timing chips from evidence time mentions, news hooks and cited calendar
  facts only), playbook prompt (this-week may link a hook), UI "Ride this now", exports.
- **Config:** `modes.yaml` `news: {lookback_days: 30, lookahead_days: 90, max_hooks: 5, searches_max: 3}`.
- **Tests:** every hook and external timing item has a URL; none without; fixture timing chips.
- **Paid:** web searches per run (about $0.03-0.05).

### V8 Post briefs, drafts and a Notion calendar - about 6 h
- **Files:** `synthesis/playbook.py` + `prompts/playbook.md` (post briefs; drafts in the playbook
  stage with brand voice; guardrail and claim checks in code), new `exports/calendar_csv.py`,
  `exports/safe_cells.py` (implement), Markdown / skill (`references/posts.md`) / prompt block,
  API + MCP `get_post_briefs`, `get_calendar`.
- **Config:** `modes.yaml` `posts: {briefs_min: 5, briefs_max: 8, drafts: 3, calendar_weeks: 4}`.
- **Tests:** every key point cites evidence; drafts contain no unsupported claim or forbidden phrase;
  CSV with BOM, formula-safe cells, Dutch and Polish characters intact; user channels preferred.
- **Paid:** rebuild check (about $0.30 per pack).

### V9 Revised pack page and handoff - about 8 h (revised 2026-10-08 after a marketing-director audit)

Goal: easier to **read**, **trust** and **act on**. Changes against the original V9 request are marked
(new) / (changed) / (cut).

- **Summary (first screen, under a minute)**
  - One line: audience, goal, market, plus **"Who this represents"** (new): "N public posts from about
    M people, mostly <platforms>; the vocal online minority, not market share".
  - **What we heard most clearly** (changed: replaces "What we found" + "Five key truths"): 3 findings,
    each with one quote (English translation shown under non-English quotes, new), a plain strength
    label and "N people, M communities".
  - **Recommended position** (new): one message, for whom, against which doubt, with item links.
    Written by the existing playbook call (no new call).
  - **Your plan** (changed): the top 3 calendar items = "Do this first", each with a **success
    measure** (new, playbook call), and up to 2 news hooks (Ride this now).
  - **How sure are we?** (new): one line per finding, "Good enough to: test a post / brief creative /
    commit budget", from scoring.yaml labels.
- **Understand your audience**
  - Their words (vocabulary, phrases, say / don't say).
  - (changed) **What they want / What stops them** as two blocks (motivations | pain points +
    objections), with tensions as the bridge cards between them; linked chips (V4) kept.
  - Segments (empty-state reason), Landscape by platform and over time.
  - **Generic AI answer vs. what people say** (changed): per generic point a status: confirmed /
    contradicted / not seen / new - from the existing non-obvious check (no new call).
- **Act on it**
  - **One plan** (changed): post briefs + 4-week calendar; week 1 = "this week" (the separate
    this-week table and Do-first list fold into it; JSON keeps both fields for agents).
  - Channels with timing chips; what performs (takeaways first); opportunities (supported | early
    signal); guardrails.
- **The research** (collapsed): sources, method, hypotheses, blind spots, all evidence,
  "Watch how this pack was made" (renamed; "a recording - it won't run again or cost anything").
- **Trust fixes** (new, code only): no "grade A" next to "thin evidence" (the grade is capped and
  says why); "Five truths" renamed everywhere; confidence never colour-only.
- **Hand-off** (changed: 4 options + "More"): Quick brief (half a page, new tier), Brief for your AI
  writer (~2 pages), Full report (Notion / Docs / PDF; print view = one-page executive summary
  first), Content calendar (CSV). More: Teach Claude (skill), For developers (JSON, API).
  Length labels computed (words -> pages); toast after copy. (cut) "Send to Notion".
- Progressive disclosure, sticky part nav ("How to read this" from scoring.yaml), mobile one column,
  exports in page order - as in the original request.
- **Files:** PackPage.tsx + components, Handoff.tsx, exports (markdown, print, new quick_brief.py),
  synthesis/playbook.py + prompt (position, success measures), the non-obvious check (generic-point
  status), finalize.py (findings, represents line, grade cap), schema 1.1 additions + migration.
- **Schema 1.1 additions:** `snapshot.findings[]` {text, item_ids, quote, strength_text, good_enough_to},
  `snapshot.represents`, `snapshot.position` {statement, for_whom, against_doubt, item_ids},
  `generic_vs_found.comparison[]` {generic_point, status, item_ids}, `success_measure` on
  do_first and post briefs. Old packs: empty / derived in code; `five_truths` kept for agents.
- **Config:** `exports.words_per_page: 450`, `exports.quick_brief_max_words: 250`;
  `scoring.yaml good_enough_to` per label.
- **Tests:** e2e first screen shows the Summary at 1300x900; no "token", "JSON schema", "evidence id"
  in UI strings; every badge has a tooltip; 390 px has no horizontal scroll; exports follow page
  order; thin packs never show grade A; every comparison row has a status.
- **Paid:** one rebuild on a saved corpus (`pack --from-run RUN_ID --redo`, about USD 0.40 Anthropic,
  no Apify) to check the position, measures and comparison wording. Asked before running.

Wireframe (desktop; on a phone the left nav becomes a menu and everything is one column):

```
+----------------------------------------------------------------------------------+
| SIGNAL                                                       Packs  [Hand off v]  |
+------------------+---------------------------------------------------------------+
| SUMMARY        * | Homeowners in DE - goal: content calendar                      |
|  Understand      | 101 posts from ~80 people, mostly Reddit + YouTube (vocal       |
|   Their words    | online minority, not market share)        How to read this (?) |
|   Want / Stops   | ------------------------------------------------------------- |
|   Segments       | WHAT WE HEARD MOST CLEARLY                                     |
|   Generic vs us  |  1. finding   "quote" (EN: ...)   Emerging - 5 people, 2 comm. |
|   Landscape      |     Good enough to: test a post                                |
|  Act on it       |  2. ...   3. ...                                               |
|   Your plan      | RECOMMENDED POSITION                                           |
|   Channels       |  "Honest numbers, house by house" - for Altbau owners who      |
|   Opportunities  |   doubt a heat pump fits their house          [TEN-01 MOT-01]  |
|   Guardrails     | YOUR PLAN - DO THIS FIRST                                      |
|  The research >  |  [1] post ... measure: replies asking for the table  (Wk1 Tue) |
|                  |  [2] ...  [3] ...        RIDE THIS NOW [hook · date · source]  |
|                  +---------------------------------------------------------------+
|                  | UNDERSTAND YOUR AUDIENCE                                       |
|                  |  Their words | What they want  <-tension->  What stops them    |
|                  |  Generic AI answer vs. what people say:                        |
|                  |   subsidies are the main worry  -> NOT SEEN in the posts      |
|                  |   old houses: will it work?     -> CONFIRMED  [TEN-01]        |
|                  +---------------------------------------------------------------+
|                  | ACT ON IT                                                      |
|                  |  Your plan: Wk1 | Wk2 | Wk3 | Wk4   brief cards > draft (copy)  |
|                  |  Channels + timing · What performs · Opportunities · Guardrails|
|                  +---------------------------------------------------------------+
|                  | THE RESEARCH (collapsed) sources · method · hypotheses ·      |
|                  |   blind spots · evidence · Watch how this pack was made        |
+------------------+---------------------------------------------------------------+
Hand off: Quick brief (1/2 page) · AI writer brief (~2 pages) · Full report · Calendar CSV · More v
```

### V10 "Ask this pack" - about 4 h
- **Files:** `api/routes.py` + `service.py` (`POST /api/v1/packs/{id}/ask`), new `agent/ask.py`
  (read-only Sonnet tool loop over get_pack_view, get_insight, search_evidence; cited ids checked
  in code), `mcp_server.py` (`ask_pack`), frontend side panel with 4 suggested questions built in
  code, recorded fake answers for tests.
- **Config:** `modes.yaml` `ask: {max_tool_calls: 6, max_usd: 0.10, questions_per_pack_per_day: 20}`.
- **Tests:** citations open real posts; unanswerable -> says so; invented id stripped; limit message.
- **Paid:** a few real questions (about $0.10).

## Totals and money

- **Work:** about 46 hours (roughly 6-7 working days). Cut order from the change file applies.
- **Free:** all step tests (fixtures, fake model).
- **Paid during the steps:** roughly $3-5 Anthropic and under $0.50 Apify (V6 check).
- **Finish:** eval on 5 briefs needs **one new Standard run for brief 5** (Anthropic about $2-3,
  Apify up to $4) and rebuilt flagship packs (Anthropic about $2, Apify $0 if rebuilt from saved
  corpora, which expire on 3 Nov). **Apify has $1.48 left this month**, so the brief-5 run will
  only fit if you add Apify budget or run it after the 3 Nov reset.

## Risks

- **LinkedIn (V6):** collecting content visible only when logged in conflicts with LinkedIn's terms
  and raises GDPR questions for a commercial product; a session account can be banned mid-run.
  Mitigation: prefer actors without our cookies; ban -> blind spot. Your decision.
- **Apify budget:** $1.48 left; LinkedIn actors are usually more expensive than Reddit.
- **Schema 1.1:** every consumer (UI, exports, MCP, skill, mirror) changes; mitigated by one version,
  a tested migration and validating every featured pack after each step.
- **Scope:** V4 and V9 are the largest and depend on each other; V9 should wait for V4-V8 data.
- **Notion:** "Send to Notion" needs a new service and token (see conflicts).
