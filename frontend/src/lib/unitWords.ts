// Source units in plain words for marketers (UX audit); the technical unit stays in a tooltip.
/** "reddit:r/MealPrepSunday" -> "r/MealPrepSunday on Reddit"; 'web:search:x' -> 'Web search: "x"'. */
export function unitWords(unit: string): string {
  const [platform, ...rest] = unit.split(":");
  const target = rest.join(":");
  const name: Record<string, string> = { reddit: "Reddit", tiktok: "TikTok", youtube: "YouTube", instagram: "Instagram",
    linkedin: "LinkedIn", x: "X", facebook: "Facebook", web: "the web", trends: "Google Trends" };
  if (target.startsWith("search:")) return `${platform === "web" ? "Web" : name[platform] ?? platform} search: "${target.slice(7)}"`;
  if (platform === "web") return target;
  if (platform === "facebook" && target.startsWith("group:")) return `Public Facebook group ${target.slice(6)}`;
  return target ? `${target} on ${name[platform] ?? platform}` : (name[platform] ?? unit);
}

const PLATFORM: Record<string, string> = { reddit: "Reddit", tiktok: "TikTok", youtube: "YouTube", instagram: "Instagram",
  linkedin: "LinkedIn", x: "X", facebook: "Facebook", web: "Web", web_forum: "Forums", blog: "Blog", newsletter: "Newsletter",
  web_review: "Review sites", web_editorial: "Articles", trends: "Google Trends" };
/** "web_review" -> "Review sites", "youtube" -> "YouTube": platform codes never reach a reader (UX audit). */
export function platformName(p: string): string {
  return PLATFORM[p] ?? (p.charAt(0).toUpperCase() + p.slice(1)).replace(/_/g, " ");
}
