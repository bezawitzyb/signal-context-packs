// Confidence, claim type and "safe to state" (PRD 10.3). Confidence is never colour-only:
// a shape (● ◐ ○ ◌), a word and the counts, readable in greyscale.
import { ShieldCheck } from "lucide-react";
import type { Label } from "../lib/api";
import { useGuide } from "../lib/readingGuide";

const LEVEL: Record<Label, { glyph: string; word: string; tone: string }> = {
  strong: { glyph: "●", word: "Strong", tone: "bg-ink text-paper border-ink" },
  moderate: { glyph: "◐", word: "Moderate", tone: "bg-wash text-ink border-line-strong" },
  emerging: { glyph: "○", word: "Emerging", tone: "bg-paper text-ink border-line-strong" },
  speculative: { glyph: "◌", word: "Speculative", tone: "bg-paper text-ink-2 border-dashed border-ink-3" },
};

export function ConfidenceBadge({ label, matching, ofTotal, score }: {
  label: Label; matching?: number; ofTotal?: number; score?: number;
}) {
  const l = LEVEL[label];
  const guide = useGuide();
  const counts = matching !== undefined && ofTotal !== undefined ? `${matching} of ${ofTotal} posts` : null;
  const plain = guide?.labels[label];
  // V9: every badge explains itself in plain words (scoring.yaml), never colour-only
  const title = plain ? `${plain.words}. Good enough to: ${plain.good_enough_to}.${counts ? ` (${counts})` : ""}`
    : `${l.word}${counts ? ` - ${counts}` : ""}${score !== undefined ? ` (score ${score.toFixed(2)})` : ""}`;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs ${l.tone}`}
      title={title} data-badge="confidence"
    >
      <span aria-hidden="true" className="text-[1.05em] font-bold leading-none">{l.glyph}</span>
      <span className="font-medium">{l.word}</span>
      {counts && <span className="font-mono text-[0.85em] opacity-80">· {counts}</span>}
    </span>
  );
}

export function ClaimTypeTag({ type }: { type: "observed" | "inferred" | "external" }) {
  const guide = useGuide();
  const text = { observed: "Seen in posts", inferred: "Our interpretation", external: "Outside source" }[type];
  const hint = guide?.claim_types[type] ?? {
    observed: "People say this directly in the posts.",
    inferred: "Our reading of the posts, not said in so many words.",
    external: "From outside the posts.",
  }[type];
  return (
    <span title={hint} className="inline-flex items-center rounded border border-line px-1.5 py-0.5 text-xs text-ink-2">
      {text}
    </span>
  );
}

export function SafeTag() {
  return (
    <span
      title="Strong, observed and confirmed by the claim check: safe to state as fact."
      className="inline-flex items-center gap-1 rounded border border-ink px-1.5 py-0.5 text-xs font-medium text-ink"
    >
      <ShieldCheck aria-hidden="true" size={13} strokeWidth={2} />
      Safe to state
    </span>
  );
}

export function IdTag({ id }: { id: string }) {
  return <span className="font-mono text-xs text-ink-3">{id}</span>;
}

export function ModeBadge({ mode }: { mode: string }) {
  return (
    <span className="rounded border border-line px-1.5 py-0.5 font-mono text-xs uppercase tracking-wide text-ink-2">
      {mode}
    </span>
  );
}
