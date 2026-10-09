// V9 SUMMARY (first screen, readable in under a minute): who this represents, what we heard most clearly,
// the recommended position and the plan's first moves. Their words in serif, our work in sans.
import { CircleHelp } from "lucide-react";
import type { ContextPack, Label } from "../lib/api";
import { useGuide } from "../lib/readingGuide";
import { safeUrl } from "../lib/safe";
import { ConfidenceBadge } from "./badges";
import { IdLink, usePack } from "./cards";
import { CopyButton } from "./CopyButton";

const ORDER: Label[] = ["strong", "moderate", "emerging", "speculative"];

/** "How to read this": every strength label and claim type in plain words (scoring.yaml). */
export function HowToRead() {
  const guide = useGuide();
  return (
    <details className="group inline-block text-sm print:hidden">
      <summary className="inline-flex cursor-pointer items-center gap-1 text-ink-2 underline-offset-2 hover:text-ink hover:underline">
        <CircleHelp aria-hidden="true" size={14} /> How to read this
      </summary>
      <div className="mt-2 max-w-xl space-y-2 rounded-lg border border-line bg-paper p-3 text-ink-2">
        {guide ? (
          <>
            <ul className="space-y-1.5">
              {ORDER.map((l) => (
                <li key={l} className="flex flex-wrap items-center gap-2">
                  <ConfidenceBadge label={l} /><span>{guide.labels[l].words}.</span>
                  <span className="text-ink-3">Good enough to: {guide.labels[l].good_enough_to}.</span>
                </li>
              ))}
            </ul>
            <p>Every finding also says where it comes from: {Object.values(guide.claim_types).join(", ")}.</p>
          </>
        ) : <p>Strength labels go from strong (many people in several communities) to early signal (one or two people).</p>}
        <p className="text-ink-3">Counts, strength and quotes are computed from real posts; nothing is made up by the AI.</p>
      </div>
    </details>
  );
}

function Clamp({ text, lines = 2, className = "" }: { text: string; lines?: 1 | 2; className?: string }) {
  return (
    <details className={`group ${className}`}>
      <summary className={`cursor-pointer list-none ${lines === 1 ? "line-clamp-1" : "line-clamp-2"} group-open:line-clamp-none`}>{text}</summary>
    </details>
  );
}

export function SummaryPart({ pack }: { pack: ContextPack }) {
  const s = pack.snapshot;
  const { onOpen } = usePack();
  const i = pack.brief.interpreted;
  const goal = i.intent;  // V11: the confirmed goals in plain words (filled in code, never guessed)
  const findings = s.findings ?? [];
  const head = "mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3";
  return (
    <div className="space-y-4">
      <div className="space-y-0.5 text-sm">
        <p className="line-clamp-1 text-ink" title={i.audience}><span className="text-ink-3">For </span>{i.audience}
          {goal && <><span className="text-ink-3"> · goals: </span>{goal}</>}<span className="text-ink-3"> · {i.market}</span></p>
        {s.represents && <p className="text-ink-2">{s.represents}</p>}
        <HowToRead />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <h3 className={head}>What we heard most clearly</h3>
          <ol className="space-y-2">
            {findings.map((f, n) => (
              <li key={f.text} className="rounded-lg border border-line p-3">
                <p className="flex gap-2 text-[0.95rem] font-medium leading-snug text-ink"><span className="shrink-0 font-mono text-sm text-ink-3">{n + 1}.</span>{f.text}</p>
                {f.quote && (
                  <blockquote className="mt-1.5 border-l-2 border-line-strong pl-2.5">
                    <p className="line-clamp-1 font-serif text-sm text-ink" title={f.quote.text}>“{f.quote.text}”</p>
                    {f.quote_en && <p className="line-clamp-1 text-xs text-ink-3" title={f.quote_en}>In English (the post): {f.quote_en}</p>}
                  </blockquote>
                )}
                <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-ink-2">
                  <ConfidenceBadge label={f.label} />
                  <span>{f.people} {f.people === 1 ? "person" : "people"}, {f.communities} {f.communities === 1 ? "community" : "communities"} · good enough to: <span className="font-medium text-ink">{f.good_enough_to}</span></span>
                  <button type="button" onClick={() => onOpen?.(f.item_ids[0])} className="underline underline-offset-2 hover:text-ink">posts</button>
                </p>
              </li>
            ))}
            {!findings.length && s.five_truths.slice(0, 3).map((t) => (
              <li key={t.text} className="rounded-lg border border-line p-3 text-ink">{t.text} <IdLink id={t.item_ids[0]} /></li>
            ))}
          </ol>
        </div>

        <div className="space-y-4">
          {s.position && (
            <div className="rounded-lg border border-ink p-3">
              <h3 className={head}>Recommended position</h3>
              <p className="font-semibold leading-snug text-ink">{s.position.statement}</p>
              <p className="mt-1 text-sm text-ink-2">For {s.position.for_whom} - answering: {s.position.against_doubt}</p>
            </div>
          )}
          <div>
            <h3 className={head}>Your plan: do this first</h3>
            <ol className="space-y-1.5">
              {pack.do_first.map((d, n) => (
                <li key={d.id} className="flex items-start gap-2 rounded-lg border border-line p-2.5 text-sm">
                  <span className="shrink-0 font-mono text-ink-3">{n + 1}.</span>
                  <div className="min-w-0 flex-1">
                    <Clamp text={d.action} className="text-ink" />
                    {d.success_measure && <p className="mt-0.5 line-clamp-1 text-xs text-ink-2" title={d.success_measure}>
                      <span className="font-medium text-ink">How you'll know:</span> {d.success_measure}</p>}
                  </div>
                  <CopyButton text={d.action} />
                </li>
              ))}
            </ol>
            {(pack.post_briefs ?? []).length > 0 && <a href="#plan" className="mt-1.5 inline-block text-sm text-ink-2 underline">The full 4-week plan</a>}
          </div>
          {(pack.news_hooks ?? []).length > 0 && (
            <div>
              <h3 className={head}>Ride this now</h3>
              <ul className="space-y-1.5">
                {pack.news_hooks.slice(0, 2).map((h) => {
                  const url = safeUrl(h.source_url);
                  return (
                    <li key={h.id} className="rounded-lg border border-dashed border-ink-3 p-2.5 text-sm">
                      <p className="line-clamp-1 font-medium text-ink" title={h.headline}>{h.headline}</p>
                      <p className="text-xs text-ink-3">{h.date} · outside source: {url
                        ? <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="underline">{new URL(url).hostname}</a>
                        : "source"}</p>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
