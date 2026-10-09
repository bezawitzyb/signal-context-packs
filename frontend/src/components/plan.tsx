// V9 "Your plan" (V8 data): a 4-week calendar grid and post brief cards with expandable drafts and copy buttons.
// Packs made before V8 show this week's plan instead.
import { ChevronDown } from "lucide-react";
import type { ContextPack } from "../lib/api";
import { ConfidenceBadge } from "./badges";
import { IdLink } from "./cards";
import { CopyButton } from "./CopyButton";
import { ShowMore } from "./blocks";

type Brief = ContextPack["post_briefs"][number];
type Draft = ContextPack["drafts"][number];

export const CHANNEL: Record<string, string> = {
  reddit: "Reddit", tiktok: "TikTok", youtube: "YouTube", instagram: "Instagram", linkedin: "LinkedIn", x: "X", facebook: "Facebook",
  web_forum: "Forums", blog: "Blog", newsletter: "Newsletter", web_review: "Review sites", web_editorial: "Articles",
};
const FORMAT: Record<string, string> = { text_post: "text post", carousel: "carousel", short_video: "short video",
  blog_article: "blog article", newsletter: "newsletter" };
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function CalendarGrid({ pack }: { pack: ContextPack }) {
  const briefs = Object.fromEntries(pack.post_briefs.map((b) => [b.id, b]));
  const weeks = Math.max(...pack.content_calendar.map((e) => e.week), 1);
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" aria-label="Content calendar">
      {Array.from({ length: weeks }, (_, w) => w + 1).map((week) => (
        <section key={week} aria-label={`Week ${week}`} className="rounded-lg border border-line">
          <h4 className="border-b border-line bg-wash px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">
            {week === 1 ? "Week 1 (this week)" : `Week ${week}`}
          </h4>
          <ul className="divide-y divide-line">
            {pack.content_calendar.filter((e) => e.week === week).map((e) => (
              <li key={e.id} className="px-3 py-2 text-sm">
                <p className="font-mono text-xs text-ink-3">{cap(e.suggested_day)} · {CHANNEL[e.channel] ?? e.channel}</p>
                <a href={`#${e.post_brief_id}`} className="text-ink underline-offset-2 hover:underline">
                  {briefs[e.post_brief_id]?.angle || briefs[e.post_brief_id]?.hook}
                </a>
                <p className="text-xs text-ink-3">{e.timing_reason}</p>
              </li>
            ))}
            {!pack.content_calendar.some((e) => e.week === week) && <li className="px-3 py-2 text-xs text-ink-3">Nothing planned</li>}
          </ul>
        </section>
      ))}
    </div>
  );
}

function BriefCard({ b, draft, words }: { b: Brief; draft?: Draft; words: Record<string, string> }) {
  const text = [`${CHANNEL[b.channel] ?? b.channel} ${FORMAT[b.format] ?? b.format} for ${b.role}`, `Goal: ${b.goal}`,
    `Hook: ${b.hook}`, `Angle: ${b.angle}`, `Structure: ${b.structure}`, ...b.key_points.map((k) => `- ${k.text}`),
    `Call to action: ${b.cta}`, ...(b.avoid.length ? [`Avoid: ${b.avoid.join("; ")}`] : [])].join("\n");
  return (
    <article id={b.id} className="scroll-mt-24 rounded-lg border border-line p-4">
      <header className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
        <span className="rounded border border-line px-1.5 py-0.5 font-medium text-ink">{CHANNEL[b.channel] ?? b.channel}</span>
        <span>{FORMAT[b.format] ?? b.format}</span><span>· for {b.role}</span>
        <ConfidenceBadge label={b.confidence} />
        <span className="ml-auto"><CopyButton text={text} label="Copy brief" /></span>
      </header>
      <p className="mt-2 font-medium text-ink">{b.hook}</p>
      <p className="mt-1 text-sm text-ink-2">{b.angle} <span className="text-ink-3">({b.structure})</span></p>
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-ink">
        {b.key_points.map((k) => <li key={k.text}>{k.text} <span className="text-xs text-ink-3"><IdLink id={k.item_ids[0]} /></span></li>)}
      </ul>
      <p className="mt-2 text-sm text-ink-2"><span className="text-ink-3">Call to action:</span> {b.cta}</p>
      {b.their_words_to_use.length > 0 && (
        <p className="mt-1 text-sm text-ink-2"><span className="text-ink-3">Their words:</span>{" "}
          <span className="font-serif text-ink">{b.their_words_to_use.map((w) => words[w] ?? w).join(", ")}</span></p>
      )}
      {b.avoid.length > 0 && <p className="mt-1 text-sm text-ink-2"><span className="text-ink-3">Avoid:</span> {b.avoid.join("; ")}</p>}
      {b.success_measure && <p className="mt-1 text-sm text-ink-2"><span className="text-ink-3">How you'll know it worked:</span> {b.success_measure}</p>}
      {draft && (
        <details className="group mt-3 rounded-lg border border-line bg-wash">
          <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm font-medium text-ink">
            <ChevronDown aria-hidden="true" size={14} className="transition group-open:rotate-180" />
            {draft.label}
            <span className="font-normal text-xs text-ink-3">({draft.voice === "brand" ? "your brand voice" : "neutral voice"}
              {draft.removed_sentences ? `; ${draft.removed_sentences} unsupported sentence${draft.removed_sentences === 1 ? "" : "s"} removed` : ""})</span>
          </summary>
          <div className="border-t border-line px-3 py-3">
            <div className="mb-2 flex justify-end"><CopyButton text={[draft.title, draft.body].filter(Boolean).join("\n\n")} label="Copy draft" /></div>
            {draft.title && <p className="mb-2 font-semibold text-ink">{draft.title}</p>}
            <p className="whitespace-pre-wrap text-sm text-ink">{draft.body}</p>
          </div>
        </details>
      )}
    </article>
  );
}

export function PlanPart({ pack, fallback }: { pack: ContextPack; fallback: React.ReactNode }) {
  const briefs = pack.post_briefs ?? [];
  if (!briefs.length) return <>{fallback}</>;
  const drafts = Object.fromEntries((pack.drafts ?? []).map((d) => [d.post_brief_id, d]));
  const words = Object.fromEntries(pack.voice.lexicon.map((x) => [x.id, x.term]));
  return (
    <div className="space-y-6">
      <p className="text-sm text-ink-3">Drafts are written by AI from the research. Review before posting; nothing is scheduled for you.</p>
      {pack.content_calendar.length > 0 && <CalendarGrid pack={pack} />}
      <ShowMore items={briefs} limit={3} render={(part) => (
        <div className="space-y-3">{part.map((b) => <BriefCard key={b.id} b={b} draft={drafts[b.id]} words={words} />)}</div>
      )} />
    </div>
  );
}
