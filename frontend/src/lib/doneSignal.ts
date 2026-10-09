// UX audit: a run takes minutes and people switch tabs. The tab title shows progress and "Pack ready", and a
// short soft chime plays once when it finishes (Web Audio - no files, no permission prompt; silent if blocked).
import { useEffect, useRef } from "react";

function chime() {
  try {
    const ctx = new AudioContext();
    [660, 880].forEach((freq, n) => {
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      const t = ctx.currentTime + n * 0.18;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.08, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t); osc.stop(t + 0.4);
    });
    setTimeout(() => ctx.close().catch(() => {}), 1000);
  } catch { /* no audio: the title still changes */ }
}

export function useDoneSignal(state: { brief: string; finished: boolean; ok: boolean } | null) {
  const wasRunning = useRef(false);
  const short = state ? (state.brief.length > 40 ? state.brief.slice(0, 40) + "…" : state.brief) : "";
  useEffect(() => {
    if (!state) return;
    const before = document.title;
    if (!state.finished) {
      wasRunning.current = true;
      document.title = `Researching… – ${short}`;
    } else {
      document.title = `${state.ok ? "✓ Pack ready" : "Finished"} – ${short}`;
      if (wasRunning.current) { wasRunning.current = false; chime(); }   // only when watched live, never on reload
    }
    return () => { document.title = before; };
  }, [state?.finished, state?.ok, short]);   // eslint-disable-line react-hooks/exhaustive-deps
}
