// UX audit (2026-10-10): one post often backs several findings, so the same quote kept coming back across the
// page. Walking the page top to bottom, each card shows the first of ITS OWN quotes (then its other posts) that
// is not already on screen higher up; a repeat only when the card has nothing else. Display only: every quote
// is still the writer's exact quote or the post's own excerpt, and the drawer still lists every post.
import type { ContextPack } from "./api";

export interface Pick { evidence_id: string; text: string }
type Item = { id: string; quotes?: { evidence_id: string; text: string }[]; evidence_ids?: string[] };
type Side = { text: string; evidence_ids: string[] };

/** Pack items in the order their sections appear on the page (`order` = the pack's section order). */
function pageItems(pack: ContextPack, order: string[]): (Item | { id: string; want: Side; but: Side })[] {
  const p = pack as unknown as Record<string, unknown>;
  const list = (v: unknown) => (Array.isArray(v) ? v : []) as Item[];
  const culture = (p.culture ?? {}) as Record<string, unknown>;
  const bySection: Record<string, unknown[]> = {
    brand: list((p.brand_perception as { findings?: unknown } | undefined)?.findings),
    "want-stops": [...list(p.motivations), ...list(p.pain_points), ...list(p.objections), ...list(p.tensions)],
    segments: list(p.segments),
    landscape: [...list((p.landscape as { themes?: unknown } | undefined)?.themes), ...list(p.moments),
      ...list(culture.formats), ...list(culture.communities), ...list(culture.creators), ...list(culture.codes)],
  };
  return order.flatMap((id) => bySection[id] ?? []) as (Item | { id: string; want: Side; but: Side })[];
}

export function pickQuotes(pack: ContextPack, order: string[]): Record<string, Pick> {
  const ev = Object.fromEntries((pack.evidence ?? []).map((e) => [e.id, e.text]));
  const used = new Set<string>((pack.snapshot.findings ?? []).map((f) => f.quote?.evidence_id).filter(Boolean) as string[]);
  const out: Record<string, Pick> = {};
  const choose = (key: string, candidates: Pick[]) => {
    const pick = candidates.find((c) => !used.has(c.evidence_id)) ?? candidates[0];
    if (!pick) return;
    out[key] = pick;
    used.add(pick.evidence_id);
  };
  const posts = (ids: string[] = []) => ids.filter((id) => ev[id]).map((id) => ({ evidence_id: id, text: ev[id] }));
  for (const it of pageItems(pack, order)) {
    if ("want" in it && "but" in it) {   // a tension: each side shows one of its own posts
      choose(`${it.id}:want`, posts(it.want.evidence_ids));
      choose(`${it.id}:but`, posts(it.but.evidence_ids));
      continue;
    }
    const quotes = (it.quotes ?? []).filter((q) => ev[q.evidence_id] !== undefined);
    const quoted = new Set(quotes.map((q) => q.evidence_id));
    choose(it.id, [...quotes, ...posts((it.evidence_ids ?? []).filter((id) => !quoted.has(id)))]);
  }
  return out;
}
