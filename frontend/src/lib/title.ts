// UX audit: a pack or run is named by a short title, never the whole brief. A one-line brief is already a good
// name ("Launching a snack brand in the Netherlands"); a long or templated brief is named by its topic.
const MAX = 90;

const looksLikeTemplate = (line: string) => /^[A-Z][A-Z /()-]+(\([^)]*\))?:/.test(line.trim());

export function packTitle(brief: string, topic?: string | null): string {
  const text = brief.trim();
  if (text && !text.includes("\n") && text.length <= MAX && !looksLikeTemplate(text)) return text;
  if (topic?.trim()) return topic.trim().charAt(0).toUpperCase() + topic.trim().slice(1);
  const first = text.split("\n").find((l) => l.trim() && !looksLikeTemplate(l))?.trim() ?? text;
  return first.length > MAX ? first.slice(0, MAX - 1).trimEnd() + "…" : first || "Your research";
}

/** The template's headings only ("GOALS (main first):" ...), with nothing written after them. */
export function isEmptyTemplate(brief: string): boolean {
  const lines = brief.split("\n").map((l) => l.trim()).filter(Boolean);
  return lines.length > 0 && lines.every((l) => /^[^:]{1,60}:\s*$/.test(l));
}
