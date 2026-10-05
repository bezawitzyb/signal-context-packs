// Coverage strip and limitation callout (PRD 10.3, 10.4).
import { Info } from "lucide-react";
import type { ContextPack } from "../lib/api";
import { ModeBadge } from "./badges";

const GRADE: Record<string, string> = {
  a: "A - broad: 4+ platforms, all target languages",
  b: "B - good: 3+ platforms",
  c: "C - narrow: 2 platforms or fewer posts",
  d: "D - thin: under 100 posts or one platform",
};

export function CoverageStrip({ pack }: { pack: ContextPack }) {
  const c = pack.coverage;
  const platforms = [...new Set((c.sources_used ?? []).map((s) => s.platform))];
  const pct = (share: number) => (share > 0 && share < 0.005 ? "<1%" : `${Math.round(share * 100)}%`);
  const langs = (c.language_mix ?? []).map((l) => `${l.language} ${pct(l.share)}`);
  const items: [string, string][] = [
    ["Coverage", GRADE[pack.snapshot.coverage_grade] ?? pack.snapshot.coverage_grade],
    ["Relevant posts", String(c.counts.relevant)],
    ["Platforms", platforms.join(", ") || "-"],
    ["Languages", langs.join(", ") || "-"],
    ["Dates", c.date_range?.start ? `${c.date_range.start} → ${c.date_range.end}` : "mostly undated"],
  ];
  return (
    <div className="flex flex-wrap items-stretch gap-px overflow-hidden rounded-lg border border-line bg-line">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-[8rem] flex-1 bg-paper px-3 py-2">
          <p className="text-[0.7rem] font-medium uppercase tracking-wide text-ink-3">{k}</p>
          <p className={`mt-0.5 font-mono text-xs text-ink ${k === "Dates" ? "whitespace-nowrap" : ""}`}>{v}</p>
        </div>
      ))}
      <div className="flex items-center gap-2 bg-paper px-3 py-2">
        <ModeBadge mode={pack.mode} />
        {c.thin_evidence && <span className="rounded border border-accent px-1.5 py-0.5 text-xs text-accent-ink">Thin evidence</span>}
      </div>
    </div>
  );
}

export function LimitationCallout({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <aside className="flex gap-3 rounded-lg border border-line-strong bg-wash p-3 text-sm text-ink-2">
      <Info aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-ink" />
      <div>
        <p className="font-medium text-ink">{title}</p>
        <div className="mt-0.5">{children}</div>
      </div>
    </aside>
  );
}
