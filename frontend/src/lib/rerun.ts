// "Run again with these inputs" (V1) and what this browser remembers: the Ask form draft and "My packs".
// Browser storage can be missing or blocked (private windows): every read and write is wrapped.

import type { IntakeData } from "./api";

export interface RunInputs {
  brief: string; mode: string; time_window_days: number | null; brand_voice: string | null;
  intake: IntakeData | null;
}

/** The Ask page pre-filled with a run's inputs; `change` applies a one-click re-plan (thin screen). */
export function rerunUrl(i: RunInputs, change: { brief?: string; mode?: string; window?: number } = {}): string {
  const p = new URLSearchParams({ brief: change.brief ?? i.brief, mode: change.mode ?? i.mode });
  const window = change.window ?? i.time_window_days;
  if (window) p.set("window", String(window));
  if (i.brand_voice) p.set("voice", i.brand_voice);
  const answers = i.intake ? { ...i.intake, questions_asked: undefined } : null;
  if (answers && Object.values(answers).some((v) => (Array.isArray(v) ? v.length : v))) {
    p.set("intake", JSON.stringify(answers));  // your earlier answers: the new run is not asked again
  }
  return `/?${p.toString()}#ask`;
}

function read<T>(store: () => Storage, key: string, fallback: T): T {
  try {
    const raw = store().getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(store: () => Storage, key: string, value: unknown): void {
  try {
    store().setItem(key, JSON.stringify(value));
  } catch {
    /* storage blocked: nothing is remembered, everything still works */
  }
}

// --- the Ask form keeps its values after a failure or refresh (this tab only) -------------
export interface AskDraft { brief: string; mode: "quick" | "standard"; window: number | null; voice: string }
const DRAFT = "signal.askDraft";
export const loadDraft = (): AskDraft | null => read<AskDraft | null>(() => sessionStorage, DRAFT, null);
export const saveDraft = (d: AskDraft): void => write(() => sessionStorage, DRAFT, d);

/** The intake carried by a "Run again" link (?intake=...), or null. */
export function intakeFromParam(raw: string | null): IntakeData | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw);
    return v && typeof v === "object" ? (v as IntakeData) : null;
  } catch {
    return null;
  }
}

// --- "My packs": packs made in this browser -------------------------------------------------
export interface MyPack { pack_id: string; brief: string; at: string }
const MINE = "signal.myPacks";
export const myPacks = (): MyPack[] => read<MyPack[]>(() => localStorage, MINE, []);
export function addMyPack(p: MyPack): void {
  const rest = myPacks().filter((x) => x.pack_id !== p.pack_id);
  write(() => localStorage, MINE, [p, ...rest].slice(0, 30));
}
