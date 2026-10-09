// Source units in plain words for marketers (UX audit); the technical unit stays in a tooltip.
/** "reddit:r/MealPrepSunday" -> "r/MealPrepSunday on Reddit"; 'web:search:x' -> 'Web search: "x"'. */
export function unitWords(unit: string): string {
  const [platform, ...rest] = unit.split(":");
  const target = rest.join(":");
  const name: Record<string, string> = { reddit: "Reddit", tiktok: "TikTok", youtube: "YouTube", instagram: "Instagram",
    linkedin: "LinkedIn", x: "X", facebook: "Facebook", web: "the web", trends: "Google Trends" };
  if (target.startsWith("search:")) return `${platform === "web" ? "Web" : name[platform] ?? platform} search: "${target.slice(7)}"`;
  if (platform === "web") return target;
  return target ? `${target} on ${name[platform] ?? platform}` : (name[platform] ?? unit);
}
