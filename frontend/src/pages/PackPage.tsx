// S3 PACK PAGE (PRD 10.2, guide Step 4.4): one scrollable page, ~760 px content column, sticky section nav,
// filters, banners, evidence drawer, View as agent, Handoff. Sections in PRD S3 order.
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Braces, History, RotateCcw, Share2 } from "lucide-react";
import { friendlyError, getPack, getPackInputs, type ContextPack, type InsightLike, type Label } from "../lib/api";
import { indexPack, labelCounts } from "../lib/packIndex";
import { safeUrl } from "../lib/safe";
import { ConfidenceBadge, IdTag, ModeBadge } from "../components/badges";
import { CoverageStrip, LimitationCallout } from "../components/callouts";
import { HookCard, PackContext, SourceCard, TensionCard, usePack } from "../components/cards";
import { applyFilter, type Filter, ItemSection, TableSection } from "../components/blocks";
import { CopyButton } from "../components/CopyButton";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { AgentJson } from "../components/AgentJson";
import { Handoff } from "../components/Handoff";
import { Skeleton } from "../components/Skeleton";
import { ErrorNote } from "../components/ErrorNote";
import { rerunUrl } from "../lib/rerun";

const NAV: [string, string][] = [
  ["summary", "Summary"], ["channels", "Channels & this week"], ["voice", "Voice"], ["tensions", "Tensions & motivations"],
  ["segments", "Segments"], ["objections", "Objections & competitors"], ["landscape", "Landscape & platforms"],
  ["performs", "What performs"], ["moments", "Moments"], ["white-space", "White space & opportunities"],
  ["playbook", "Playbook"], ["blind-spots", "Blind spots"], ["method", "Method"],
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

function IdButton({ id }: { id: string }) {
  const { onOpen } = usePack();
  return (
    <button type="button" onClick={() => onOpen?.(id)} title="Open the evidence"
            className="rounded px-0.5 font-mono text-xs text-ink-3 underline-offset-2 hover:text-ink hover:underline">
      {id}
    </button>
  );
}

function Ids({ ids }: { ids: string[] }) {
  return <span className="inline-flex flex-wrap gap-x-1">{ids.map((id) => <IdButton key={id} id={id} />)}</span>;
}

// --- sections ------------------------------------------------------------------------------

function Summary({ pack, items }: { pack: ContextPack; items: Map<string, Record<string, unknown>> }) {
  const s = pack.snapshot;
  const badgeOf = (id: string) => {
    const it = items.get(id) as InsightLike | undefined;
    return it?.confidence
      ? <ConfidenceBadge label={it.confidence.label} matching={it.counts.matching} ofTotal={it.counts.of_total} />
      : null;
  };
  return (
    <>
      <div className="mb-6 space-y-3">
        <CoverageStrip pack={pack} />
        <LimitationCallout title="What this can't tell you">
          <ul className="list-disc space-y-0.5 pl-4">
            {pack.blind_spots.slice(0, 3).map((b) => <li key={b.id}>{b.text}</li>)}
          </ul>
          {pack.blind_spots.length > 3 && <a href="#blind-spots" className="mt-1 inline-block underline">All blind spots</a>}
        </LimitationCallout>
      </div>
      <Sub title="Do this first">
        <ol className="space-y-3">
          {pack.do_first.map((d) => (
            <li key={d.id} className="rounded-lg border border-line p-4">
              <div className="flex items-start justify-between gap-3">
                <p className="font-medium text-ink">{d.action}</p>
                <CopyButton text={d.action} />
              </div>
              <p className="mt-1 text-sm text-ink-2">{d.why}</p>
              <p className="mt-2 flex flex-wrap items-center gap-x-2 font-mono text-xs text-ink-3">
                <span>{d.id}</span><span>effort {d.effort}</span><span>impact {d.impact}</span>
                {d.owner_hint && <span className="font-sans">{d.owner_hint}</span>}
                <span>· based on</span><Ids ids={d.why_ids} />
              </p>
            </li>
          ))}
        </ol>
      </Sub>
      <Sub title="Five truths">
        <ul className="space-y-3">
          {s.five_truths.map((t) => (
            <li key={t.text} className="flex flex-wrap items-baseline gap-2">
              <span className="text-[1.02rem] text-ink">{t.text}</span>
              {badgeOf(t.item_ids[0])}<Ids ids={t.item_ids} />
            </li>
          ))}
        </ul>
      </Sub>
      <Sub title="A generic AI answer vs. what people actually say">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border border-line bg-wash p-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-3">Generic answer (no research)</p>
            <ul className="list-disc space-y-1.5 pl-4 text-sm text-ink-3">
              {s.generic_vs_found.generic_points.map((g) => <li key={g}>{g}</li>)}
            </ul>
          </div>
          <div className="rounded-lg border border-ink p-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink">What people actually say</p>
            <ul className="space-y-3">
              {s.generic_vs_found.what_we_found.map((f) => (
                <li key={f.text}>
                  <p className="text-sm text-ink">{f.text}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">{badgeOf(f.item_ids[0])}<Ids ids={f.item_ids} /></div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Sub>
    </>
  );
}

function Channels({ pack }: { pack: ContextPack }) {
  const pb = pack.playbook;
  const hooks = Object.fromEntries(pb.hooks.map((h) => [h.id, h.text]));
  const planText = pb.this_week.map((w) => `${w.day}: ${w.platform}, ${w.format} - "${hooks[w.hook_id] ?? w.hook_id}" - ${w.angle}`).join("\n");
  return (
    <>
      <Sub title="Where to show up">
        <ol className="space-y-3">
          {pack.channel_plan.map((c) => (
            <li key={c.id} className="rounded-lg border border-line p-4">
              <p className="flex items-baseline gap-2"><span className="font-mono text-sm text-ink-3">{c.priority}.</span>
                <span className="font-medium text-ink">{c.platform}</span><IdTag id={c.id} /></p>
              <p className="mt-1 text-sm text-ink">{c.why}</p>
              <p className="mt-2 text-sm text-ink-2">Formats: {c.formats.join(", ") || "-"}</p>
              {c.communities_or_hashtags.length > 0 && <p className="text-sm text-ink-2">Where: {c.communities_or_hashtags.join(", ")}</p>}
              {c.tone_note && <p className="text-sm text-ink-2">Tone: {c.tone_note}</p>}
              <p className="mt-1 font-mono text-xs text-ink-3">based on <Ids ids={c.why_ids} /></p>
            </li>
          ))}
        </ol>
      </Sub>
      <Sub title="This week">
        <div className="mb-2 flex justify-end"><CopyButton text={planText} label="Copy plan" /></div>
        <TableSection caption="This week" rowKey={(r) => r.id} rows={pb.this_week} columns={[
          { header: "Day", cell: (r) => r.day, kind: "data" },
          { header: "Where", cell: (r) => `${r.platform} · ${r.format}` },
          { header: "Hook", cell: (r) => <>{hooks[r.hook_id]} <IdButton id={r.hook_id} /></> },
          { header: "Angle and why now", cell: (r) => <>{r.angle}<span className="block text-xs text-ink-3">{r.why_now}</span></> },
        ]} />
      </Sub>
    </>
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
                <p className="flex items-baseline justify-between"><span className="font-medium text-ink">{l.platform}</span>
                  <span className="font-mono text-xs text-ink-3">{l.kept_posts} posts · {l.id}</span></p>
                {l.tone && <p className="mt-2 text-sm text-ink">{l.tone}</p>}
                {l.what_is_unique && <p className="mt-1 text-sm text-ink-2">{l.what_is_unique}</p>}
                <ul className="mt-3 space-y-1.5">
                  {l.theme_shares.slice(0, 5).map((t) => (
                    <li key={t.theme_id} className="text-xs">
                      <div className="flex justify-between gap-2 text-ink-2"><span className="truncate">{themes[t.theme_id] ?? t.theme_id}</span>
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
      {culture.length > 0 && <ItemSection level={3} title="Culture and codes" items={asItems(culture)} filter={filter} titleKey={"name" as keyof InsightLike} />}
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
  const otherFlags = pack.compliance_flags.filter((f) => !f.item_id.startsWith("HOOK-"));
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
                <span className="ml-2 font-mono text-xs text-ink-3">{t.kind} · {t.platform}</span></li>;
            })}
          </ul>
        </Sub>
      )}
      {otherFlags.length > 0 && (
        <Sub title="Other compliance flags">
          <ul className="space-y-2 text-sm">
            {otherFlags.map((f) => (
              <li key={f.id} className="rounded-lg border border-accent/40 p-3 text-ink-2">
                <span className="font-medium text-ink">Check with legal ({f.category.replace("_", " ")}) on <IdButton id={f.item_id} />.</span>{" "}
                {f.why} <span className="text-ink">Safer: {f.safer_wording}</span>
              </li>
            ))}
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
          <p>Only public posts are used. Authors are stored as salted hashes, never names; emails, phone numbers, @handles and
            names written in posts are removed before analysis. Quoted excerpts are for internal research and briefs only,
            not for ads or other public material. {PRIVACY_LINE}</p>
          <p>Counts and confidence are computed in code from posts checked to belong to each finding; every quote is copied
            word for word from its post. Labels: strong, moderate, emerging, speculative. "Safe to state" means strong, observed
            and confirmed by the claim check. This is AI-assisted analysis and may contain errors; compliance flags are not
            legal advice.</p>
          <p><Link to={`/packs/${pack.pack_id}/replay`} className="inline-flex items-center gap-1 text-ink underline"><History aria-hidden="true" size={14} /> Replay the research</Link></p>
        </div>
      </Sub>
    </>
  );
}

// --- the page ----------------------------------------------------------------------------------

export function PackBody({ pack }: { pack: ContextPack }) {
  const index = useMemo(() => indexPack(pack), [pack]);
  const [filter, setFilter] = useState<Filter>("all");
  const [agent, setAgent] = useState(false);
  const [handoff, setHandoff] = useState(false);
  const navigate = useNavigate();
  const [drawer, setDrawer] = useState<string | null>(null);
  const counts = labelCounts(pack);
  const v = pack.schema_version;
  const sec = (id: string, title: string, name: string, data: unknown, children: React.ReactNode, note?: React.ReactNode) =>
    <Section id={id} title={title} agent={agent} agentData={data} name={name} version={v} note={note}>{children}</Section>;

  return (
    <PackContext.Provider value={{ evidence: index.evidence, onOpen: setDrawer }}>
      <div className="pack-layout lg:grid lg:grid-cols-[13rem_1fr] lg:gap-10">
        <nav aria-label="Sections" className="hidden print:hidden lg:block">
          <ul className="sticky top-20 space-y-1 text-sm">
            {NAV.map(([id, label]) => <li key={id}><a href={`#${id}`} className="block rounded px-2 py-1 text-ink-2 hover:bg-wash hover:text-ink">{label}</a></li>)}
          </ul>
        </nav>
        <div className="min-w-0 max-w-[760px]">
          <header className="mb-8 space-y-3">
            <p className="flex flex-wrap items-center gap-2 font-mono text-xs text-ink-3">
              <span>{pack.pack_id}</span><span>{pack.generated_at.slice(0, 10)}</span><ModeBadge mode={pack.mode} />
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-ink">{pack.brief.text}</h1>
            <p className="text-ink-2">{pack.brief.interpreted.audience} · {pack.brief.interpreted.market}</p>
            <p className="hidden font-mono text-xs text-ink print:block">
              Context Pack {pack.pack_id} · {pack.generated_at.slice(0, 10)} · coverage grade {pack.snapshot.coverage_grade} · {pack.mode}
            </p>
            <p className="flex flex-wrap gap-3 text-sm text-ink-2" aria-label="Confidence summary">
              {(Object.keys(GLYPH) as Label[]).map((l) => (
                <span key={l}><span aria-hidden="true">{GLYPH[l]}</span> {counts[l]} {l}</span>
              ))}
            </p>
            <div className="flex flex-wrap gap-2 print:hidden">
              <button type="button" onClick={() => setHandoff(true)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-3 py-1.5 text-sm text-paper">
                <Share2 aria-hidden="true" size={14} /> Handoff
              </button>
              <button type="button" onClick={() => getPackInputs(pack.pack_id)
                        .then((i) => navigate(rerunUrl(i))).catch(() => navigate(rerunUrl({
                          brief: pack.brief.text, mode: pack.mode, time_window_days: pack.brief.interpreted.time_window_days,
                          brand_voice: pack.brief.brand_voice ?? null, clarification: null })))}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-ink-2">
                <RotateCcw aria-hidden="true" size={14} /> Run again with these inputs
              </button>
              <button type="button" onClick={() => setAgent(!agent)} aria-pressed={agent}
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm ${agent ? "border-ink bg-wash text-ink" : "border-line text-ink-2"}`}>
                <Braces aria-hidden="true" size={14} /> View as agent
              </button>
              <div className="ml-auto flex gap-1" role="group" aria-label="Filter findings">
                {(["all", "observed", "strong"] as Filter[]).map((f) => (
                  <button key={f} type="button" onClick={() => setFilter(f)} aria-pressed={filter === f}
                          className={`rounded-lg border px-2.5 py-1.5 text-sm ${filter === f ? "border-ink bg-ink text-paper" : "border-line text-ink-2"}`}>
                    {{ all: "All", observed: "Observed only", strong: "Strong only" }[f]}
                  </button>
                ))}
              </div>
            </div>
          </header>

          <div className="mb-10 space-y-2">
            {pack.coverage.thin_evidence && (
              <LimitationCallout title="Thin evidence">
                This pack does not meet the minimum content bar, so treat its findings as early signals (see Blind spots for what is short).
                <span className="mt-2 flex flex-wrap gap-2 print:hidden">
                  {[["Run it as Standard", { mode: "standard" }], ["Widen the time window", { window: "365" }],
                    ["Include English discussion", { suffix: " (include English-language discussion)" }]].map(([label, o]) => {
                    const opt = o as { mode?: string; window?: string; suffix?: string };
                    const q = new URLSearchParams({ brief: pack.brief.text + (opt.suffix ?? ""), mode: opt.mode ?? pack.mode,
                      ...(opt.window ? { window: opt.window } : {}) });
                    return <Link key={label as string} to={`/?${q}`} className="rounded border border-ink px-2 py-0.5 text-xs text-ink">{label as string}</Link>;
                  })}
                </span>
              </LimitationCallout>
            )}
            {pack.blind_spots[0]?.text.startsWith("Partial pack:") && (
              <LimitationCallout title="Partial pack">{pack.blind_spots[0].text.replace("Partial pack: ", "")}</LimitationCallout>
            )}
            {pack.coverage.loop.fallback_used && (
              <LimitationCallout title="Collected automatically">The research agent stopped early, so the remaining planned sources were collected automatically.</LimitationCallout>
            )}
          </div>

          {sec("summary", "Summary", "snapshot", { snapshot: pack.snapshot, do_first: pack.do_first },
            <Summary pack={pack} items={index.items as Map<string, Record<string, unknown>>} />)}
          {sec("channels", "Channels & this week", "channel_plan", { channel_plan: pack.channel_plan, this_week: pack.playbook.this_week },
            <Channels pack={pack} />)}
          {sec("voice", "Voice", "voice", pack.voice, <Voice pack={pack} filter={filter} />)}
          {sec("tensions", "Tensions & motivations", "tensions", { tensions: pack.tensions, motivations: pack.motivations },
            <>
              <div className="mb-8 space-y-3">
                {applyFilter(asItems(pack.tensions), filter).map((t) => <TensionCard key={t.id} item={t as Tension} />)}
                {applyFilter(asItems(pack.tensions), filter).length === 0 && <p className="text-sm text-ink-3">No tensions match this filter.</p>}
              </div>
              <ItemSection level={3} title="Needs, pains and jobs" items={asItems(pack.motivations)} filter={filter} />
            </>)}
          {sec("segments", "Segments", "segments", pack.segments,
            <ItemSection level={3} title="Who they are" items={asItems(pack.segments)} filter={filter} titleKey={"name" as keyof InsightLike} />)}
          {sec("objections", "Objections & competitors", "objections", { objections: pack.objections, competitors: pack.competitors },
            <>
              <ItemSection level={3} title="Objections" items={asItems(pack.objections)} filter={filter} />
              {pack.playbook.objection_handling.length > 0 && (
                <Sub title="How to answer them">
                  <ul className="space-y-2 text-sm">
                    {pack.playbook.objection_handling.map((h) => <li key={h.objection_id} className="text-ink"><IdButton id={h.objection_id} /> {h.response}</li>)}
                  </ul>
                </Sub>
              )}
              {pack.competitors.length > 0 && (
                <Sub title="Brands they mention">
                  <TableSection caption="Competitors" rowKey={(r) => r.id} rows={pack.competitors} columns={[
                    { header: "Brand", cell: (r) => r.name },
                    { header: "Mentions", cell: (r) => `${r.mentions} · ${Math.round(r.share_of_mentions * 100)}%`, kind: "data" },
                    { header: "How they talk about it", cell: (r) => r.tone || "-" },
                    { header: "", cell: (r) => <IdButton id={r.id} />, kind: "data" },
                  ]} />
                </Sub>
              )}
            </>)}
          {sec("landscape", "Landscape & platform lens", "landscape", { landscape: pack.landscape, culture: pack.culture },
            <Landscape pack={pack} filter={filter} />)}
          {sec("performs", "What performs", "what_performs", pack.what_performs,
            pack.what_performs.length ? (
              <ul className="space-y-3">
                {pack.what_performs.map((p) => {
                  const url = safeUrl(p.url);
                  return (
                    <li key={p.id} className="rounded-lg border border-line p-4">
                      <p className="text-sm text-ink"><span className="font-medium">{p.format}</span> on {p.platform} ·
                        <span className="font-mono text-xs"> engagement p{Math.round(p.engagement_percentile)}</span></p>
                      <p className="mt-1 text-sm text-ink-2">{p.why_it_worked} <span className="text-ink-3">(our reading)</span></p>
                      <p className="mt-1 flex gap-2 text-xs">{url && <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="underline">Open the post</a>}
                        <IdButton id={p.id} /></p>
                    </li>
                  );
                })}
              </ul>
            ) : <p className="text-sm text-ink-3">No engagement data in this pack, so nothing can be ranked by what performs.</p>)}
          {sec("moments", "Moments", "moments", pack.moments,
            <ItemSection level={3} title="When it matters" items={asItems(pack.moments)} filter={filter} titleKey={"name" as keyof InsightLike} />)}
          {sec("white-space", "White space & opportunities", "white_space", { white_space: pack.white_space, opportunities: pack.opportunities },
            <>
              <ItemSection level={3} title="What nobody serves" items={asItems(pack.white_space)} filter={filter} columns={1} />
              <Sub title="Opportunities">
                <ul className="space-y-3">
                  {pack.opportunities.map((o) => (
                    <li key={o.id} className="rounded-lg border border-line p-4">
                      <div className="flex items-baseline justify-between gap-3">
                        <p className="font-medium text-ink">{o.title}</p>
                        <span className="font-mono text-sm text-ink">{o.score.toFixed(2)}</span>
                      </div>
                      <p className="mt-1 text-sm text-ink-2">{o.description}</p>
                      <p className="mt-2 font-mono text-xs text-ink-3">
                        demand {o.components.demand.toFixed(2)} × dissatisfaction {o.components.dissatisfaction.toFixed(2)} ×
                        novelty {o.components.novelty.toFixed(1)} × (1 − saturation {o.components.saturation.toFixed(2)}) · builds on <Ids ids={o.builds_on} />
                      </p>
                    </li>
                  ))}
                </ul>
              </Sub>
            </>)}
          {sec("playbook", "Playbook", "playbook", { playbook: pack.playbook, compliance_flags: pack.compliance_flags },
            <Playbook pack={pack} />)}
          {sec("blind-spots", "Blind spots", "blind_spots", pack.blind_spots,
            <ul className="list-disc space-y-1.5 pl-5 text-ink">{pack.blind_spots.map((b) => <li key={b.id}>{b.text}</li>)}</ul>)}
          {sec("method", "Method", "coverage", pack.coverage, <Method pack={pack} />)}
        </div>
      </div>
      <EvidenceDrawer itemId={drawer} index={index} packId={pack.pack_id} onClose={() => setDrawer(null)} onOpen={setDrawer} />
      <Handoff packId={pack.pack_id} open={handoff} onClose={() => setHandoff(false)} />
    </PackContext.Provider>
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
