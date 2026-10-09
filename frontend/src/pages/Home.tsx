// S1 ASK + PLAN arrives in Step 4.2. For now: what this is, and the featured packs.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import { friendlyError, listPacks, LIVE_URL, MIRROR, type FeaturedPack } from "../lib/api";
import { ErrorNote } from "../components/ErrorNote";
import { myPacks } from "../lib/rerun";
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
          p.strong_findings ? `${p.strong_findings} strong findings` : p.findings ? `${p.findings} findings` : null,
        ].filter(Boolean) as string[];
        return (
          <li key={p.pack_id} className="flex">
            <Link to={`/packs/${p.pack_id}`}
                  className="group flex w-full flex-col rounded-lg border border-line p-4 hover:border-line-strong">
              <p className="font-medium text-ink">{p.brief}</p>
              <p className="mt-1 line-clamp-2 flex-1 text-sm text-ink-2">{p.audience}</p>
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

export function Home() {
  const { packs, error } = useFeatured();
  return (
    <div className="space-y-10">
      <section className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          What your audience actually says - in their words.
        </h1>
        <p className="mt-3 text-lg text-ink-2">
          Find out what your audience really says - their words, frustrations and objections - from real public posts in
          their own market and language, with a plan you can act on. Every finding links to the posts behind it.
        </p>
        {!MIRROR && (
          <a href="#ask" className="mt-5 inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-ink hover:brightness-95">
            Start your research <ArrowRight aria-hidden="true" size={16} />
          </a>
        )}
        <ol className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-sm text-ink-2" aria-label="How it works">
          {["Write a brief", "Answer 2 quick questions", "Check the plan", "Get your pack in about 7 minutes"].map((s, n) => (
            <li key={s} className="flex items-center gap-2">
              <span className="flex size-6 items-center justify-center rounded-full border border-line-strong font-mono text-xs text-ink">{n + 1}</span>
              {s}
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-ink-3">The pack also works with AI tools: Claude, ChatGPT and agents (MCP).</p>
      </section>
      {myPacks().length > 0 && (
        <section aria-labelledby="mine">
          <h2 id="mine" className="mb-3 text-lg font-semibold text-ink">My packs</h2>
          <ul className="grid gap-2 md:grid-cols-2">
            {myPacks().map((p) => (
              <li key={p.pack_id}>
                <Link to={`/packs/${p.pack_id}`} className="block rounded-lg border border-line p-3 hover:border-line-strong">
                  <span className="font-medium text-ink">{p.brief}</span>
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
        {!MIRROR && <p className="mb-4 text-sm text-ink-2">Running new research needs an access key. No key? The example
          packs above are open to everyone - every finding and every post behind it.</p>}
        {MIRROR
          ? <p className="text-ink-2">This is the read-only mirror of the featured packs. Research your own brief on
              the <a href={LIVE_URL} className="text-ink underline">live app</a>.</p>
          : <AskFlow />}
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
