// "Run again with these inputs" (V1) and what this browser remembers: the Ask form draft and "My packs".
// Browser storage can be missing or blocked (private windows): every read and write is wrapped.

export interface RunInputs {
  brief: string; mode: string; time_window_days: number | null; brand_voice: string | null;
  clarification: { question: string; answer: string } | null;
}

/** The Ask page pre-filled with a run's inputs; `change` applies a one-click re-plan (thin screen). */
export function rerunUrl(i: RunInputs, change: { brief?: string; mode?: string; window?: number } = {}): string {
  const p = new URLSearchParams({ brief: change.brief ?? i.brief, mode: change.mode ?? i.mode });
  const window = change.window ?? i.time_window_days;
  if (window) p.set("window", String(window));
  if (i.brand_voice) p.set("voice", i.brand_voice);
  if (i.clarification?.answer) p.set("answer", i.clarification.answer);
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

const ANSWER = "signal.rememberedAnswer";
export const rememberAnswer = (a: string): void => write(() => sessionStorage, ANSWER, a);
export const rememberedAnswer = (): string => read<string>(() => sessionStorage, ANSWER, "");

// --- "My packs": packs made in this browser -------------------------------------------------
export interface MyPack { pack_id: string; brief: string; at: string }
const MINE = "signal.myPacks";
export const myPacks = (): MyPack[] => read<MyPack[]>(() => localStorage, MINE, []);
export function addMyPack(p: MyPack): void {
  const rest = myPacks().filter((x) => x.pack_id !== p.pack_id);
  write(() => localStorage, MINE, [p, ...rest].slice(0, 30));
}
