// Live run events over SSE (guide B6). The browser's EventSource reconnects by itself and sends
// Last-Event-ID, so the server resumes after the last event seen. When the stream ends for a finished
// run, we check the run's status once and stop reconnecting.
import { useEffect, useRef, useState } from "react";
import { getRun, runEventsUrl } from "./api";

export const EVENT_TYPES = ["stage", "agent_call", "agent_result", "coverage", "fallback", "queue",
  "counters", "cost", "pack_ready", "error"] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export interface RunEvent { seq: number; type: EventType; payload: Record<string, unknown> }

const FINISHED = new Set(["complete", "partial", "failed", "stopped"]);

export function useRunEvents(runId: string | undefined) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [live, setLive] = useState(false);
  const [done, setDone] = useState(false);
  const seen = useRef(new Set<number>());

  useEffect(() => {
    if (!runId) return;
    seen.current = new Set();
    setEvents([]);
    setDone(false);
    const source = new EventSource(runEventsUrl(runId));
    const onEvent = (type: EventType) => (e: MessageEvent) => {
      // The event's own number is the SSE id (the browser resends it as Last-Event-ID on reconnect).
      // The data is the payload as written: its own "seq" (an agent call number) stays untouched.
      const seq = Number(e.lastEventId);
      if (!Number.isFinite(seq) || seen.current.has(seq)) return; // a reconnect never shows an event twice
      seen.current.add(seq);
      const payload = JSON.parse(e.data) as Record<string, unknown>;
      setEvents((prev) => [...prev, { seq, type, payload }]);
    };
    EVENT_TYPES.forEach((t) => source.addEventListener(t, onEvent(t) as EventListener));
    source.onopen = () => setLive(true);
    source.onerror = async () => {
      setLive(false);
      try {
        const run = await getRun(runId);
        if (FINISHED.has(run.status)) {
          source.close();
          setDone(true);
        }
      } catch {
        /* keep reconnecting: the browser retries by itself */
      }
    };
    return () => source.close();
  }, [runId]);

  return { events, live, done };
}
