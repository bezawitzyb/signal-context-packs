// UX audit: text shortened to fit the first screen is never lost - a "more" link appears only when a line
// is actually cut (tooltips do not work on phones or with a keyboard), and print always shows everything.
import { type ReactNode, useLayoutEffect, useRef, useState } from "react";

const cutOff = (el: HTMLElement | null) => !!el && el.scrollHeight > el.clientHeight + 1;

export function Clamp({ children, sub, clamp = "line-clamp-1", className = "", subClassName = "", open: forced = false }: {
  children: ReactNode;
  sub?: ReactNode;            // an optional second line (shortened to one line), opened together with the first
  clamp?: string;             // a static Tailwind class, e.g. "line-clamp-2 sm:line-clamp-1"
  className?: string;
  subClassName?: string;
  open?: boolean;             // a parent "show everything" toggle
}) {
  const main = useRef<HTMLParagraphElement>(null);
  const second = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [cut, setCut] = useState(false);
  const shown = open || forced;
  useLayoutEffect(() => {
    if (shown) return;
    const check = () => setCut(cutOff(main.current) || cutOff(second.current));
    check();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(check);
    [main.current, second.current].forEach((el) => el && ro.observe(el));
    return () => ro.disconnect();
  }, [shown]);
  const lines = shown ? "" : `${clamp} print:line-clamp-none`;
  return (
    <div className="flex min-w-0 items-start gap-1.5">
      <div className="min-w-0 flex-1">
        <p ref={main} className={`${lines} ${className}`}>{children}</p>
        {sub && <p ref={second} className={`${shown ? "" : "line-clamp-1 print:line-clamp-none"} ${subClassName}`}>{sub}</p>}
      </div>
      {!forced && (cut || open) && (
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
                aria-label={open ? "Show less" : "Show the full text"}
                className="mt-0.5 shrink-0 text-xs text-ink-2 underline underline-offset-2 hover:text-ink print:hidden">
          {open ? "less" : "more"}
        </button>
      )}
    </div>
  );
}
