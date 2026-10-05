// The run's live status. The full Research Theatre (stage stepper, agent log, counters) is Step 4.3.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { getRun, stopRun, type RunStatus } from "../lib/api";
import { readRunKey } from "../lib/runKey";
import { useRunEvents } from "../lib/useRunEvents";

export function RunPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<RunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { events } = useRunEvents(runId);
  const last = events[events.length - 1];

  useEffect(() => {
    getRun(runId).then(setRun).catch((e: Error) => setError(e.message));
  }, [runId, last?.seq]); // refresh the status whenever a new event arrives

  if (error) return <p className="text-ink-2">{error}</p>;
  if (!run) return <p className="text-ink-3">Loading…</p>;
  const finished = ["complete", "partial", "failed", "stopped"].includes(run.status);
  return (
    <div className="max-w-3xl space-y-4">
      <p className="font-mono text-xs text-ink-3">{run.run_id}</p>
      <h1 className="text-2xl font-semibold tracking-tight text-ink">{run.brief}</h1>
      <p className="text-ink">
        {run.status === "queued" && run.queue_position
          ? `Waiting in line: position ${run.queue_position}. It starts by itself.`
          : finished ? `Finished: ${run.status}.` : `Working: ${run.stage ?? run.status}.`}
      </p>
      {run.pack_id && <Link to={`/packs/${run.pack_id}`} className="inline-block rounded-lg bg-ink px-4 py-2 text-sm text-paper">Open the pack</Link>}
      {!finished && (
        <button type="button" onClick={() => stopRun(readRunKey(), runId).then(setRun).catch((e: Error) => setError(e.message))}
                className="rounded-lg border border-line-strong px-3 py-1.5 text-sm text-ink">
          Stop and build the pack now
        </button>
      )}
      <ol className="space-y-1 font-mono text-xs text-ink-2">
        {events.slice(-30).map((e) => <li key={e.seq}>{e.seq} · {e.type} · {JSON.stringify(e.payload).slice(0, 140)}</li>)}
      </ol>
      <p className="text-sm text-ink-3">The full Research Theatre comes in Step 4.3.</p>
    </div>
  );
}
