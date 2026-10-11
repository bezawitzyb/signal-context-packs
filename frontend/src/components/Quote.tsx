// THEIR WORDS: a real post, in serif, with its language set; machine metadata in mono.
// Original / translated toggle; a link to the source (text-fragment link when we have one).
import { useState } from "react";
import { ExternalLink, Languages } from "lucide-react";
import type { Evidence } from "../lib/api";
import { safeUrl } from "../lib/safe";
import { platformName, unitWords } from "../lib/unitWords";

export function Quote({ text, evidence, size = "md", translation, details = true }: {
  text: string; evidence?: Evidence; size?: "sm" | "md";
  translation?: string | null;   // the quoted words' own translation (Summary); else the whole post's
  details?: boolean;             // false: the caption is only the English / original button (Summary)
}) {
  const [english, setEnglish] = useState(false);
  const lang = evidence?.language && evidence.language !== "und" ? evidence.language : undefined;
  const english_text = translation || evidence?.text_en;
  const canTranslate = Boolean(english_text) && lang !== "en";
  // owner 2026-10-11 (choice B): every quote translates the same way, with an English / original button
  const shown = english && english_text ? english_text : text;
  const link = safeUrl(evidence?.text_fragment_url) || safeUrl(evidence?.url);
  return (
    <figure className="border-l-2 border-line-strong pl-3">
      <blockquote
        lang={english ? "en" : lang}
        className={`t-quote font-serif italic text-ink ${size === "sm" ? "text-[1.0625rem]" : "text-[1.125rem]"} leading-relaxed`}
      >
        “{shown}”
      </blockquote>
      {evidence && !details && canTranslate && (
        <figcaption className="t-meta mt-1 text-xs text-ink-3">
          <button type="button" onClick={() => setEnglish(!english)} aria-pressed={english}
                  className="inline-flex items-center gap-1 text-ink-2 underline-offset-2 hover:underline">
            <Languages aria-hidden="true" size={12} />{english ? "original" : "English"}
          </button>
        </figcaption>
      )}
      {evidence && details && (
        // UX audit: one short line (platform, date, language); where it was found is a tooltip, the id stays (same ids everywhere)
        <figcaption className="t-meta mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.72rem] text-ink-3">
          <span title={unitWords(evidence.source_unit)}>{platformName(evidence.platform)}</span>
          {evidence.posted_at && <span>{shortDate(evidence.posted_at)}</span>}
          {lang && <span className="font-mono uppercase">{lang}</span>}
          {evidence.redacted && <span title="Personal details were removed">redacted</span>}
          {evidence.requires_login && <span title="You may need to log in to LinkedIn to view this">login needed</span>}
          {canTranslate && (
            <button
              type="button"
              onClick={() => setEnglish(!english)}
              className="inline-flex items-center gap-1 rounded px-1 text-ink-2 underline-offset-2 hover:underline"
              aria-pressed={english}
            >
              <Languages aria-hidden="true" size={12} />
              {english ? "original" : "English"}
            </button>
          )}
          {link && (
            <a href={link} target="_blank" rel="noopener noreferrer nofollow" data-host={hostOf(link)}
               className="print-url inline-flex items-center gap-1 text-ink-2 underline-offset-2 hover:underline">
              source <ExternalLink aria-hidden="true" size={11} />
            </a>
          )}
          <span className="font-mono print:hidden">{evidence.id}</span>
        </figcaption>
      )}
    </figure>
  );
}

/** "2026-09-10" -> "10 Sep 2026"; anything else is shown as it is. */
function shortDate(d: string): string {
  const t = Date.parse(d.slice(0, 10));
  return Number.isNaN(t) ? d : new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** "https://www.youtube.com/watch?v=..." -> "youtube.com" (printed after "source" instead of the whole link). */
function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}
