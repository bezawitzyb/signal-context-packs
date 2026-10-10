// HANDOFF (guide Step 4.4, V9): options written for marketers - purpose, length and preview from the API. The run key is never shown:
// the MCP command uses the <YOUR_KEY> placeholder.
import { useEffect, useRef, useState } from "react";
import { Bot, Braces, CalendarDays, Check, Copy, Download, ExternalLink, FileText, Link2, Printer, X } from "lucide-react";
import { exportUrl, getHandoff, LIVE_URL, MIRROR, type ExportKind, type HandoffOption } from "../lib/api";
import { markdownToHtml } from "../lib/markdown";

async function copyText(url: string): Promise<void> {
  const text = await (await fetch(url)).text();
  await navigator.clipboard.writeText(text);
}

async function copyRich(url: string): Promise<void> {
  const md = await (await fetch(url)).text();
  const html = `<meta charset="utf-8">${markdownToHtml(md)}`;
  if ("ClipboardItem" in window) {
    await navigator.clipboard.write([new ClipboardItem({
      "text/plain": new Blob([md], { type: "text/plain" }),
      "text/html": new Blob([html], { type: "text/html" }),
    })]);
  } else {
    await navigator.clipboard.writeText(md);
  }
}

function CommandLine({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-line bg-wash p-2">
      <code className="flex-1 break-all font-mono text-[0.72rem] text-ink">{text}</code>
      <button type="button" aria-label="Copy command" onClick={async () => {
        await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}
        className="shrink-0 rounded p-1 text-ink-2 hover:text-ink">
        {done ? <Check aria-hidden="true" size={14} /> : <Copy aria-hidden="true" size={14} />}
      </button>
    </div>
  );
}

const TOAST: Partial<Record<ExportKind, string>> = {
  quick: "Quick brief copied - paste it into your AI tool",
  prompt: "Brief for your AI writer copied - paste it into your AI tool",
  md: "Full report copied - paste it into Notion or Google Docs",
};
const ICON: Record<ExportKind, typeof Copy> = { quick: Bot, prompt: Bot, md: FileText, calendar: CalendarDays,
  skill: Download, json: Braces };

/** V9: one hand-off option - what it is for, how long it is, and a one-line preview. */
function Option({ packId, o, onToast }: { packId: string; o: HandoffOption; onToast: (t: string) => void }) {
  const [error, setError] = useState(false);
  const Icon = ICON[o.kind];
  const body = (
    <>
      <span className="flex flex-wrap items-center gap-x-2 text-sm font-medium text-ink"><Icon aria-hidden="true" size={15} />{o.title}
        {/* UX audit: say what a click does */}
        <span className="ml-auto whitespace-nowrap font-normal text-xs text-ink-3">{o.length} · {o.action === "download" ? "downloads" : "copies"}</span></span>
      <span className="mt-0.5 block text-sm text-ink-2">{error ? "Could not copy - try again" : o.purpose}</span>
      {o.preview && <span className="mt-1 block truncate text-xs text-ink-3">{o.preview}</span>}
    </>
  );
  const cls = `block w-full rounded-lg border p-3 text-left hover:border-ink ${o.more ? "border-dashed border-line" : "border-line"}`;
  if (o.length.startsWith("no ")) {  // UX audit: nothing to export (e.g. no post ideas) - shown, but clearly unavailable
    return <div aria-disabled="true" className="block w-full rounded-lg border border-dashed border-line p-3 text-left opacity-60">{body}</div>;
  }
  if (o.action === "download") {
    return <a href={exportUrl(packId, o.kind)} download className={cls}
              onClick={() => onToast(`${o.title} downloading`)}>{body}</a>;
  }
  const copy = async () => {
    try {
      await (o.kind === "md" ? copyRich : copyText)(exportUrl(packId, o.kind));
      setError(false);
      onToast(TOAST[o.kind] ?? `${o.title} copied`);
    } catch { setError(true); }
  };
  return <button type="button" onClick={copy} className={cls}>{body}</button>;
}

export function Handoff({ packId, open, onClose }: { packId: string; open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [options, setOptions] = useState<HandoffOption[] | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
    if (open && !options) getHandoff(packId).then(setOptions).catch(() => setOptions([]));
  }, [open, options, packId]);
  const say = (t: string) => { setToast(t); setTimeout(() => setToast(null), 2600); };
  const mcp = `${MIRROR ? LIVE_URL : window.location.origin}/mcp`;  // the mirror has no server
  const main = (options ?? []).filter((o) => !o.more);
  const more = (options ?? []).filter((o) => o.more);
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="handoff-title"
            className="m-auto w-full max-w-2xl rounded-xl border border-line bg-paper p-0 text-ink backdrop:bg-ink/30">
      <header className="flex items-center justify-between border-b border-line px-5 py-3">
        <h2 id="handoff-title" className="text-lg font-semibold">Share &amp; export</h2>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-ink-2 hover:text-ink">
          <X aria-hidden="true" size={18} />
        </button>
      </header>
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-ink p-3">
          <span className="flex min-w-0 flex-1 items-center gap-2 text-sm text-ink"><Link2 aria-hidden="true" size={15} />
            <span><span className="font-medium">Link to this pack</span>
              <span className="block text-ink-2">Anyone with the link can read it. No key needed.</span></span></span>
          <button type="button" onClick={() => {
                    const url = window.location.href.split("#")[0];
                    navigator.clipboard.writeText(url).then(() => say("Link copied"), () => say("Could not copy - copy the address bar instead"));
                  }}
                  className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-ink hover:brightness-95">Copy link</button>
        </div>
        {options === null && <p className="text-sm text-ink-3">Loading the options…</p>}
        <div className="grid gap-2 sm:grid-cols-2">
          {main.map((o) => <Option key={o.kind} packId={packId} o={o} onToast={say} />)}
          <button type="button" onClick={() => { onClose(); setTimeout(() => window.print(), 50); }}
                  className="block w-full rounded-lg border border-line p-3 text-left hover:border-ink">
            <span className="flex flex-wrap items-center gap-x-2 text-sm font-medium text-ink"><Printer aria-hidden="true" size={15} />Print / Save as PDF
              <span className="ml-auto whitespace-nowrap font-normal text-xs text-ink-3">summary first · opens print</span></span>
            <span className="mt-0.5 block text-sm text-ink-2">A clean printable report: the one-page summary, then the rest.</span>
          </button>
        </div>
        {more.length > 0 && (
          <details className="rounded-lg border border-line p-3">
            <summary className="cursor-pointer text-sm text-ink-2">More: Claude and developers</summary>
            <div className="mt-3 space-y-2">
              {more.map((o) => <Option key={o.kind} packId={packId} o={o} onToast={say} />)}
              <p className="text-xs text-ink-2">Programs can also read packs directly:{" "}
                <a href={`${MIRROR ? LIVE_URL : ""}/docs`} target="_blank" rel="noopener noreferrer"
                   className="inline-flex items-center gap-1 text-ink underline">API docs <ExternalLink aria-hidden="true" size={11} /></a></p>
              <p className="text-xs text-ink-2">Connect Claude Code (read-only, no key needed):</p>
              <CommandLine text={`claude mcp add --transport http signal ${mcp}`} />
              <p className="text-xs text-ink-2">To also start research, add your access key:</p>
              <CommandLine text={`claude mcp add --transport http signal ${mcp} --header "X-API-Key: <YOUR_KEY>"`} />
            </div>
          </details>
        )}
      </div>
      <p role="status" aria-live="polite"
         className={`mx-5 mb-4 rounded-lg bg-ink px-3 py-2 text-sm text-paper ${toast ? "" : "sr-only"}`}>{toast ?? ""}</p>
    </dialog>
  );
}
