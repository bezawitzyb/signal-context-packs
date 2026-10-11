// S1 ASK + PLAN arrives in Step 4.2. For now: what this is, and the featured packs.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import { friendlyError, listPacks, LIVE_URL, MIRROR, type FeaturedPack } from "../lib/api";
import { ErrorNote } from "../components/ErrorNote";
import { myPacks } from "../lib/rerun";
import { packTitle } from "../lib/title";
import { AskFlow } from "./Ask";
import { Skeleton } from "../components/Skeleton";

/** "nl" -> "Dutch" (the browser knows every language name). */
const languageName = (code: string) => {
  try { return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code; } catch { return code; }
};

/** UX audit: a card says what the pack holds (posts, languages, findings), not its codes; caveats live inside. */
export function PackCards({ packs }: { packs: FeaturedPack[] }) {
  return (
    <ul className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {packs.map((p) => {
        const facts = [
          p.relevant_posts != null && `${p.relevant_posts} real posts`,
          p.languages?.length && p.languages.map(languageName).join(" & "),
          p.findings ? `${p.findings} findings${p.strong_findings ? ` (${p.strong_findings} strong)` : ""}` : null,
        ].filter(Boolean) as string[];
        return (
          <li key={p.pack_id} className="flex">
            <Link to={`/packs/${p.pack_id}`}
                  className="neo group flex w-full flex-col rounded-lg bg-paper p-4">
              <p className="font-medium text-ink">{packTitle(p.brief, p.topic)}</p>
              {p.top_finding
                ? <p className="mt-1 line-clamp-3 flex-1 text-sm text-ink-2"><span className="text-ink-3">Heard most: </span>{p.top_finding}</p>
                : <p className="mt-1 line-clamp-2 flex-1 text-sm text-ink-2">{p.audience}</p>}
              <p className="mt-3 text-xs text-ink-3">{facts.join(" · ")}</p>
              <span className="mt-2 inline-flex items-center gap-1 text-sm text-ink group-hover:underline">
                See the pack <ArrowRight aria-hidden="true" size={14} />
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function useFeatured() {
  const [packs, setPacks] = useState<FeaturedPack[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    listPacks().then(setPacks).catch((e) => setError(friendlyError(e)));
  }, []);
  return { packs, error };
}

const STEPS = ["Write a brief", "Answer quick questions", "Check the plan", "Start research", "Get your Context Pack"];

/** Owner 2026-10-11: how it works; once in view, one step at a time is highlighted, in a loop (always visible). */
function HowItWorks() {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    if (!("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.dataset.play = "done";
      return;
    }
    const seen = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { el.dataset.play = "on"; seen.disconnect(); }
    }, { rootMargin: "0px 0px -15% 0px" });
    seen.observe(el);
    return () => seen.disconnect();
  }, []);
  return (
    <div ref={box} className="how mb-6" style={{ "--n": STEPS.length + 1 } as React.CSSProperties}>
      <ol className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6" aria-label="How it works">
        {STEPS.map((s, n) => (
          <li key={s} className="how-step flex items-center gap-2 rounded-lg border border-line px-3 py-2.5 text-sm text-ink"
              style={{ "--i": n } as React.CSSProperties}>
            <span className="how-dot flex size-6 shrink-0 items-center justify-center rounded-full border border-ink font-mono text-xs">{n + 1}</span>
            {s}
          </li>
        ))}
        <li className="how-step flex items-center gap-2 rounded-lg border border-dashed border-line-strong px-3 py-2.5 text-sm text-ink-3"
            style={{ "--i": STEPS.length, "--how-fg": "var(--ink-3)" } as React.CSSProperties}>
          <span aria-hidden="true" className="how-dot flex size-6 shrink-0 items-center justify-center rounded-full border border-dashed border-line-strong font-mono text-xs">+</span>
          Optional: ask the pack/share
        </li>
      </ol>
      <p className="mt-2 text-xs text-ink-3">
        The pack also works with AI tools: Claude, ChatGPT and agents (MCP).</p>
    </div>
  );
}

export function Home() {
  const { packs, error } = useFeatured();
  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          What your audience actually says - in their words.
        </h1>
        <p className="mt-3 text-lg text-ink-2">
          Their frustrations, objections and the words they use - from real public posts in their own market and
          language, with a plan you can act on. Every finding links to the posts behind it.
        </p>
        <p className="mt-2 text-sm text-ink-2">You get a <span className="font-medium text-ink">Context Pack</span>: a
          report to read and share, plus a file your AI tools can use to write in your audience's words.</p>
        {!MIRROR && (
          <a href="#ask" onClick={() => window.setTimeout(() => document.getElementById("brief")?.focus({ preventScroll: true }), 0)}
             className="mt-5 inline-flex items-center gap-2 neo rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-ink hover:brightness-95">
            Start your research <ArrowRight aria-hidden="true" size={16} />
          </a>
        )}
      </section>
      {myPacks().length > 0 && (
        <section aria-labelledby="mine">
          <h2 id="mine" className="mb-3 text-lg font-semibold text-ink">My packs</h2>
          <ul className="grid gap-2 md:grid-cols-2">
            {myPacks().map((p) => (
              <li key={p.pack_id}>
                <Link to={`/packs/${p.pack_id}`} className="block rounded-lg border border-line p-3 hover:border-line-strong">
                  <span className="font-medium text-ink">{packTitle(p.brief)}</span>
                  <span className="block font-mono text-xs text-ink-3">{p.at.slice(0, 10)} · made in this browser</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-labelledby="featured">
        <h2 id="featured" className="mb-3 text-lg font-semibold text-ink">See an example pack</h2>
        {error && <ErrorNote message={error} />}
        {!packs && !error && <Skeleton lines={1} label="Loading the example packs" />}
        {packs && <PackCards packs={packs} />}
      </section>
      <section aria-labelledby="ask">
        <h2 id="ask" className="mb-1 scroll-mt-20 text-lg font-semibold text-ink">Research your own brief</h2>
        {!MIRROR && <p className="mb-4 text-sm text-ink-2">Running new research needs an access key. No access key yet?
          Explore the example packs above to see what's included in the Context Packs.</p>}
        {MIRROR
          ? <p className="text-ink-2">This is the read-only mirror of the featured packs. Research your own brief on
              the <a href={LIVE_URL} className="text-ink underline">live app</a>.</p>
          : <><HowItWorks /><AskFlow /></>}
      </section>
    </div>
  );
}

export function Packs() {
  const { packs, error } = useFeatured();
  return (
    <div>
      <h1 className="mb-4 text-2xl font-semibold tracking-tight text-ink">Featured packs</h1>
      {error && <ErrorNote message={error} />}
      {packs && <PackCards packs={packs} />}
    </div>
  );
}
