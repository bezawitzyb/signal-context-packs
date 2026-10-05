// THEIR WORDS: a real post, in serif, with its language set; machine metadata in mono.
// Original / translated toggle; a link to the source (text-fragment link when we have one).
import { useState } from "react";
import { ExternalLink, Languages } from "lucide-react";
import type { Evidence } from "../lib/api";
import { safeUrl } from "../lib/safe";

export function Quote({ text, evidence, size = "md" }: {
  text: string; evidence?: Evidence; size?: "sm" | "md";
}) {
  const [english, setEnglish] = useState(false);
  const lang = evidence?.language && evidence.language !== "und" ? evidence.language : undefined;
  const canTranslate = Boolean(evidence?.text_en) && lang !== "en";
  // A quote is part of the post: when translated we show the whole post's translation.
  const shown = english && evidence?.text_en ? evidence.text_en : text;
  const link = safeUrl(evidence?.text_fragment_url) || safeUrl(evidence?.url);
  return (
    <figure className="border-l-2 border-line-strong pl-3">
      <blockquote
        lang={english ? "en" : lang}
        className={`font-serif text-ink ${size === "sm" ? "text-[0.95rem]" : "text-[1.05rem]"} leading-snug`}
      >
        “{shown}”
      </blockquote>
      {evidence && (
        <figcaption className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[0.72rem] text-ink-3">
          <span>{evidence.id}</span>
          <span>{evidence.platform}</span>
          <span className="max-w-[18rem] truncate" title={evidence.source_unit}>{evidence.source_unit}</span>
          {evidence.posted_at && <span>{evidence.posted_at}</span>}
          {lang && <span>{lang}</span>}
          {evidence.redacted && <span title="Personal details were removed">redacted</span>}
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
            <a href={link} target="_blank" rel="noopener noreferrer nofollow"
               className="inline-flex items-center gap-1 text-ink-2 underline-offset-2 hover:underline">
              source <ExternalLink aria-hidden="true" size={11} />
            </a>
          )}
        </figcaption>
      )}
    </figure>
  );
}
