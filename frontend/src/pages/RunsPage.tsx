// /runs: what each run cost - for the owner only (main run key; the guest key is refused). Not linked in the menu.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { KeyRound } from "lucide-react";
import { ApiError, friendlyError, getOwnerRuns, MIRROR, type OwnerRuns } from "../lib/api";
import { readRunKey, saveRunKey } from "../lib/runKey";
import { Skeleton } from "../components/Skeleton";
import { ErrorNote } from "../components/ErrorNote";

const usd = (x: number) => `$${x.toFixed(2)}`;

export function RunsPage() {
  const keyRef = useRef<HTMLInputElement>(null);
  const [data, setData] = useState<OwnerRuns | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [needKey, setNeedKey] = useState(!readRunKey());

  const load = (key: string) => {
    setLoading(true);
    setError(null);
    getOwnerRuns(key).then((d) => { setData(d); setNeedKey(false); })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          setNeedKey(true);
          setError("That key doesn't open this page. It needs the owner key (a guest key can't see costs).");
        } else setError(friendlyError(e));
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const key = readRunKey();
    if (key && !MIRROR) load(key);
  }, []);

  if (MIRROR) return <ErrorNote message="Run costs are only available on the live app." />;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Runs and costs</h1>
        <p className="text-ink-2">Only you can see this page: it opens with the owner key. Costs are what each run spent at
          Apify and Anthropic; re-running analysis steps later adds to a run's total.</p>
      </header>

      {needKey && (
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
          e.preventDefault();
          const key = keyRef.current?.value.trim() ?? "";
          if (!key) return;
          saveRunKey(key);
          if (keyRef.current) keyRef.current.value = "";
          load(key);
        }}>
          <div>
            <label htmlFor="ownerkey" className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ink-3">
              <KeyRound aria-hidden="true" size={13} /> Owner key
            </label>
            <input id="ownerkey" ref={keyRef} type="password" autoComplete="off" spellCheck={false}
                   className="w-72 rounded-lg border border-line bg-paper px-3 py-2 font-mono text-sm text-ink" />
          </div>
          <button type="submit" className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-paper hover:bg-ink-2">Show costs</button>
        </form>
      )}
      {error && <ErrorNote message={error} />}
      {loading && <Skeleton lines={3} label="Loading the runs" />}

      {data && (
        <>
          <dl className="flex flex-wrap gap-6 text-sm">
            <div><dt className="text-ink-3">Today (all runs)</dt>
              <dd className="font-mono text-lg text-ink">{usd(data.today.spent_usd)} <span className="text-sm text-ink-3">of {usd(data.today.cap_usd)} daily cap</span></dd></div>
            <div><dt className="text-ink-3">The {data.runs.length} runs below</dt>
              <dd className="font-mono text-lg text-ink">{usd(data.listed_total_usd)}</dd></div>
          </dl>
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-sm">
              <caption className="sr-only">Recent runs with their cost</caption>
              <thead className="bg-wash text-left text-xs text-ink-2">
                <tr>{["Started (UTC)", "Brief", "Mode", "Status", "Apify", "Anthropic", "Total", ""].map((h) => (
                  <th key={h} scope="col" className="px-3 py-2 font-medium">{h}</th>))}</tr>
              </thead>
              <tbody>
                {data.runs.map((r) => (
                  <tr key={r.run_id} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-ink-2">{r.created_at.replace("T", " ").slice(0, 16)}</td>
                    <td className="px-3 py-2 text-ink">{r.brief}<span className="block font-mono text-xs text-ink-3">{r.run_id} · {r.requester}</span></td>
                    <td className="px-3 py-2 text-ink-2">{r.mode}</td>
                    <td className="px-3 py-2 text-ink-2">{r.status}</td>
                    <td className="px-3 py-2 text-right font-mono text-ink-2">{usd(r.apify_usd)}</td>
                    <td className="px-3 py-2 text-right font-mono text-ink-2">{usd(r.anthropic_usd)}</td>
                    <td className="px-3 py-2 text-right font-mono font-medium text-ink">{usd(r.total_usd)}</td>
                    <td className="whitespace-nowrap px-3 py-2">
                      {r.pack_id
                        ? <Link to={`/packs/${r.pack_id}`} className="text-ink underline">pack</Link>
                        : <Link to={`/runs/${r.run_id}`} className="text-ink underline">run</Link>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
