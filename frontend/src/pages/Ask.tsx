// S1 ASK + PLAN (PRD 10.2, guide Step 4.2): brief, mode, window, brand voice, masked run key ->
// 0-3 clarifying questions (answer chips, own words, skip) or the plan to review, with editable chips
// that re-plan in place (V3) -> Start (the run joins the queue).
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ArrowRight, CircleHelp, KeyRound, Loader2, Plus, RefreshCw, X } from "lucide-react";
import {
  ApiError, answerQuestions, createRun, getOptions, replanRun, startRun,
  type IntakeData, type Options, type PlanEdits, type PlanUnit, type Question, type QuestionAnswer, type RunStatus,
} from "../lib/api";
import { explain, readRunKey, saveRunKey } from "../lib/runKey";
import { intakeFromParam, loadDraft, saveDraft } from "../lib/rerun";
import { BRIEF_TEMPLATE, BriefGuide, BriefGuideButton } from "../components/BriefGuide";

const EXAMPLES = [
  "Launching a snack brand in the Netherlands",
  "Gen Z and meal prep",
  "Heat pumps for homeowners in Germany",
  "Protein supplements for women in the Netherlands",
  "Bouldering gyms for beginners",
];

const FIELD_LABELS: Record<string, string> = {
  topic: "Topic", market: "Markets", languages: "Languages", audience: "Audience", category: "Category",
  intent: "Goal", time_window_days: "Time window", competitors: "Brands named", compliance_category: "Rules area",
};

function useRotatingExample(paused: boolean) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (paused || still) return;
    const t = setInterval(() => setN((x) => (x + 1) % EXAMPLES.length), 3500);
    return () => clearInterval(t);
  }, [paused]);
  return EXAMPLES[n];
}

/** "pl" -> "Polish" (the browser knows every language name; the code is the fallback). */
function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}

// --- the form -------------------------------------------------------------------------------

export function AskForm({ onRun }: { onRun: (run: RunStatus) => void }) {
  // Prefill: "Run again" or a re-plan (?brief=&mode=&window=&voice=&answer=), else this tab's last draft.
  const [params] = useSearchParams();
  const draft = params.get("brief") ? null : loadDraft();
  const [options, setOptions] = useState<Options | null>(null);
  const [brief, setBrief] = useState(params.get("brief") ?? draft?.brief ?? "");
  const [mode, setMode] = useState<"quick" | "standard">(
    (params.get("mode") ?? draft?.mode) === "standard" ? "standard" : "quick");
  const [windowDays, setWindowDays] = useState<number | null>(
    params.get("window") ? Number(params.get("window")) : draft?.window ?? null);
  const [voice, setVoice] = useState(params.get("voice") ?? draft?.voice ?? "");
  const [intake, setIntake] = useState<IntakeData | null>(intakeFromParam(params.get("intake")));  // "Run again"
  const [guideOpen, setGuideOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keyRef = useRef<HTMLInputElement>(null);
  const example = useRotatingExample(brief.length > 0);

  useEffect(() => saveDraft({ brief, mode, window: windowDays, voice }), [brief, mode, windowDays, voice]);
  useEffect(() => {
    getOptions().then((o) => { setOptions(o); if (!params.get("mode") && !draft) setMode(o.default_mode); })
      .catch(() => setOptions(null));
    if (keyRef.current) keyRef.current.value = readRunKey(); // the DOM property only - never an attribute
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const key = keyRef.current?.value.trim() ?? "";
    setError(null);
    if (brief.trim().length < 3) return setError("Please describe what you want to research.");
    if (!key) return setError("Please enter the run key to start research.");
    saveRunKey(key);
    setBusy(true);
    try {
      const run = await createRun(key, {
        brief: brief.trim(), mode, time_window_days: windowDays ?? undefined,
        brand_voice: voice.trim() || undefined, intake: intake ?? undefined,
      });
      onRun(run);
    } catch (err) {
      setError(err instanceof ApiError ? explain(err.status, err.message) : "Could not reach the server.");
    } finally {
      setBusy(false);
    }
  };

  const est = options?.modes[mode];
  return (
    <form onSubmit={submit} className="space-y-4" aria-describedby={error ? "ask-error" : undefined}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <BriefGuideButton open={guideOpen} onToggle={() => setGuideOpen((o) => !o)} />
        <button type="button" onClick={() => setBrief(BRIEF_TEMPLATE)} disabled={brief.trim().length > 0}
                title={brief.trim() ? "Clear the box first to use the template" : undefined}
                className="text-sm text-ink underline disabled:text-ink-3 disabled:no-underline">
          Use the template
        </button>
      </div>
      {guideOpen && <BriefGuide onClose={() => setGuideOpen(false)} />}
      <label htmlFor="brief" className="sr-only">Your brief</label>
      <textarea
        id="brief" value={brief} onChange={(e) => setBrief(e.target.value)} maxLength={2000}
        rows={Math.min(10, Math.max(3, brief.split("\n").length))}
        placeholder={`e.g. ${example}`} aria-describedby="brief-count"
        className="w-full resize-y rounded-lg border border-line-strong bg-paper px-4 py-3 text-lg text-ink placeholder:text-ink-3 focus:border-ink focus:outline-none"
      />
      <p id="brief-count" className="-mt-3 text-right font-mono text-xs text-ink-3">{brief.length} / 2000</p>
      <div className="grid gap-4 md:grid-cols-[auto_auto_1fr]">
        <fieldset>
          <legend className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-3">Depth</legend>
          <div className="flex rounded-lg border border-line p-0.5">
            {(["quick", "standard"] as const).map((m) => (
              <label key={m} className={`cursor-pointer rounded-md px-3 py-1.5 text-sm ${mode === m ? "bg-ink text-paper" : "text-ink-2"}`}>
                <input type="radio" name="mode" value={m} checked={mode === m} onChange={() => setMode(m)} className="sr-only" />
                {m === "quick" ? "Quick" : "Standard"}
                {options && <span className="ml-1 font-mono text-xs opacity-80">~{options.modes[m].typical_minutes} min</span>}
              </label>
            ))}
          </div>
        </fieldset>
        <div>
          <label htmlFor="window" className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-3">Time window</label>
          <select id="window" value={windowDays ?? options?.default_time_window_days ?? ""}
                  onChange={(e) => setWindowDays(Number(e.target.value))}
                  className="rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink">
            {(options?.time_window_days_options ?? []).map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="voice" className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-3">
            Brand voice (one line, optional)
          </label>
          <input id="voice" value={voice} onChange={(e) => setVoice(e.target.value)}
                 maxLength={options?.brand_voice_max_chars ?? 200} placeholder="e.g. dry Dutch humour, no hype"
                 aria-describedby="voice-help"
                 className="w-full rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink placeholder:text-ink-3" />
          <p id="voice-help" className="mt-1 text-xs text-ink-3">How your brand sounds. Used only for hooks and post ideas, never to change what the research finds.</p>
        </div>
      </div>
      <div className="grid items-end gap-4 md:grid-cols-[1fr_auto]">
        <div>
          <label htmlFor="runkey" className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ink-3">
            <KeyRound aria-hidden="true" size={13} /> Run key
          </label>
          <input id="runkey" ref={keyRef} type="password" autoComplete="off" spellCheck={false}
                 aria-describedby="runkey-help"
                 className="w-full rounded-lg border border-line bg-paper px-3 py-2 font-mono text-sm text-ink md:max-w-sm" />
          <p id="runkey-help" className="mt-1 text-xs text-ink-3">
            Your key stays in this browser tab only.
          </p>
        </div>
        <button type="submit" disabled={busy}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-ink px-5 py-2.5 text-sm font-medium text-paper hover:bg-ink-2 disabled:opacity-60">
          {busy ? <Loader2 aria-hidden="true" size={16} className="animate-spin" /> : <ArrowRight aria-hidden="true" size={16} />}
          {busy ? "Reading your brief…" : "Plan the research"}
        </button>
      </div>
      {est && (
        <p className="text-xs text-ink-3">
          {mode === "quick" ? "Quick" : "Standard"}: about {est.typical_minutes} minutes. Planning first: nothing is
          collected until you press Start.
        </p>
      )}
      {intake && (
        <p className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm text-ink-2">
          Your earlier answers will be used, so there are no questions this time.
          <button type="button" onClick={() => setIntake(null)} className="text-ink underline">Ask me again</button>
        </p>
      )}
      {error && <p id="ask-error" role="alert" className="rounded-lg border border-line-strong bg-wash px-3 py-2 text-sm text-ink">{error}</p>}
    </form>
  );
}

// --- the clarifying questions (V3) -------------------------------------------------------------

type Draft = { chosen: string[]; text: string; skipped: boolean };

function QuestionBox({ q, value, onChange, disabled }: {
  q: Question; value: Draft; onChange: (d: Draft) => void; disabled: boolean;
}) {
  const pick = (o: string) => {
    const has = value.chosen.includes(o);
    const chosen = q.multi_select ? (has ? value.chosen.filter((x) => x !== o) : [...value.chosen, o]) : (has ? [] : [o]);
    onChange({ ...value, chosen, skipped: false });
  };
  return (
    <fieldset className={`rounded-lg border p-4 ${value.skipped ? "border-dashed border-line-strong opacity-70" : "border-line-strong"}`}
              disabled={disabled}>
      <legend className="px-1 font-medium text-ink">{q.question}</legend>
      {q.why_it_helps && <p className="text-sm text-ink-3">{q.why_it_helps}</p>}
      <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label={q.multi_select ? "Pick one or more" : "Pick one"}>
        {q.options.map((o) => (
          <button key={o} type="button" aria-pressed={value.chosen.includes(o)} onClick={() => pick(o)}
                  className={`rounded-full border px-3 py-1.5 text-sm ${value.chosen.includes(o) ? "border-ink bg-ink text-paper" : "border-line-strong text-ink hover:border-ink"}`}>
            {o}
          </button>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {q.allow_free_text !== false && (
          <>
            <label htmlFor={`own-${q.id}`} className="sr-only">Or in your own words</label>
            <input id={`own-${q.id}`} value={value.text} placeholder="Or in your own words"
                   onChange={(e) => onChange({ ...value, text: e.target.value, skipped: false })}
                   className="w-full max-w-sm rounded-lg border border-line px-3 py-1.5 text-sm" />
          </>
        )}
        <button type="button" onClick={() => onChange({ chosen: [], text: "", skipped: !value.skipped })}
                aria-pressed={value.skipped} className="text-sm text-ink-2 underline">
          {value.skipped ? "Answer this after all" : "Skip - let the agent decide"}
        </button>
      </div>
    </fieldset>
  );
}

export function QuestionCards({ run, onPlanned }: { run: RunStatus; onPlanned: (run: RunStatus) => void }) {
  const qs = run.clarifying_questions;
  const [drafts, setDrafts] = useState<Record<string, Draft>>(
    Object.fromEntries(qs.map((q) => [q.id, { chosen: [], text: "", skipped: false }])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = async (skipAll: boolean) => {
    setBusy(true);
    setError(null);
    const answers: QuestionAnswer[] = qs.map((q) => {
      const d = drafts[q.id];
      const empty = !d.chosen.length && !d.text.trim();
      return { id: q.id, chosen: d.chosen, text: d.text.trim() || undefined, skipped: d.skipped || empty };
    });
    try {
      onPlanned(await answerQuestions(readRunKey(), run.run_id, { answers, skip_all: skipAll }));
    } catch (err) {
      setError(err instanceof ApiError ? explain(err.status, err.message) : "Could not reach the server.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-labelledby="clarify" className="space-y-4">
      <h2 id="clarify" className="flex items-center gap-2 text-lg font-semibold text-ink">
        <CircleHelp aria-hidden="true" size={18} /> {qs.length === 1 ? "One question" : `${qs.length} quick questions`} to sharpen the research
      </h2>
      {qs.map((q) => (
        <QuestionBox key={q.id} q={q} value={drafts[q.id]} disabled={busy}
                     onChange={(d) => setDrafts((all) => ({ ...all, [q.id]: d }))} />
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => send(false)} disabled={busy}
                className="inline-flex items-center gap-2 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-paper disabled:opacity-60">
          {busy ? <Loader2 aria-hidden="true" size={15} className="animate-spin" /> : <ArrowRight aria-hidden="true" size={15} />}
          Plan with my answers
        </button>
        <button type="button" onClick={() => send(true)} disabled={busy} className="text-sm text-ink underline">
          Skip all and plan
        </button>
      </div>
      {error && <p role="alert" className="text-sm text-ink">{error}</p>}
    </section>
  );
}

// --- editable chips on the plan (V3): any edit re-plans in place ---------------------------------

function ChipList({ label, hint, items, onRemove, onAdd, addLabel, options }: {
  label: string; hint?: string; items: { key: string; text: string }[]; onRemove: (key: string) => void;
  onAdd: (value: string) => void; addLabel: string; options?: { value: string; text: string }[];
}) {
  const [adding, setAdding] = useState("");
  const id = `add-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className="bg-paper px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</p>
      {hint && <p className="text-xs text-ink-3">{hint}</p>}
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((it) => (
          <li key={it.key} className="inline-flex items-center gap-1 rounded-full border border-line-strong py-0.5 pl-2.5 pr-1 text-sm text-ink">
            {it.text}
            <button type="button" onClick={() => onRemove(it.key)} aria-label={`Remove ${it.text}`}
                    className="rounded-full p-0.5 text-ink-3 hover:text-ink"><X aria-hidden="true" size={13} /></button>
          </li>
        ))}
      </ul>
      <form className="mt-2 flex gap-1.5" onSubmit={(e) => { e.preventDefault(); if (adding.trim()) { onAdd(adding.trim()); setAdding(""); } }}>
        <label htmlFor={id} className="sr-only">{addLabel}</label>
        {options ? (
          <select id={id} value={adding} onChange={(e) => setAdding(e.target.value)}
                  className="rounded-lg border border-line bg-paper px-2 py-1 text-sm">
            <option value="">{addLabel}…</option>
            {options.map((o) => <option key={o.value} value={o.value}>{o.text}</option>)}
          </select>
        ) : (
          <input id={id} value={adding} onChange={(e) => setAdding(e.target.value)} placeholder={addLabel}
                 className="w-48 rounded-lg border border-line px-2 py-1 text-sm" />
        )}
        <button type="submit" aria-label={addLabel} disabled={!adding.trim()}
                className="rounded-lg border border-line px-2 text-ink-2 disabled:opacity-40"><Plus aria-hidden="true" size={14} /></button>
      </form>
    </div>
  );
}

function EditablePlan({ run, onReplanned }: { run: RunStatus; onReplanned: (run: RunStatus) => void }) {
  const interp = run.interpretation!;
  const original = {
    markets: interp.markets.map((m) => m.code), languages: interp.languages, audience: interp.audience,
    audience_roles: run.intake?.audience_roles ?? [], competitors: interp.competitors ?? [],
  };
  const [edits, setEdits] = useState(original);
  const [options, setOptions] = useState<Options | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { getOptions().then(setOptions).catch(() => setOptions(null)); }, []);
  const changed = JSON.stringify(edits) !== JSON.stringify(original);
  const set = (k: keyof typeof original, v: string[] | string) => setEdits((e) => ({ ...e, [k]: v }));
  const marketText = (code: string) => {
    const cs = interp.markets.find((x) => x.code === code)?.countries ?? [];
    return cs.length > 1 ? `${code.toUpperCase()} (${cs.slice(0, 4).join(", ")}${cs.length > 4 ? ", …" : ""})` : code;
  };
  const replan = async () => {
    setBusy(true);
    setError(null);
    const body: PlanEdits = {};
    (Object.keys(original) as (keyof typeof original)[]).forEach((k) => {
      if (JSON.stringify(edits[k]) !== JSON.stringify(original[k])) (body as Record<string, unknown>)[k] = edits[k];
    });
    try {
      onReplanned(await replanRun(readRunKey(), run.run_id, body));
    } catch (err) {
      setError(err instanceof ApiError ? explain(err.status, err.message) : "Could not reach the server.");
    } finally {
      setBusy(false);
    }
  };
  const langOptions = Object.entries(options?.languages ?? {})
    .filter(([code]) => !edits.languages.includes(code)).map(([value, text]) => ({ value, text }));
  return (
    <section aria-labelledby="adjust" className="space-y-2">
      <h3 id="adjust" className="text-sm font-semibold text-ink">Adjust before you start</h3>
      <div className="grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2">
        <ChipList label="Markets" items={edits.markets.map((c) => ({ key: c, text: marketText(c) }))}
                  onRemove={(k) => set("markets", edits.markets.filter((x) => x !== k))}
                  onAdd={(v) => set("markets", [...edits.markets, v])} addLabel="Add a country or region" />
        <ChipList label="Languages" items={edits.languages.map((c) => ({ key: c, text: languageName(c) }))}
                  onRemove={(k) => set("languages", edits.languages.filter((x) => x !== k))}
                  onAdd={(v) => set("languages", [...edits.languages, v])} addLabel="Add a language" options={langOptions} />
        <ChipList label="Who to reach" hint="Roles or groups, e.g. plant managers who sign off budgets"
                  items={edits.audience_roles.map((r) => ({ key: r, text: r }))}
                  onRemove={(k) => set("audience_roles", edits.audience_roles.filter((x) => x !== k))}
                  onAdd={(v) => set("audience_roles", [...edits.audience_roles, v])} addLabel="Add a role" />
        <ChipList label="Competitors" hint="Starter list - edit or add yours (yours are always searched)"
                  items={edits.competitors.map((c) => ({ key: c, text: c }))}
                  onRemove={(k) => set("competitors", edits.competitors.filter((x) => x !== k))}
                  onAdd={(v) => set("competitors", [...edits.competitors, v])} addLabel="Add a competitor" />
        <div className="bg-paper px-4 py-3 sm:col-span-2">
          <label htmlFor="edit-audience" className="text-xs font-medium uppercase tracking-wide text-ink-3">Audience</label>
          <input id="edit-audience" value={edits.audience} onChange={(e) => set("audience", e.target.value)}
                 className="mt-1 w-full rounded-lg border border-line px-3 py-1.5 text-sm text-ink" />
        </div>
      </div>
      {changed && (
        <button type="button" onClick={replan} disabled={busy}
                className="inline-flex items-center gap-2 rounded-lg border border-ink px-3 py-1.5 text-sm text-ink disabled:opacity-60">
          {busy ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <RefreshCw aria-hidden="true" size={14} />}
          Update the plan with my changes
        </button>
      )}
      {error && <p role="alert" className="text-sm text-ink">{error}</p>}
    </section>
  );
}

// --- the plan -----------------------------------------------------------------------------------

function UnitCard({ unit, on, onToggle, last }: { unit: PlanUnit; on: boolean; onToggle: () => void; last: boolean }) {
  return (
    <article className={`rounded-lg border p-3 ${on ? "border-line" : "border-dashed border-line-strong opacity-70"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-xs text-ink-3">{unit.platform} · {unit.kind}</p>
          <p className="truncate font-mono text-sm text-ink" title={unit.target}>{unit.target}</p>
        </div>
        <button type="button" onClick={onToggle} aria-pressed={on} disabled={on && last}
                title={on && last ? "At least one source must stay on" : undefined}
                className={`shrink-0 rounded border px-2 py-0.5 text-xs ${on ? "border-ink text-ink" : "border-line text-ink-3"} disabled:opacity-50`}>
          {on ? "On" : "Off"}
        </button>
      </div>
      <p className="mt-2 text-sm text-ink-2">{unit.reason}</p>
      {unit.queries.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1">
          {unit.queries.slice(0, 4).map((q) => (
            <li key={q.language + q.query} lang={q.language}
                className="rounded border border-line px-1.5 py-0.5 font-mono text-[0.72rem] text-ink-2">
              {q.language} · {q.query}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

export function PlanReview({ run, onReplanned }: { run: RunStatus; onReplanned: (run: RunStatus) => void }) {
  const navigate = useNavigate();
  const plan = run.plan!;
  const interp = run.interpretation!;
  const [off, setOff] = useState<Set<number>>(new Set());
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const questions = plan.research_questions.filter((q) => !removed.has(q.id));
  const onCount = plan.starting_units.length - off.size;
  const assumed = new Set(interp.assumed ?? []);
  const est = run.estimate;

  const toggle = (n: number) => setOff((s) => { const t = new Set(s); if (t.has(n)) t.delete(n); else t.add(n); return t; });
  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      await startRun(readRunKey(), run.run_id, { disabled_units: [...off], removed_questions: [...removed] });
      navigate(`/runs/${run.run_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? explain(err.status, err.message) : "Could not reach the server.");
      setBusy(false);
    }
  };

  const fields: [string, string][] = [
    ["topic", interp.topic], ["market", interp.market ?? ""], ["languages", interp.languages.map(languageName).join(", ")],
    ["audience", interp.audience], ["intent", interp.intent],
    ["time_window_days", `last ${interp.time_window_days} days`],
    ...(interp.competitors?.length ? [["competitors", interp.competitors.join(", ")] as [string, string]] : []),
  ];

  return (
    <div className="space-y-8">
      <section aria-labelledby="understood">
        <h2 id="understood" className="mb-3 text-lg font-semibold text-ink">Here's what I understood</h2>
        <dl className="grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2">
          {fields.map(([k, v]) => (
            <div key={k} className="bg-paper px-4 py-3">
              <dt className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-3">
                {FIELD_LABELS[k] ?? k}
                {assumed.has(k as never) && (
                  <span title="Not in your brief: my assumption" className="rounded border border-line-strong px-1 py-px text-[0.65rem] normal-case tracking-normal text-ink-2">
                    assumed
                  </span>
                )}
              </dt>
              <dd className="mt-0.5 text-ink">{v}</dd>
            </div>
          ))}
        </dl>
        {(interp.languages_excluded ?? []).length > 0 && (
          <div className="mt-3 rounded-lg border border-line px-4 py-3 text-sm">
            <p className="text-xs font-medium uppercase tracking-wide text-ink-3">Languages left out</p>
            <ul className="mt-1 space-y-0.5 text-ink-2">
              {interp.languages_excluded!.map((e) => (
                <li key={e.language}><span className="text-ink">{languageName(e.language)}</span>: {e.reason}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <EditablePlan run={run} onReplanned={onReplanned} />

      <section aria-labelledby="start-here">
        <h2 id="start-here" className="mb-1 text-lg font-semibold text-ink">Here's where I'll start</h2>
        <p className="mb-3 text-sm text-ink-2">
          Starting points, each with a reason. The agent adapts from here: it digs where people really talk and drops
          sources that are off-topic. Switch off any you don't want.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          {plan.starting_units.map((u, n) => (
            <UnitCard key={n} unit={u} on={!off.has(n)} onToggle={() => toggle(n)} last={onCount <= 1} />
          ))}
        </div>
      </section>

      <section aria-labelledby="questions">
        <h2 id="questions" className="mb-3 text-lg font-semibold text-ink">Questions the research will answer</h2>
        <ul className="space-y-2">
          {questions.map((q) => (
            <li key={q.id} className="flex items-start justify-between gap-3 rounded-lg border border-line px-3 py-2">
              <span className="text-ink"><span className="mr-2 font-mono text-xs text-ink-3">{q.id}</span>{q.text}</span>
              <button type="button" onClick={() => setRemoved((s) => new Set(s).add(q.id))}
                      disabled={questions.length <= 5} aria-label={`Remove ${q.id}`}
                      title={questions.length <= 5 ? "At least 5 questions are needed" : "Remove this question"}
                      className="shrink-0 rounded p-1 text-ink-3 hover:text-ink disabled:opacity-40">
                <X aria-hidden="true" size={15} />
              </button>
            </li>
          ))}
        </ul>
        {plan.hypotheses.length > 0 && (
          <details className="mt-3 text-sm text-ink-2">
            <summary className="cursor-pointer text-ink">Hypotheses to test ({plan.hypotheses.length})</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {plan.hypotheses.map((h) => <li key={h.id}><span className="font-mono text-xs text-ink-3">{h.id}</span> {h.statement}</li>)}
            </ul>
          </details>
        )}
      </section>

      <section className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-line-strong p-4">
        <p className="text-sm text-ink-2">
          <span className="font-medium text-ink">{run.mode === "standard" ? "Standard" : "Quick"}</span>: about{" "}
          {est.typical_minutes} minutes. If someone else's research is running, yours waits in line and starts by
          itself.
        </p>
        <button type="button" onClick={start} disabled={busy}
                className="inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-ink hover:brightness-95 disabled:opacity-60">
          {busy ? <Loader2 aria-hidden="true" size={16} className="animate-spin" /> : <ArrowRight aria-hidden="true" size={16} />}
          Start research
        </button>
      </section>
      {error && <p role="alert" className="rounded-lg border border-line-strong bg-wash px-3 py-2 text-sm text-ink">{error}</p>}
    </div>
  );
}

export function AskFlow() {
  const [run, setRun] = useState<RunStatus | null>(null);
  const result = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (run) result.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [run]);
  return (
    <div className="space-y-8">
      <AskForm onRun={setRun} />
      <div ref={result} className="scroll-mt-20">
        {run?.status === "needs_clarification" && run.clarifying_questions?.length > 0 && <QuestionCards run={run} onPlanned={setRun} />}
        {run?.status === "awaiting_approval" && run.plan && <PlanReview key={JSON.stringify([run.plan, run.interpretation, run.intake])} run={run} onReplanned={setRun} />}
      </div>
    </div>
  );
}
