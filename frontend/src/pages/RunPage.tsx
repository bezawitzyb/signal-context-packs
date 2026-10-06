// /runs/:id - the Research Theatre for a live run (SSE). ?replay=1 plays the finished run back from its pack.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ArrowRight, Hourglass, Square } from "lucide-react";
import { friendlyError, getRun, stopRun, ApiError, type RunStatus } from "../lib/api";
import { explain, readRunKey } from "../lib/runKey";
import { summarize } from "../lib/runSummary";
import { useRunEvents } from "../lib/useRunEvents";
import { AgentLog, Announcer, CoverageBars, Counters, Notices, SourcesVerdict, StageStepper } from "../components/Theatre";
import { ReplayPage } from "./ReplayPage";
import { Skeleton } from "../components/Skeleton";
import { ErrorNote } from "../components/ErrorNote";

const FINISHED = ["complete", "partial", "failed", "stopped"];

function minutes(secs: number) {
  return secs < 60 ? "under a minute" : `about ${Math.round(secs / 60)} min`;
}

export function TheatreLayout({ title, status, summary, collection, children }: {
  title: string; status: React.ReactNode; summary: ReturnType<typeof summarize>;
  collection: RunStatus["collection"]; children?: React.ReactNode;
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
          <h2 id="log" className="mb-3 text-lg font-semibold text-ink">What the agent is doing</h2>
          <AgentLog moves={summary.moves} />
        </section>
        <aside className="space-y-6">
          <section aria-labelledby="funnel">
            <h2 id="funnel" className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-3">Posts so far</h2>
            <Counters counters={summary.counters} cost={summary.cost} />
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
          <h2 id="verdicts" className="mb-3 text-lg font-semibold text-ink">Sources kept and dropped</h2>
          <SourcesVerdict collection={collection} />
        </section>
      )}
    </div>
  );
}

function LiveRun({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const { events, live } = useRunEvents(runId);
  const summary = useMemo(() => summarize(events), [events]);
  const last = events[events.length - 1];

  useEffect(() => {
    getRun(runId).then(setRun).catch((e) => setError(friendlyError(e)));
  }, [runId, last?.seq, summary.step]);

  if (error) return <ErrorNote message={error} />;
  if (!run) return <Skeleton lines={3} label="Loading the run" />;
  const finished = FINISHED.includes(run.status);
  const packId = summary.packId ?? run.pack_id;

  const stop = async () => {
    const key = readRunKey();
    if (!key) return setError("Stopping needs the run key: enter it on the start page first.");
    setStopping(true);
    try { setRun(await stopRun(key, runId)); } catch (e) {
      setError(e instanceof ApiError ? explain(e.status, e.message) : "Could not reach the server.");
    } finally { setStopping(false); }
  };

  const status = run.status === "queued" && summary.queue
    ? <p className="flex items-center gap-2"><Hourglass aria-hidden="true" size={15} />
        Waiting in line: position {run.queue_position ?? summary.queue.position}, starts in {minutes(summary.queue.estimated_start_secs)}. It starts by itself.</p>
    : run.status === "failed" ? (
        <p role="alert" className="text-ink">
          {run.error ?? "The run failed."}{" "}
          {packId ? "A partial pack was saved from what was collected." : "The posts collected so far were saved; no pack could be built from them."}
        </p>)
    : finished ? <p>Finished: {run.status}{run.status === "partial" ? " (stopped early - the pack uses what was collected)" : ""}.</p>
    : <p>{live ? "Live" : "Reconnecting…"} · {run.mode === "standard" ? "Standard" : "Quick"} · started {new Date(run.created_at).toLocaleTimeString()}</p>;

  return (
    <TheatreLayout title={run.brief} status={status} summary={summary} collection={run.collection}>
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
      </div>
    </TheatreLayout>
  );
}

export function RunPage() {
  const { runId = "" } = useParams();
  const [params] = useSearchParams();
  return params.get("replay") === "1" ? <ReplayPage runId={runId} /> : <LiveRun runId={runId} />;
}
