// Typed client for /api/v1 (PRD 11.1). The run key is passed in per call as the X-API-Key header;
// this file never stores, logs or shows it.
import type {
  ConfidenceLabel,
  ContextPack11,
  Evidence1,
  Interpretation,
} from "./types";
import type { RunInputs } from "./rerun";

/** The API always sends every field (the backend dumps defaults too), so responses are fully present. */
type DeepRequired<T> = T extends (infer U)[] ? DeepRequired<U>[]
  : T extends object ? { [K in keyof T]-?: DeepRequired<T[K]> } : T;

export type ContextPack = DeepRequired<ContextPack11>;
export type Evidence = DeepRequired<Evidence1>;
export type Label = ConfidenceLabel;

/** The fields every claim-like item shares (themes, tensions, lexicon, ...). */
export interface InsightLike {
  id: string;
  claim: string;
  summary_for_humans?: string;
  cluster_id?: string | null;
  counts: { matching: number; of_total: number };
  confidence: { score: number; label: Label };
  claim_type: "observed" | "inferred" | "external";
  safe_to_assert: boolean;
  non_obvious: boolean;
  strength: { evidence_count: number; distinct_authors: number; platforms: string[];
              engagement_percentile_median?: number | null };
  emotion?: string[];
  trend?: string;
  recency?: string | null;
  evidence_ids: string[];
  quotes?: { evidence_id: string; text: string }[];
  segment_ids?: string[];
  related_ids?: string[];
  relations?: { id: string; kind: "comes_from" | "blocks" | "related" }[];
}

export interface FeaturedPack {
  pack_id: string; brief: string; topic: string; market: string; audience: string; mode: string;
  generated_at: string; coverage_grade: string; thin_evidence: boolean;
}

export interface RunStatus {
  run_id: string; brief: string; mode: string;
  status: "created" | "needs_clarification" | "awaiting_approval" | "queued" | "running" | "interrupted"
    | "complete" | "partial" | "failed" | "stopped";
  stage: string | null; queue_position: number | null; pack_id: string | null; error: string | null;
  created_at: string; interpretation: Interpretation | null; plan: Plan | null;
  clarifying_questions: Question[];
  intake: IntakeData | null;
  collection: {
    sources_used: { source_unit: string; platform: string; reason: string; kept: number; relevant_share: number }[];
    sources_dropped: { source_unit: string; reason: string }[];
    gaps: string[]; finish_reason: string | null; fallback_used: boolean; top_up_used: boolean;
    thin?: { relevant: number; needed: number; reasons: { code: string; text: string }[]; replans: string[] } | null;
  } | null;
  inputs?: RunInputs;
  estimate: Estimate;
}

/** A clarifying question written for this brief (V3): answer chips, free text, or skip. */
export interface Question {
  id: string; question: string; why_it_helps?: string; fills: string; options: string[];
  multi_select?: boolean; allow_free_text?: boolean;
}
/** What the user told us before planning (brief.intake). */
export interface IntakeData {
  audience_roles?: string[]; goal?: string | null; offer?: string | null; channels_in_use?: string[];
  competitors_user?: string[]; timeframe?: string | null; other_answers?: { question: string; answer: string }[];
  questions_asked?: Question[];
}
export interface QuestionAnswer { id: string; chosen?: string[]; text?: string; skipped?: boolean }
export interface PlanEdits {
  markets?: string[]; languages?: string[]; audience?: string; audience_roles?: string[]; competitors?: string[];
}

export interface ItemResult { pack_id: string; item: Record<string, unknown>; evidence: Evidence[]; note: string }
export interface EvidenceResult { pack_id: string; total: number; evidence: Evidence[]; note: string }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const BASE = "/api/v1";

// Read-only static mirror on GitHub Pages (guide B15): built with VITE_MIRROR=1, it reads the
// featured packs from pre-built files under data/ and never calls the API.
export const MIRROR = import.meta.env.VITE_MIRROR === "1";
export const LIVE_URL = "https://signal-l2w5.onrender.com";
export const MIRROR_URL = "https://bezawitzyb.github.io/signal-context-packs/";
const DATA = `${import.meta.env.BASE_URL}data`;
const NOT_IN_MIRROR = "This read-only mirror only shows the featured packs. Live research runs happen on the live app.";

async function staticJson<T>(path: string): Promise<T> {
  const res = await fetch(`${DATA}/${path}`);
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? "This pack is not in the mirror." : `Could not load (${res.status}).`);
  return res.json() as Promise<T>;
}

/** A message a person can act on; never a stack trace or a bare status code. */
export function friendlyError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status >= 500 || e.status === 0) return "We couldn't load this right now. Please try again in a minute.";
    return e.message;
  }
  if (e instanceof TypeError) return "We couldn't reach the service right now. Please try again in a minute.";
  return e instanceof Error ? e.message : "Something went wrong.";
}

async function request<T>(path: string, init: RequestInit = {}, runKey?: string): Promise<T> {
  if (MIRROR) throw new ApiError(400, NOT_IN_MIRROR);
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (runKey) headers.set("X-API-Key", runKey);
  headers.set("X-Requester", "web");
  const res = await fetch(BASE + path, { ...init, headers });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

// --- packs (public) ---------------------------------------------------------------
export const listPacks = () => MIRROR ? staticJson<FeaturedPack[]>("packs.json") : request<FeaturedPack[]>("/packs");
export const getPack = (packId: string) => MIRROR
  ? staticJson<ContextPack>(`packs/${encodeURIComponent(packId)}/context_pack.json`)
  : request<ContextPack>(`/packs/${encodeURIComponent(packId)}`);
export const getEvals = <T,>() => MIRROR ? staticJson<T>("evals.json") : request<T>("/evals");
export const getDigest = (packId: string) =>
  request<Record<string, unknown>>(`/packs/${encodeURIComponent(packId)}?view=digest`);
export const getItem = (packId: string, itemId: string, evidence = 3) =>
  request<ItemResult>(`/packs/${encodeURIComponent(packId)}/items/${encodeURIComponent(itemId)}?evidence=${evidence}`);
export const searchEvidence = (packId: string, q: string, opts: { platform?: string; language?: string } = {}) => {
  const params = new URLSearchParams({ q, ...opts });
  return request<EvidenceResult>(`/packs/${encodeURIComponent(packId)}/evidence?${params}`);
};
const MIRROR_FILES = { json: "context_pack.json", md: "brief.md", prompt: "prompt_block.txt", skill: "skill.zip" };
export const exportUrl = (packId: string, kind: "json" | "md" | "prompt" | "skill") => MIRROR
  ? `${DATA}/packs/${encodeURIComponent(packId)}/${MIRROR_FILES[kind]}`
  : `${BASE}/packs/${encodeURIComponent(packId)}/export/${kind}`;

export interface Estimate { mode: string; max_usd: number; typical_usd_low: number; typical_usd_high: number;
  typical_minutes: number; collection_secs: number; max_tool_calls: number }
export interface Options { modes: Record<"quick" | "standard", Estimate>; default_mode: "quick" | "standard";
  time_window_days_options: number[]; default_time_window_days: number; brand_voice_max_chars: number;
  languages: Record<string, string>; max_languages: Record<"quick" | "standard", number> }
export const getOptions = () => request<Options>("/options");

export interface PlanUnit { platform: string; kind: string; target: string; reason: string; enabled: boolean;
  queries: { language: string; query: string }[] }
export interface Plan { hypotheses: { id: string; statement: string }[];
  research_questions: { id: string; text: string }[]; starting_units: PlanUnit[] }

// --- runs (the run key is required to create, answer, start and stop) -----------------
export const createRun = (runKey: string, body: { brief: string; mode: "quick" | "standard";
  time_window_days?: number; brand_voice?: string; auto_approve?: boolean; intake?: IntakeData }) =>
  request<RunStatus>("/runs", { method: "POST", body: JSON.stringify(body) }, runKey);
export const answerQuestions = (runKey: string, runId: string, body: { answers: QuestionAnswer[]; skip_all?: boolean }) =>
  request<RunStatus>(`/runs/${runId}/answer`, { method: "POST", body: JSON.stringify(body) }, runKey);
export const replanRun = (runKey: string, runId: string, edits: PlanEdits) =>
  request<RunStatus>(`/runs/${runId}/replan`, { method: "POST", body: JSON.stringify(edits) }, runKey);
export const startRun = (runKey: string, runId: string,
  body: { disabled_units?: number[]; removed_questions?: string[] } = {}) =>
  request<RunStatus>(`/runs/${runId}/start`, { method: "POST", body: JSON.stringify(body) }, runKey);
export const stopRun = (runKey: string, runId: string) =>
  request<RunStatus>(`/runs/${runId}/stop`, { method: "POST" }, runKey);
export const getRun = (runId: string) => request<RunStatus>(`/runs/${runId}`);
export const getPackInputs = (packId: string) => request<RunInputs>(`/packs/${encodeURIComponent(packId)}/inputs`);

// --- owner views (the main run key only; the guest key is refused) ----------------
export interface OwnerRun { run_id: string; brief: string; mode: string; status: string; requester: string;
  created_at: string; pack_id: string | null; tool_calls: number; apify_usd: number; anthropic_usd: number;
  anthropic_analysis_usd: number; total_usd: number }
export interface OwnerRuns { runs: OwnerRun[]; listed_total_usd: number; today: { spent_usd: number; cap_usd: number } }
export interface OwnerRunCost extends OwnerRun {
  breakdown: { supplier: string; item: string; calls: number; usd: number }[] }
export const getOwnerRuns = (runKey: string) => request<OwnerRuns>("/owner/runs?limit=100", {}, runKey);
export const getOwnerRunCost = (runKey: string, runId: string) =>
  request<OwnerRunCost>(`/owner/runs/${encodeURIComponent(runId)}`, {}, runKey);
export const runEventsUrl = (runId: string) => `${BASE}/runs/${runId}/events`;
