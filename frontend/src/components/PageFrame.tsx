"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { beginPage, startNavigation, usePageLoadState } from "@/lib/pageload";
import { ProgressRing } from "./ProgressRing";

const NAMES: [RegExp, string][] = [
  [/^\/$/, "Today"],
  [/^\/portfolio/, "your portfolio"],
  [/^\/watchlist/, "your watchlist"],
  [/^\/people\/setup/, "your network"],
  [/^\/people\/[^/]+/, "the profile"],
  [/^\/people/, "your network"],
  [/^\/c\/([^/]+)/, "$1"],
  [/^\/compare/, "the comparison"],
  [/^\/ask/, "Ask"],
  [/^\/accuracy/, "the accuracy checks"],
];

function pageName(path: string): string {
  for (const [re, name] of NAMES) {
    const m = path.match(re);
    if (m) return name.replace("$1", decodeURIComponent(m[1] ?? "").toUpperCase());
  }
  return "the page";
}

/** The page appears whole: until every part has its data, a loading bar and a ring cover
 *  it (the tab bar stays usable). The page renders underneath, so its loads run meanwhile. */
export function PageFrame({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const st = usePageLoadState();
  const [now, setNow] = useState(0);

  // a new route mounted: wait for its loads
  useEffect(() => {
    beginPage();
  }, [path]);

  // a tapped link shows the bar at once, before the next route's code arrives
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a");
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname === window.location.pathname) return;
      startNavigation(url.pathname);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  useEffect(() => {
    if (!st.active) return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [st.active]);

  const elapsed = st.active && st.started && now ? Math.max(0, now - st.started) : 0;
  // finished loads, plus a slow creep so a single long load still visibly moves
  const done = st.peak ? (st.peak - st.pending) / st.peak : 0;
  const creep = 0.7 * (1 - Math.exp(-elapsed / 6000));
  const value = Math.min(0.95, Math.max(0.06, done * 0.95, creep));
  const secs = Math.round(elapsed / 1000);

  return (
    <>
      <div aria-hidden={st.active || undefined} inert={st.active || undefined} style={st.active ? { visibility: "hidden" } : undefined}>
        {children}
      </div>
      {st.active && (
        <div role="status" aria-live="polite" className="fixed inset-x-0 top-0 bottom-[calc(64px+env(safe-area-inset-bottom))] z-[35] bg-bg">
          <div className="absolute inset-x-0 top-0 h-[3px] bg-accent/15">
            <div className="h-full bg-accent transition-[width] duration-300 ease-out" style={{ width: `${value * 100}%` }} />
          </div>
          <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
            <ProgressRing value={value} size={44} stroke={3.5} className="text-accent" />
            <p className="text-[15px] font-medium text-ink">Loading {pageName(path)}</p>
            <p className="tnum h-4 text-[12px] text-ink-3">
              {st.peak > 1 ? `${st.peak - st.pending} of ${st.peak} parts` : ""}
              {secs >= 3 ? `${st.peak > 1 ? " · " : ""}${secs} s` : ""}
            </p>
            {secs >= 8 && (
              <p className="max-w-xs text-[12px] leading-snug text-ink-2">
                The free server sleeps when nobody has used it for a while. Waking it can take up to a minute; the page appears as soon as everything is in.
              </p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
