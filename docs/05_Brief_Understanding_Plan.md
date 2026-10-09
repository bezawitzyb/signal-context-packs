# V11 plan: understand the brief, ask what is missing

Status: **approved 2026-10-09 (all four decisions: yes) and built.** Estimates are working hours with Claude Code, tests
included. Paid calls are listed; everything else runs on fixtures (free).

## Goal of this step

The agent understands the brief, asks only the missing questions that matter for a great research
and a useful pack, and never guesses the user's goal or offer. The plan screen shows one editable
"Here's what I understood" box that says where each item came from.

The five things only the user knows (same as the brief guide in the app,
`frontend/src/components/BriefGuide.tsx`): **goals, offer, who, markets, key question (and by
when)**. Everything else - competitors, channels, hashtags, their words, pain points, trends,
timing - is found by the research and is never asked.

## Findings that shape the plan (current code)

1. `prompts/interpret_plan.md:50-55` allows at most one question when the brief names a market and
   an action ("launching ...") and none when it also names an audience or offer, so the goal and
   offer are often never asked. "Launching" is treated as the goal.
2. Only the model decides what to ask. Code checks one thing: a market question is dropped when
   the brief names a place (`agent/interpret.py` `drop_answered`).
3. `interpretation.intent` is always filled, as a guess when the brief does not say it, and later
   stages fall back to it (`synthesis/write.py:795`, `synthesis/finalize.py:466`,
   `synthesis/baseline.py:21`).
4. Every question can be skipped ("Skip all and plan"), so the goal and offer can end up guessed.
5. `intake.goal` is one free-text string (several chips are joined with ";"); the offer has no stage.
6. Plan screen (`frontend/src/pages/Ask.tsx`): a read-only "Here's what I understood" box (topic,
   markets, languages, audience, goal, time window, brands named, "assumed" badges, languages left
   out) and a second "Adjust before you start" box that repeats markets, languages and competitors
   and splits "audience" from "who to reach". There's no offer or key question. Category and
   rules area are worked out but not shown.

## Conflicts with current docs and rules (resolve in "docs first")

| Where | Today | Change |
|---|---|---|
| PRD FR-A2 / V3 rules (`docs/04_Changes.txt`, `interpret_plan.md`) | specific brief -> 0-1 questions; all skippable | Goals and offer always asked when missing and never skippable; other questions as today |
| `modes.yaml` `clarifying.max_questions` | 3 | **4** (owner's decision: a vague brief may need goal + offer + who + market) |
| MCP `create_context_pack`, API with auto-approve | intake optional | **`goals` required** (owner's decision: a breaking change for agents; the error lists the allowed goals) |
| README "What is new" V3 line | 0-3 questions | Updated to the new rules |

## Design

### 1. Understand (one planning call, as today - no extra call)
The model returns a new `understanding` block next to the interpretation. For each of the five
inputs it gives:
- `value`: what it understood, in plain words (empty when missing),
- `brief_quote`: the exact words of the brief it is based on,
- `status`: `stated`, `unclear` (named but too vague to research well, e.g. "Europe",
  "businesses") or `missing`.

It never fills a value from a guess. **Code checks** every `brief_quote` is a substring of the brief
(case and whitespace normalised); if not, the input becomes `missing`. Goals must map to the fixed
goal list; unknown goals become `unclear`.

### 2. Decide what to ask
The model proposes the questions; code guarantees the rules:

| Input | Asked when | Skippable |
|---|---|---|
| Goals | missing or unclear - **always** (code adds the fixed goal question if the model left it out) | no |
| Offer | missing - **always** (code adds the fixed offer question if left out) | no ("no offer of my own" is an answer) |
| Who | several groups could be meant (buyers vs users, consumers vs retailers) or unclear | yes |
| Markets | none named, or too broad (confirmation question: "You said Europe: which countries first?") | yes |
| Key question / timing | the goal depends on a date (launch, campaign, content plan) and none is given | yes |
| Channels in use | only for a content-plan goal named in the brief | yes |
| Competitors to watch | only for a positioning goal named in the brief, none named | yes |

Order: goals, offer, then the gap that would change the research most. Total
<= `clarifying.max_questions`. Never ask what the research finds; never ask what the brief
already states (extends `drop_answered` to every input with status `stated`).

### 3. The two fixed questions
- **Goals** - "What will you use this research for?" Chips from `config/goals.yaml` (multi-select;
  click order = priority, shown as 1, 2, 3; first = main goal) + own words. Why it helps: "Your goal
  decides what the pack focuses on: a message, post ideas, a go/no-go, or sales answers."
- **Offer** - "What do you offer?" Free text (placeholder example written by the model for this
  brief; the model never invents products as chips) + stage chips from `config/goals.yaml`: idea,
  launching soon, already selling, no offer of my own (agency, client work or exploring). A stage
  chip is required.

### 4. Plan screen: one editable "Here's what I understood" box
Replaces the read-only box **and** "Adjust before you start". Every row shows its source:
*from your brief: "..."*, *your answer*, *assumed* (never for goals or offer) or *chosen in code*.

| Row | Editable | Note |
|---|---|---|
| Goals (ranked) | yes | replaces "Goal" (intent) |
| Offer + stage | yes | new |
| Who (roles as chips) | yes | merges "Audience" and "Who to reach" |
| Markets + languages (+ languages left out with reason) | yes | as today, now in one place |
| Key question and timing | yes | new |
| Topic | yes | was read-only |
| Time window | in the form | as today |
| Competitors to watch | yes | renamed from "Brands named"; line: "the research finds the others" |
| Rules area | no | shown only when not "other" |

Any edit re-plans in place (existing `replanRun`). Starting sources, research questions and
hypotheses stay below, unchanged.

### 5. Agents and CLI (cannot be asked)
- MCP `create_context_pack` and `POST /api/v1/runs` with auto-approve: `goals` required (list of
  goal ids), `offer` and `offer_stage` optional. Missing goals -> clear error listing the goals; no
  run is created. Old single `goal` string still accepted (mapped to the list when it matches a
  goal id, else rejected with the list).
- CLI `research`: `--goal` (repeatable, in priority order), `--offer`, `--offer-stage`. Missing
  goals -> asked interactively; with `--auto-approve` -> stops with the list.

### 6. Later stages use only confirmed goals
`synthesis/write.py` (so-what lines), `synthesis/finalize.py` (playbook brief), `synthesis/baseline.py`,
`exports/markdown.py` and `exports/quick_brief.py` read `intake.goals` (+ offer and stage). The
`intent` fallback is removed; `interpretation.intent` is kept for old packs and filled in code
from the goals (never by the model).

## Schema 1.2

| Field | Migration from 1.1 |
|---|---|
| `brief.intake.goals[]` (enum, ranked; lowercase snake_case: `understand_audience`, `content_plan`, `campaign_launch`, `positioning`, `product_validation`, `market_entry`, `brand_perception`, `sales_enablement`) | `goal` text kept as `goal_note`; `goals` = [] |
| `brief.intake.goal_note` (the user's own words) | from `goal` |
| `brief.intake.offer_stage` (enum: `idea`, `launching`, `selling`, `no_offer`) | null |
| `brief.intake.key_question` | from `timeframe` / `other_answers` only if a question was asked for it, else null |
| `brief.interpreted.understanding {goal, goals[], offer, offer_stage, who, markets, key_question}` (each input: value, brief_quote, status, source) | built in code from the pack's brief and intake; status `missing` where unknown, source `assumed` for who and markets |

Bump `schema_version` to `"1.2"`, extend `schemas/migrate.py`, add a CHANGELOG entry, run
`export-schema` (regenerates `docs/SCHEMA.md`) and `npm run types`. `featured/` and `examples/`
are migrated and must validate.

## Files

- **Config:** new `config/goals.yaml` (goal ids, chip text, one-line description; offer stages);
  `modes.yaml` `clarifying.max_questions: 4`.
- **Backend:** `schemas/enums.py` (Goal, OfferStage, InputStatus, InputSource), `schemas/plan.py`
  (Understanding, Intake fields), `schemas/pack.py` + `schemas/migrate.py` (1.2),
  `agent/interpret.py` (quote check, required questions, fallback questions built in code,
  `drop_answered` for every stated input), `llm/prompts/interpret_plan.md` (understand first; an
  action is not a goal; never guess goal or offer; question rules above), `api/service.py`
  (`intake_from_answers`: ranked goals, offer + stage, refuse a skipped goal/offer question),
  `api/routes.py` (goals required with auto-approve; new edit fields: goals, offer, offer_stage,
  key_question, topic), `mcp_server.py`, `cli.py`, `orchestrator.py` + `collect/loop.py` (pass
  goals, offer, key question to the agent), `synthesis/write.py`, `finalize.py`, `baseline.py`,
  `exports/markdown.py`, `exports/quick_brief.py`.
- **Fixtures:** recorded planning answers (`tests/fixtures/llm/record_plan.json` and the LLM_FAKE
  plan) gain an `understanding` block; the fake "snacks" path asks goals + offer + market.
- **Frontend:** `lib/api.ts` types; `pages/Ask.tsx` - ranked goal chips, offer card with stage
  chips, no skip on required questions ("Skip all" skips only the others), merged editable
  understood box with source labels, "Adjust before you start" removed.
- **Evals:** `backend/evals/briefs.yaml` - each brief gets its goals (and offer where known);
  question checks updated.
- **Docs first:** PRD FR-A2, `04_Changes.txt` V3 rules, README (V3 line, MCP section, new V11 line).

## Tests (free)

- Brief that states goal and offer (e.g. the template) -> no goal or offer question.
- "Launching a snack brand in the Netherlands" -> goal question and offer question asked.
- A goal whose quote is not in the brief -> dropped, question asked.
- Model leaves out the goal question -> code adds the fixed one.
- Goal or offer question skipped (or "Skip all") -> refused with a plain message; other questions
  can still be skipped.
- "No offer of my own" accepted; chip click order -> goal priority.
- "Europe" -> a confirmation question for countries, not a new market question.
- Never more than `max_questions`; never a question about something the brief states.
- MCP / API auto-approve without goals -> error listing the goals, no run created; old `goal`
  string mapped or refused.
- Later stages and exports use `intake.goals`; no code path reads a guessed intent.
- Migration 1.1 -> 1.2 of every featured and example pack validates.
- E2E: the V3 flow test updated (goal + offer cards, then the merged understood box); a11y checks
  on the questions and the new box.

## Money and time

- **Work:** about 9-10 hours.
- **Paid:** planning calls on the 5 eval briefs plus 3 new test briefs to check the questions
  (Anthropic about $0.20; Apify $0).

## Decisions for the owner

1. Raise `clarifying.max_questions` from 3 to 4? (recommended: yes)
2. Make `goals` required for MCP and API agents? (recommended: yes - otherwise their goal is
   guessed)
3. Goal list and wording as above?
4. Schema 1.2 now (recommended), or keep 1.1 and add optional fields only?

## Next step (not in V11): a goal-driven pack

With confirmed goals in place, `config/goals.yaml` can also decide which sections each goal gets,
the Summary per goal and the order of sections (main goal first; sections for several goals
combined, no duplicates), with a cap on goals per mode. Planned separately after V11.
