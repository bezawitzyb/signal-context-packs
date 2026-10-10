// Cards (PRD 10.3). OUR WORK (claims) in sans, THEIR WORDS (quotes, terms) in serif, ids in mono.
import { createContext, useContext } from "react";
import { ArrowRight } from "lucide-react";
import { unitWords } from "../lib/unitWords";
import type { Evidence, InsightLike } from "../lib/api";
import { ClaimTypeTag, ConfidenceBadge, IdTag, SafeTag } from "./badges";
import { CopyButton } from "./CopyButton";
import { Quote } from "./Quote";
import { LegalNote } from "./legal";
import type { FlagLike } from "../lib/legal";

/** Evidence lookup + "open evidence" handler shared by every card on a pack page. */
export const PackContext = createContext<{
  evidence: Record<string, Evidence>;
  onOpen?: (itemId: string) => void;
  claims?: Record<string, string>;   // item id -> claim, for linked chips (V4)
  picks?: Record<string, { evidence_id: string; text: string }>;   // the quote each card shows (lib/quotePicks)
}>({ evidence: {} });

const LINK: Record<string, string> = { comes_from: "comes from", blocks: "blocks", related: "see also" };

/** V4: connected items in other sections as small chips - never a restated paragraph. */
export function LinkChips({ links }: { links: { id: string; kind?: string }[] }) {
  const { claims = {}, onOpen } = usePack();
  const shown = links.filter((l) => claims[l.id]);
  if (!shown.length) return null;
  return (
    <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Connected findings">
      {shown.map((l) => (
        <li key={l.id}>
          <button type="button" onClick={() => onOpen?.(l.id)} title={claims[l.id]}
                  className="max-w-full truncate rounded-full border border-line px-2.5 py-0.5 text-left text-xs text-ink-2 hover:border-ink hover:text-ink">
            <span className="text-ink-3">{LINK[l.kind ?? "related"] ?? "see also"}:</span> {claims[l.id].length > 60 ? claims[l.id].slice(0, 58) + "…" : claims[l.id]}
          </button>
        </li>
      ))}
    </ul>
  );
}

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
            aria-label={`See the posts behind ${id}`} title={id}
            className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-xs text-ink-2 hover:text-ink">
      See the posts <ArrowRight aria-hidden="true" size={12} />
    </button>
  );
}

/** An item id that opens the evidence drawer when the page provides one. */
export function IdLink({ id }: { id: string }) {
  const { onOpen } = usePack();
  return onOpen
    ? <button type="button" onClick={() => onOpen(id)} title="Open the evidence"
              className="underline-offset-2 hover:text-ink hover:underline">{id}</button>
    : <span>{id}</span>;
}

export function ClaimCard({ item, title, maxQuotes = 1 }: { item: InsightLike; title?: string; maxQuotes?: number }) {
  const { evidence, picks } = usePack();
  const pick = maxQuotes === 1 ? picks?.[item.id] : undefined;   // one quote: the one not already shown above
  const shown = pick ? [pick] : (item.quotes ?? []).slice(0, maxQuotes);
  return (
    <article className="rounded-lg border border-line bg-paper p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          {/* UX audit: the label is a quiet eyebrow, the claim is what you read */}
          {title && <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-3">{title}</p>}
          <p className="text-[0.98rem] leading-snug text-ink">{item.claim}</p>
        </div>
        <OpenEvidence id={item.id} />
      </div>
      {item.summary_for_humans && <p className="mb-2 text-sm text-ink-2">{item.summary_for_humans}</p>}
      <Meta item={item} />
      {shown.map((q) => (
        <div key={q.evidence_id + q.text} className="mt-3">
          <Quote text={q.text} evidence={evidence[q.evidence_id]} size="sm" />
        </div>
      ))}
      <LinkChips links={item.relations ?? []} />
    </article>
  );
}

type Side = { text: string; evidence_ids: string[] };

export function TensionCard({ item }: { item: InsightLike & { want: Side; but: Side } }) {
  const { evidence, picks } = usePack();
  const firstQuote = (side: Side, key: "want" | "but") => {
    const picked = picks?.[`${item.id}:${key}`]?.evidence_id;
    const ev = (picked && evidence[picked]) || side.evidence_ids.map((id) => evidence[id]).find(Boolean);
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
          {firstQuote(item.want, "want")}
        </div>
        <div className="sm:border-l sm:border-line sm:pl-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-3">But</p>
          <p className="mb-2 font-serif text-[1rem] text-ink">{item.but.text}</p>
          {firstQuote(item.but, "but")}
        </div>
      </div>
      <div className="mt-3"><Meta item={item} /></div>
      <LinkChips links={item.relations ?? []} />
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
  flags?: FlagLike[];
}) {
  return (
    <article className="rounded-lg border border-line bg-paper p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[1rem] leading-snug text-ink">{hook.text}</p>
        <CopyButton text={hook.text} label="Copy hook" />
      </div>
      <p className="mt-2 flex flex-wrap gap-x-1 font-mono text-xs text-ink-3">
        <span>{hook.id} · builds on</span>
        {hook.why_ids.map((id) => <IdLink key={id} id={id} />)}
      </p>
      <LegalNote flags={flags} />
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
        <span className="min-w-0 break-words text-sm text-ink" title={source.source_unit}>{unitWords(source.source_unit)}</span>
        <span className="shrink-0 text-xs font-medium text-ink-2">{dropped ? "Dropped" : "Kept"}</span>
      </div>
      {!dropped && source.kept !== undefined && (
        <div className="mt-2" aria-label={`${Math.round(share * 100)}% relevant`}>
          <div className="h-1.5 rounded-full bg-wash">
            <div className="h-1.5 rounded-full bg-ink" style={{ width: `${Math.round(share * 100)}%` }} />
          </div>
          <p className="mt-1 font-mono text-[0.72rem] text-ink-3">
            {source.kept} kept · {Math.round(share * 100)}% relevant
          </p>
        </div>
      )}
      <p className="mt-2 text-sm text-ink-2">{source.reason}</p>
    </article>
  );
}
