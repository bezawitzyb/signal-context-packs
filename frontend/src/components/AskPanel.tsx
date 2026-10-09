// V10 "Ask this pack": a side panel. Answers come from this pack only; citations show as small numbered
// links that open the source post. Suggested questions are built from the pack in code (no extra call).
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Loader2, MessageCircleQuestion, X } from "lucide-react";
import { askPack, friendlyError, MIRROR, type AskAnswer, type AskTurn, type ContextPack } from "../lib/api";
import { readRunKey, saveRunKey } from "../lib/runKey";
import { safeUrl } from "../lib/safe";
import { CHANNEL } from "./plan";

const FORMAT: Record<string, string> = { text_post: "text post", carousel: "carousel", short_video: "short video",
  blog_article: "blog article", newsletter: "newsletter" };

/** Four questions this pack can answer, from its own content. */
export function suggestedQuestions(pack: ContextPack): string[] {
  const who = pack.brief.intake?.audience_roles?.[0] || "they";
  const brief = pack.post_briefs?.[0];
  const out = [
    brief ? `Turn the first post brief into a ${CHANNEL[brief.channel] ?? brief.channel} ${FORMAT[brief.format] ?? brief.format} outline`
      : "Write three post ideas from the strongest finding",
    `How do ${who} describe their biggest pain point?`,
    pack.objections.length ? "What is their strongest objection, and how should we answer it?"
      : "What holds them back, in their own words?",
    pack.tensions.length ? "Where do they want one thing but do another?" : "What should we never say to them?",
  ];
  return out.slice(0, 4);
}

function AnswerText({ a }: { a: AskAnswer }) {
  const parts = a.answer.split(/(\[\d+\])/g);
  const byN = Object.fromEntries(a.citations.map((c) => [c.n, c]));
  return (
    <div className="space-y-2">
      <p className="whitespace-pre-wrap text-sm text-ink">
        {parts.map((part, i) => {
          const m = part.match(/^\[(\d+)\]$/);
          const c = m ? byN[Number(m[1])] : undefined;
          if (!c) return <span key={i}>{part}</span>;
          const url = safeUrl(c.url);
          return url
            ? <a key={i} href={url} target="_blank" rel="noopener noreferrer nofollow" title={c.label}
                 className="mx-0.5 align-super text-[0.7rem] text-ink-2 underline">{c.n}</a>
            : <sup key={i} title={c.label} className="mx-0.5 text-[0.7rem] text-ink-3">{c.n}</sup>;
        })}
      </p>
      {a.citations.length > 0 && (
        <ol className="space-y-0.5 border-t border-line pt-2 text-xs text-ink-3">
          {a.citations.map((c) => {
            const url = safeUrl(c.url);
            return (
              <li key={c.n} className="truncate">{c.n}.{" "}
                {url ? <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="underline">
                  {c.kind === "post" ? `Post on ${CHANNEL[c.platform ?? ""] ?? c.platform}${c.date ? `, ${c.date}` : ""}` : c.label}</a>
                  : c.label}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

export function AskPanel({ pack, open, onClose }: { pack: ContextPack; open: boolean; onClose: () => void }) {
  const [turns, setTurns] = useState<{ q: string; a?: AskAnswer; error?: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [hasKey, setHasKey] = useState(() => readRunKey() !== "");
  const keyInput = useRef<HTMLInputElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open, onClose]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [turns]);
  if (!open) return null;

  const send = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    const history: AskTurn[] = turns.flatMap((t) => t.a
      ? [{ role: "user" as const, text: t.q }, { role: "assistant" as const, text: t.a.answer }] : []);
    setTurns((all) => [...all, { q }]);
    if (input.current) input.current.value = "";
    setBusy(true);
    try {
      const a = await askPack(pack.pack_id, q, history, readRunKey());
      setTurns((all) => all.map((t, i) => i === all.length - 1 ? { ...t, a } : t));
    } catch (e) {
      setTurns((all) => all.map((t, i) => i === all.length - 1 ? { ...t, error: friendlyError(e) } : t));
    } finally { setBusy(false); }
  };
  const last = [...turns].reverse().find((t) => t.a)?.a;
  const keyed = MIRROR || hasKey;   // asking needs a key (2026-10-09); users only ever hear "access key"

  return (
    <aside aria-label="Ask this pack"
           className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-line bg-paper shadow-xl sm:w-[28rem] print:hidden">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
          <MessageCircleQuestion aria-hidden="true" size={18} /> Ask this pack</h2>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-ink-2 hover:text-ink">
          <X aria-hidden="true" size={18} /></button>
      </header>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        <p className="text-xs text-ink-3">Answers use only this pack's research. Numbers open the real posts.</p>
        {MIRROR && <p className="rounded-lg border border-line bg-wash p-3 text-sm text-ink-2">Asking works on the live app; this read-only copy has no server.</p>}
        {!keyed && (
          <form className="space-y-2 rounded-lg border border-line-strong bg-wash p-3 text-sm text-ink"
                onSubmit={(e) => { e.preventDefault(); const k = keyInput.current?.value.trim() ?? "";
                                   if (k) { saveRunKey(k); setHasKey(true); } }}>
            <p role="status">Asking needs an access key.</p>
            <label htmlFor="ask-key" className="sr-only">Access key</label>
            <div className="flex gap-2">
              <input id="ask-key" ref={keyInput} type="password" autoComplete="off" spellCheck={false}
                     placeholder="Access key" className="min-w-0 flex-1 rounded-lg border border-line bg-paper px-3 py-1.5 font-mono text-sm" />
              <button type="submit" className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-ink hover:brightness-95">Use key</button>
            </div>
            <p className="text-xs text-ink-2">It stays in this browser tab only. No key? Everything in this pack stays
              open to read.</p>
          </form>
        )}
        {turns.length === 0 && !MIRROR && keyed && (
          <ul className="space-y-2" aria-label="Suggested questions">
            {suggestedQuestions(pack).map((q) => (
              <li key={q}><button type="button" onClick={() => send(q)}
                                  className="w-full rounded-lg border border-line p-2.5 text-left text-sm text-ink hover:border-ink">{q}</button></li>
            ))}
          </ul>
        )}
        {turns.map((t, i) => (
          <div key={i} className="space-y-2">
            <p className="ml-8 rounded-lg bg-wash px-3 py-2 text-sm text-ink">{t.q}</p>
            {t.a ? <AnswerText a={t.a} />
              : t.error ? <p role="alert" className="rounded-lg border border-line-strong p-3 text-sm text-ink">{t.error}</p>
              : <p className="flex items-center gap-2 text-sm text-ink-3"><Loader2 aria-hidden="true" size={14} className="animate-spin" /> Reading the pack…</p>}
          </div>
        ))}
        <div ref={end} />
      </div>
      {!MIRROR && keyed && (
        <form className="border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); send(input.current?.value ?? ""); }}>
          <label htmlFor="ask-input" className="sr-only">Your question about this pack</label>
          <div className="flex items-end gap-2">
            <textarea id="ask-input" ref={input} rows={2} maxLength={500} placeholder="Ask about their words, pains, objections or the plan…"
                      onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(e.currentTarget.value); } }}
                      className="min-h-[2.75rem] flex-1 resize-none rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink placeholder:text-ink-3" />
            <button type="submit" disabled={busy} aria-label="Ask"
                    className="rounded-lg bg-ink p-2.5 text-paper disabled:opacity-50"><ArrowUp aria-hidden="true" size={16} /></button>
          </div>
          {last?.questions_left_today != null && (
            <p className="mt-1 text-xs text-ink-3">{last.questions_left_today} questions left today.</p>
          )}
        </form>
      )}
    </aside>
  );
}
