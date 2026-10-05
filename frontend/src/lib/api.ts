// Typed client for /api/v1 (PRD 11.1). The run key is passed in per call as the X-API-Key header;
// this file never stores, logs or shows it.
import type {
  ConfidenceLabel,
  ContextPack10,
  Evidence1,
  Interpretation,
} from "./types";

/** The API always sends every field (the backend dumps defaults too), so responses are fully present. */
type DeepRequired<T> = T extends (infer U)[] ? DeepRequired<U>[]
  : T extends object ? { [K in keyof T]-?: DeepRequired<T[K]> } : T;

export type ContextPack = DeepRequired<ContextPack10>;
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
  clarifying_question: { question: string; options: string[] } | null;
  estimate: Estimate;
}

export interface ItemResult { pack_id: string; item: Record<string, unknown>; evidence: Evidence[]; note: string }
export interface EvidenceResult { pack_id: string; total: number; evidence: Evidence[]; note: string }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const BASE = "/api/v1";

async function request<T>(path: string, init: RequestInit = {}, runKey?: string): Promise<T> {
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
export const listPacks = () => request<FeaturedPack[]>("/packs");
export const getPack = (packId: string) => request<ContextPack>(`/packs/${encodeURIComponent(packId)}`);
export const getDigest = (packId: string) =>
  request<Record<string, unknown>>(`/packs/${encodeURIComponent(packId)}?view=digest`);
export const getItem = (packId: string, itemId: string, evidence = 3) =>
  request<ItemResult>(`/packs/${encodeURIComponent(packId)}/items/${encodeURIComponent(itemId)}?evidence=${evidence}`);
export const searchEvidence = (packId: string, q: string, opts: { platform?: string; language?: string } = {}) => {
  const params = new URLSearchParams({ q, ...opts });
  return request<EvidenceResult>(`/packs/${encodeURIComponent(packId)}/evidence?${params}`);
};
export const exportUrl = (packId: string, kind: "json" | "md" | "prompt" | "skill") =>
  `${BASE}/packs/${encodeURIComponent(packId)}/export/${kind}`;

export interface Estimate { mode: string; max_usd: number; typical_usd_low: number; typical_usd_high: number;
  typical_minutes: number; collection_secs: number; max_tool_calls: number }
export interface Options { modes: Record<"quick" | "standard", Estimate>; default_mode: "quick" | "standard";
  time_window_days_options: number[]; default_time_window_days: number; brand_voice_max_chars: number }
export const getOptions = () => request<Options>("/options");

export interface PlanUnit { platform: string; kind: string; target: string; reason: string; enabled: boolean;
  queries: { language: string; query: string }[] }
export interface Plan { hypotheses: { id: string; statement: string }[];
  research_questions: { id: string; text: string }[]; starting_units: PlanUnit[] }

// --- runs (the run key is required to create, answer, start and stop) -----------------
export const createRun = (runKey: string, body: { brief: string; mode: "quick" | "standard";
  time_window_days?: number; brand_voice?: string; auto_approve?: boolean }) =>
  request<RunStatus>("/runs", { method: "POST", body: JSON.stringify(body) }, runKey);
export const answerQuestion = (runKey: string, runId: string, answer: string) =>
  request<RunStatus>(`/runs/${runId}/answer`, { method: "POST", body: JSON.stringify({ answer }) }, runKey);
export const startRun = (runKey: string, runId: string,
  body: { disabled_units?: number[]; removed_questions?: string[] } = {}) =>
  request<RunStatus>(`/runs/${runId}/start`, { method: "POST", body: JSON.stringify(body) }, runKey);
export const stopRun = (runKey: string, runId: string) =>
  request<RunStatus>(`/runs/${runId}/stop`, { method: "POST" }, runKey);
export const getRun = (runId: string) => request<RunStatus>(`/runs/${runId}`);
export const runEventsUrl = (runId: string) => `${BASE}/runs/${runId}/events`;
