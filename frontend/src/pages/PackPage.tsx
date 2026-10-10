// S3 PACK PAGE (PRD 10.2, change V9): three parts - Summary, Understand your audience, Act on it - plus The research
// (collapsed). Sticky part nav (a menu on phones), progressive disclosure, evidence drawer, View as agent, Hand off.
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Braces, History, Menu, MessageCircleQuestion, RotateCcw, Share2, TextQuote, ArrowUp } from "lucide-react";
import { friendlyError, getPack, getPackInputs, type ContextPack, type InsightLike, type Label } from "../lib/api";
import { indexPack, labelCounts } from "../lib/packIndex";
import { safeUrl } from "../lib/safe";
import { ConfidenceBadge } from "../components/badges";
import { BrandPart } from "../components/brand";
import { CoverageStrip } from "../components/callouts";
import { HookCard, PackContext, SourceCard, TensionCard, usePack } from "../components/cards";
import { applyFilter, EmptyNote, type Filter, ItemSection, SectionLead, type SectionNotes, ShowMore, TableSection } from "../components/blocks";
import { SummaryPart } from "../components/summary";
import { CHANNEL, PlanPart } from "../components/plan";
import { GuideContext, useLoadGuide } from "../lib/readingGuide";
import { CopyButton } from "../components/CopyButton";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { AgentJson } from "../components/AgentJson";
import { Handoff } from "../components/Handoff";
import { AskPanel } from "../components/AskPanel";
import { Skeleton } from "../components/Skeleton";
import { ErrorNote } from "../components/ErrorNote";
import { rerunUrl } from "../lib/rerun";
import { packTitle } from "../lib/title";
import { platformName } from "../lib/unitWords";

const DEFAULT_ORDER = ["their-words", "want-stops", "segments", "generic", "landscape", "brand", "plan", "channels",
  "performs", "opportunities", "guardrails"];

const PARTS: { id: string; title: string; sections: [string, string][] }[] = [
  { id: "summary", title: "Summary", sections: [] },
  { id: "understand", title: "Understand your audience", sections: [["brand", "Your brand"], ["their-words", "Their words"],
    ["want-stops", "Want / what stops them"], ["segments", "Segments"], ["generic", "Generic AI vs. people"],
    ["landscape", "Landscape"]] },
  { id: "act", title: "Act on it", sections: [["plan", "Your plan"], ["channels", "Channels"], ["performs", "What performs"],
    ["opportunities", "Opportunities"], ["guardrails", "Guardrails"]] },
  { id: "research", title: "The research", sections: [] },
];
const GLYPH: Record<Label, string> = { strong: "●", moderate: "◐", emerging: "○", speculative: "◌" };
const STOPPED: Record<string, string> = {
  finish: "finished when it judged the evidence enough", tool_call_limit: "stopped at its move limit",
  time_limit: "stopped at the time limit", budget_limit: "stopped at the budget limit",
  no_tool_call: "stopped when it made no further call", error: "stopped after an error", stopped: "was stopped by hand",
};
const PRIVACY_LINE = "Collected posts are deleted after 30 days. Author names are never stored.";

type Tension = InsightLike & { want: { text: string; evidence_ids: string[] }; but: { text: string; evidence_ids: string[] } };
const asItems = (x: unknown) => x as InsightLike[];

function Section({ id, title, agent, agentData, name, version, children, note }: {
  id: string; title: string; agent: boolean; agentData: unknown; name: string; version: string;
  children: React.ReactNode; note?: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="pack-section mb-14">
      <header className="mb-4 flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-2">
        <h2 id={id} className="scroll-mt-24 text-xl font-semibold tracking-tight text-ink">{title}</h2>
        {note && <p className="text-sm text-ink-3">{note}</p>}
      </header>
      {agent ? <AgentJson name={name} data={agentData} schemaVersion={version} /> : children}
    </section>
  );
}

function Sub({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-3">{title}</h3>
      {children}
    </div>
  );
}

/** UX audit: marketers see "posts" (opens the evidence); the item id stays in the accessible name and tooltip,
 *  and in Developer view, so ids still match the JSON and exports. */
/** UX audit: the pack is long - after a screen or two, a small button jumps back to the top (and the sections). */
function BackToTop() {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const onScroll = () => setShown(window.scrollY > 1200);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  if (!shown) return null;
  return (
    <button type="button" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
            className="fixed bottom-4 right-4 z-20 inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-paper px-3 py-2 text-sm text-ink shadow-md hover:border-ink print:hidden">
      <ArrowUp aria-hidden="true" size={14} /> Top and sections
    </button>
  );
}

function IdButton({ id, label = "posts" }: { id: string; label?: string }) {
  const { onOpen } = usePack();
  return (
    <button type="button" onClick={() => onOpen?.(id)} title={`Open the posts behind this (${id})`}
            aria-label={`Open the posts behind ${id}`}
            className="inline-flex items-center gap-0.5 rounded px-0.5 text-xs text-ink-3 underline decoration-line-strong underline-offset-2 hover:text-ink">
      <TextQuote aria-hidden="true" size={11} />{label}
    </button>
  );
}

function Ids({ ids }: { ids: string[] }) {
  return <span className="inline-flex flex-wrap gap-x-1">{ids.map((id) => <IdButton key={id} id={id} />)}</span>;
}

function SourceLink({ url, label = "source" }: { url: string | null | undefined; label?: string }) {
  const safe = safeUrl(url);
  return safe ? <a href={safe} target="_blank" rel="noopener noreferrer nofollow" className="underline underline-offset-2">{label}</a> : null;
}

function TimingChips({ timing }: { timing: ContextPack["channel_plan"][number]["timing"] }) {
  if (!timing?.length) return null;
  return (
    <div className="mt-2">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-3">When</p>
      <ul className="mt-1 flex flex-wrap gap-2">
        {timing.map((t, n) => (
          <li key={n} title={t.why}
              className={`inline-flex flex-wrap items-center gap-1 rounded-full border px-2 py-0.5 text-xs text-ink-2 ${t.claim_type === "external" ? "border-dashed border-ink-3" : "border-line"}`}>
            <span className="text-ink">{t.label}</span><span>· {t.when}</span>
            {t.claim_type === "observed"
              ? <><span>· seen in posts</span>{t.item_id && <IdButton id={t.item_id} />}</>
              : <><span>· external</span><SourceLink url={t.source_url} /></>}
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- sections ------------------------------------------------------------------------------

function Channels({ pack }: { pack: ContextPack }) {
  return (
    <ShowMore items={pack.channel_plan} limit={3} render={(part) => (
      <ol className="space-y-3">
        {part.map((c) => (
          <li key={c.id} className="rounded-lg border border-line p-4">
            <p className="flex items-baseline gap-2"><span className="font-mono text-sm text-ink-3">{c.priority}.</span>
              <span className="font-medium text-ink">{CHANNEL[c.platform] ?? c.platform}</span>
              {c.posts_per_week ? <span className="text-xs text-ink-3">{c.posts_per_week} post{c.posts_per_week === 1 ? "" : "s"} a week</span> : null}
              </p>
            <p className="mt-1 text-sm text-ink">{c.why}</p>
            <p className="mt-2 text-sm text-ink-2">Formats: {c.formats.join(", ") || "-"}</p>
            {c.communities_or_hashtags.length > 0 && <p className="text-sm text-ink-2">Where: {c.communities_or_hashtags.join(", ")}</p>}
            {c.tone_note && <p className="text-sm text-ink-2">Tone: {c.tone_note}</p>}
            <TimingChips timing={c.timing} />
          </li>
        ))}
      </ol>
    )} />
  );
}

/** Packs made before V8 have no post briefs: their plan is this week's five posts. */
function ThisWeek({ pack }: { pack: ContextPack }) {
  const pb = pack.playbook;
  const hooks = Object.fromEntries(pb.hooks.map((h) => [h.id, h.text]));
  const news = Object.fromEntries((pack.news_hooks ?? []).map((h) => [h.id, h]));
  const planText = pb.this_week.map((w) => `${w.day}: ${w.platform}, ${w.format} - "${hooks[w.hook_id] ?? w.hook_id}" - ${w.angle}`).join("\n");
  if (!pb.this_week.length) return <EmptyNote fallback="No posts planned in this pack." />;
  return (
    <>
      <div className="mb-2 flex justify-end"><CopyButton text={planText} label="Copy plan" /></div>
      <TableSection caption="This week" rowKey={(r) => r.id} rows={pb.this_week} columns={[
        // UX audit: "tuesday" wrapped as "tue / sda / y" in the narrow column - short day names, never broken
        { header: "Day", cell: (r) => r.day.charAt(0).toUpperCase() + r.day.slice(1, 3), kind: "data",
          className: "whitespace-nowrap" },
        { header: "Where", cell: (r) => `${CHANNEL[r.platform] ?? r.platform} · ${r.format}`, className: "min-w-[8rem]" },
        { header: "Hook", cell: (r) => <>{hooks[r.hook_id]} <IdButton id={r.hook_id} /></> },
        { header: "Angle and why now", cell: (r) => {
          const n = r.news_hook_id ? news[r.news_hook_id] : undefined;
          return <>{r.angle}<span className="block text-xs text-ink-3">{r.why_now}</span>
            {n && <span className="block text-xs text-ink-2">Rides the news: {n.headline} ({n.date}, <SourceLink url={n.source_url} />)</span>}</>;
        } },
      ]} />
    </>
  );
}

/** V9: what they want and what stops them, with tensions as the bridge between the two. */
function WantStops({ pack, filter, meta }: { pack: ContextPack; filter: Filter; meta: (n: string) => SectionNotes | undefined }) {
  const { claims } = usePack();
  const tensions = applyFilter(asItems(pack.tensions), filter);
  const stops = [...asItems(pack.pain_points ?? []), ...asItems(pack.objections)];
  return (
    <>
      <div className="grid gap-6 lg:grid-cols-2">
        <ItemSection level={3} title="What they want" items={asItems(pack.motivations)} filter={filter} columns={1} limit={3}
                     meta={meta("motivations")} />
        <ItemSection level={3} title="What stops them" items={stops} filter={filter} columns={1} limit={3}
                     meta={meta("pain_points")} empty="No pain points or objections stood out." />
      </div>
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-3">Where wanting meets what stops them</h3>
      <SectionLead meta={meta("tensions")} />
      <ShowMore items={tensions} limit={2} render={(part) => (
        <div className="mb-6 space-y-3">{part.map((t) => <TensionCard key={t.id} item={t as Tension} />)}</div>
      )} />
      {!tensions.length && <p className="mb-6 text-sm text-ink-3">No tensions match this filter.</p>}
      {pack.playbook.objection_handling.length > 0 && (
        <details className="rounded-lg border border-line p-3">
          <summary className="cursor-pointer text-sm text-ink-2">How to answer their objections ({pack.playbook.objection_handling.length})</summary>
          <ul className="mt-2 space-y-2 text-sm">
            {pack.playbook.objection_handling.map((h) => <li key={h.objection_id} className="text-ink">
              {claims?.[h.objection_id] && <span className="block font-medium">“{claims[h.objection_id]}”</span>}
              {h.response} <IdButton id={h.objection_id} /></li>)}
          </ul>
        </details>
      )}
    </>
  );
}

const STATUS: Record<string, { word: string; glyph: string }> = {
  confirmed: { word: "Confirmed by the posts", glyph: "✓" },
  contradicted: { word: "Contradicted by the posts", glyph: "✕" },
  not_seen: { word: "Not seen in the posts", glyph: "–" },
};

/** V9: every generic point with what the posts show; then what a generic answer misses. */
function Generic({ pack }: { pack: ContextPack }) {
  const g = pack.snapshot.generic_vs_found;
  const rows = g.comparison ?? [];
  return (
    <div className="space-y-4">
      {rows.length > 0 ? (
        <TableSection caption="A generic AI answer checked against the posts" rowKey={(r) => r.generic_point} rows={rows} columns={[
          { header: "A generic answer says", cell: (r) => <span className="text-ink-2">{r.generic_point}</span> },
          { header: "What the posts show", cell: (r) => <span className="whitespace-nowrap">
            <span aria-hidden="true">{STATUS[r.status].glyph} </span>{STATUS[r.status].word}{" "}
            {r.item_ids.slice(0, 2).map((id) => <IdButton key={id} id={id} />)}</span> },
        ]} />
      ) : (
        <div className="rounded-lg border border-line bg-wash p-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-3">Generic answer (no research)</p>
          <ul className="list-disc space-y-1.5 pl-4 text-sm text-ink-3">{g.generic_points.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      )}
      {g.what_we_found.length > 0 && (
        <div className="rounded-lg border border-ink p-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink">New: what a generic answer misses</p>
          <ul className="space-y-2">
            {g.what_we_found.map((f) => <li key={f.text} className="text-sm text-ink">{f.text} <Ids ids={f.item_ids} /></li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function Guardrails({ pack }: { pack: ContextPack }) {
  const g = pack.guardrails;
  const flags = pack.compliance_flags;
  return (
    <div className="space-y-4 text-sm">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-dashed border-line-strong p-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink">Never claim</p>
          <ul className="list-disc space-y-1 pl-4 text-ink">{g.never_claim.length ? g.never_claim.map((x) => <li key={x}>{x}</li>) : <li>-</li>}</ul>
        </div>
        <div className="rounded-lg border border-line p-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink">Handle with care</p>
          <ul className="list-disc space-y-1 pl-4 text-ink">{g.sensitivities.length ? g.sensitivities.map((x) => <li key={x}>{x}</li>) : <li>-</li>}</ul>
        </div>
      </div>
      <p className="text-ink-2">{g.quote_reuse_note}</p>
      {flags.length > 0 && (
        <ul className="space-y-2">
          {flags.map((f) => (
            <li key={f.id} className="rounded-lg border border-line-strong p-3 text-ink-2">
              <span className="font-medium text-ink">Check with legal ({f.category.replace("_", " ")}).</span>{" "}
              {f.why} <span className="text-ink">Safer: {f.safer_wording}</span> <IdButton id={f.item_id} label="the item" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Voice({ pack, filter }: { pack: ContextPack; filter: Filter }) {
  const v = pack.voice;
  const g = pack.guardrails;
  const lexicon = applyFilter(asItems(v.lexicon), filter) as unknown as typeof v.lexicon;
  return (
    <>
      <div className="mb-6 space-y-1 text-ink">
        <p><span className="text-sm text-ink-3">Tone: </span>{v.tone}</p>
        {v.code_switching && <p><span className="text-sm text-ink-3">Mixing languages: </span>{v.code_switching}</p>}
        {v.category_words_they_use.length > 0 && (
          <p><span className="text-sm text-ink-3">What they call it: </span>
            <span className="font-serif">{v.category_words_they_use.join(", ")}</span></p>
        )}
      </div>
      <Sub title="Their words">
        <TableSection caption="Lexicon" rowKey={(r) => r.id} rows={lexicon} columns={[
          { header: "Their word", cell: (r) => <span lang={r.language}>{r.term}</span>, kind: "their" },
          { header: "Meaning", cell: (r) => r.meaning },
          { header: "Confidence", cell: (r) => <ConfidenceBadge label={r.confidence.label} matching={r.counts.matching} ofTotal={r.counts.of_total} /> },
          { header: "", cell: (r) => <IdButton id={r.id} />, kind: "data" },
        ]} />
        {v.phrases.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {v.phrases.map((p) => (
              <span key={p.id} className="rounded-md border border-line px-2 py-1">
                <span lang={p.language} className="font-serif text-ink">“{p.text}”</span> <IdButton id={p.id} />
              </span>
            ))}
          </div>
        )}
      </Sub>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-line p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink">Say this</p>
          <ul className="list-disc space-y-1 pl-4 text-sm text-ink">{g.say_this.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
        <div className="rounded-lg border border-dashed border-line-strong p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink">Don't say</p>
          <ul className="list-disc space-y-1 pl-4 text-sm text-ink">{g.not_this.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      </div>
    </>
  );
}

function Landscape({ pack, filter }: { pack: ContextPack; filter: Filter }) {
  const themes = Object.fromEntries(pack.landscape.themes.map((t) => [t.id, t.label]));
  const lens = pack.landscape.platform_lens;
  const culture = [...pack.culture.formats, ...pack.culture.communities, ...pack.culture.creators, ...pack.culture.codes];
  return (
    <>
      <ItemSection level={3} title="Themes" items={asItems(pack.landscape.themes)} filter={filter} titleKey={"label" as keyof InsightLike} />
      {lens.length > 0 && (
        <Sub title="Platform lens">
          <div className={`grid gap-3 ${lens.length > 1 ? "md:grid-cols-2" : ""}`}>
            {lens.map((l) => (
              <div key={l.id} className="rounded-lg border border-line p-4">
                <p className="flex items-baseline justify-between"><span className="font-medium text-ink">{platformName(l.platform)}</span>
                  <span className="font-mono text-xs text-ink-3">{l.kept_posts} posts · {l.id}</span></p>
                {l.tone && <p className="mt-2 text-sm text-ink">{l.tone}</p>}
                {l.what_is_unique && <p className="mt-1 text-sm text-ink-2">{l.what_is_unique}</p>}
                <ul className="mt-3 space-y-1.5">
                  {l.theme_shares.slice(0, 5).map((t) => (
                    <li key={t.theme_id} className="text-xs">
                      <div className="flex justify-between gap-2 text-ink-2"><span className="min-w-0">{themes[t.theme_id] ?? t.theme_id}</span>
                        <span className="font-mono">{Math.round(t.share * 100)}%</span></div>
                      <div className="mt-0.5 h-1 rounded-full bg-wash"><div className="h-1 rounded-full bg-ink" style={{ width: `${Math.max(2, t.share * 100)}%` }} /></div>
                    </li>
                  ))}
                </ul>
                {l.emotion_mix.length > 0 && (
                  <p className="mt-2 font-mono text-xs text-ink-3">
                    {l.emotion_mix.slice(0, 4).map((e) => `${e.emotion} ${Math.round(e.share * 100)}%`).join(" · ")}
                  </p>
                )}
              </div>
            ))}
          </div>
        </Sub>
      )}
      <ItemSection level={3} title="When it matters" items={asItems(pack.moments)} filter={filter} titleKey={"name" as keyof InsightLike} />
      {culture.length > 0 && <ItemSection level={3} title="Culture and codes" items={asItems(culture)} filter={filter} titleKey={"name" as keyof InsightLike} />}
      {pack.competitors.length > 0 && (
        <Sub title="Brands they mention">
          <TableSection caption="Competitors" rowKey={(r) => r.id} rows={pack.competitors} columns={[
            { header: "Brand", cell: (r) => r.name },
            { header: "Mentions", cell: (r) => `${r.mentions} · ${Math.round(r.share_of_mentions * 100)}%`, kind: "data" },
            { header: "How they talk about it", cell: (r) => r.tone || "-" },
          ]} />
        </Sub>
      )}
    </>
  );
}

function Playbook({ pack }: { pack: ContextPack }) {
  const pb = pack.playbook;
  const flagsFor = (id: string) => pack.compliance_flags.filter((f) => f.item_id === id);
  const cb = pb.creative_brief;
  const cbText = cb ? ["objective", "audience", "insight", "message", "tone"].map((k) => `${k}: ${(cb as Record<string, unknown>)[k]}`)
    .concat(cb.mandatories.length ? [`mandatories: ${cb.mandatories.join("; ")}`] : [], cb.avoid.length ? [`avoid: ${cb.avoid.join("; ")}`] : [])
    .join("\n") : "";
  return (
    <>
      <Sub title={`Hooks (${pb.hooks.length})`}>
        <p className="mb-3 text-sm text-ink-3">Drafts written by AI from the research. Review before use; items marked
          "check with legal" need sign-off.</p>
        <div className="space-y-3">{pb.hooks.map((h) => <HookCard key={h.id} hook={h} flags={flagsFor(h.id)} />)}</div>
      </Sub>
      {cb && (
        <Sub title="Creative brief">
          <div className="rounded-lg border border-line p-4">
            <div className="mb-2 flex justify-end"><CopyButton text={cbText} label="Copy brief" /></div>
            <dl className="space-y-2 text-sm">
              {(["objective", "audience", "insight", "message", "tone"] as const).map((k) => (
                <div key={k}><dt className="text-xs font-medium uppercase tracking-wide text-ink-3">{k}</dt><dd className="text-ink">{cb[k]}</dd></div>
              ))}
              {cb.mandatories.length > 0 && <div><dt className="text-xs font-medium uppercase tracking-wide text-ink-3">Must include</dt>
                <dd><ul className="list-disc pl-4 text-ink">{cb.mandatories.map((m) => <li key={m}>{m}</li>)}</ul></dd></div>}
              {cb.avoid.length > 0 && <div><dt className="text-xs font-medium uppercase tracking-wide text-ink-3">Avoid</dt>
                <dd><ul className="list-disc pl-4 text-ink">{cb.avoid.map((m) => <li key={m}>{m}</li>)}</ul></dd></div>}
            </dl>
          </div>
        </Sub>
      )}
      <Sub title="Keywords">
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          {(["seo", "paid", "negatives", "hashtags"] as const).map((k) => (
            <div key={k} className="rounded-lg border border-line p-3">
              <dt className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-3">{k === "seo" ? "SEO" : k}</dt>
              <dd className="font-mono text-xs text-ink">{pb.keywords[k].join(", ") || "-"}</dd>
            </div>
          ))}
        </dl>
      </Sub>
      {pb.targets.length > 0 && (
        <Sub title="Public communities and creators">
          <ul className="space-y-1 text-sm">
            {pb.targets.map((t) => {
              const url = safeUrl(t.url);
              return <li key={t.name} className="text-ink">{url ? <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="underline">{t.name}</a> : t.name}
                <span className="ml-2 font-mono text-xs text-ink-3">{t.kind} · {platformName(t.platform)}</span></li>;
            })}
          </ul>
        </Sub>
      )}
    </>
  );
}

function Method({ pack }: { pack: ContextPack }) {
  const c = pack.coverage;
  const n = c.counts;
  const funnel: [string, number][] = [["Collected", n.collected], ["Duplicates removed", n.duplicates], ["Spam removed", n.spam],
    ["Outside the time window", n.out_of_window], ["Relevant to the brief", n.relevant], ["Quoted as evidence", pack.evidence.length]];
  return (
    <>
      <Sub title="How the evidence was found">
        <ul className="space-y-1.5">
          {funnel.map(([k, v]) => (
            <li key={k} className="grid grid-cols-[12rem_1fr_4rem] items-center gap-3 text-sm">
              <span className="text-ink-2">{k}</span>
              <span className="h-1.5 rounded-full bg-wash"><span className="block h-1.5 rounded-full bg-ink" style={{ width: `${n.collected ? Math.max(1, (v / n.collected) * 100) : 0}%` }} /></span>
              <span className="text-right font-mono text-xs text-ink">{v}</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-sm text-ink-3">
          {n.undated} of {n.kept} kept posts have no date. The research agent made {c.loop.tool_calls} moves and{" "}
          {STOPPED[c.loop.finish_reason] ?? `stopped (${c.loop.finish_reason.replace(/_/g, " ")})`}
          {c.loop.fallback_used ? "; the remaining planned sources were collected automatically" : ""}{c.loop.top_up_used ? "; more evidence was collected from sources already working" : ""}.
        </p>
      </Sub>
      {pack.hypotheses.length > 0 && (
        <Sub title="Hypotheses from the plan">
          <TableSection caption="Hypotheses and what the evidence showed" rowKey={(r) => r.id} rows={pack.hypotheses} columns={[
            { header: "Hypothesis", cell: (r) => r.statement },
            { header: "Result", cell: (r) => r.status.replace(/_/g, " "), kind: "data" },
            { header: "Why", cell: (r) => r.why },
          ]} />
        </Sub>
      )}
      <Sub title="Sources kept and dropped">
        <div className="grid gap-2 md:grid-cols-2">
          {c.sources_used.map((s) => <SourceCard key={s.source_unit} source={s} />)}
          {c.sources_dropped.map((s) => <SourceCard key={s.source_unit} source={s} dropped />)}
        </div>
      </Sub>
      <Sub title="Decision log">
        <TableSection caption="Every research move" rowKey={(r) => String(r.seq)}
                      rows={[...c.decision_log].sort((a, b) => a.seq - b.seq)} columns={[
          { header: "#", cell: (r) => r.seq, kind: "data" },
          { header: "Move", cell: (r) => <>{r.tool.replace(/_/g, " ")}<span className="block font-mono text-xs text-ink-3 break-all">{r.source_unit ?? ""}</span></> },
          { header: "Why", cell: (r) => r.reason },
          { header: "Result", cell: (r) => r.result_summary, kind: "data" },
        ]} />
      </Sub>
      <Sub title="Privacy and limits">
        <div className="space-y-2 text-sm text-ink-2">
          <p>Only public posts are used, plus LinkedIn posts any logged-in user can see (never private groups, messages or closed profiles). Authors are stored as salted hashes, never names; emails, phone numbers, @handles and
            names written in posts are removed before analysis. Quoted excerpts are for internal research and briefs only,
            not for ads or other public material. {PRIVACY_LINE}</p>
          <p>Counts and confidence are computed in code from posts checked to belong to each finding; every quote is copied
            word for word from its post. Labels: strong, moderate, emerging, speculative. "Safe to state" means strong, observed
            and confirmed by the claim check. This is AI-assisted analysis and may contain errors; compliance flags are not
            legal advice.</p>
          <p><Link to={`/packs/${pack.pack_id}/replay`} className="inline-flex items-center gap-1 text-ink underline"><History aria-hidden="true" size={14} /> Watch how this pack was made</Link>
            <span className="ml-1 text-ink-3">- a recording of the research; it won't run again or cost anything.</span></p>
        </div>
      </Sub>
    </>
  );
}

// --- the page ----------------------------------------------------------------------------------

function PartNav({ order, hasBrand }: { order: string[]; hasBrand: boolean }) {
  const rank = (id: string) => (order.indexOf(id) < 0 ? order.length : order.indexOf(id));
  const links = PARTS.map((part) => (
    <li key={part.id}>
      <a href={`#${part.id}`} className="block rounded px-2 py-1 font-medium text-ink hover:bg-wash">{part.title}</a>
      {part.sections.length > 0 && (
        <ul className="mb-1 ml-2 border-l border-line pl-2">
          {part.sections.filter(([id]) => id !== "brand" || hasBrand)
            .sort((a, b) => rank(a[0]) - rank(b[0])).map(([id, label]) => (
            <li key={id}><a href={`#${id}`} className="block rounded px-2 py-0.5 text-ink-2 hover:bg-wash hover:text-ink">{label}</a></li>
          ))}
        </ul>
      )}
    </li>
  ));
  return (
    <>
      <nav aria-label="Pack parts" className="hidden print:hidden lg:block">
        <ul className="sticky top-20 space-y-1 text-sm">{links}</ul>
      </nav>
      <details className="sticky top-14 z-10 mb-4 rounded-lg border border-line bg-paper text-sm print:hidden lg:hidden">
        <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-ink"><Menu aria-hidden="true" size={15} /> Sections</summary>
        <ul className="space-y-1 px-2 pb-2">{links}</ul>
      </details>
    </>
  );
}

function Part({ id, title, children, lead }: { id: string; title: string; children: React.ReactNode; lead?: string }) {
  return (
    <section aria-labelledby={id} className={`pack-part mb-16 ${id === "summary" ? "" : "max-w-[760px]"}`}>
      <h2 id={id} className="mb-1 scroll-mt-24 text-2xl font-semibold tracking-tight text-ink">{title}</h2>
      {lead && <p className="mb-6 text-sm text-ink-3">{lead}</p>}
      {children}
    </section>
  );
}

export function PackBody({ pack }: { pack: ContextPack }) {
  const index = useMemo(() => indexPack(pack), [pack]);
  const guide = useLoadGuide();
  const [filter, setFilter] = useState<Filter>("all");
  const [agent, setAgent] = useState(false);
  const [handoff, setHandoff] = useState(false);
  const [asking, setAsking] = useState(false);
  const navigate = useNavigate();
  const claims = useMemo(() => Object.fromEntries([...index.items.entries()]
    .map(([id, it]) => [id, (it as unknown as { claim?: unknown }).claim])
    .filter(([, claim]) => typeof claim === "string")) as Record<string, string>, [index]);
  const meta = (name: string): SectionNotes | undefined =>
    (pack.sections_meta as Record<string, SectionNotes> | undefined)?.[name];
  const [drawer, setDrawer] = useState<string | null>(null);
  const counts = labelCounts(pack);
  const v = pack.schema_version;
  const sec = (id: string, title: string, name: string, data: unknown, children: React.ReactNode, note?: React.ReactNode) =>
    <Section id={id} title={title} agent={agent} agentData={data} name={name} version={v} note={note}>{children}</Section>;
  const order = pack.section_order?.length ? pack.section_order : DEFAULT_ORDER;   // V12: the user's goals decide it
  const rank = (id: string) => (order.indexOf(id) < 0 ? order.length : order.indexOf(id));
  const ordered = (items: [string, React.ReactNode][]) =>
    [...items].sort((a, b) => rank(a[0]) - rank(b[0])).map(([id, node]) => <Fragment key={id}>{node}</Fragment>);
  const title = packTitle(pack.brief.text, pack.brief.interpreted.topic);
  const partial = Boolean(pack.blind_spots[0]?.text.startsWith("Partial pack:"));
  useEffect(() => {
    const before = document.title;
    document.title = `${title} – SIGNAL`;
    return () => { document.title = before; };
  }, [title]);
  useEffect(() => {   // UX audit: a shared link to a section (#plan) opens at that section, not at the top
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (!id) return;
    const t = window.setTimeout(() => {
      const el = document.getElementById(id);
      el?.closest("details")?.setAttribute("open", "");
      el?.scrollIntoView();
    }, 50);
    return () => window.clearTimeout(t);
  }, [pack.pack_id]);
  useEffect(() => {   // printing / Save as PDF shows everything that is folded away on screen
    const open = () => document.querySelectorAll("main details").forEach((d) => d.setAttribute("open", ""));
    window.addEventListener("beforeprint", open);
    return () => window.removeEventListener("beforeprint", open);
  }, []);

  return (
    <GuideContext.Provider value={guide}>
    <PackContext.Provider value={{ evidence: index.evidence, onOpen: setDrawer, claims }}>
      <div className="pack-layout lg:grid lg:grid-cols-[13rem_1fr] lg:gap-10">
        <PartNav order={pack.section_order?.length ? pack.section_order : DEFAULT_ORDER} hasBrand={!!pack.brand_perception} />
        <div className="min-w-0 max-w-[760px] xl:max-w-[920px]">
          <header className="mb-4 space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight text-ink md:text-3xl">{title}</h1>
            {title !== pack.brief.text.trim() && (
              <details className="text-sm text-ink-2 print:hidden">
                <summary className="cursor-pointer underline-offset-2 hover:underline">The brief as written</summary>
                <p className="mt-1 whitespace-pre-line font-serif text-ink">{pack.brief.text}</p>
              </details>
            )}
            <p className="text-sm text-ink-3 print:hidden">
              Made {new Date(pack.generated_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
              {" "}· {pack.mode === "standard" ? "Standard" : "Quick"} research
            </p>
            <p className="hidden font-mono text-xs text-ink print:block">
              Context Pack {pack.pack_id} · {pack.generated_at.slice(0, 10)} · coverage grade {pack.snapshot.coverage_grade} · {pack.mode}
            </p>
            <div className="flex flex-wrap gap-2 print:hidden">
              <button type="button" onClick={() => setHandoff(true)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-ink hover:brightness-95">
                <Share2 aria-hidden="true" size={14} /> Share &amp; export
              </button>
              <button type="button" onClick={() => setAsking(true)} aria-expanded={asking}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-ink px-3 py-1.5 text-sm text-ink">
                <MessageCircleQuestion aria-hidden="true" size={14} /> Ask this pack
              </button>
              <button type="button" onClick={() => getPackInputs(pack.pack_id)
                        .then((i) => navigate(rerunUrl(i))).catch(() => navigate(rerunUrl({
                          brief: pack.brief.text, mode: pack.mode, time_window_days: pack.brief.interpreted.time_window_days,
                          brand_voice: pack.brief.brand_voice ?? null, intake: pack.brief.intake ?? null })))}
                      title="Run again with the same brief" className="inline-flex items-center gap-1.5 rounded-lg border border-line-strong px-3 py-1.5 text-sm text-ink">
                <RotateCcw aria-hidden="true" size={14} /> Run again
              </button>
              <button type="button" onClick={() => setAgent(!agent)} aria-pressed={agent}
                      className={`ml-auto inline-flex items-center gap-1.5 rounded px-2 py-1.5 text-xs ${agent ? "bg-wash text-ink" : "text-ink-3 hover:text-ink"}`}>
                <Braces aria-hidden="true" size={13} /> Developer view
              </button>
            </div>
          </header>

          {(pack.coverage.thin_evidence || partial) && (
            // UX audit: one calm line, not two warnings before the Summary; the details fold inside
            <details className="mb-4 text-sm text-ink-2">
              <summary className="cursor-pointer">
                {pack.coverage.thin_evidence
                  ? "Early signals: built on fewer posts than a full pack needs. "
                  : "Partial pack: collection stopped at its time limit. "}
                <span className="underline">Why, and how to get more</span>
              </summary>
              <div className="mt-1 space-y-1 pl-5">
                {pack.coverage.thin_evidence && <p>{pack.snapshot.grade_note || "This pack does not meet the minimum content bar."}</p>}
                {partial && <p>{pack.blind_spots[0].text.replace("Partial pack: ", "").replace(/^./, (c) => c.toUpperCase())}</p>}
                <p><a href="#research" className="underline">What's short</a></p>
                {pack.coverage.thin_evidence && (
                  <span className="mt-2 flex flex-wrap gap-2 print:hidden">
                    {[["Run it as Standard", { mode: "standard" }], ["Widen the time window", { window: "365" }],
                      ["Include English discussion", { suffix: " (include English-language discussion)" }]].map(([label, o]) => {
                      const opt = o as { mode?: string; window?: string; suffix?: string };
                      const q = new URLSearchParams({ brief: pack.brief.text + (opt.suffix ?? ""), mode: opt.mode ?? pack.mode,
                        ...(opt.window ? { window: opt.window } : {}) });
                      return <Link key={label as string} to={`/?${q}`} className="rounded border border-ink px-2 py-0.5 text-xs text-ink">{label as string}</Link>;
                    })}
                  </span>
                )}
              </div>
            </details>
          )}

          <Part id="summary" title="Summary">
            {agent ? <AgentJson name="snapshot" data={{ snapshot: pack.snapshot, do_first: pack.do_first }} schemaVersion={v} />
              : <SummaryPart pack={pack} />}
          </Part>

          <Part id="understand" title="Understand your audience" lead="How they talk, what they want, what stops them.">
            <div className="mb-6 flex flex-wrap items-center gap-3 print:hidden">
              <p className="flex flex-wrap gap-3 text-sm text-ink-2" aria-label="Findings by strength">
                {(Object.keys(GLYPH) as Label[]).map((l) => (
                  <span key={l} title={guide?.labels[l]?.words}><span aria-hidden="true">{GLYPH[l]}</span> {counts[l]} {l}</span>
                ))}
              </p>
              <div className="ml-auto flex gap-1" role="group" aria-label="Filter findings">
                {(["all", "observed", "strong"] as Filter[]).map((f) => (
                  <button key={f} type="button" onClick={() => setFilter(f)} aria-pressed={filter === f}
                          className={`rounded-lg border px-2.5 py-1.5 text-sm ${filter === f ? "border-ink bg-ink text-paper" : "border-line text-ink-2"}`}>
                    {{ all: "All", observed: "Seen in posts only", strong: "Strong only" }[f]}
                  </button>
                ))}
              </div>
            </div>
            {ordered([
              ["brand", pack.brand_perception ? sec("brand", "How people see your brand", "brand_perception",
                pack.brand_perception, <BrandPart bp={pack.brand_perception} />) : null],
              ["their-words", sec("their-words", "Their words", "voice", pack.voice, <Voice pack={pack} filter={filter} />)],
              ["want-stops", sec("want-stops", "What they want and what stops them", "motivations",
              { motivations: pack.motivations, pain_points: pack.pain_points, objections: pack.objections, tensions: pack.tensions },
              <WantStops pack={pack} filter={filter} meta={meta} />)],
              ["segments", sec("segments", "Segments", "segments", pack.segments,
              <ItemSection level={3} title="Who they are" items={asItems(pack.segments)} filter={filter} titleKey={"name" as keyof InsightLike}
                           meta={meta("segments")} />)],
              ["generic", sec("generic", "A generic AI answer vs. what people actually say", "generic_vs_found",
              pack.snapshot.generic_vs_found, <Generic pack={pack} />)],
              ["landscape", sec("landscape", "Landscape: by platform and over time", "landscape", { landscape: pack.landscape, culture: pack.culture },
              <Landscape pack={pack} filter={filter} />)],
            ])}
          </Part>

          <Part id="act" title="Act on it" lead="One plan: post briefs and a 4-week calendar, where to show up, and what to avoid.">
            {ordered([
              ["plan", sec("plan", "Your plan", "post_briefs",
              { post_briefs: pack.post_briefs, drafts: pack.drafts, content_calendar: pack.content_calendar, this_week: pack.playbook.this_week },
              <PlanPart pack={pack} fallback={<ThisWeek pack={pack} />} />)],
              ["channels", sec("channels", "Channels", "channel_plan", pack.channel_plan, <Channels pack={pack} />)],
              ["performs", sec("performs", "What performs", "what_performs", pack.what_performs,
              pack.what_performs.length ? (
                <>
                <SectionLead meta={meta("what_performs")} />
                {(pack.performance_takeaways ?? []).length > 0 && (
                  <ul className="mb-4 space-y-2">
                    {pack.performance_takeaways.map((t) => (
                      <li key={t.id} className="rounded-lg border border-ink p-4">
                        <p className="font-medium text-ink">{t.takeaway}</p>
                        <p className="mt-1 text-sm text-ink-2">{t.why} <span className="text-ink-3">(our reading)</span></p>
                      </li>
                    ))}
                  </ul>
                )}
                <details className="group" open={!(pack.performance_takeaways ?? []).length}>
                  <summary className="cursor-pointer text-sm text-ink-2 hover:text-ink">Example posts ({pack.what_performs.length})</summary>
                <ul className="mt-3 space-y-3">
                  {pack.what_performs.map((p) => {
                    const url = safeUrl(p.url);
                    return (
                      <li key={p.id} className="rounded-lg border border-line p-4">
                        <p className="text-sm text-ink"><span className="font-medium">{p.format}</span> on {CHANNEL[p.platform] ?? p.platform} ·
                          <span className="font-mono text-xs"> more engagement than {Math.round(p.engagement_percentile)}% of posts</span></p>
                        <p className="mt-1 text-sm text-ink-2">{p.why_it_worked} <span className="text-ink-3">(our reading)</span></p>
                        <p className="mt-1 flex gap-2 text-xs">{url && <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="underline">Open the post</a>}
                          <IdButton id={p.id} /></p>
                      </li>
                    );
                  })}
                </ul>
                </details>
                </>
              ) : <EmptyNote meta={meta("what_performs")} fallback="No engagement data in this pack, so nothing can be ranked by what performs." />)],
              ["opportunities", sec("opportunities", "Opportunities", "opportunities", pack.opportunities,
              pack.opportunities.length ? (
                <>
                  <SectionLead meta={meta("opportunities")} />
                  <ShowMore items={[...pack.opportunities].sort((a, b) => Number(b.status === "supported") - Number(a.status === "supported"))}
                            limit={3} render={(part) => (
                  <ul className="space-y-3">
                    {part.map((o) => (
                      <li key={o.id} className="rounded-lg border border-line p-4">
                        <div className="flex flex-wrap items-center gap-2">
                          {/* UX audit: one strength scale everywhere; "supported" only meant the people/community minimum */}
                          <ConfidenceBadge label={o.confidence.label} />
                          {o.status !== "supported" && <span className="text-xs text-ink-2">check before acting</span>}
                          <span className="rounded border border-line px-1.5 py-0.5 text-xs text-ink-2">{o.kind.replace(/_/g, " ")}</span>
                          <span className="ml-auto"><IdButton id={o.id} /></span>
                        </div>
                        <p className="mt-2 text-ink">{o.opportunity}</p>
                        <p className="mt-1 text-xs text-ink-3">
                          {o.distinct_authors} {o.distinct_authors === 1 ? "person" : "people"} in {o.communities.length}{" "}
                          {o.communities.length === 1 ? "community" : "communities"}
                        </p>
                        {o.existing_solutions.length > 0 ? (
                          <p className="mt-2 text-sm text-ink-2">Already out there:{" "}
                            {o.existing_solutions.map((x, n) => {
                              const url = safeUrl(x.url);
                              return <span key={x.url}>{n > 0 && "; "}{url ? <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="underline">{x.name}</a> : x.name}</span>;
                            })}
                          </p>
                        ) : o.search_note ? <p className="mt-2 text-sm text-ink-3">{o.search_note.charAt(0).toUpperCase() + o.search_note.slice(1)}.</p> : null}
                      </li>
                    ))}
                  </ul>
                  )} />
                </>
              ) : <EmptyNote meta={meta("opportunities")} fallback="No opportunities stood out in this evidence." />)],
              ["guardrails", sec("guardrails", "Guardrails", "guardrails", { guardrails: pack.guardrails, compliance_flags: pack.compliance_flags },
              <>
                <Guardrails pack={pack} />
                <details className="mt-6 rounded-lg border border-line p-3">
                  <summary className="cursor-pointer text-sm text-ink-2">More from the playbook: hooks, creative brief, keywords, communities</summary>
                  <div className="mt-4"><Playbook pack={pack} /></div>
                </details>
              </>)],
            ])}
          </Part>

          <section aria-labelledby="research" className="pack-part mb-16">
            <details className="research group rounded-lg border border-line">
              <summary className="cursor-pointer px-4 py-3">
                <h2 id="research" className="inline scroll-mt-24 text-2xl font-semibold tracking-tight text-ink">The research</h2>
                <span className="ml-2 text-sm text-ink-3">sources, method, hypotheses, blind spots, every post</span>
              </summary>
              <div className="space-y-8 px-4 pb-4">
                <CoverageStrip pack={pack} />
                <Sub title="Blind spots">
                  <ul className="list-disc space-y-1.5 pl-5 text-ink">{pack.blind_spots.map((b) => <li key={b.id}>{b.text}</li>)}</ul>
                </Sub>
                <Method pack={pack} />
              </div>
            </details>
          </section>
        </div>
      </div>
      <EvidenceDrawer itemId={drawer} index={index} packId={pack.pack_id} onClose={() => setDrawer(null)} onOpen={setDrawer} />
      <Handoff packId={pack.pack_id} open={handoff} onClose={() => setHandoff(false)} />
      <AskPanel pack={pack} open={asking} onClose={() => setAsking(false)} />
      <BackToTop />
    </PackContext.Provider>
    </GuideContext.Provider>
  );
}

export function PackPage() {
  const { packId = "" } = useParams();
  const [pack, setPack] = useState<ContextPack | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setPack(null);
    getPack(packId).then(setPack).catch((e) => setError(friendlyError(e)));
  }, [packId]);
  if (error) return <ErrorNote message={error} />;
  if (!pack) return <div className="max-w-[760px] lg:ml-[15.5rem]"><Skeleton lines={4} label="Loading the pack" /></div>;
  return <PackBody pack={pack} />;
}
