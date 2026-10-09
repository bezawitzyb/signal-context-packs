// Generic, schema-driven blocks so most pack sections need no bespoke code (guide Step 4.1).
import { useState, type ReactNode } from "react";
import type { Evidence, InsightLike } from "../lib/api";
import { ClaimCard, usePack, LinkChips } from "./cards";
import { Quote } from "./Quote";

export type Filter = "all" | "observed" | "strong";

export function applyFilter<T extends InsightLike>(items: T[], filter: Filter): T[] {
  if (filter === "observed") return items.filter((i) => i.claim_type === "observed");
  if (filter === "strong") return items.filter((i) => i.confidence.label === "strong");
  return items;
}

export function SectionTitle({ id, title, note, level = 2 }: { id?: string; title: string; note?: ReactNode; level?: 2 | 3 }) {
  const H = level === 3 ? "h3" : "h2";
  return (
    <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <H id={id} className={`scroll-mt-20 tracking-tight ${level === 3
        ? "text-sm font-semibold uppercase tracking-wide text-ink-3" : "text-lg font-semibold text-ink"}`}>{title}</H>
      {note && <p className="text-sm text-ink-3">{note}</p>}
    </header>
  );
}

/** Any list of claim-like items, filtered (All / Observed only / Strong only). */
export interface SectionNotes { so_what?: string; empty_reason?: string; next_steps?: string[]; see_also?: string[] }

/** V4: the section's so-what line and its "also relevant" links. */
export function SectionLead({ meta }: { meta?: SectionNotes }) {
  if (!meta?.so_what && !meta?.see_also?.length) return null;
  return (
    <div className="mb-3 space-y-1">
      {meta.so_what && <p className="text-sm text-ink-2"><span className="font-medium text-ink">So what:</span> {meta.so_what}</p>}
      {meta.see_also?.length ? <LinkChips links={meta.see_also.map((id) => ({ id, kind: "related" }))} /> : null}
    </div>
  );
}

/** V4: an empty section says why, in plain words, and what to try next. */
export function EmptyNote({ meta, fallback }: { meta?: SectionNotes; fallback: string }) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong p-4 text-sm text-ink-2">
      <p>{meta?.empty_reason || fallback}</p>
      {meta?.next_steps?.length ? <p className="mt-1 text-ink-3">Try: {meta.next_steps.join(" · ")}</p> : null}
    </div>
  );
}

/** V9 progressive disclosure: the top items, then "Show more (n)". */
export function ShowMore<T>({ items, limit, render }: { items: T[]; limit: number; render: (shown: T[]) => ReactNode }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, limit);
  return (
    <>
      {render(shown)}
      {items.length > limit && (
        <button type="button" onClick={() => setAll(!all)} aria-expanded={all}
                className="mt-3 rounded-lg border border-line px-3 py-1.5 text-sm text-ink-2 hover:border-ink hover:text-ink print:hidden">
          {all ? "Show fewer" : `Show more (${items.length - limit})`}
        </button>
      )}
    </>
  );
}

export function ItemSection<T extends InsightLike>({ id, title, items, filter = "all", titleKey, empty, columns = 2, level = 2, meta,
  limit = 4 }: {
  id?: string; title: string; items: T[]; filter?: Filter; titleKey?: keyof T; empty?: string; columns?: 1 | 2; level?: 2 | 3;
  meta?: SectionNotes; limit?: number;
}) {
  const shown = applyFilter(items, filter);
  return (
    <section aria-labelledby={id} className="mb-10">
      <SectionTitle id={id} title={title} level={level}
                    note={filter !== "all" && items.length ? `${shown.length} of ${items.length} shown` : undefined} />
      <SectionLead meta={meta} />
      {shown.length === 0 ? (
        items.length ? <p className="rounded-lg border border-dashed border-line-strong p-4 text-sm text-ink-3">Nothing matches this filter.</p>
          : <EmptyNote meta={meta} fallback={empty ?? "None found in this evidence."} />
      ) : (
        <ShowMore items={shown} limit={limit} render={(part) => (
          <div className={`grid gap-3 ${columns === 2 ? "md:grid-cols-2" : ""}`}>
            {part.map((it) => (
              <ClaimCard key={it.id} item={it} title={titleKey ? String(it[titleKey] ?? "") : undefined} />
            ))}
          </div>
        )} />
      )}
    </section>
  );
}

/** Real posts, each as a quote with its metadata. */
export function QuoteList({ evidence, limit }: { evidence: Evidence[]; limit?: number }) {
  return (
    <ul className="space-y-4">
      {evidence.slice(0, limit ?? evidence.length).map((e) => (
        <li key={e.id}><Quote text={e.text} evidence={e} /></li>
      ))}
    </ul>
  );
}

/** Quotes for a list of evidence ids, looked up in the pack. */
export function QuotesFor({ ids, limit = 3 }: { ids: string[]; limit?: number }) {
  const { evidence } = usePack();
  return <QuoteList evidence={ids.map((id) => evidence[id]).filter(Boolean)} limit={limit} />;
}

export interface Column<Row> {
  header: string;
  cell: (row: Row) => ReactNode;
  kind?: "their" | "ours" | "data"; // serif / sans / mono (PRD 10.1)
  className?: string;
}

const KIND = { their: "font-serif text-[0.98rem]", ours: "text-sm", data: "font-mono text-xs" };

export function TableSection<Row>({ caption, columns, rows, rowKey }: {
  caption: string; columns: Column<Row>[]; rows: Row[]; rowKey: (row: Row) => string;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-wash">
          <tr>
            {columns.map((c) => (
              <th key={c.header} scope="col" className={`px-3 py-2 text-xs font-medium uppercase tracking-wide text-ink-3 ${c.className?.includes("whitespace-nowrap") ? "whitespace-nowrap" : ""}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={rowKey(r)} className="border-t border-line align-top">
              {columns.map((c) => (
                <td key={c.header} className={`px-3 py-2 text-ink ${KIND[c.kind ?? "ours"]} ${c.className ?? ""}`}>
                  {c.cell(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
