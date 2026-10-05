// The run key lives only in this browser tab's session storage (gone when the tab closes).
// It is never rendered: the input is uncontrolled, so the key never becomes a DOM attribute.
const STORE = "signal.runKey";

export function readRunKey(): string {
  try {
    return sessionStorage.getItem(STORE) ?? "";
  } catch {
    return "";
  }
}

export function saveRunKey(key: string): void {
  try {
    if (key) sessionStorage.setItem(STORE, key);
    else sessionStorage.removeItem(STORE);
  } catch {
    /* storage blocked: the key is used for this request only */
  }
}

/** A refusal in plain words (never the key itself). */
export function explain(status: number, message: string): string {
  if (status === 401) return "That run key was not accepted. Please check it and try again.";
  if (status === 503) return "Starting new research is switched off on this server right now. The sample packs still work.";
  if (status === 429) return message; // queue full / daily cap: the server's own polite words
  if (status === 422) return "Please check the brief: it needs at least a few words.";
  return message || "Something went wrong. Please try again in a moment.";
}
