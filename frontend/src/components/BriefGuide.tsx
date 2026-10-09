// "How to write a brief": the 5 things only the user knows, behind an info button, plus a template to fill in.
// The research finds everything else (competitors, channels, their words, pain points, timing).
import { Info, X } from "lucide-react";

export const BRIEF_TEMPLATE = [
  "GOALS (main first): ",
  "OFFER (and stage): ",
  "WHO (buyers / influencers / users): ",
  "MARKETS (most important first): ",
  "KEY QUESTION (and by when): ",
  "Optional - competitors to watch / channels we use: ",
].join("\n");

const PARTS: { title: string; what: string; why: string; good: string; vague: string }[] = [
  {
    title: "1. Goals - what will you use this research for?",
    what: "Pick one or more, most important first: content plan, campaign launch, positioning, product validation, "
      + "market entry, brand perception, sales, or just understand the audience. Add one line in your own words.",
    why: "Your goals decide what the pack focuses on. A positioning pack leads with your message and how you compare "
      + "with competitors; a content-plan pack leads with post ideas and a calendar.",
    good: "1) Positioning 2) Content plan - we need a clear message and 3 months of LinkedIn posts before launch.",
    vague: "Marketing.",
  },
  {
    title: "2. Offer - what do you sell, and how far along is it?",
    what: "The product or service in plain words, and its stage: idea, launching soon, or already selling.",
    why: "We look for the problems, doubts and objections that matter to your offer. The stage changes the advice: "
      + "at the idea stage you test demand; when it is live you win people over.",
    good: "Booking software for event venues; launching in January.",
    vague: "A SaaS platform.",
  },
  {
    title: "3. Who - whose conversations should we listen to?",
    what: "The people you need to reach, in your own words. If different people play different parts, name each: "
      + "who buys, who influences the decision, who uses it.",
    why: "The agent chooses where to listen based on who you name. Buyers, influencers and users often talk in "
      + "different places and use different words.",
    good: "Event managers at agencies who book venues (buyers); venue owners who list spaces (users).",
    vague: "Businesses.",
  },
  {
    title: "4. Markets - where are these people?",
    what: "Countries, regions or cities, most important first. Mention a language only if it is unusual "
      + "(for example, English-speaking expats in Germany).",
    why: "The market decides which languages we search in, which local communities we find, and the culture "
      + "section. The wrong market makes every finding less useful.",
    good: "Netherlands (Amsterdam first), then Belgium.",
    vague: "Europe - fine if you really mean all of it, but expect less local depth.",
  },
  {
    title: "5. Key question - what decision do you need to make, and by when?",
    what: "The question you most need answered, or the decision the research should help with, plus your deadline "
      + "or key date.",
    why: "It shapes what the research sets out to answer and how far back we look. The deadline decides which "
      + "news, seasons and moments the pack flags.",
    good: "How do planners shortlist venues, and what makes them trust a new platform? We launch in January; "
      + "Q4 is budget season.",
    vague: "What do people think?",
  },
];

export function BriefGuideButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open} aria-controls="brief-guide"
            className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
      <Info aria-hidden="true" size={15} /> How to write a brief
    </button>
  );
}

export function BriefGuide({ onClose }: { onClose: () => void }) {
  return (
    <section id="brief-guide" aria-labelledby="brief-guide-title"
             className="space-y-4 rounded-lg border border-line-strong bg-paper p-4 text-sm text-ink-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="brief-guide-title" className="text-base font-semibold text-ink">How to write a brief</h2>
          <p className="mt-1">
            A good brief tells us <span className="font-medium text-ink">5 things only you know</span>. The research
            finds the rest. Short, specific answers work best: one or two lines each.
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close the guide"
                className="shrink-0 rounded p-1 text-ink-3 hover:text-ink"><X aria-hidden="true" size={16} /></button>
      </div>
      {PARTS.map((p) => (
        <div key={p.title} className="space-y-1">
          <h3 className="font-medium text-ink">{p.title}</h3>
          <p><span className="font-medium text-ink">What to write:</span> {p.what}</p>
          <p><span className="font-medium text-ink">Why it matters:</span> {p.why}</p>
          <p><span className="font-medium text-ink">Good:</span> <em>"{p.good}"</em></p>
          <p><span className="font-medium text-ink">Too vague:</span> <em>"{p.vague}"</em></p>
        </div>
      ))}
      <div className="space-y-1">
        <h3 className="font-medium text-ink">Optional - add only if you already have them</h3>
        <ul className="list-disc space-y-1 pl-5">
          <li><span className="text-ink">Competitors to watch:</span> brands you want searched by name, even if
            people rarely mention them. The research finds the others.</li>
          <li><span className="text-ink">Channels you use:</span> your post ideas and calendar start there. The
            research suggests new ones.</li>
          <li><span className="text-ink">Your voice:</span> use the Brand voice field below. It shapes only hooks and
            post ideas, never what the research finds.</li>
        </ul>
      </div>
      <div className="space-y-1">
        <h3 className="font-medium text-ink">You don't need to tell us</h3>
        <p>
          Competitors, channels, hashtags, the audience's words, pain points, trends or timing - finding these is the
          research. If you have a guess, put it in your key question ("Is unclear pricing really their biggest
          frustration?") and the pack will show whether the posts support it.
        </p>
      </div>
    </section>
  );
}
