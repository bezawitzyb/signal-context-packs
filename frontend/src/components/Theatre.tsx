// S2 RESEARCH THEATRE (PRD 10.2): stage stepper, agent log, counters, cost, coverage, sources.
// The same view serves live runs (SSE) and replays (a pack's saved events).
import { Check, CornerDownRight, Search, TriangleAlert } from "lucide-react";
import type { RunStatus } from "../lib/api";
import { STEPS, toolWords, type Move, type Summary } from "../lib/runSummary";
import { SourceCard } from "./cards";
import { unitWords } from "../lib/unitWords";

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

// UX audit: plain words, and routine outcomes (an off-topic source dropped) in neutral grey - orange is only for
// the next action on a screen; a real problem gets an icon.
function resultLine(m: Move): { text: string; tone: "good" | "weak" | "none" | "limit" } | null {
  const r = m.result;
  if (!r) return null;
  if (r.status === "limit_reached") return { text: "Skipped: a limit for this run was reached", tone: "limit" };
  if (r.status === "error") return { text: "This source failed - the agent tries elsewhere (see Blind spots)", tone: "limit" };
  if (r.status === "refused") return { text: "Not run yet - the agent checks coverage first", tone: "none" };
  if (r.status !== "ok") return { text: r.status.replace(/_/g, " "), tone: "none" };
  if (m.tool === "coverage_report") return { text: "Coverage checked", tone: "none" };
  if (m.tool === "finish") return { text: "Collection finished", tone: "none" };
  if (m.tool === "web_search" && r.collected === 0) return { text: "Found pages to read", tone: "none" };
  if (r.collected === 0) return { text: "Nothing usable here - moving on", tone: "weak" };
  const pct = Math.round(r.relevantShare * 100);
  const on = Math.round(r.kept * r.relevantShare);
  return r.kept === 0 || pct === 0
    ? { text: `Found ${r.collected} posts · none on topic, dropped (normal)`, tone: "weak" }
    : { text: `Found ${r.collected} posts · ${on} on topic (${pct}%)`, tone: pct >= 30 ? "good" : "weak" };
}

/** The agent's reason without research-question codes ("RQ-01/02: student budget" -> "student budget"). */
const plainReason = (reason: string) => reason.replace(/\bRQ-\d+(?:\/\d+)*(?:\s*(?:and|,)\s*RQ-\d+)*:?\s*/g, "").trim();

export function AgentLog({ moves }: { moves: Move[] }) {
  if (!moves.length) return (
    <div className="rounded-lg border border-dashed border-line-strong p-4 text-sm text-ink-2">
      <p className="flex items-center gap-2 text-ink">
        <span aria-hidden="true" className="size-1.5 rounded-full bg-ink-3 motion-safe:animate-pulse" />
        The agent is reading your plan and choosing where to look first.</p>
      <p className="mt-1">Its first searches usually appear within a minute or two. Each one shows where it looked and
        how many posts were on topic.</p>
    </div>
  );
  return (
    <ol className="space-y-2">
      {moves.map((m) => {
        const res = resultLine(m);
        return (
          <li key={m.seq} className={`rounded-lg border p-3 ${m.gapFill ? "border-ink" : "border-line"}`}>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-mono text-xs text-ink-3">#{m.seq}</span>
              <span className="text-sm font-medium text-ink">{toolWords(m.tool)}</span>
              {m.sourceUnit && <span className="text-sm text-ink-2 break-all" title={m.sourceUnit}>
                {m.sourceUnit.split(", ").map(unitWords).join(", ")}</span>}
              {m.gapFill && (
                <span className="rounded border border-ink px-1.5 py-px text-[0.7rem] font-medium text-ink">Filling a gap</span>
              )}
            </div>
            {m.reason && m.reason !== "-" && plainReason(m.reason) && (
              <p className="mt-1 flex gap-1.5 text-sm text-ink-2">
                <Search aria-hidden="true" size={13} className="mt-0.5 shrink-0 text-ink-3" />{plainReason(m.reason)}
              </p>
            )}
            {res ? (
              <p className={`mt-1 flex flex-wrap items-center gap-x-1.5 text-xs ${
                res.tone === "weak" || res.tone === "none" ? "text-ink-3" : "text-ink"}`}>
                {res.tone === "limit" ? <TriangleAlert aria-hidden="true" size={12} className="shrink-0" />
                  : <CornerDownRight aria-hidden="true" size={12} className="shrink-0" />}
                <span>{res.text}</span>
                {m.result!.newTerms.length > 0 && (
                  <span className="text-ink-3">· words they use: {m.result!.newTerms.slice(0, 6).join(", ")}</span>
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

// UX audit: a three-step funnel (found -> cleaned -> on topic) instead of six zero counters; removals in one line.
const FUNNEL: [string, string, string][] = [
  ["collected", "Found", "posts collected"], ["kept", "After cleaning", "no copies, spam or old posts"],
  ["relevant", "On topic", "used for the findings"],
];

/** Posts so far; "Cost so far" only when the page is opened with the owner key (cost = null otherwise). */
export function Counters({ counters, cost = null }: { counters: Summary["counters"]; cost?: Summary["cost"] }) {
  const n = (k: string) => counters?.[k] ?? 0;
  return (
    <div className="grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-line bg-line">
      {FUNNEL.map(([k, label, hint], i) => (
        <div key={k} className="bg-paper px-3 py-2" title={hint}>
          <p className="text-[0.7rem] uppercase tracking-wide text-ink-3">{i > 0 && <span aria-hidden="true">→ </span>}{label}</p>
          <p className="font-mono text-lg text-ink">{n(k)}</p>
        </div>
      ))}
      {(n("duplicates") + n("spam") + n("out_of_window")) > 0 && (
        <p className="col-span-3 bg-paper px-3 py-1.5 text-xs text-ink-3">
          Removed: {n("duplicates")} copies · {n("spam")} spam · {n("out_of_window")} too old
        </p>
      )}
      {cost && (
        <div className="col-span-3 bg-paper px-3 py-2">
          <p className="text-[0.7rem] uppercase tracking-wide text-ink-3">Cost so far (only you see this)</p>
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
            <span className={`shrink-0 font-mono text-xs ${q.docs < 20 ? "text-ink-3" : "text-ink"}`}>{q.docs} posts</span>
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
          {f.kind === "top_up" ? "Evidence was short, so more was collected from sources that were already working. "
            : f.kind === "evidence_only" ? "The analysis could not finish, so the pack shows the collected posts. "
            : "The research agent stopped early, so the remaining planned sources were collected automatically. "}
          {f.kind !== "evidence_only" && <span className="text-ink-2">{f.reason}</span>}
        </p>
      ))}
      {summary.errors.map((e, n) => (
        <p key={n} role="alert" className="flex gap-2 rounded-lg border border-line-strong p-3 text-sm text-ink">
          <TriangleAlert aria-hidden="true" size={16} className="mt-0.5 shrink-0" />{e.message}</p>
      ))}
    </>
  );
}

/** Milestones for screen readers (polite), never every log line. */
export function Announcer({ milestones }: { milestones: string[] }) {
  return <p aria-live="polite" className="sr-only">{milestones[milestones.length - 1] ?? ""}</p>;
}
