// /components: every component with fictional sample data (tests/fixtures/example_pack.json).
// The greyscale switch is the Step 4.1 check: the four confidence levels must stay distinguishable.
import { useMemo, useState } from "react";
import sample from "../sample/pack.sample.json";
import type { ContextPack, Evidence, InsightLike, Label } from "../lib/api";
import { ClaimTypeTag, ConfidenceBadge, IdTag, ModeBadge, SafeTag } from "../components/badges";
import { ClaimCard, HookCard, LexiconChip, PackContext, SourceCard, TensionCard } from "../components/cards";
import { CopyButton } from "../components/CopyButton";
import { CoverageStrip, LimitationCallout } from "../components/callouts";
import { ItemSection, QuoteList, SectionTitle, TableSection, type Filter } from "../components/blocks";
import { Quote } from "../components/Quote";

const pack = sample as unknown as ContextPack;
const LEVELS: Label[] = ["strong", "moderate", "emerging", "speculative"];

// A fictional Dutch post to show the original / English toggle and the lang attribute.
const DUTCH: Evidence = {
  id: "EV-9001", platform: "web_forum", source_unit: "web:forum.example.nl", url: "https://example.com/forum/1",
  language: "nl", text: "Die nieuwe chips zijn echt kartonsmaak geworden, jammer.",
  text_en: "Those new crisps really taste like cardboard now, a shame.", trust: "untrusted_user_content",
} as Evidence;

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="mb-3 border-b border-line pb-1 font-mono text-xs uppercase tracking-wide text-ink-3">{title}</h2>
      {children}
    </section>
  );
}

export function ComponentsPreview() {
  const [grey, setGrey] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const evidence = useMemo(() => Object.fromEntries(pack.evidence.map((e) => [e.id, e as Evidence])), []);
  const themes = pack.landscape.themes as unknown as InsightLike[];
  const tension = pack.tensions[0] as unknown as InsightLike & { want: { text: string; evidence_ids: string[] };
    but: { text: string; evidence_ids: string[] } };
  const flags = pack.compliance_flags.filter((f) => f.item_id === pack.playbook.hooks[0]?.id);

  return (
    <PackContext.Provider value={{ evidence, onOpen: (id) => alert(`Evidence drawer for ${id} (Step 4.3)`) }}>
      <div style={grey ? { filter: "grayscale(1)" } : undefined}>
        <div className="mb-8 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-ink">Components</h1>
            <p className="text-sm text-ink-2">Sample data is fictional (EXAMPLE ONLY).</p>
          </div>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" checked={grey} onChange={(e) => setGrey(e.target.checked)} />
            Greyscale check
          </label>
        </div>

        <Block title="Three voices (PRD 10.1)">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-lg border border-line p-4">
              <p className="mb-1 font-mono text-xs text-ink-3">THEIR WORDS · serif</p>
              <p className="font-serif text-lg text-ink">“meal prep sunday is my therapy”</p>
            </div>
            <div className="rounded-lg border border-line p-4">
              <p className="mb-1 font-mono text-xs text-ink-3">OUR WORK · sans</p>
              <p className="text-ink">Students want to eat healthy but refuse to give up Sunday.</p>
            </div>
            <div className="rounded-lg border border-line p-4">
              <p className="mb-1 font-mono text-xs text-ink-3">MACHINE DATA · mono</p>
              <p className="font-mono text-sm text-ink">TEN-02 · 41 of 248 · 0.78</p>
            </div>
          </div>
        </Block>

        <Block title="Confidence, claim type, safe to state">
          <div className="flex flex-wrap items-center gap-2">
            {LEVELS.map((l, n) => <ConfidenceBadge key={l} label={l} matching={12 - n * 3} ofTotal={248} score={0.9 - n * 0.2} />)}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <ClaimTypeTag type="observed" /><ClaimTypeTag type="inferred" /><SafeTag /><IdTag id="TEN-01" /><ModeBadge mode="standard" />
            <CopyButton text="Copied from the components page" />
          </div>
        </Block>

        <Block title="Coverage strip and limitation callout">
          <div className="space-y-3">
            <CoverageStrip pack={pack} />
            <LimitationCallout title="Thin evidence">
              Fewer than 200 relevant posts: findings are capped at emerging. Treat them as early signals.
            </LimitationCallout>
          </div>
        </Block>

        <Block title="Quote (original / English, lang attribute, source link)">
          <div className="grid gap-4 md:grid-cols-2">
            <Quote text={DUTCH.text} evidence={DUTCH} />
            {pack.evidence[0] && <Quote text={pack.evidence[0].text} evidence={pack.evidence[0] as Evidence} />}
          </div>
        </Block>

        <Block title="Claim card and tension card">
          <div className="grid gap-3 md:grid-cols-2">
            {themes[0] && <ClaimCard item={themes[0]} />}
            {tension && <TensionCard item={tension} />}
          </div>
        </Block>

        <Block title="Lexicon chips">
          <div className="flex flex-wrap gap-2">
            {pack.voice.lexicon.map((x) => <LexiconChip key={x.id} term={x.term} meaning={x.meaning} language={x.language} id={x.id} />)}
            <LexiconChip term="borrelnootjes" meaning="nuts eaten with drinks" language="nl" />
          </div>
        </Block>

        <Block title="Hook card (with a compliance flag) and source cards">
          <div className="grid gap-3 md:grid-cols-2">
            {pack.playbook.hooks[0] && <HookCard hook={pack.playbook.hooks[0]} flags={flags.length ? flags : [{
              id: "CMP-01", category: "food_nutrition", why: "'Keeps you full' is a satiety claim.",
              safer_wording: "A snack for your afternoon." }]} />}
            <div className="space-y-3">
              {pack.coverage.sources_used[0] && <SourceCard source={pack.coverage.sources_used[0]} />}
              <SourceCard dropped source={{ source_unit: "reddit:r/food", reason: "4 of 40 posts on-topic." }} />
            </div>
          </div>
        </Block>

        <Block title="ItemSection (filters) · QuoteList · TableSection">
          <div className="mb-3 flex gap-1" role="group" aria-label="Filter claims">
            {(["all", "observed", "strong"] as Filter[]).map((f) => (
              <button key={f} type="button" onClick={() => setFilter(f)} aria-pressed={filter === f}
                      className={`rounded border px-2 py-0.5 text-sm ${filter === f ? "border-ink bg-ink text-paper" : "border-line text-ink-2"}`}>
                {{ all: "All", observed: "Observed only", strong: "Strong only" }[f]}
              </button>
            ))}
          </div>
          <ItemSection id="preview-themes" title="Themes" items={themes} filter={filter} titleKey={"label" as keyof InsightLike} />
          <SectionTitle title="Quotes" />
          <QuoteList evidence={pack.evidence as Evidence[]} limit={2} />
          <div className="mt-6">
            <TableSection
              caption="Lexicon"
              rowKey={(r) => r.id}
              rows={pack.voice.lexicon}
              columns={[
                { header: "Their word", cell: (r) => r.term, kind: "their" },
                { header: "Meaning", cell: (r) => r.meaning, kind: "ours" },
                { header: "Id", cell: (r) => r.id, kind: "data" },
              ]}
            />
          </div>
        </Block>
      </div>
    </PackContext.Provider>
  );
}
