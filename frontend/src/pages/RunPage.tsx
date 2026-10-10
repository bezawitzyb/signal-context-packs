// /runs/:id - the Research Theatre for a live run (SSE). ?replay=1 plays the finished run back from its pack.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ArrowRight, Hourglass, Square } from "lucide-react";
import { friendlyError, getOwnerRunCost, getRun, stopRun, ApiError, type RunStatus } from "../lib/api";
import { explain, readRunKey } from "../lib/runKey";
import { summarize } from "../lib/runSummary";
import { useRunEvents } from "../lib/useRunEvents";
import { AgentLog, Announcer, CoverageBars, Counters, Notices, SourcesVerdict, StageStepper } from "../components/Theatre";
import { STEPS } from "../lib/runSummary";
import { useDoneSignal } from "../lib/doneSignal";
import { ReplayPage } from "./ReplayPage";
import { Skeleton } from "../components/Skeleton";
import { ErrorNote } from "../components/ErrorNote";
import { addMyPack, rerunUrl, type RunInputs } from "../lib/rerun";
import { packTitle } from "../lib/title";

const FINISHED = ["complete", "partial", "failed", "stopped"];

const REPLANS: Record<string, { label: string; change: (i: RunInputs) => Parameters<typeof rerunUrl>[1] }> = {
  broaden_audience: { label: "Broaden the audience", change: (i) => ({ brief: `${i.brief} (any audience, broadly)` }) },
  include_english: { label: "Include English posts", change: (i) => ({ brief: `${i.brief} (include English-language posts)` }) },
  widen_window: { label: "Look back a full year", change: () => ({ window: 365 }) },
  run_standard: { label: "Run Standard (more sources)", change: () => ({ mode: "standard" }) },
};

/** Below the floor (V1): why, in plain words, and one-click re-plans - never a silent hang. */
function ThinScreen({ thin, inputs }: { thin: NonNullable<NonNullable<RunStatus["collection"]>["thin"]>; inputs: RunInputs }) {
  return (
    <section aria-labelledby="thin" className="space-y-3 rounded-lg border border-line-strong bg-wash p-4">
      <h2 id="thin" className="text-lg font-semibold text-ink">Not enough to build a pack this time</h2>
      <p className="text-sm text-ink-2">The research found {thin.relevant} posts about this topic; a pack needs at least {thin.needed}.</p>
      <ul className="list-disc space-y-1 pl-5 text-sm text-ink">
        {thin.reasons.map((r) => <li key={r.code}>{r.text}</li>)}
      </ul>
      <p className="text-sm font-medium text-ink">Try again with one change:</p>
      <div className="flex flex-wrap gap-2">
        {thin.replans.filter((k) => REPLANS[k]).map((k) => (
          <Link key={k} to={rerunUrl(inputs, REPLANS[k].change(inputs))}
                className="rounded-lg border border-ink px-3 py-1.5 text-sm text-ink hover:bg-paper">{REPLANS[k].label}</Link>
        ))}
        <Link to={rerunUrl(inputs)} className="rounded-lg px-3 py-1.5 text-sm text-ink underline">Edit the brief yourself</Link>
      </div>
    </section>
  );
}

function minutes(secs: number) {
  return secs < 60 ? "under a minute" : `about ${Math.round(secs / 60)} min`;
}

export function TheatreLayout({ title, status, summary, collection, children, ownerCost = null }: {
  title: string; status: React.ReactNode; summary: ReturnType<typeof summarize>;
  collection: RunStatus["collection"]; children?: React.ReactNode; ownerCost?: { apify_usd: number; llm_usd: number } | null;
}) {
  const done = Boolean(summary.packId);
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        <div className="text-ink-2">{status}</div>
        <StageStepper step={summary.step} done={done} />
      </header>
      {children}
      <Notices summary={summary} />
      <Announcer milestones={summary.milestones} />
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <section aria-labelledby="log">
          <h2 id="log" className="mb-3 text-lg font-semibold text-ink">{done ? "What the agent did" : "What the agent is doing"}</h2>
          <AgentLog moves={summary.moves} />
        </section>
        <aside className="space-y-6">
          <section aria-labelledby="funnel">
            <h2 id="funnel" className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-3">{done ? "Posts collected" : "Posts so far"}</h2>
            <Counters counters={summary.counters} cost={ownerCost} />
          </section>
          {summary.coverage.length > 0 && (
            <section aria-labelledby="cov">
              <h2 id="cov" className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-3">Evidence per question</h2>
              <CoverageBars questions={summary.coverage} />
            </section>
          )}
        </aside>
      </div>
      {collection && (
        <section aria-labelledby="verdicts">
          <h2 id="verdicts" className="mb-1 text-lg font-semibold text-ink">Sources kept and dropped</h2>
          <p className="mb-3 text-sm text-ink-2">Dropping sources is normal: the agent keeps only places where people
            really talk about the topic.</p>
          <SourcesVerdict collection={collection} questions={summary.coverage} />
        </section>
      )}
    </div>
  );
}

function LiveRun({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  // The owner key is in this tab: show what the run costs (live events first, else the saved totals).
  const [ownerCost, setOwnerCost] = useState<{ apify_usd: number; llm_usd: number } | null>(null);
  const { events, live } = useRunEvents(runId);
  const summary = useMemo(() => summarize(events), [events]);
  const last = events[events.length - 1];

  useEffect(() => {
    getRun(runId).then(setRun).catch((e) => setError(friendlyError(e)));
  }, [runId, last?.seq, summary.step]);

  useEffect(() => {
    const key = readRunKey();
    if (key) getOwnerRunCost(key, runId).then((c) => setOwnerCost({ apify_usd: c.apify_usd, llm_usd: c.anthropic_usd }))
      .catch(() => setOwnerCost(null));
  }, [runId, summary.packId]);

  useDoneSignal(run && { brief: packTitle(run.brief, run.interpretation?.topic), finished: FINISHED.includes(run.status), ok: Boolean(summary.packId ?? run.pack_id) });

  if (error) return <ErrorNote message={error} />;
  if (!run) return <Skeleton lines={3} label="Loading the run" />;
  const finished = FINISHED.includes(run.status);
  const packId = summary.packId ?? run.pack_id;
  const thin = run.collection?.thin;
  if (packId && finished) addMyPack({ pack_id: packId, brief: packTitle(run.brief, run.interpretation?.topic), at: run.created_at });

  const stop = async () => {
    const key = readRunKey();
    if (!key) return setError("Stopping needs your access key: enter it on the start page first.");
    setStopping(true);
    try { setRun(await stopRun(key, runId)); } catch (e) {
      setError(e instanceof ApiError ? explain(e.status, e.message) : "Could not reach the server.");
    } finally { setStopping(false); }
  };

  const status = run.status === "queued" && summary.queue
    ? <p className="flex items-center gap-2"><Hourglass aria-hidden="true" size={15} />
        Waiting in line: position {run.queue_position ?? summary.queue.position}, starts in {minutes(summary.queue.estimated_start_secs)}. It starts by itself.</p>
    : run.status === "failed" && thin ? <p className="text-ink">Finished without a pack: too few posts about this topic.</p>
    : run.status === "failed" ? (
        <p role="alert" className="text-ink">{run.error ?? "The run could not finish."} Your inputs are kept: run it again below.</p>)
    : run.status === "partial" && packId ? <p>Finished with a partial pack: open it to see what is missing and why (first blind spot).</p>
    : finished ? <p>Finished: the pack is ready.</p>
    : <p>{live ? "Live" : "Reconnecting…"} · {run.mode === "standard" ? "Standard" : "Quick"} research
        · about {Math.max(1, Math.round(run.estimate.typical_minutes * (1 - summary.step / STEPS.length)))} min left
        <span className="text-ink-3"> · you can leave this page: the research keeps going</span></p>;

  return (
    <TheatreLayout title={packTitle(run.brief, run.interpretation?.topic)} status={status} summary={summary} collection={run.collection}
                   ownerCost={ownerCost && (summary.cost ?? ownerCost)}>
      {finished && thin && run.inputs && <ThinScreen thin={thin} inputs={run.inputs} />}
      <div className="flex flex-wrap gap-2">
        {packId && (
          <Link to={`/packs/${packId}`} className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-ink">
            Open the pack <ArrowRight aria-hidden="true" size={15} />
          </Link>
        )}
        {!finished && (
          <button type="button" onClick={stop} disabled={stopping}
                  className="inline-flex items-center gap-2 rounded-lg border border-ink px-3 py-2 text-sm text-ink disabled:opacity-60">
            <Square aria-hidden="true" size={13} /> Stop and build the pack now
          </button>
        )}
        {finished && run.inputs && (!packId || run.status === "partial") && (
          <Link to={rerunUrl(run.inputs)} className="inline-flex items-center gap-2 rounded-lg border border-ink px-3 py-2 text-sm text-ink">
            Run again with these inputs
          </Link>
        )}
      </div>
    </TheatreLayout>
  );
}

export function RunPage() {
  const { runId = "" } = useParams();
  const [params] = useSearchParams();
  return params.get("replay") === "1" ? <ReplayPage runId={runId} /> : <LiveRun runId={runId} />;
}
