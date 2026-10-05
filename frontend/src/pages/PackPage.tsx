// S3 PACK PAGE: the full page (sticky nav, every section, evidence drawer) is Step 4.3.
// For now: coverage, do first, five truths, tensions and voice, built from the shared components.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { getPack, type ContextPack, type Evidence, type InsightLike } from "../lib/api";
import { CoverageStrip, LimitationCallout } from "../components/callouts";
import { LexiconChip, PackContext, TensionCard } from "../components/cards";
import { SectionTitle } from "../components/blocks";

export function PackBody({ pack }: { pack: ContextPack }) {
  const evidence = useMemo(
    () => Object.fromEntries(pack.evidence.map((e) => [e.id, e as Evidence])), [pack]);
  return (
    <PackContext.Provider value={{ evidence }}>
      <div className="space-y-8">
        <header>
          <p className="font-mono text-xs text-ink-3">{pack.pack_id} · {pack.generated_at.slice(0, 10)}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">{pack.brief.text}</h1>
          <p className="mt-1 text-ink-2">{pack.brief.interpreted.audience}</p>
          <Link to={`/packs/${pack.pack_id}/replay`} className="mt-2 inline-block text-sm text-ink underline underline-offset-2">
            Replay the research
          </Link>
        </header>
        <CoverageStrip pack={pack} />
        {pack.coverage.thin_evidence && (
          <LimitationCallout title="Thin evidence">
            This pack does not meet the minimum content bar. Treat its findings as early signals; see Blind spots.
          </LimitationCallout>
        )}
        <section>
          <SectionTitle title="Do first" />
          <ol className="space-y-2">
            {pack.do_first.map((d) => (
              <li key={d.id} className="rounded-lg border border-line p-3">
                <p className="text-ink">{d.action}</p>
                <p className="mt-1 text-sm text-ink-2">{d.why}</p>
                <p className="mt-1 font-mono text-xs text-ink-3">{d.id} · {d.effort} effort · {d.impact} impact · {d.why_ids.join(", ")}</p>
              </li>
            ))}
          </ol>
        </section>
        <section>
          <SectionTitle title="Five truths" />
          <ul className="space-y-1.5">
            {pack.snapshot.five_truths.map((t) => (
              <li key={t.text} className="text-ink">{t.text} <span className="font-mono text-xs text-ink-3">{t.item_ids.join(", ")}</span></li>
            ))}
          </ul>
        </section>
        <section>
          <SectionTitle title="Tensions" />
          <div className="space-y-3">
            {pack.tensions.map((t) => <TensionCard key={t.id} item={t as unknown as InsightLike & { want: { text: string; evidence_ids: string[] }; but: { text: string; evidence_ids: string[] } }} />)}
          </div>
        </section>
        <section>
          <SectionTitle title="Their words" />
          <div className="flex flex-wrap gap-2">
            {pack.voice.lexicon.map((x) => <LexiconChip key={x.id} term={x.term} meaning={x.meaning} language={x.language} id={x.id} />)}
          </div>
        </section>
        <p className="text-sm text-ink-3">The full pack page with every section and the evidence drawer comes in Step 4.3.</p>
      </div>
    </PackContext.Provider>
  );
}

export function PackPage() {
  const { packId = "" } = useParams();
  const [pack, setPack] = useState<ContextPack | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getPack(packId).then(setPack).catch((e: Error) => setError(e.message));
  }, [packId]);
  if (error) return <p className="text-ink-2">{error}</p>;
  if (!pack) return <p className="text-ink-3">Loading the pack…</p>;
  return <PackBody pack={pack} />;
}
