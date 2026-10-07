// /evals: evaluation on the four test briefs (Step 5.1, PRD 14). Pass / fail is a word and a glyph,
// never colour only. Failures carry their reason from the eval itself.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Skeleton } from "../components/Skeleton";
import { friendlyError, getEvals } from "../lib/api";

interface Metric {
  value: number | string | Record<string, unknown> | null;
  target: number | string | null;
  pass: boolean | null;
  detail: string;
  simulated?: boolean;
  assumption?: string;
}
interface Expectation { check: string; pass: boolean | null; detail: string }
interface BriefResult {
  id: string; brief: string; mode: string; pack_id: string; reused: boolean; note: string;
  interpreted: { topic: string; market: string; languages: string[] };
  coverage_grade: string | null; relevant_posts: number | null;
  thin_evidence: boolean; thin_evidence_note: string;
  metrics: Record<string, Metric>;
  expectations: Expectation[];
}
interface HumanBrief { hooks_would_use: number | null; hooks_rated: number | null; complaints: string[] }
interface Human {
  session: { date: string | null; brief_team_tomorrow: boolean | null; why: string | null;
             quote: string | null; quote_permission: boolean } | null;
  briefs: Record<string, HumanBrief>;
  target_would_use_share?: number;
}
interface Evals {
  status: string; note?: string; generated_at?: string; eval_cost_usd?: number;
  headline?: Record<string, Metric>; briefs: BriefResult[]; notes?: string[]; human?: Human;
}

const RATES = new Set(["quote_groundedness", "claim_entailment", "claims_with_evidence", "relevance_rate",
  "schema_valid", "plan_divergence"]);

const NAMES: Record<string, string> = {
  quote_groundedness: "Quote groundedness",
  claim_entailment: "Claim entailment",
  claims_with_evidence: "Claims with evidence",
  relevance_rate: "Relevance rate",
  source_diversity: "Source diversity",
  plan_divergence: "Plan divergence",
  allocation_efficiency: "Allocation efficiency",
  loop_health: "Loop health",
  cost_usd: "Cost (USD)",
  latency_min: "Latency (min)",
  peak_mem_mb: "Peak memory (MB)",
  schema_valid: "Schema valid",
};

function fmt(name: string, v: Metric["value"]): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "object") return `${v.tool_calls} calls · ${v.finish_reason}`;
  if (typeof v === "number" && RATES.has(name)) return `${Math.round(v * 1000) / 10}%`;
  if (typeof v === "number" && name === "cost_usd") return `$${v.toFixed(2)}`;
  if (typeof v === "number" && name === "allocation_efficiency") return `${v.toFixed(2)}×`;
  return String(v);
}

function fmtTarget(name: string, t: Metric["target"]): string {
  if (t === null || t === undefined) return "";
  if (typeof t === "number" && RATES.has(name)) return name === "plan_divergence" ? `< ${t * 100}% shared` : `≥ ${t * 100}%`;
  if (typeof t === "number" && name === "cost_usd") return `cap $${t.toFixed(2)}`;
  if (typeof t === "number" && name === "latency_min") return `~${t} min`;
  if (typeof t === "number" && name === "peak_mem_mb") return `< ${t} MB`;
  return String(t);
}

function Verdict({ pass }: { pass: boolean | null }) {
  if (pass === true) return <span className="inline-flex items-center gap-1 font-medium text-ink"><span aria-hidden="true">✓</span>Pass</span>;
  if (pass === false) return <span className="inline-flex items-center gap-1 font-medium text-accent-ink"><span aria-hidden="true">✗</span>Fail</span>;
  return <span className="inline-flex items-center gap-1 text-ink-3"><span aria-hidden="true">–</span>n/a</span>;
}

function Simulated() {
  return (
    <span title="Estimated, not measured: see the assumption below."
          className="ml-1.5 rounded border border-dashed border-ink-3 px-1 py-px font-mono text-[10px] uppercase tracking-wide text-ink-2">
      Simulated
    </span>
  );
}

function humanCell(h: HumanBrief | undefined, target: number): string {
  if (!h || h.hooks_rated === null || h.hooks_would_use === null) return "not rated yet";
  const share = h.hooks_rated ? h.hooks_would_use / h.hooks_rated : 0;
  return `${h.hooks_would_use}/${h.hooks_rated} hooks (${Math.round(share * 100)}%) ${share >= target ? "✓" : "✗"}`;
}

const OVERVIEW = ["quote_groundedness", "claim_entailment", "relevance_rate", "source_diversity",
  "allocation_efficiency", "cost_usd", "latency_min"];

export function EvalsPage() {
  const [data, setData] = useState<Evals | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getEvals<Evals>().then(setData).catch((e) => setError(friendlyError(e)));
  }, []);
  const human = data?.human;
  const target = human?.target_would_use_share ?? 0.6;

  return (
    <div className="max-w-5xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Evaluations</h1>
        <p className="max-w-3xl text-ink-2">
          Four test briefs: a global English brief, a Dutch launch, a German
          B2B-like brief with energy claims, and a deliberately vague one. Numbers are computed in code from the
          finished packs; claim entailment is a fresh re-check by a different model than the pipeline's verifier.
        </p>
        {data?.generated_at && (
          <p className="font-mono text-xs text-ink-3">
            generated {data.generated_at.replace("T", " ").slice(0, 16)} UTC
            {data.eval_cost_usd !== undefined && ` · eval checks $${data.eval_cost_usd.toFixed(2)}`}
          </p>
        )}
      </header>

      {error && <p className="text-ink-2">{error}</p>}
      {!data && !error && <Skeleton lines={4} />}
      {data && data.status !== "ok" && (
        <p className="rounded-lg border border-dashed border-line-strong p-4 text-sm text-ink-2">{data.note}</p>
      )}

      {data?.status === "ok" && data.headline && (
        <>
          <section aria-labelledby="headline" className="space-y-3">
            <h2 id="headline" className="text-lg font-semibold text-ink">Headline vs. targets (PRD 14.3)</h2>
            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full text-sm">
                <thead className="bg-wash text-left text-xs text-ink-2">
                  <tr><th className="px-3 py-2 font-medium">Metric</th><th className="px-3 py-2 font-medium">Result</th>
                    <th className="px-3 py-2 font-medium">Target</th><th className="px-3 py-2 font-medium">Verdict</th>
                    <th className="px-3 py-2 font-medium">Why</th></tr>
                </thead>
                <tbody>
                  {Object.entries(data.headline).map(([name, m]) => (
                    <tr key={name} className="border-t border-line align-top">
                      <th scope="row" className="px-3 py-2 text-left font-medium text-ink">
                        {NAMES[name] ?? name}{m.simulated && <Simulated />}
                      </th>
                      <td className="px-3 py-2 font-mono text-ink">{name === "source_diversity" ? `${m.value} of ${m.target} briefs` : fmt(name, m.value)}</td>
                      <td className="px-3 py-2 font-mono text-xs text-ink-2">{name === "source_diversity" ? "≥ 3 platforms" : fmtTarget(name, m.target)}</td>
                      <td className="px-3 py-2"><Verdict pass={m.pass} /></td>
                      <td className="px-3 py-2 text-ink-2">{m.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section aria-labelledby="overview" className="space-y-3">
            <h2 id="overview" className="text-lg font-semibold text-ink">Per brief</h2>
            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full text-sm">
                <thead className="bg-wash text-left text-xs text-ink-2">
                  <tr>
                    <th className="px-3 py-2 font-medium">Brief</th>
                    {OVERVIEW.map((n) => (
                      <th key={n} className="px-3 py-2 font-medium">{NAMES[n]}{n === "allocation_efficiency" && <Simulated />}</th>
                    ))}
                    <th className="px-3 py-2 font-medium">Human: would use</th>
                  </tr>
                </thead>
                <tbody>
                  {data.briefs.map((b) => (
                    <tr key={b.id} className="border-t border-line align-top">
                      <th scope="row" className="px-3 py-2 text-left font-medium text-ink">
                        <a href={`#${b.id}`} className="hover:underline">{b.brief}</a>
                        <span className="block font-mono text-xs font-normal text-ink-3">{b.mode} · grade {b.coverage_grade}</span>
                      </th>
                      {OVERVIEW.map((n) => (
                        <td key={n} className="px-3 py-2">
                          <span className="block font-mono text-ink">{fmt(n, b.metrics[n]?.value ?? null)}</span>
                          <span className="text-xs"><Verdict pass={b.metrics[n]?.pass ?? null} /></span>
                        </td>
                      ))}
                      <td className="px-3 py-2 font-mono text-xs text-ink-2">{humanCell(human?.briefs[b.id], target)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {data.briefs.map((b) => (
            <section key={b.id} id={b.id} aria-labelledby={`${b.id}-h`} className="scroll-mt-6 space-y-3">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 id={`${b.id}-h`} className="text-lg font-semibold text-ink">{b.brief}</h2>
                <Link to={`/packs/${b.pack_id}`} className="font-mono text-xs text-ink-2 hover:underline">{b.pack_id}</Link>
                <span className="font-mono text-xs text-ink-3">
                  {b.mode} · {b.interpreted.market} · {b.interpreted.languages.join("+")} · {b.relevant_posts} relevant
                  {b.reused ? " · reused pack" : " · new run"}
                </span>
              </div>
              {b.note && <p className="text-sm text-ink-2">{b.note}</p>}
              {b.thin_evidence && (
                <p className="rounded border border-line-strong bg-wash px-3 py-2 text-sm text-ink">
                  <span className="font-medium">Thin evidence:</span> {b.thin_evidence_note}
                </p>
              )}
              <ul className="divide-y divide-line rounded-lg border border-line text-sm">
                {Object.entries(b.metrics).map(([name, m]) => (
                  <li key={name} className="grid gap-1 px-3 py-2 md:grid-cols-[12rem_8rem_5rem_1fr]">
                    <span className="font-medium text-ink">{NAMES[name] ?? name}{m.simulated && <Simulated />}</span>
                    <span className="font-mono text-ink">{fmt(name, m.value)}</span>
                    <Verdict pass={m.pass} />
                    <span className="text-ink-2">
                      {m.detail}
                      {m.assumption && <span className="mt-1 block text-xs text-ink-3">Assumption: {m.assumption}</span>}
                    </span>
                  </li>
                ))}
                {b.expectations.map((e) => (
                  <li key={e.check} className="grid gap-1 px-3 py-2 md:grid-cols-[20rem_5rem_1fr]">
                    <span className="font-medium text-ink">Brief check: {e.check}</span>
                    <Verdict pass={e.pass} />
                    <span className="text-ink-2">{e.detail}</span>
                  </li>
                ))}
                <li className="grid gap-1 px-3 py-2 md:grid-cols-[20rem_1fr]">
                  <span className="font-medium text-ink">Human rating (PRD 14.4)</span>
                  <span className="text-ink-2">
                    {humanCell(human?.briefs[b.id], target)}
                    {(human?.briefs[b.id]?.complaints ?? []).length > 0 &&
                      ` · complaints: ${human!.briefs[b.id].complaints.join("; ")}`}
                  </span>
                </li>
              </ul>
            </section>
          ))}

          {human?.session?.date && (
            <section aria-labelledby="human" className="space-y-2">
              <h2 id="human" className="text-lg font-semibold text-ink">Marketer session</h2>
              <p className="text-sm text-ink-2">
                {human.session.date} · would brief their team with this tomorrow:{" "}
                <span className="font-medium text-ink">
                  {human.session.brief_team_tomorrow === null ? "not asked" : human.session.brief_team_tomorrow ? "yes" : "no"}
                </span>
                {human.session.why && ` – ${human.session.why}`}
              </p>
              {human.session.quote && human.session.quote_permission && (
                <blockquote className="border-l-2 border-line-strong pl-3 font-serif text-lg text-ink">“{human.session.quote}”</blockquote>
              )}
            </section>
          )}

          {data.notes && (
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
              {data.notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
