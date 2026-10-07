// S1 ASK + PLAN arrives in Step 4.2. For now: what this is, and the featured packs.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import { friendlyError, listPacks, LIVE_URL, MIRROR, type FeaturedPack } from "../lib/api";
import { ErrorNote } from "../components/ErrorNote";
import { ModeBadge } from "../components/badges";
import { AskFlow } from "./Ask";
import { Skeleton } from "../components/Skeleton";

export function PackCards({ packs }: { packs: FeaturedPack[] }) {
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {packs.map((p) => (
        <li key={p.pack_id}>
          <Link to={`/packs/${p.pack_id}`}
                className="group block rounded-lg border border-line p-4 hover:border-line-strong">
            <p className="font-medium text-ink">{p.brief}</p>
            <p className="mt-1 text-sm text-ink-2">{p.audience}</p>
            <div className="mt-3 flex flex-wrap items-center gap-2 font-mono text-xs text-ink-3">
              <ModeBadge mode={p.mode} />
              <span>{p.market}</span>
              <span>coverage {p.coverage_grade}</span>
              {p.thin_evidence && <span>thin evidence</span>}
              <span className="ml-auto inline-flex items-center gap-1 font-sans text-sm text-ink group-hover:underline">
                See the pack <ArrowRight aria-hidden="true" size={14} />
              </span>
            </div>
          </Link>
        </li>
      ))}
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
        <p className="mt-3 text-ink-2">
          Give a brief. An agent listens to real public posts in the right market and language, and builds a
          evidence-linked Context Pack: tensions, their words, objections and a playbook, every claim tied to the posts
          behind it. Ready for your team and for AI agents.
        </p>
      </section>
      <section aria-labelledby="featured">
        <h2 id="featured" className="mb-3 text-lg font-semibold text-ink">See an example pack</h2>
        {error && <ErrorNote message={error} />}
        {!packs && !error && <Skeleton lines={1} label="Loading the example packs" />}
        {packs && <PackCards packs={packs} />}
      </section>
      <section aria-labelledby="ask">
        <h2 id="ask" className="mb-3 text-lg font-semibold text-ink">Research your own brief</h2>
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
