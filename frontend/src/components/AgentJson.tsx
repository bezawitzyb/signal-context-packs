// VIEW AS AGENT: the section's JSON, same ids and schema version. Escaped before colouring (scraped text is data).
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function colour(json: string): string {
  return esc(json).replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (m, str: string | undefined, colon: string | undefined, lit: string | undefined, num: string | undefined) => {
      if (str) return colon ? `<span class="text-ink font-medium">${str}</span>${colon}` : `<span class="text-ink-2">${str}</span>`;
      if (lit) return `<span class="text-accent-ink">${lit}</span>`;
      if (num) return `<span class="text-accent-ink">${num}</span>`;
      return m;
    });
}

export function AgentJson({ name, data, schemaVersion }: { name: string; data: unknown; schemaVersion: string }) {
  // A list gets its section name; an object of several parts is shown as it is (no doubled wrapper).
  const json = JSON.stringify(Array.isArray(data) ? { [name]: data } : data, null, 2);
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <p className="border-b border-line bg-wash px-3 py-1.5 font-mono text-xs text-ink-3">
        context_pack.json · schema {schemaVersion} · {name}
      </p>
      <pre className="max-h-[32rem] overflow-auto p-3 font-mono text-[0.75rem] leading-relaxed text-ink"
           dangerouslySetInnerHTML={{ __html: colour(json) }} />
    </div>
  );
}
