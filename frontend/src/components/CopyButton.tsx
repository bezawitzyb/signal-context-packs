import { useState } from "react";
import { Check, Copy } from "lucide-react";

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: nothing to do */
    }
  };
  return (
    <button type="button" onClick={copy}
            className="inline-flex shrink-0 items-center gap-1 rounded border border-line px-1.5 py-0.5 text-xs text-ink-2 hover:border-line-strong hover:text-ink">
      {copied ? <Check aria-hidden="true" size={13} /> : <Copy aria-hidden="true" size={13} />}
      <span aria-live="polite">{copied ? "Copied" : label}</span>
    </button>
  );
}
