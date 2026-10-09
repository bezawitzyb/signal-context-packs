import { Link, NavLink, Outlet } from "react-router";
import { LIVE_URL, MIRROR } from "../lib/api";

export function Shell() {
  const nav = ({ isActive }: { isActive: boolean }) =>
    `rounded px-2 py-1 text-sm ${isActive ? "text-ink font-medium" : "text-ink-2 hover:text-ink"}`;
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:rounded focus:border focus:border-ink focus:bg-paper focus:px-2 focus:py-1">
        Skip to content
      </a>
      <header className="sticky top-0 z-20 border-b border-line bg-paper/95 backdrop-blur print:hidden">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link to="/" className="flex items-center gap-2" aria-label="SIGNAL home">
            <span aria-hidden="true" className="inline-block size-2.5 rounded-full bg-accent" />
            <span className="font-semibold tracking-[0.14em] text-ink">SIGNAL</span>
            <span className="hidden text-sm text-ink-3 sm:inline">Context Packs</span>
          </Link>
          <nav aria-label="Main" className="flex items-center gap-1">
            <NavLink to="/" end className={nav}>{MIRROR ? "Home" : "New research"}</NavLink>
            <NavLink to="/packs" className={nav}>Example packs</NavLink>
          </nav>
        </div>
      </header>
      {MIRROR && (
        <p className="border-b border-line bg-wash px-4 py-2 text-center text-sm text-ink-2 print:hidden">
          Read-only mirror of the featured packs. Live research: <a href={LIVE_URL} className="text-ink underline">{LIVE_URL.replace("https://", "")}</a>
        </p>
      )}
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
        <Outlet />
      </main>
      <footer className="border-t border-line print:hidden">
        <div className="mx-auto flex max-w-6xl flex-wrap justify-between gap-2 px-4 py-4 text-xs text-ink-3">
          <span>Built from public online conversations. Quoted excerpts are for research use only.</span>
          <span className="flex gap-3"><Link to="/evals" className="hover:text-ink">How we test</Link><a href={MIRROR ? `${LIVE_URL}/docs` : "/docs"} className="hover:text-ink">API for developers</a><span className="font-mono">/mcp</span></span>
        </div>
      </footer>
    </div>
  );
}
