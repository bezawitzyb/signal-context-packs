// S2 RESEARCH THEATRE (PRD 10.2): stage stepper, agent log, counters, cost, coverage, sources.
// The same view serves live runs (SSE) and replays (a pack's saved events).
import { Check, CornerDownRight, Search, TriangleAlert } from "lucide-react";
import type { RunStatus } from "../lib/api";
import { STEPS, toolWords, type Move, type Summary } from "../lib/runSummary";
import { SourceCard } from "./cards";

export function StageStepper({ step, done }: { step: number; done: boolean }) {
  return (
    <ol className="flex flex-wrap items-center gap-1 text-sm" aria-label="Progress">
      {STEPS.map((s, n) => {
        const state = done || n < step ? "done" : n === step ? "now" : "next";
        return (
          <li key={s.key} className="flex items-center gap-1" aria-current={state === "now" ? "step" : undefined}>
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 ${
              state === "done" ? "border-ink bg-ink text-paper"
                : state === "now" ? "border-ink text-ink font-medium" : "border-line text-ink-3"}`}>
              {state === "done" && <Check aria-hidden="true" size={13} />}
              {state === "now" && <span aria-hidden="true" className="size-1.5 rounded-full bg-accent motion-safe:animate-pulse" />}
              {s.label}
            </span>
            {n < STEPS.length - 1 && <span aria-hidden="true" className="text-ink-3">›</span>}
          </li>
        );
      })}
    </ol>
  );
}

function resultLine(m: Move): { text: string; tone: "good" | "weak" | "none" | "limit" } | null {
  const r = m.result;
  if (!r) return null;
  if (r.status === "limit_reached") return { text: "limit reached - not run", tone: "limit" };
  if (r.status !== "ok") return { text: r.status, tone: "limit" };
  if (m.tool === "coverage_report") return { text: "coverage checked", tone: "none" };
  if (m.tool === "finish") return { text: "collection finished", tone: "none" };
  if (m.tool === "web_search" && r.collected === 0) return { text: "pages found for reading", tone: "none" };
  if (r.collected === 0) return { text: "nothing found", tone: "weak" };
  const pct = Math.round(r.relevantShare * 100);
  return { text: `collected ${r.collected} · kept ${r.kept} · ${pct}% relevant`, tone: pct >= 30 ? "good" : "weak" };
}

export function AgentLog({ moves }: { moves: Move[] }) {
  if (!moves.length) return <p className="text-sm text-ink-3">The agent's first moves will appear here.</p>;
  return (
    <ol className="space-y-2">
      {moves.map((m) => {
        const res = resultLine(m);
        return (
          <li key={m.seq} className={`rounded-lg border p-3 ${m.gapFill ? "border-ink" : "border-line"}`}>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-mono text-xs text-ink-3">#{m.seq}</span>
              <span className="text-sm font-medium text-ink">{toolWords(m.tool)}</span>
              {m.sourceUnit && <span className="font-mono text-xs text-ink-2 break-all">{m.sourceUnit}</span>}
              {m.gapFill && (
                <span className="rounded border border-ink px-1.5 py-px text-[0.7rem] font-medium text-ink">Filling a gap</span>
              )}
            </div>
            {m.reason && m.reason !== "-" && (
              <p className="mt-1 flex gap-1.5 text-sm text-ink-2">
                <Search aria-hidden="true" size={13} className="mt-0.5 shrink-0 text-ink-3" />{m.reason}
              </p>
            )}
            {res ? (
              <p className={`mt-1 flex flex-wrap items-center gap-x-1.5 font-mono text-xs ${
                res.tone === "weak" || res.tone === "limit" ? "text-accent-ink" : "text-ink"}`}>
                <CornerDownRight aria-hidden="true" size={12} className="shrink-0" />
                <span className="whitespace-nowrap">{res.text}</span>
                {m.result!.newTerms.length > 0 && (
                  <span className="text-ink-3">· new terms: {m.result!.newTerms.slice(0, 6).join(", ")}</span>
                )}
              </p>
            ) : (
              <p className="mt-1 font-mono text-xs text-ink-3">working…</p>
            )}
          </li>
        );
      })}
    </ol>
  );
}

const COUNTER_LABELS: [string, string][] = [
  ["collected", "Collected"], ["duplicates", "Duplicates"], ["spam", "Spam"], ["out_of_window", "Out of window"],
  ["kept", "Kept"], ["relevant", "Relevant"],
];

export function Counters({ counters, cost }: { counters: Summary["counters"]; cost: Summary["cost"] }) {
  return (
    <div className="grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-line bg-line">
      {COUNTER_LABELS.map(([k, label]) => (
        <div key={k} className="bg-paper px-3 py-2">
          <p className="text-[0.7rem] uppercase tracking-wide text-ink-3">{label}</p>
          <p className="font-mono text-lg text-ink">{counters?.[k] ?? 0}</p>
        </div>
      ))}
      {cost && (
        <div className="col-span-3 bg-paper px-3 py-2">
          <p className="text-[0.7rem] uppercase tracking-wide text-ink-3">Cost so far</p>
          <p className="font-mono text-sm text-ink">
            ${(cost.apify_usd + cost.llm_usd).toFixed(2)}
            <span className="text-ink-3"> · Apify ${cost.apify_usd.toFixed(2)} · Anthropic ${cost.llm_usd.toFixed(2)}</span>
          </p>
        </div>
      )}
    </div>
  );
}

export function CoverageBars({ questions }: { questions: Summary["coverage"] }) {
  if (!questions.length) return null;
  const max = Math.max(...questions.map((q) => q.docs), 1);
  return (
    <ul className="space-y-2">
      {questions.map((q) => (
        <li key={q.id}>
          <div className="flex items-baseline justify-between gap-2 text-sm">
            <span className="text-ink-2"><span className="mr-1 font-mono text-xs text-ink-3">{q.id}</span>{q.text}</span>
            <span className={`shrink-0 font-mono text-xs ${q.docs < 20 ? "text-accent-ink" : "text-ink"}`}>{q.docs} posts</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-wash" aria-hidden="true">
            <div className="h-1.5 rounded-full bg-ink" style={{ width: `${Math.max(3, (q.docs / max) * 100)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function SourcesVerdict({ collection }: { collection: RunStatus["collection"] }) {
  if (!collection) return null;
  return (
    <div className="space-y-3">
      <div className="grid gap-2 md:grid-cols-2">
        {collection.sources_used.map((s) => <SourceCard key={s.source_unit} source={s} />)}
        {collection.sources_dropped.map((s) => <SourceCard key={s.source_unit} source={s} dropped />)}
      </div>
      {collection.gaps.length > 0 && (
        <div className="rounded-lg border border-line p-3">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-3">Gaps the agent reported</p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
            {collection.gaps.map((g) => <li key={g}>{g}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export function Notices({ summary }: { summary: Summary }) {
  return (
    <>
      {summary.fallbacks.map((f, n) => (
        <p key={n} className="flex gap-2 rounded-lg border border-line-strong bg-wash p-3 text-sm text-ink">
          <TriangleAlert aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
          {f.kind === "top_up" ? "Evidence was short, so the agent topped up from sources it had kept. " : "The agent loop failed, so the fallback plan collected from the untried starting sources. "}
          <span className="text-ink-2">{f.reason}</span>
        </p>
      ))}
      {summary.errors.map((e, n) => (
        <p key={n} role="alert" className="rounded-lg border border-accent p-3 text-sm text-ink">{e.message}</p>
      ))}
    </>
  );
}

/** Milestones for screen readers (polite), never every log line. */
export function Announcer({ milestones }: { milestones: string[] }) {
  return <p aria-live="polite" className="sr-only">{milestones[milestones.length - 1] ?? ""}</p>;
}
