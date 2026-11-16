"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Newspaper, PieChart, Search, Star, Users } from "lucide-react";
import clsx from "clsx";

type Tab = { href: string; label: string; Icon: typeof Newspaper; active: (p: string) => boolean; tour?: string };

/** Five places, always one tap away. Ask sits in the middle, as the way into any company. */
const TABS: Tab[] = [
  { href: "/", label: "Today", Icon: Newspaper, active: (p) => p === "/" },
  { href: "/portfolio", label: "Portfolio", Icon: PieChart, active: (p) => p.startsWith("/portfolio") },
  { href: "/ask", label: "Ask", Icon: Search, active: (p) => p.startsWith("/ask") || p.startsWith("/c/") || p.startsWith("/compare"), tour: "ask" },
  { href: "/watchlist", label: "Watchlist", Icon: Star, active: (p) => p.startsWith("/watchlist") },
  { href: "/people", label: "Network", Icon: Users, active: (p) => p.startsWith("/people") },
];

export function TabBar() {
  const path = usePathname();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/90 backdrop-blur-md"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto grid max-w-xl grid-cols-5">
        {TABS.map(({ href, label, Icon, active, tour }) => {
          const on = active(path);
          return (
            <Link
              key={href}
              href={href}
              data-tour={tour}
              aria-current={on ? "page" : undefined}
              className={clsx("relative flex flex-col items-center gap-0.5 pb-2 pt-2.5 text-[11px] font-medium", on ? "text-ink" : "text-ink-3")}
            >
              {on && <span className="absolute inset-x-5 top-0 h-0.5 rounded-full bg-accent" aria-hidden />}
              <span className={clsx("flex h-6 w-10 items-center justify-center rounded-full", tour === "ask" && (on ? "bg-ink text-bg" : "bg-surface-2 text-ink-2"))}>
                <Icon size={tour === "ask" ? 16 : 21} strokeWidth={on || tour === "ask" ? 2.2 : 1.7} />
              </span>
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
