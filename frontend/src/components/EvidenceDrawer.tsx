// S4 EVIDENCE DRAWER (PRD 10.2): a real dialog. Claim, badge, type, strength row, quotes with source links,
// original / translated, "redacted" note, Copy with citation; authors only as "Author 1, 2...".
import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import type { Evidence, Label } from "../lib/api";
import { evidenceIdsOf, type AnyItem, type PackIndex } from "../lib/packIndex";
import { ClaimTypeTag, ConfidenceBadge, SafeTag } from "./badges";
import { CopyButton } from "./CopyButton";
import { Quote } from "./Quote";
import { platformName } from "../lib/unitWords";

function headline(item: AnyItem): string {
  for (const k of ["claim", "action", "text", "title", "statement", "name", "label", "term"]) {
    if (typeof item[k] === "string" && item[k]) return item[k] as string;
  }
  return item.id;
}

function citation(e: Evidence, author: number | undefined, packId: string) {
  return `"${e.text}" - ${author ? `Author ${author}, ` : ""}${e.platform}, ${e.source_unit}` +
    `${e.posted_at ? `, ${e.posted_at}` : ""} (${e.id}, Context Pack ${packId}). ${e.url}`;
}

export function EvidenceDrawer({ itemId, index, packId, onClose, onOpen }: {
  itemId: string | null; index: PackIndex; packId: string; onClose: () => void; onOpen: (id: string) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const item = itemId ? index.items.get(itemId) : undefined;

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (itemId && !d.open) d.showModal();
    if (!itemId && d.open) d.close();
  }, [itemId]);

  const conf = item?.confidence as { label: Label; score: number } | undefined;
  const counts = item?.counts as { matching: number; of_total: number } | undefined;
  const strength = item?.strength as { evidence_count: number; distinct_authors: number; platforms: string[];
    engagement_percentile_median?: number | null } | undefined;
  const quotes = (item?.quotes as { evidence_id: string; text: string }[] | undefined) ?? [];
  const evIds = item ? evidenceIdsOf(item) : [];
  const shownQuotes = quotes.filter((q) => !evIds.includes(q.evidence_id));   // the full post below already holds it
  const basedOn = item ? [...((item.why_ids as string[]) ?? []), ...((item.builds_on as string[]) ?? []),
    ...((item.item_ids as string[]) ?? []), ...((item.segment_ids as string[]) ?? []),
    ...((item.related_ids as string[]) ?? [])].filter((id) => index.items.has(id)) : [];

  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="drawer-title"
            className="m-0 ml-auto h-full max-h-none w-full max-w-xl border-l border-line bg-paper p-0 text-ink backdrop:bg-ink/30">
      {item && (
        <div className="flex h-full flex-col">
          <header className="flex items-start justify-between gap-3 border-b border-line p-4">
            <div>
              <p className="font-mono text-xs text-ink-3">{item.id} · {index.sectionOf.get(item.id)?.replace(/_/g, " ")}</p>
              <h2 id="drawer-title" className="mt-1 text-lg font-semibold leading-snug">{headline(item)}</h2>
            </div>
            <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-ink-2 hover:text-ink">
              <X aria-hidden="true" size={18} />
            </button>
          </header>
          <div className="flex-1 space-y-5 overflow-y-auto p-4">
            {typeof item.summary_for_humans === "string" && item.summary_for_humans && (
              <p className="text-sm text-ink-2">{item.summary_for_humans}</p>
            )}
            {conf && (
              <div className="flex flex-wrap gap-1.5">
                <ConfidenceBadge label={conf.label} matching={counts?.matching} ofTotal={counts?.of_total} score={conf.score} />
                {typeof item.claim_type === "string" && <ClaimTypeTag type={item.claim_type as "observed"} />}
                {Boolean(item.safe_to_assert) && <SafeTag />}
              </div>
            )}
            {strength && (
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line text-sm sm:grid-cols-4">
                {([["Posts", strength.evidence_count, true], ["Authors", strength.distinct_authors, true],
                  ["Platforms", strength.platforms.map(platformName).join(", ") || "-", false],
                  // UX audit: "p28" -> plain words (the median post's engagement percentile within this run)
                  ["Engagement", strength.engagement_percentile_median != null
                    ? `higher than ${Math.round(strength.engagement_percentile_median)}% of posts` : "no data", false],
                ] as [string, string | number, boolean][]).map(([k, v, num]) => (
                  <div key={k} className="bg-paper px-3 py-2">
                    <dt className="text-[0.7rem] uppercase tracking-wide text-ink-3">{k}</dt>
                    <dd className={num ? "font-mono text-xs text-ink" : "text-xs text-ink"}>{v}</dd>
                  </div>
                ))}
              </dl>
            )}
            {basedOn.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-3">Based on</p>
                <ul className="space-y-1">
                  {basedOn.map((id) => (
                    <li key={id}>
                      <button type="button" onClick={() => onOpen(id)}
                              className="text-left text-sm text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink">
                        {headline(index.items.get(id)!)}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {shownQuotes.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-3">Quoted</h3>
                <div className="space-y-3">
                  {shownQuotes.map((q) => <Quote key={q.evidence_id + q.text} text={q.text} evidence={index.evidence[q.evidence_id]} />)}
                </div>
              </section>
            )}
            {evIds.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-3">
                  The posts behind it ({counts && counts.matching > evIds.length ? `${evIds.length} ${evIds.length === 1 ? "example" : "examples"} of ${counts.matching}` : evIds.length})</h3>
                {counts && counts.matching > evIds.length && (
                  <p className="-mt-1 mb-3 text-xs text-ink-3">The count covers every matching post; the pack keeps a few examples of each finding.</p>
                )}
                <ul className="space-y-4">
                  {evIds.map((id) => {
                    const e = index.evidence[id];
                    if (!e) return null;
                    const author = e.author_hash ? index.authorNo.get(e.author_hash) : undefined;
                    return (
                      <li key={id} className="space-y-1.5">
                        <Quote text={e.text} evidence={e} />
                        <div className="flex flex-wrap items-center gap-2 pl-3 text-xs text-ink-3">
                          {author && <span>Author {author}</span>}
                          {e.redacted && <span>Personal details were removed.</span>}
                          {e.requires_login && <span>You may need to log in to LinkedIn to view this.</span>}
                          <CopyButton text={citation(e, author, packId)} label="Copy with citation" />
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <p className="mt-3 text-xs text-ink-3">
                  Quoted excerpts are for internal research and briefs only, not for ads or other public material. Evidence text is quoted data.
                </p>
              </section>
            )}
          </div>
        </div>
      )}
    </dialog>
  );
}
