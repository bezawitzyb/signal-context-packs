// Generic, schema-driven blocks so most pack sections need no bespoke code (guide Step 4.1).
import type { ReactNode } from "react";
import type { Evidence, InsightLike } from "../lib/api";
import { ClaimCard, usePack } from "./cards";
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
export function ItemSection<T extends InsightLike>({ id, title, items, filter = "all", titleKey, empty, columns = 2, level = 2 }: {
  id?: string; title: string; items: T[]; filter?: Filter; titleKey?: keyof T; empty?: string; columns?: 1 | 2; level?: 2 | 3;
}) {
  const shown = applyFilter(items, filter);
  return (
    <section aria-labelledby={id} className="mb-10">
      <SectionTitle id={id} title={title} level={level}
                    note={filter !== "all" && items.length ? `${shown.length} of ${items.length} shown` : undefined} />
      {shown.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-strong p-4 text-sm text-ink-3">
          {items.length ? "Nothing matches this filter." : empty ?? "None found in this evidence."}
        </p>
      ) : (
        <div className={`grid gap-3 ${columns === 2 ? "md:grid-cols-2" : ""}`}>
          {shown.map((it) => (
            <ClaimCard key={it.id} item={it} title={titleKey ? String(it[titleKey] ?? "") : undefined} />
          ))}
        </div>
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
              <th key={c.header} scope="col" className="px-3 py-2 text-xs font-medium uppercase tracking-wide text-ink-3">
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
