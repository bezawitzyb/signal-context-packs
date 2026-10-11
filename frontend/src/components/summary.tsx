// V9 SUMMARY (first screen, readable in under a minute): who this represents, what we heard most clearly,
// the recommended position and the plan's first moves. Their words in serif, our work in sans.
import { CircleHelp } from "lucide-react";
import { useState } from "react";
import type { ContextPack, Label } from "../lib/api";
import { useGuide } from "../lib/readingGuide";
import { safeUrl } from "../lib/safe";
import { ConfidenceBadge } from "./badges";
import { Clamp } from "./Clamp";
import { LegalNote } from "./legal";
import { flaggedWords, flagsFor } from "../lib/legal";
import { IdLink, usePack } from "./cards";
import { CopyButton } from "./CopyButton";
import { Quote } from "./Quote";

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

/** "brand_perception" -> "Brand perception" (the mirror has no API, so no config lookup here). */
const goalWords = (g: string) => (g.charAt(0).toUpperCase() + g.slice(1)).replace(/_/g, " ");

export function SummaryPart({ pack }: { pack: ContextPack }) {
  const s = pack.snapshot;
  const { onOpen, evidence } = usePack();
  const i = pack.brief.interpreted;
  const goal = i.intent;  // V11: the confirmed goals in plain words (filled in code, never guessed)
  const findings = s.findings ?? [];
  const head = "t-label mb-3 text-xs font-semibold uppercase tracking-wide text-ink-3";
  const block = "mt-5 border-t border-line pt-4";   // the blocks of the Summary card: a thin rule, a little room (owner: tighter)
  const [allMoves, setAllMoves] = useState(false);
  return (
    // owner 2026-10-11: the whole Summary is one white card, like every section below it; its blocks are split by
    // the same thin rule and label style the sections use
    <div className="panel p-5 text-sm sm:p-8">
      <div className="space-y-1">
        <p className="t-body text-ink"><span className="t-lead">For: </span>{i.audience}<span className="text-ink-3"> · {i.market}</span></p>
        {goal && <p className="t-body text-ink"><span className="t-lead">Goals: </span>{goal}</p>}
        <div className="flex flex-wrap items-baseline gap-x-3">
          {s.represents && <p className="t-explain text-ink-2">{s.represents}</p>}
          <HowToRead />
        </div>
      </div>
      {(s.for_goals ?? []).length > 0 && (
        <ul className="mt-4 space-y-2 border-l-2 border-ink pl-3" aria-label="For your goals">
          {s.for_goals.map((g, n) => (
            <li key={g.goal} className="t-body text-ink">
              <span className="t-lead font-semibold">For your {n === 0 ? "main " : ""}goal - {goalWords(g.goal)}:</span> {g.headline}
              {g.first_moves.length > 0 && <span className="text-ink-3"> · first moves {g.first_moves.map((m) => Number(m.slice(3))).join(", ")}</span>}
            </li>
          ))}
        </ul>
      )}

      {/* owner 2026-10-11: the recommended position across the card, then what we heard and the plan side by side */}
      {s.position && (
        <div className={block}>
          <h3 className={head}>Recommended position</h3>
          <div className="featured p-4">
            <p className="t-finding text-base font-semibold leading-snug text-ink">{s.position.statement}</p>
            <div className="mt-2"><Clamp className="t-explain text-sm text-ink-2">
              For {s.position.for_whom} - answering: {s.position.against_doubt}</Clamp></div>
            <LegalNote folded words={flaggedWords(s.position.statement, pack.guardrails.never_claim, pack.compliance_flags)} />
          </div>
        </div>
      )}

      <div className={`${block} grid gap-8 lg:grid-cols-2`}>
        <div>
          <h3 className={head}>What we heard most clearly</h3>
          <ol className="space-y-3">
            {findings.map((f, n) => (
              <li key={f.text} className="border border-line p-4">
                <div className="flex items-start gap-2">
                  <p className="t-finding flex min-w-0 flex-1 gap-2 text-[0.95rem] font-medium leading-snug text-ink"><span className="shrink-0 font-mono text-sm text-ink-3">{n + 1}.</span>{f.text}</p>
                  <button type="button" onClick={() => onOpen?.(f.item_ids[0])} aria-label={`See the posts behind ${f.item_ids[0]}`}
                          className="mt-0.5 shrink-0 whitespace-nowrap text-[0.8125rem] text-ink-2 underline underline-offset-2 hover:text-ink">See the posts</button>
                </div>
                {f.quote && (
                  <div className="mt-2">
                    <Quote text={f.quote.text} evidence={evidence[f.quote.evidence_id]} translation={f.quote_en} size="sm" details={false} />
                  </div>
                )}
                <p className="t-meta mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-ink-2">
                  <ConfidenceBadge label={f.label} />
                  <span>{f.people} {f.people === 1 ? "person" : "people"}, {f.communities} {f.communities === 1 ? "community" : "communities"}</span>
                  {/* UX audit: each piece wraps as a whole, never leaving one word alone on a line */}
                  <span className="whitespace-nowrap">Good enough to: <span className="font-medium text-ink">{f.good_enough_to}</span></span>
                </p>
              </li>
            ))}
            {!findings.length && s.five_truths.slice(0, 3).map((t) => (
              <li key={t.text} className="border border-line p-4 text-ink">{t.text} <IdLink id={t.item_ids[0]} /></li>
            ))}
          </ol>
        </div>
        <div className="space-y-6">
          <div>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <h3 className={head}>Your plan: do this first</h3>
              <p className="t-meta mb-2 flex gap-3 text-xs text-ink-2">
                <button type="button" onClick={() => setAllMoves(!allMoves)} aria-expanded={allMoves} aria-controls="first-moves"
                        className="underline underline-offset-2 hover:text-ink">{allMoves ? "Show shorter" : "Show the full moves"}</button>
                {(pack.post_briefs ?? []).length > 0 && <a href="#plan" className="underline underline-offset-2 hover:text-ink">The full 4-week plan</a>}
              </p>
            </div>
            <ol className="space-y-2" id="first-moves">
              {pack.do_first.map((d, n) => (
                <li key={d.id} className="flex items-start gap-2 border border-line p-3 text-sm">
                  <span className="shrink-0 font-mono text-ink-3">{n + 1}.</span>
                  <div className="min-w-0 flex-1">
                    {/* two lines per move; the whole move is one click away, never lost */}
                    <Clamp clamp="line-clamp-2" open={allMoves} className="t-body text-ink" subClassName="t-meta mt-0.5 text-xs text-ink-2"
                           sub={(d.goal || d.success_measure) && <>
                             {d.goal && <span className="text-ink-3">for: {goalWords(d.goal)}{d.success_measure ? " · " : ""}</span>}
                             {d.success_measure && <><span className="t-lead font-medium text-ink">How you'll know:</span> {d.success_measure}</>}</>}>
                      {d.action}</Clamp>
                    <LegalNote folded flags={flagsFor(pack, d.id)} />
                  </div>
                  <CopyButton text={d.action} />
                </li>
              ))}
            </ol>
          </div>
          {(pack.news_hooks ?? []).length > 0 && (
            <div>
              <h3 className={head}>Ride this now</h3>
              <ul className="space-y-2">
                {pack.news_hooks.slice(0, 1).map((h) => {
                  const url = safeUrl(h.source_url);
                  return (
                    <li key={h.id} className="border border-dashed border-ink-3 p-3 text-sm">
                      <Clamp className="t-body font-medium text-ink" subClassName="t-meta text-xs text-ink-3"
                             sub={<>{h.date} · outside source: {url
                               ? <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="underline">{new URL(url).hostname}</a>
                               : "source"}</>}>{h.headline}</Clamp>
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
