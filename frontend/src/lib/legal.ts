// Exports audit (2026-10-10): the compliance check's flags shown on every flagged item, and "Say this" never
// using flagged wording. Same rule as backend/ctxpack/synthesis/guardrail_check.py (keep the two in step).
import type { ContextPack } from "./api";

export type Flag = ContextPack["compliance_flags"][number];
/** What a "Check with legal first" note needs to show. */
export type FlagLike = Pick<Flag, "id" | "category" | "why" | "safer_wording">;

const QUOTED = /['‘"“]([^'’"”]{3,40})['’"”]/g;
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** `small` appears in `big` as whole words ("lekker" is not inside "lekkere"). */
const inside = (small: string, big: string) => new RegExp(`(?<![\\p{L}\\p{N}_])${esc(small)}(?![\\p{L}\\p{N}_])`, "u").test(big);

function unique(items: string[]): string[] {
  const seen = new Map<string, string>();
  for (const x of items) if (!seen.has(x.toLowerCase())) seen.set(x.toLowerCase(), x);
  return [...seen.values()];
}

/** Short terms the compliance reasons put in quote marks ("'Slimmer' is a vague health claim"). */
export function namedTerms(flags: Flag[]): string[] {
  const safer = flags.map((f) => f.safer_wording.toLowerCase()).join(" ");
  const terms = flags.flatMap((f) => [...f.why.matchAll(QUOTED)].map((m) => m[1].trim()));
  return unique(terms.filter((t) => t.split(/\s+/).length <= 3 && !inside(t.toLowerCase(), safer)));
}

/** The flagged wording `phrase` uses (empty = none). */
export function flaggedWords(phrase: string, neverClaim: string[], flags: Flag[]): string[] {
  const p = phrase.toLowerCase().trim();
  if (!p) return [];
  const out = neverClaim.filter((r) => {
    const rc = r.toLowerCase().trim();
    return rc && (inside(rc, p) || (p.split(/\s+/).length >= 2 && inside(p, rc)));
  });
  return unique([...out, ...namedTerms(flags).filter((t) => inside(t.toLowerCase(), p))]);
}

export function cleanSayThis(pack: ContextPack): string[] {
  const g = pack.guardrails;
  return g.say_this.filter((s) => !flaggedWords(s, g.never_claim, pack.compliance_flags).length);
}

export const flagsFor = (pack: ContextPack, ...ids: (string | undefined)[]) =>
  pack.compliance_flags.filter((f) => ids.includes(f.item_id));
