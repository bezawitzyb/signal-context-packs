// Cards (PRD 10.3). OUR WORK (claims) in sans, THEIR WORDS (quotes, terms) in serif, ids in mono.
import { createContext, useContext } from "react";
import { AlertTriangle, ArrowRight } from "lucide-react";
import type { Evidence, InsightLike } from "../lib/api";
import { ClaimTypeTag, ConfidenceBadge, IdTag, SafeTag } from "./badges";
import { CopyButton } from "./CopyButton";
import { Quote } from "./Quote";

/** Evidence lookup + "open evidence" handler shared by every card on a pack page. */
export const PackContext = createContext<{
  evidence: Record<string, Evidence>;
  onOpen?: (itemId: string) => void;
}>({ evidence: {} });

export function usePack() {
  return useContext(PackContext);
}

function Meta({ item }: { item: InsightLike }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <ConfidenceBadge label={item.confidence.label} matching={item.counts.matching}
                       ofTotal={item.counts.of_total} score={item.confidence.score} />
      <ClaimTypeTag type={item.claim_type} />
      {item.safe_to_assert && <SafeTag />}
      {item.non_obvious && (
        <span title="Not in what a generic AI answer says" className="rounded border border-line px-1.5 py-0.5 text-xs text-ink-2">
          Non-obvious
        </span>
      )}
    </div>
  );
}

function OpenEvidence({ id }: { id: string }) {
  const { onOpen } = usePack();
  if (!onOpen) return <IdTag id={id} />;
  return (
    <button type="button" onClick={() => onOpen(id)}
            className="inline-flex items-center gap-1 font-mono text-xs text-ink-3 hover:text-ink">
      {id} <ArrowRight aria-hidden="true" size={12} />
      <span className="sr-only">open the evidence</span>
    </button>
  );
}

export function ClaimCard({ item, title, maxQuotes = 1 }: { item: InsightLike; title?: string; maxQuotes?: number }) {
  const { evidence } = usePack();
  return (
    <article className="rounded-lg border border-line bg-paper p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          {title && <p className="mb-0.5 text-sm font-semibold text-ink">{title}</p>}
          <p className="text-[0.98rem] leading-snug text-ink">{item.claim}</p>
        </div>
        <OpenEvidence id={item.id} />
      </div>
      {item.summary_for_humans && <p className="mb-2 text-sm text-ink-2">{item.summary_for_humans}</p>}
      <Meta item={item} />
      {(item.quotes ?? []).slice(0, maxQuotes).map((q) => (
        <div key={q.evidence_id + q.text} className="mt-3">
          <Quote text={q.text} evidence={evidence[q.evidence_id]} size="sm" />
        </div>
      ))}
    </article>
  );
}

type Side = { text: string; evidence_ids: string[] };

export function TensionCard({ item }: { item: InsightLike & { want: Side; but: Side } }) {
  const { evidence } = usePack();
  const firstQuote = (side: Side) => {
    const ev = side.evidence_ids.map((id) => evidence[id]).find(Boolean);
    return ev ? <Quote text={ev.text} evidence={ev} size="sm" /> : null;
  };
  return (
    <article className="rounded-lg border border-line bg-paper p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <p className="text-[0.98rem] font-medium leading-snug text-ink">{item.claim}</p>
        <OpenEvidence id={item.id} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-3">They want</p>
          <p className="mb-2 font-serif text-[1rem] text-ink">{item.want.text}</p>
          {firstQuote(item.want)}
        </div>
        <div className="sm:border-l sm:border-line sm:pl-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-3">But</p>
          <p className="mb-2 font-serif text-[1rem] text-ink">{item.but.text}</p>
          {firstQuote(item.but)}
        </div>
      </div>
      <div className="mt-3"><Meta item={item} /></div>
    </article>
  );
}

export function LexiconChip({ term, meaning, language, id }: { term: string; meaning: string; language?: string; id?: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-md border border-line bg-paper px-2 py-1"
          title={meaning}>
      <span lang={language} className="font-serif text-[1rem] text-ink">{term}</span>
      <span className="text-xs text-ink-2">{meaning}</span>
      {id && <span className="font-mono text-[0.7rem] text-ink-3">{id}</span>}
    </span>
  );
}

export function HookCard({ hook, flags = [] }: {
  hook: { id: string; text: string; why_ids: string[] };
  flags?: { id: string; category: string; why: string; safer_wording: string }[];
}) {
  return (
    <article className="rounded-lg border border-line bg-paper p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[1rem] leading-snug text-ink">{hook.text}</p>
        <CopyButton text={hook.text} label="Copy hook" />
      </div>
      <p className="mt-2 font-mono text-xs text-ink-3">{hook.id} · builds on {hook.why_ids.join(", ")}</p>
      {flags.map((f) => (
        <div key={f.id} className="mt-2 flex gap-2 rounded-md border border-accent/40 bg-paper p-2 text-xs text-ink-2">
          <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-accent-ink" />
          <div>
            <span className="font-medium text-ink">Check with legal ({f.category.replace("_", " ")}).</span>{" "}
            {f.why} <span className="text-ink">Safer: {f.safer_wording}</span>
            <span className="ml-1 font-mono text-ink-3">{f.id}</span>
          </div>
        </div>
      ))}
    </article>
  );
}

export function SourceCard({ source, dropped = false }: {
  source: { source_unit: string; platform?: string; reason: string; kept?: number; relevant_share?: number };
  dropped?: boolean;
}) {
  const share = source.relevant_share ?? 0;
  return (
    <article className={`rounded-lg border p-3 ${dropped ? "border-dashed border-line-strong" : "border-line"}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate font-mono text-xs text-ink" title={source.source_unit}>{source.source_unit}</span>
        <span className="shrink-0 text-xs font-medium text-ink-2">{dropped ? "Dropped" : "Kept"}</span>
      </div>
      {!dropped && source.kept !== undefined && (
        <div className="mt-2" aria-label={`${Math.round(share * 100)}% relevant`}>
          <div className="h-1.5 rounded-full bg-wash">
            <div className="h-1.5 rounded-full bg-ink" style={{ width: `${Math.round(share * 100)}%` }} />
          </div>
          <p className="mt-1 font-mono text-[0.72rem] text-ink-3">
            {source.kept} kept · {Math.round(share * 100)}% relevant{source.platform ? ` · ${source.platform}` : ""}
          </p>
        </div>
      )}
      <p className="mt-2 text-sm text-ink-2">{source.reason}</p>
    </article>
  );
}
