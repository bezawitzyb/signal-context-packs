# V12 plan: a goal-driven pack, with brand-perception analysis

Status: **approved and built 2026-10-09.** Decisions: 1 keep post briefs, drafts and the calendar for every goal;
2 cap goals at 3 (Quick and Standard); 3 brand name required for brand perception; 4 schema 1.3;
5 one paid Quick run of a brand-perception brief at the end. Estimates are working hours with Claude Code, tests
included. Paid calls are listed; everything else runs on fixtures (free).

## Goal of this step

Since V11 the user's goals are confirmed (ranked, main first, never guessed). V12 makes the pack
follow them: what is in the pack, its order, the Summary and the first moves depend on the goals.
"Brand perception" (one of the eight goals) gets real analysis: how people talk about the user's
brand, how many mention it without being asked, how they feel about it, and whether they tell it
apart from its parent brand.

Out of scope (owner's decision, 2026-10-09): customer journey section, brand voice word lists,
AI-search visibility, "refresh this brief" and scheduled refreshes.

## Findings that shape the plan (current code)

1. Every pack gets the same sections in the same order (`synthesis/write.py` `SECTION_ORDER`;
   `frontend/src/pages/PackPage.tsx` `PARTS`). Goals reach only the agent loop, the section "so
   what" lines and the playbook call (V11).
2. The relevance check, extraction and writing see topic, market, languages, audience and research
   questions (`collect/relevance.py` `brief_block`), not the goals, offer or key question.
3. Post briefs, drafts and the calendar are written for every pack (playbook stage, V8), whatever
   the goal.
4. Extraction already records every brand named in a post with a stance (`brand_mentions`:
   positive, negative, mixed, neutral; `analysis/extract.py`). Competitors are clusters of those
   mentions, with counts and shares computed in code (`analysis/metrics.py` `competitor_shares`).
   Nothing treats the user's own brand differently, and nothing records how a brand relates to a
   parent brand.
5. Every post keeps the source unit that found it (`documents.source_unit`, e.g.
   `reddit:query text`), so code can tell posts found by searching the brand's name ("prompted")
   from posts that name it unasked ("unprompted").
6. The user's brand name is not an input: the offer is ("oat bars"), the brand is not.

## Design

### 1. goals.yaml decides the pack (config, no numbers in code)
Each goal gets:
- `lead`: the sections that come first for it, in order (ids as the pack page uses them), e.g.
  - content_plan: plan (post briefs + calendar), their words, channels, what performs, moments
  - campaign_launch: plan, news hooks and timing, tensions, channels
  - positioning: position, competitors, tensions, objections, their words (say this / not this)
  - product_validation: opportunities (supported / signal, existing solutions), pain points,
    hypotheses, segments
  - market_entry: culture and codes, their words, channels and communities, platform lens,
    competitors
  - brand_perception: **brand perception (new)**, competitors, objections and trust markers, their
    words
  - sales_enablement: objections and objection answers, pain points, segments by role, competitors
  - understand_audience: today's order
- `needs`: extra work only this goal pays for: `brand_perception` for brand_perception. Post briefs,
  drafts and the calendar stay in every pack (owner's decision 1).

Code builds `section_order` from the ranked goals: the main goal's lead sections, then the next
goal's (no repeats), then everything else in today's order. Sections are never dropped, only
ordered; the brand-perception section exists only when that goal is chosen.

### 2. A cap on goals per mode
`modes.yaml` `goals.max: 3` for both modes (owner's decision 2). More goals picked -> the first three
are kept; the rest are listed as "left out: at most 3 goals per pack", like left-out languages.
Shown on the plan screen and in Method.

### 3. Goals reach every analysis step
`BriefContext` gains goals (plain words), offer and stage, key question and, for brand perception,
the brand names. `brief_block` prints them for relevance, extraction, clustering and writing, with
one rule: relevance stays about the topic and audience (goals decide emphasis, never what counts
as on-topic), so a narrow goal cannot starve the corpus.

### 4. Summary and first moves per goal
- `snapshot.for_goals[]`: one block per kept goal, main first: `{goal, headline, first_moves[]
  (DO ids), success_measure, item_ids[]}` - written in the existing playbook call (no extra call);
  every item id checked in code.
- `do_first[].goal`: the goal each action serves. The three actions lean to the main goal.
- The page opens with "For your goal: Positioning" (then the second goal), each with its first
  moves and links into the sections that matter for it.

### 5. Brand perception (the goal's analysis)
**Inputs.** New intake fields `brand` (the user's brand as people write it, aliases allowed) and
`parent_brand` (optional). When brand_perception is chosen:
- web app: the goal card shows "Your brand (and parent brand, if any)" as soon as the chip is
  picked; the brand is then required (owner's decision 3);
- a brief that states the brand: the understanding gains a `brand` input (quote checked, as in V11);
- agents and CLI: `brand` is required with the brand_perception goal (`--brand`, `--parent-brand`).

**Collection.** The brand and parent brand join `must_search` (like competitors the user names:
finish is refused until each was searched by name). The agent also keeps its usual topic searches,
so unprompted mentions can appear.

**Extraction** (same call, two optional fields, only when a brand is given):
- `brand_mentions[].aspect`: what about the brand the post talks about (price, service, app, ...),
  short English words;
- `brand_mentions[].relation`: for the user's brand when the post also names (or asks about) the
  parent: `same_as_parent`, `part_of_parent`, `distinct` or `unclear`.

**Numbers, all in code** (per brand; the parent shown next to it):
- mentions, distinct authors, platforms;
- **unprompted mentions**: posts naming the brand that were found by a search *not* containing the
  brand's name - the awareness signal; and **share of voice** among unprompted posts: brand vs
  competitors named in the same posts;
- **stance mix**: positive / negative / mixed / neutral shares;
- **differentiation**: share of brand posts that also name the parent, and the relation mix
  (same / part of / distinct / unclear).
Minimums in `scoring.yaml` (`brand_min_mentions`, e.g. 5). Below them the section says plainly
"too few mentions to judge" - and few unprompted mentions is itself reported as a finding about
awareness, never padded.

**Findings, written and verified like every other claim:** 2-5 items (`BRP-xx`): how the brand is
seen, what is praised and what is criticised (by aspect), and whether people tell it apart from the
parent - each with counts from code, quotes that are exact substrings, a confidence label (PRD 5.4)
and the claim check. One writer call for the section (only when the goal is chosen).

**Honest framing,** shown with the section: "Online mentions from vocal people, not a survey:
use it as a signal, not as awareness numbers."

**Where it shows:** a "How people see your brand" section in "Understand your audience" (first
when brand perception is the main goal), the Summary block for the goal, the full report,
quick brief, prompt block, Claude skill and MCP digest.

### 6. Exports and agents follow the order
Full report, quick brief, prompt block, skill and `get_pack_view` use `section_order` and start with
the main goal's block. The MCP digest gains `for_goals` and, when present, a short brand-perception
summary (numbers and safe-to-assert claims only).

## Schema 1.3

| Field | Migration from 1.2 |
|---|---|
| `section_order[]` (section ids, computed in code) | today's order |
| `snapshot.for_goals[] {goal, headline, first_moves[], success_measure, item_ids[]}` | empty |
| `do_first[].goal` | null |
| `brand_perception {brands[] {name, is_parent, mentions, unprompted, share_of_voice, distinct_authors, platforms, stance_mix, relation_mix, aspects_praised[], aspects_criticised[]}, findings[] (BRP-xx InsightItems), note}` | null (no brand perception before 1.3) |
| `brief.intake.brand`, `brief.intake.parent_brand`, `brief.intake.goals_left_out[] {goal, reason}` | null / empty |
| `brief.interpreted.understanding.brand` | missing |
| ID prefix `BRP` (PRD 6.5) | - |

Bump to `"1.3"`, extend `schemas/migrate.py`, CHANGELOG, `export-schema`, `npm run types`;
featured packs and examples migrated through the privacy check (as in V11).

## Files

- **Config:** `goals.yaml` (`lead`, `needs` per goal; brand question text), `modes.yaml`
  (`goals.max`), `scoring.yaml` (`brand_min_mentions`, `brand_min_unprompted`).
- **Schemas:** `enums.py` (BrandRelation, `BRP` prefix), `plan.py` (intake brand fields, goals left
  out, understanding.brand), `pack.py` + `migrate.py` + `schema_doc.py` (1.3).
- **Planning:** `agent/interpret.py` (cap goals, brand question rules, quote check for the brand),
  `prompts/interpret_plan.md`; `api/service.py` + `routes.py` (brand in answers and edits, agents'
  brand rule), `mcp_server.py`, `cli.py` (`--brand`, `--parent-brand`).
- **Collection:** `orchestrator.py` (brand into must_search and the loop's "what the user told us").
- **Analysis:** `collect/relevance.py` (`BriefContext`, `brief_block`), `prompts/relevance.md`
  (goals do not change what is on-topic), `analysis/extract.py` + `prompts/extract.md` (aspect,
  relation), new `analysis/brand.py` (all brand numbers), `analysis/metrics.py` (unprompted from
  source units).
- **Synthesis:** new `synthesis/brand.py` + `prompts/brand_perception.md` (one writer call, then
  the usual verify), `synthesis/write.py` (`section_order` from goals.yaml), `synthesis/playbook.py`
  + `prompts/playbook.md` (`for_goals`, `do_first[].goal`, post briefs only for content goals),
  `synthesis/finalize.py`, `synthesis/verify.py` (BRP items through the claim check).
- **Exports:** `markdown.py`, `quick_brief.py`, `prompt_block.py`, `skill.py`, `views.py` (digest).
- **Frontend:** `lib/api.ts`, `pages/Ask.tsx` (brand field on the goal card, goals left out on the
  plan screen), `pages/PackPage.tsx` (section order, "For your goal" blocks, new brand section),
  new `components/brand.tsx`, `components/summary.tsx`.
- **Fixtures:** a recorded brand-perception corpus and writer answer for LLM_FAKE; fake planning
  path for a brand brief.
- **Evals:** `evals/briefs.yaml` - a brand-perception brief (a public brand with a parent brand,
  e.g. a supermarket's own premium range) with expectations: brand searched by name, unprompted
  count computed, section present, every BRP quote grounded.
- **Docs first:** PRD (new FR for goal-driven packs and brand perception), README (V12 line),
  plan status.

## Tests (free)

- Same brief, goals [positioning] vs [content_plan]: different `section_order`, Summary blocks and
  do-first goals; post briefs, drafts and calendar in both.
- Goal cap: four goals -> three kept, one left out with the reason.
- Goals, offer and key question appear in the relevance, extraction and writer prompts; the
  relevance rule about emphasis is present.
- Brand perception chosen without a brand -> brand required (web answers refused, agents and CLI
  get a plain error); a brief that states the brand -> no brand question.
- Brand and parent are searched by name before finish.
- Brand numbers in code: prompted vs unprompted from source units, share of voice, stance and
  relation mixes; below the minimum -> "too few mentions to judge" and the awareness finding.
- BRP findings: exact-substring quotes, counts from code, claim check applied, never above the
  evidence.
- Exports and MCP digest follow `section_order` and include the goal blocks and brand summary.
- Migration 1.2 -> 1.3 of every featured and example pack validates.
- E2E: brand field appears when "Brand perception" is picked; the pack page shows "For your goal"
  and the brand section first for a brand-perception pack (fixtures); a11y checks; phone width.

## Money and time

- **Work:** about 14-16 hours.
- **Paid:** planning calls on the eval briefs and 3 brand briefs (Anthropic about $0.20); **one real
  Quick run of the brand-perception eval brief** to check the section end to end (Anthropic up to
  $2.80, Apify up to $1.80 - the Quick caps in modes.yaml; typically less).

## Decisions for the owner

All five answered on 2026-10-09 (see Status).
