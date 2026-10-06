// Replay a finished run from its pack's saved events (/runs/:id?replay=1 or /packs/:packId/replay).
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { FastForward, Pause, Play } from "lucide-react";
import { friendlyError, getPack, getRun, type ContextPack, type RunStatus } from "../lib/api";
import { summarize } from "../lib/runSummary";
import type { RunEvent } from "../lib/useRunEvents";
import { TheatreLayout } from "./RunPage";
import { ErrorNote } from "../components/ErrorNote";

const QUIET = new Set(["cost", "counters", "queue"]); // shown, but without a pause

export function ReplayPage({ runId, packId: packIdProp }: { runId?: string; packId?: string }) {
  const params = useParams();
  const packIdFromUrl = packIdProp ?? params.packId;
  const [pack, setPack] = useState<ContextPack | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);

  useEffect(() => {
    const load = async () => {
      let id = packIdFromUrl;
      if (!id && runId) {
        const run: RunStatus = await getRun(runId);
        if (!run.pack_id) throw new Error("This run has no pack yet - nothing to replay.");
        id = run.pack_id;
      }
      setPack(await getPack(id!));
    };
    load().catch((e) => setError(friendlyError(e)));
  }, [runId, packIdFromUrl]);

  const events: RunEvent[] = useMemo(
    () => (pack?.events ?? []).map((e) => ({ seq: e.seq, type: e.type as RunEvent["type"], payload: e.payload as Record<string, unknown> })),
    [pack]);

  useEffect(() => {
    if (!events.length) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) { setShown(events.length); return; }
    if (!playing || shown >= events.length) return;
    const next = events[shown];
    const delay = QUIET.has(next.type) ? 30 : next.type === "agent_call" ? 650 : 350;
    const t = setTimeout(() => setShown((n) => n + 1), delay / speed);
    return () => clearTimeout(t);
  }, [events, shown, playing, speed]);

  const finishedPlaying = shown >= events.length && events.length > 0;
  const summary = useMemo(() => {
    const sum = summarize(events.slice(0, shown));
    // A pack copies its events while it is built, before "pack ready" exists: the end of a replay is done.
    return finishedPlaying && pack ? { ...sum, packId: pack.pack_id, milestones: [...sum.milestones, "The pack is ready"] } : sum;
  }, [events, shown, finishedPlaying, pack]);
  if (error) return <ErrorNote message={error} />;
  if (!pack) return <p className="text-ink-3">Loading the replay…</p>;
  const finished = shown >= events.length;
  const c = pack.coverage;
  const collection = finished ? {
    sources_used: c.sources_used, sources_dropped: c.sources_dropped, gaps: [],
    finish_reason: c.loop.finish_reason, fallback_used: c.loop.fallback_used, top_up_used: c.loop.top_up_used,
  } as RunStatus["collection"] : null;

  return (
    <TheatreLayout title={pack.brief.text}
                   status={<p>Replay of a finished run · {shown} of {events.length} events{finished ? " · done" : ""}</p>}
                   summary={summary} collection={collection}>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Replay controls">
        <button type="button" onClick={() => (finished ? setShown(0) : setPlaying(!playing))}
                className="inline-flex items-center gap-1.5 rounded-lg border border-ink px-3 py-1.5 text-sm text-ink">
          {playing && !finished ? <Pause aria-hidden="true" size={14} /> : <Play aria-hidden="true" size={14} />}
          {finished ? "Play again" : playing ? "Pause" : "Play"}
        </button>
        {[1, 3].map((x) => (
          <button key={x} type="button" onClick={() => setSpeed(x)} aria-pressed={speed === x}
                  className={`rounded-lg border px-2.5 py-1.5 text-sm ${speed === x ? "border-ink bg-ink text-paper" : "border-line text-ink-2"}`}>
            {x}×
          </button>
        ))}
        <button type="button" onClick={() => setShown(events.length)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-ink-2">
          <FastForward aria-hidden="true" size={14} /> Skip to the end
        </button>
        <Link to={`/packs/${pack.pack_id}`} className="ml-auto text-sm text-ink underline-offset-2 hover:underline">Open the pack</Link>
      </div>
    </TheatreLayout>
  );
}
