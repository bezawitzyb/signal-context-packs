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
  const items: [string, React.ReactNode][] = [
    ["Coverage", GRADE[pack.snapshot.coverage_grade] ?? pack.snapshot.coverage_grade],
    ["Relevant posts", String(c.counts.relevant)],
    ["Platforms", platforms.join(", ") || "-"],
    ["Languages", langs.join(", ") || "-"],
    ["Dates", c.date_range?.start ? <><span className="whitespace-nowrap">{c.date_range.start}</span> → <span className="whitespace-nowrap">{c.date_range.end}</span></> : "mostly undated"],
  ];
  const dq = c.data_quality;   // data audit: how complete the relevant posts are
  if (dq?.dated_share != null) items.push(["Dated posts", `${pct(dq.dated_share)} (the time window applies to these)`]);
  if (dq?.engagement_share != null) items.push(["With engagement data", pct(dq.engagement_share)]);
  if (dq?.translated_share != null) items.push(["Translated", `${pct(dq.translated_share)} of non-English posts`]);
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <dl className="grid grid-cols-2 gap-px bg-line sm:grid-cols-3">
        {items.map(([k, v]) => (
          <div key={k} className="bg-paper px-3 py-2">
            <dt className="text-[0.7rem] font-medium uppercase tracking-wide text-ink-3">{k}</dt>
            <dd className="mt-0.5 font-mono text-xs text-ink">{v}</dd>
          </div>
        ))}
        <div className="bg-paper px-3 py-2">
          <dt className="sr-only">Mode and evidence</dt>
          <dd className="flex items-center gap-2">
            <ModeBadge mode={pack.mode} />
            {c.thin_evidence && <span className="rounded border border-accent px-1.5 py-0.5 text-xs text-accent-ink">Thin evidence</span>}
          </dd>
        </div>
      </dl>
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
