// HANDOFF (guide Step 4.4): for AI tools, for your team, for agents. The run key is never shown:
// the MCP command uses the <YOUR_KEY> placeholder.
import { useEffect, useRef, useState } from "react";
import { Bot, Check, Copy, Download, FileText, Printer, Users, X } from "lucide-react";
import { exportUrl, LIVE_URL, MIRROR } from "../lib/api";
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

function Action({ icon: Icon, label, hint, run, href, download }: {
  icon: typeof Copy; label: string; hint?: string; run?: () => Promise<void> | void; href?: string; download?: boolean;
}) {
  const [state, setState] = useState<"idle" | "done" | "error">("idle");
  const click = async () => {
    try { await run?.(); setState("done"); setTimeout(() => setState("idle"), 1800); } catch { setState("error"); }
  };
  const body = (
    <>
      <span className="flex items-center gap-2 text-sm font-medium text-ink">
        {state === "done" ? <Check aria-hidden="true" size={15} /> : <Icon aria-hidden="true" size={15} />}
        <span aria-live="polite">{state === "done" ? "Done" : state === "error" ? "Could not copy - try again" : label}</span>
      </span>
      {hint && <span className="mt-0.5 block text-xs text-ink-3">{hint}</span>}
    </>
  );
  const cls = "block w-full rounded-lg border border-line p-3 text-left hover:border-ink";
  return href
    ? <a href={href} download={download} className={cls}>{body}</a>
    : <button type="button" onClick={click} className={cls}>{body}</button>;
}

function Group({ icon: Icon, title, children }: { icon: typeof Copy; title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-3">
        <Icon aria-hidden="true" size={14} />{title}
      </h3>
      <div className="space-y-2">{children}</div>
    </section>
  );
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

export function Handoff({ packId, open, onClose }: { packId: string; open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  const mcp = `${MIRROR ? LIVE_URL : window.location.origin}/mcp`;  // the mirror has no server
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="handoff-title"
            className="m-auto w-full max-w-2xl rounded-xl border border-line bg-paper p-0 text-ink backdrop:bg-ink/30">
      <header className="flex items-center justify-between border-b border-line px-5 py-3">
        <h2 id="handoff-title" className="text-lg font-semibold">Hand this pack off</h2>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-ink-2 hover:text-ink">
          <X aria-hidden="true" size={18} />
        </button>
      </header>
      <div className="grid gap-6 p-5 md:grid-cols-3">
        <Group icon={Bot} title="For AI tools">
          <Action icon={Copy} label="Copy prompt block" hint="Paste into ChatGPT, Claude or any AI tool before you ask."
                  run={() => copyText(exportUrl(packId, "prompt"))} />
          <Action icon={Download} label="Download skill" href={exportUrl(packId, "skill")} download
                  hint="claude.ai: Settings → Features → upload the zip. Claude Code: unzip into ~/.claude/skills/." />
        </Group>
        <Group icon={Users} title="For your team">
          <Action icon={Printer} label="Print / Save as PDF" hint="A clean printable brief." run={() => { onClose(); setTimeout(() => window.print(), 50); }} />
          <Action icon={FileText} label="Copy for Notion / Docs" hint="Pastes with headings, lists and tables."
                  run={() => copyRich(exportUrl(packId, "md"))} />
        </Group>
        <Group icon={Download} title="For agents">
          <Action icon={Download} label="Download JSON" href={exportUrl(packId, "json")} download hint="context_pack.json, schema 1.0" />
          <p className="text-xs text-ink-2">Connect Claude Code (read-only, no key needed):</p>
          <CommandLine text={`claude mcp add --transport http signal ${mcp}`} />
          <p className="text-xs text-ink-2">To also start research, add your run key:</p>
          <CommandLine text={`claude mcp add --transport http signal ${mcp} --header "X-API-Key: <YOUR_KEY>"`} />
        </Group>
      </div>
    </dialog>
  );
}
