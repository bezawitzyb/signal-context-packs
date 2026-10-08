// Turns a run's event list (live SSE or a pack's saved events) into what the Theatre shows.
import type { RunEvent } from "./useRunEvents";

export const STEPS = [
  { key: "plan", label: "Plan", stages: [] as string[] },
  { key: "collect", label: "Collect", stages: ["collecting"] },
  { key: "process", label: "Process", stages: ["extracting", "clustering"] },
  { key: "write", label: "Write", stages: ["writing"] },
  { key: "verify", label: "Verify", stages: ["verifying"] },
  { key: "pack", label: "Pack", stages: ["packaging"] },
];

export interface Move {
  seq: number;
  tool: string;
  sourceUnit: string | null;
  reason: string;
  gapFill: boolean; // made after a coverage check: filling an under-served question
  result?: { collected: number; kept: number; relevantShare: number; newTerms: string[]; status: string };
}

export interface Summary {
  step: number; // index in STEPS reached so far (0 = plan)
  moves: Move[];
  counters: Record<string, number> | null;
  cost: { apify_usd: number; llm_usd: number } | null;
  queue: { position: number; estimated_start_secs: number } | null;
  coverage: { id: string; text: string; docs: number }[];
  fallbacks: { kind: string; reason: string }[];
  errors: { message: string; recoverable: boolean }[];
  packId: string | null;
  milestones: string[];
}

const TOOL_WORDS: Record<string, string> = {
  search_reddit: "Search Reddit", search_tiktok: "Search TikTok", search_youtube: "Search YouTube",
  search_instagram: "Search Instagram", search_linkedin: "Search LinkedIn", search_x: "Search X",
  web_search: "Search the web", fetch_and_segment: "Read pages",
  get_trends: "Check Google Trends", coverage_report: "Check coverage", finish: "Finish collecting",
};
export const toolWords = (tool: string) => TOOL_WORDS[tool] ?? tool.replace(/_/g, " ");

export function summarize(events: RunEvent[]): Summary {
  const s: Summary = { step: 0, moves: [], counters: null, cost: null, queue: null, coverage: [], fallbacks: [],
    errors: [], packId: null, milestones: [] };
  const bySeq = new Map<number, Move>();
  let coverageSeen = false;
  for (const e of events) {
    const p = e.payload as Record<string, any>;
    switch (e.type) {
      case "stage": {
        const idx = STEPS.findIndex((st) => st.stages.includes(p.stage));
        if (idx > s.step) {
          s.step = idx;
          s.milestones.push(`${STEPS[idx].label} started`);
        }
        s.queue = null;
        break;
      }
      case "queue": s.queue = { position: p.position, estimated_start_secs: p.estimated_start_secs }; break;
      case "agent_call": {
        const m: Move = { seq: p.seq, tool: p.tool, sourceUnit: p.source_unit ?? null, reason: p.reason ?? "",
          gapFill: coverageSeen && !["coverage_report", "finish"].includes(p.tool) };
        bySeq.set(m.seq, m);
        s.moves.push(m);
        break;
      }
      case "agent_result": {
        const m = bySeq.get(p.seq);
        if (m) m.result = { collected: p.collected ?? 0, kept: p.kept ?? 0, relevantShare: p.relevant_share ?? 0,
          newTerms: p.new_terms ?? [], status: p.status ?? "ok" };
        break;
      }
      case "coverage": coverageSeen = true; s.coverage = p.questions ?? []; break;
      case "counters": s.counters = p as Record<string, number>; break;
      case "cost": s.cost = { apify_usd: p.apify_usd ?? 0, llm_usd: p.llm_usd ?? 0 }; break;
      case "fallback":
        s.fallbacks.push({ kind: p.kind, reason: p.reason });
        s.milestones.push(p.kind === "top_up" ? "Collecting more from sources that work"
          : p.kind === "evidence_only" ? "Building a pack from the collected posts" : "Collecting the remaining planned sources");
        break;
      case "error": s.errors.push({ message: p.message, recoverable: Boolean(p.recoverable) }); break;
      case "pack_ready": s.packId = p.pack_id; s.step = STEPS.length; s.milestones.push("The pack is ready"); break;
    }
  }
  return s;
}
