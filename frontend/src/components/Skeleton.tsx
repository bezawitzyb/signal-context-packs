// Loading placeholders (PRD 10.4): grey blocks in the page's shape; still when reduced motion is on.
export function Skeleton({ lines = 3, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-3">
      <div className="h-7 w-2/3 rounded bg-wash motion-safe:animate-pulse" />
      {Array.from({ length: lines }, (_, n) => (
        <div key={n} className="h-20 rounded-lg border border-line bg-wash motion-safe:animate-pulse" />
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}
