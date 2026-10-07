// Lookups over one pack: any item by id, its evidence, and authors as "Author 1, 2..." (never a name).
import type { ContextPack, Evidence } from "./api";

export type AnyItem = Record<string, unknown> & { id: string };

export interface PackIndex {
  items: Map<string, AnyItem>;
  sectionOf: Map<string, string>;
  evidence: Record<string, Evidence>;
  authorNo: Map<string, number>;
}

export function indexPack(pack: ContextPack): PackIndex {
  const items = new Map<string, AnyItem>();
  const sectionOf = new Map<string, string>();
  const walk = (value: unknown, section: string) => {
    if (Array.isArray(value)) value.forEach((v) => walk(v, section));
    else if (value && typeof value === "object") {
      const obj = value as Record<string, unknown>;
      if (typeof obj.id === "string" && !obj.id.startsWith("EV-") && !items.has(obj.id)) {
        items.set(obj.id, obj as AnyItem);
        sectionOf.set(obj.id, section);
      }
      Object.values(obj).forEach((v) => walk(v, section));
    }
  };
  for (const [k, v] of Object.entries(pack)) {
    if (!["evidence", "events", "coverage", "brief"].includes(k)) walk(v, k);
  }
  const evidence = Object.fromEntries(pack.evidence.map((e) => [e.id, e])) as Record<string, Evidence>;
  const authorNo = new Map<string, number>();
  for (const e of pack.evidence) {
    if (e.author_hash && !authorNo.has(e.author_hash)) authorNo.set(e.author_hash, authorNo.size + 1);
  }
  return { items, sectionOf, evidence, authorNo };
}

/** Every evidence id an item cites (its list, its quotes, tension sides, a performing post). */
export function evidenceIdsOf(item: AnyItem): string[] {
  const ids: string[] = [];
  const add = (x: unknown) => { if (typeof x === "string" && !ids.includes(x)) ids.push(x); };
  ((item.evidence_ids as string[]) ?? []).forEach(add);
  ((item.quotes as { evidence_id: string }[]) ?? []).forEach((q) => add(q.evidence_id));
  for (const side of ["want", "but"]) {
    const s = item[side] as { evidence_ids?: string[] } | undefined;
    (s?.evidence_ids ?? []).forEach(add);
  }
  add(item.evidence_id);
  return ids;
}

/** "label · n of N posts" counts across the pack's claim sections. */
export function labelCounts(pack: ContextPack): Record<string, number> {
  const counts: Record<string, number> = { strong: 0, moderate: 0, emerging: 0, speculative: 0 };
  const lists: unknown[][] = [pack.landscape.themes, pack.pain_points ?? [], pack.tensions, pack.motivations,
    pack.objections, pack.segments, pack.opportunities, pack.moments, pack.voice.lexicon, pack.voice.phrases];
  for (const list of lists) for (const it of list as { confidence?: { label: string } }[]) {
    if (it.confidence) counts[it.confidence.label] = (counts[it.confidence.label] ?? 0) + 1;
  }
  return counts;
}
