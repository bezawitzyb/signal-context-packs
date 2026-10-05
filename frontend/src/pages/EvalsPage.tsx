// /evals: evaluation results on the test briefs (filled in Phase 5).
import { useEffect, useState } from "react";
import { Skeleton } from "../components/Skeleton";

export function EvalsPage() {
  const [data, setData] = useState<{ status: string; results: unknown[]; note: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/v1/evals").then((r) => r.json()).then(setData).catch(() => setError("Could not load the evaluations."));
  }, []);
  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Evaluations</h1>
      <p className="text-ink-2">How the packs hold up on four test briefs: plan differences, groundedness, confidence labels and cost.</p>
      {error && <p className="text-ink-2">{error}</p>}
      {!data && !error && <Skeleton lines={2} />}
      {data && (data.results.length === 0
        ? <p className="rounded-lg border border-dashed border-line-strong p-4 text-sm text-ink-2">{data.note}</p>
        : <pre className="overflow-auto rounded-lg border border-line p-3 font-mono text-xs">{JSON.stringify(data.results, null, 2)}</pre>)}
    </div>
  );
}
