# User research

**What this is.** Four moderated user tests of an early SIGNAL prototype (Part 1), and the web-scraping use
cases that marketing and content teams have, including the ones the participants raised (Part 2).

**Privacy.** Participants are described by role and company only. Names are left out on purpose.

**How it was used.** Most of the changes V1-V13 in [CHANGELOG.md](../CHANGELOG.md) come from the findings
below. The table at the end of Part 1 shows which change answers which finding.

---

## Part 1 - User testing interviews

### 1. About

| | |
|---|---|
| Researcher | The builder of SIGNAL |
| Product | SIGNAL, an early prototype: free-tier hosting (Render), Claude + Apify |
| Sessions | 4 moderated, remote, screen-shared sessions |
| Recruitment | A women's tech and marketing community, and personal network |

### 2. Research goals

- Validate whether the content pack is useful in real marketing work.
- Learn which sections are valuable, which are noise, and how the output should be structured and formatted.
- Understand whether the value would justify paying for it, given the running costs of Apify and Claude.
- Learn how SIGNAL compares to tools marketers already use. The builder has no marketing background.
- Find usability problems in the input, planning and output stages.

### 3. Participants

| | Role |
|---|---|
| **P1** | Contractor at Miro (formerly an employee). Freelance marketer with B2B clients in industrial hardware and manufacturing software. Building an AI agent that keeps a Notion content calendar for a client with no marketing team. |
| **P2** | Lifecycle marketing and advisory boards at Booking.com for Business; previously built community at Miro; co-founder of a women's tech and marketing community. Long-time Netherlands resident. |
| **P3** | Senior marketer, about 18 years in IT, most recently in CMO roles. Helping IT Rebels (a Microsoft partner and system integrator) build its marketing operation. Heavy user of SEMrush, HubSpot and Supermetrics. |
| **P4** | B2B SaaS marketer (most recently fintech), based in the Netherlands. Upskilling in AI and building a personal brand; exploring a product idea in the event-venue space. Builds with Claude Code, n8n, Apify and Notion. |

**Session order.** P1, P2 and P3 tested on the same day, P1 first. P4 tested on a later day, after a
redeploy that added clarifying questions and short-term persistence.

### 4. Session summaries

#### Session 1 - P1 (Miro contractor, manufacturing clients)

**Topic.** Digital manufacturing: connecting legacy machines and frontline operations in the European
market (one of P1's clients' spaces). The second run narrowed to "business owners in Europe".

**Outcome.** Run 1 collected sources but never produced the pack. Run 2 completed, and the pack was reviewed
and copied into Notion.

**What worked**
- **Research questions and hypotheses** felt "in the right direction".
- **Industry jargon.** The tool surfaced terms (MES, Mittelstand, data sovereignty) that help speak the
  audience's language.
- **Source choices** were a reasonable start: large, active subreddits such as r/manufacturing and r/PLC.
- **Hooks** built from the audience's own words were useful for content-calendar planning. Several "have
  legs" but need reworking.
- **White space / opportunities** was useful for business or post ideas.
- **The hand-off to Notion** was seamless.
- **P1 would use it** as a contractor who can't go deep on every industry.

**Problems observed**
- **Market.** It defaulted to "global" although EU was stated.
- **Languages.** At first only English, German and Dutch. Saying "Europe" explicitly added French and
  Italian.
- **Too much Reddit.** Results over-index on Reddit, where promotion is hard and business buyers rarely
  talk.
- **Thin evidence.** Narrowing to business owners returned thin evidence, and the segments section was
  empty.
- **Repetition across sections.** Tensions and objections overlapped heavily, and themes repeated.
- **"What performs"** was a list of Reddit posts, not a recommendation.
- **"Copy brief"** pasted a condensed version P1 didn't expect.
- **No persistence.** Closing the tab lost the pack.

**Suggestions**
- **Ask follow-up questions after the topic:** buyer, influencer or end user, and the goal. Messaging
  differs sharply between leadership (ROI, time, money) and day-to-day users.
- **Nest each challenge** with how the objection is voiced, and a counter.
- **Replace lists of posts** with a concrete takeaway, with sources underneath.
- **Lean into hooks** and recommend what the full post should say.
- **Condense.** The more applicable and less theoretical, the better.
- **"Moments" could capture timing** (e.g. Q4 budget season) when evidence supports it.
- **Price** at least above the average cost per run.

#### Session 2 - P2 (Booking.com for Business)

**Topic.** Brand recognition and sentiment for Booking.com for Business in Europe, and whether people
distinguish it from consumer Booking.com.

**Outcome.** The run failed twice while building the pack. Refreshing or opening a new tab did not reset
the state. No pack was reviewed.

**What was learned anyway**
- **Very little discussion was found.** Only Reddit and YouTube were searched. P2 said this confirmed the
  assumption that the brand is not well recognised or differentiated.
- **The product.** It is a B2B corporate travel tool for SMBs: shared accounts, spend control and
  traveller visibility. It is often confused with consumer Booking.com.

**UX feedback**
- **The topic field gets treated like a ChatGPT search bar** (e.g. just "booking.com"), so the scope is
  too broad.
- **A guided flow** that asks follow-up questions to narrow the scope was supported.
- **The purpose of the brand voice field** (tuning hooks and posts) needed explaining.

#### Session 3 - P3 (Senior marketer / CMO, IT Rebels)

**Topic.** Microsoft Copilot and AI-agent implementation in the Dutch market: do companies worry more about
adoption or governance (agent cost visibility, managing 10+ agents)? English and Dutch. Competitors set to
HSO, Spark and one other system integrator.

**Outcome.** It collected 185 results from 40 sources, then content generation failed on a token/rate cap
introduced by that day's redeploy. Only a partial pack, with no hooks or content.

**What worked**
- The interface is intuitive and "speaks for itself".
- The research plan and questions were relevant.
- The live log of what the agent is doing was understandable.
- Searching Reddit was welcome; P3 wants to build presence there.

**Key feedback: the market is crowded.** Established tools already offer signal tracking, topic suggestions,
hooks and first drafts:
- HubSpot: agent-based signal tracking, strongest with first-party data.
- SEMrush and Ahrefs: signal tracking and content suggestions.
- Supermetrics: data from many sources, hooks and first drafts.
- Salesforce Marketing Cloud: similar features.
- Marketing agencies: signals, content, campaigns and design as a service.

**Ideal output for P3**
- **Topics ranked** by relevance and volume.
- **Competitor tracking:** competitor content and citations on the same topics.
- **Hooks, then first drafts.**
- **One place** that combines what several tools do.
- **Brand setup before research:** words to use and avoid, and tone.

**Opportunities flagged**
- **LinkedIn** is a major blind spot for marketers and would be a strong differentiator.
- **Agencies.** Partner with or build for marketing agencies.

#### Session 4 - P4 (B2B SaaS marketer, event-venue idea)

**Topic.** Event venues and event organising in the Netherlands, kept intentionally broad.

**Outcome.** Clarifying questions appeared after the topic. The run completed: 145-154 posts collected, only
36 judged relevant. The full pack was reviewed, including "Ask this pack" and the hand-off.

**What worked**
- **Clarifying questions and an editable plan.** Adding "Netherlands" pulled in more relevant Dutch
  sources.
- **The live view** of search queries.
- **The local market's terminology and tone of voice.**
- **"What they want / what stops them" with direct quotes** was the strongest section: quotes build trust
  that insights are real.
- **Supported vs. early-signal labels** on opportunities were clear. One opportunity validated P4's own
  direction.
- **Anonymised usernames (GDPR)** were appreciated.
- **The creative brief and tone-of-voice hand-off** were the favourite parts. They even captured cultural
  nuance (informal Dutch, occasional emoji).
- **Saved packs** reappear in the same browser.

**Problems observed**
- **The pack "jumped too far ahead".** P4 wanted the pre-phase (how organisers find and book venues), not
  the event itself.
- **Information felt scattered.** P4 wanted step 1, 2, 3.
- **Mixed Dutch and English content** with no translation.
- **The best section was buried.**
- **Confusing hypothesis labels.** Hypotheses marked "not seen in posts" were true by general knowledge.
- **Unclear labels:** "landscape", "culture codes", "moments", "paid".
- **Weak hooks and snippets.** Hooks were less clear than the brief, and some Reddit snippets made no sense
  out of context.
- **Repetition** between hooks and other sections.
- **"Ask this pack" said "not enough evidence"**, because it only searches the kept posts.

**Suggestions**
- A translation button.
- The clearest summary first.
- Mark general-knowledge claims.
- Clickable pain points.
- RSS feeds as a source, capped scraping and recent content.

### 5. Cross-session findings

| | Finding | Sessions |
|---|---|---|
| **F1** | **Briefs are too vague without guidance.** Results improve sharply when the audience (buyer vs. user) and the goal are given. | P1, P2, P4 (P3 indirectly) |
| **F2** | **Reliability is the biggest blocker.** 3 of 4 sessions hit a failure in pack generation; two participants never saw output. | P1, P2, P3 |
| **F3** | **Output needs structure, synthesis and less repetition.** A clear lead summary, a logical order, and recommendations with sources underneath. | P1, P4 |
| **F4** | **Audience language and real quotes are the most valued content.** | P1, P4 |
| **F5** | **Hooks have potential but aren't actionable yet.** Users want the post angle and the channel. | P1, P4 |
| **F6** | **Source coverage and relevance are weak.** Reddit-heavy, thin for B2B buyers, about 25% of posts relevant, no LinkedIn. | P1, P2, P4 |
| **F7** | **Market and language handling is inconsistent**, and there is no translation. | P1, P4 |
| **F8** | **Differentiation is unproven** against HubSpot, SEMrush, Ahrefs, Supermetrics, Salesforce and agencies. | P3, P1 |
| **F9** | **Some labels and features are unclear.** | P1, P4 |

### 6. Bugs found (all fixed in 1.1.0)

| | Bug | Session |
|---|---|---|
| B1 | Pack generation failed at the final stage | 1, 2 |
| B2 | A token/rate cap left a partial pack with no hooks or content | 3 |
| B3 | A run that stopped early did not build the pack from what was collected | 1 |
| B4 | A failed state persisted across refresh and a new tab | 2 |
| B5 | Packs were not saved (browser-only in session 4) | 1-3 |
| B6 | The market defaulted to "global" despite a region in the brief | 1 |
| B7 | Free hosting causes slow cold starts | all |

B7 is a limit of free hosting. A keep-alive and the static mirror soften it.

### 7. What was built in response

| Finding | Change |
|---|---|
| F2, B1-B5 | **V1** Never lose a run: packs saved in Postgres; any run with enough posts ends with a pack |
| F1 | **V3** Clarifying questions, then **V11** goals and offer always asked |
| F7, B6 | **V2** Markets and languages; quote translation (`translate-quotes`) |
| F3, F9 | **V4** Every finding once, **V9** revised pack page, plain labels |
| F5 | **V8** Post briefs, drafts and a 4-week calendar |
| F6 | **V6** LinkedIn, then X, Facebook and **V13** forum feeds |
| "Timing" suggestion | **V7** News hooks and timing |
| P2's brand question | **V12** Brand perception |

### 8. Competitive landscape (as raised by participants)

| Tool | What it does |
|---|---|
| HubSpot | Agent-based signal tracking; first-party data |
| SEMrush / Ahrefs | Signal tracking, content suggestions |
| Supermetrics | Data aggregation, hooks, first drafts |
| Salesforce Marketing Cloud | Similar marketing-intelligence features |
| Buzzabout | The closest comparable tool |
| Marketing agencies | Signals + content + campaigns + design as a service |
| AI-visibility tools | Company-level AI authority scoring (shown by P4) |

**Positioning angles to test:**
- quote-backed audience voice with hallucination checks;
- local and multilingual market research;
- LinkedIn coverage;
- an affordable option for freelancers and small teams;
- a white-label engine for agencies.

### 9. Open questions

- Would users pay, and how much, given a run cost that must at least be covered?
- Who is the primary customer: in-house marketers, freelancers and contractors, or agencies?
- Is a one-off report or an ongoing feed (content-calendar input) more valuable?
- Which sources actually reach B2B buyers and business owners?
- What is the unique proposition versus HubSpot, SEMrush and Supermetrics?

---

## Part 2 - Web-scraping use cases for marketing and content teams

A general overview of how marketing and content teams use web scraping, merged with the use cases the four
participants raised. Each use case appears once. Those raised in an interview are marked with the
participant: **[P1]** to **[P4]**.

### 1. Audience and market research
- **Audience language and terminology:** the exact words, jargon and phrasing the audience uses. [P1, P3, P4]
- **Pain points, objections and worries:** what frustrates people and what stops them from buying or
  adopting (e.g. unclear pricing, cost visibility, governance). [P1, P3, P4]
- **Audience segmentation:** how buyers, influencers and end users each talk about a product. [P1]
- **Customer journey mapping:** how people search, compare and contact providers before buying. [P4]
- **Assumption and hypothesis validation:** check your beliefs against real conversations, with quotes. [P4]
- **Product and business idea validation:** real demand or an unserved need, before building. [P1, P4]
- **Local and cultural nuance:** how a country or region communicates (language, tone, formality, habits).
  [P1, P3, P4]
- **Rapid industry onboarding:** a fast primer on an unfamiliar industry for contractors and agencies. [P1]
- Persona development from community discussions and job titles.
- Market sizing: count players, products or listings in a category.
- Product and category trends.

### 2. Content strategy and creation
- **Topic and trend discovery:** what the audience asks and discusses on forums, Q&A sites, Reddit, news
  and social. [P1, P3]
- **Topic demand ranking:** how many people ask similar questions. [P3]
- **Hooks, post ideas and first drafts** for LinkedIn, blogs and social. [P1, P3, P4]
- **Content calendar feeding:** an ongoing calendar of recommended topics and posts. [P1]
- **Creative briefs and tone-of-voice guides** that capture the audience's tone and keywords. [P4]
- **Brand-voice-consistent output:** a brand's tone, preferred words and banned words. [P3]
- **Context packs for AI tools:** research exported as context for Claude, Notion and others, so all
  generated work uses the same language. [P1, P3, P4]
- **Content format discovery:** which formats the audience prefers. [P1]
- **Newsjacking and timing:** current events and seasonal moments (e.g. Q4 budget cycles). [P1]
- **Q&A over research:** follow-up questions on collected research. [P4]
- Content curation for newsletters and roundups.
- Original data studies for reports and infographics.
- Content briefs from top-ranking pages.
- Content inventory, audits and refresh triggers.
- Repurposing published content.

### 3. Competitive intelligence
- **Competitor content tracking:** what competitors publish, how often, on which topics. [P3]
- **Competitor and existing-solution scanning:** who already serves the market, and how well. [P1, P4]
- Pricing, product and feature monitoring.
- Messaging and positioning analysis.
- Website change detection.
- Ad intelligence from public ad libraries.
- Hiring signals.
- Partnership and integration tracking.
- Promotional calendar mapping.
- Stock and availability tracking.

### 4. SEO and AI search visibility
- **AI search visibility and citations:** how often a brand and its competitors are cited in AI answers.
  [P3, P4]
- **Visibility-driven topic selection:** scraped signals combined with search and ads data. [P3]
- SERP tracking.
- Keyword research.
- Content gap analysis.
- Technical site audits.
- Backlink prospecting.
- Local SEO.
- Structured data checks.

### 5. Brand monitoring and reputation
- **Brand awareness and recognition:** how well-known a brand or sub-brand is in a market. [P2]
- **Brand differentiation:** whether people tell a sub-brand apart from its parent. [P2]
- **Sentiment analysis** in reviews, forums and social posts. [P2]
- Brand mentions.
- Review monitoring.
- Crisis detection.
- Brand protection.
- MAP compliance.

### 6. Channels and social media
- **Channel discovery:** where the audience spends time and where to build presence. [P1, P3, P4]
- **LinkedIn signal tracking**, a known gap in many tools. [P3]
- Hashtag and trend monitoring.
- Influencer discovery.
- Engagement benchmarking.
- User-generated content discovery.
- Comment analysis.

### 7. Lead generation and growth
- Prospect lists.
- Account enrichment.
- Technographic data.
- Event mining.
- Intent signals (funding, hiring, expansion).

### 8. E-commerce and product marketing
- Catalog enrichment.
- Marketplace listing optimisation.

### 9. Performance marketing and analytics
- Landing page monitoring.
- Affiliate and partner compliance.
- Ad placement verification.
- Dashboard feeds from sources without an API.

### 10. PR and communications
- Media list building.
- Coverage tracking.
- Award and speaking opportunities.

### 11. Internal operations
- Website QA across regional sites.
- Content governance.
- CMS migration.
- Knowledge bases for AI.
