// HOW PEOPLE SEE YOUR BRAND (change V12): numbers computed in code (mono = machine data), then the verified
// findings as claim cards with their strength in words (never colour only).
import type { ContextPack, InsightLike } from "../lib/api";
import { ItemSection } from "./blocks";

type BrandPerception = NonNullable<ContextPack["brand_perception"]>;

const pct = (x: number | null | undefined) => (x === null || x === undefined ? "-" : `${Math.round(x * 100)}%`);
const words = (s: string) => s.replace(/_/g, " ");

export function BrandPart({ bp }: { bp: BrandPerception }) {
  const own = bp.brands[0];
  return (
    <div className="space-y-4">
      {bp.note && <p className="text-sm text-ink-2">{bp.note}</p>}
      {bp.brands.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-left text-sm">
            <caption className="sr-only">Brand numbers, computed from the posts</caption>
            <thead className="text-xs uppercase tracking-wide text-ink-3">
              <tr><th className="py-1 pr-3 font-medium">Brand</th><th className="py-1 pr-3 font-medium">Posts</th>
                <th className="py-1 pr-3 font-medium" title="Found by a search that did not name the brand: people bringing it up unasked">Unasked</th>
                <th className="py-1 pr-3 font-medium" title="Of unasked posts naming any brand, the share naming this one">Share of voice</th>
                <th className="py-1 font-medium">How they feel</th></tr>
            </thead>
            <tbody>
              {bp.brands.map((b) => (
                <tr key={b.name} className="border-t border-line align-top">
                  <td className="py-1.5 pr-3 text-ink">{b.name}{b.is_parent && <span className="text-ink-3"> (parent)</span>}</td>
                  <td className="py-1.5 pr-3 font-mono text-ink">{b.mentions}</td>
                  <td className="py-1.5 pr-3 font-mono text-ink">{b.unprompted}</td>
                  <td className="py-1.5 pr-3 font-mono text-ink">{pct(b.share_of_voice)}</td>
                  <td className="py-1.5 font-mono text-xs text-ink-2">
                    {b.stance_mix.map((x) => `${x.stance} ${pct(x.share)}`).join(" · ") || "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {own && (own.aspects_praised.length > 0 || own.aspects_criticised.length > 0) && (
        <p className="text-sm text-ink-2">
          {own.aspects_praised.length > 0 && <>Praised: <span className="text-ink">{own.aspects_praised.join(", ")}</span>. </>}
          {own.aspects_criticised.length > 0 && <>Criticised: <span className="text-ink">{own.aspects_criticised.join(", ")}</span>.</>}
        </p>
      )}
      {own && own.relation_mix.length > 0 && (
        <p className="text-sm text-ink-2">
          Next to the parent brand ({own.with_parent} {own.with_parent === 1 ? "post names" : "posts name"} both):{" "}
          <span className="font-mono text-xs">{own.relation_mix.map((x) => `${words(x.relation)} ${pct(x.share)}`).join(" · ")}</span>
        </p>
      )}
      {bp.findings.length > 0 && (
        <ItemSection level={3} title="What people say about it" items={bp.findings as unknown as InsightLike[]} />
      )}
    </div>
  );
}
