// "Check with legal first" on every item the compliance check flagged (exports audit 2026-10-10). Never
// colour-only: an icon and the words. Folded on the first screen (it must fit one laptop screen, PRD 6.1f).
import { AlertTriangle } from "lucide-react";
import type { FlagLike } from "../lib/legal";

export function LegalNote({ flags = [], words = [], folded = false }: { flags?: FlagLike[]; words?: string[]; folded?: boolean }) {
  if (!flags.length && !words.length) return null;
  const body = flags.length
    ? flags.map((f) => (
        <span key={f.id} className="block">{f.why} <span className="text-ink">Safer: {f.safer_wording}</span></span>
      ))
    : <span>Uses wording the legal check flagged ({words.slice(0, 3).join(", ")}). Get sign-off before using it publicly.</span>;
  const title = <span className="font-medium text-ink">Check with legal first</span>;
  if (folded) {
    return (
      <details className="mt-1 text-xs text-ink-2">
        <summary className="inline-flex cursor-pointer items-center gap-1"><AlertTriangle aria-hidden="true" size={12} className="text-ink" />{title}</summary>
        <p className="mt-1 pl-4">{body} <span className="text-ink-3">Not legal advice.</span></p>
      </details>
    );
  }
  return (
    <div className="mt-2 flex gap-2 rounded-md border border-line-strong bg-paper p-2 text-xs text-ink-2">
      <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-ink" />
      <div>{title}{flags[0] && <> ({flags[0].category.replace(/_/g, " ")})</>}: {body} <span className="text-ink-3">Not legal advice.</span></div>
    </div>
  );
}
