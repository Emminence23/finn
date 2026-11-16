"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Newspaper, PieChart, Search } from "lucide-react";
import clsx from "clsx";

/** Two places and a question. Today and Portfolio are where you go; everything else
 *  (a company, a person, a theme, your network) is something you ask for, so the middle
 *  of the bar is an ask bar rather than more tabs. People open wherever a name appears. */
export function TabBar() {
  const path = usePathname();
  const asking = path.startsWith("/ask") || path.startsWith("/c/") || path.startsWith("/compare") || path.startsWith("/people");
  const place = (href: string, label: string, Icon: typeof Newspaper, active: boolean) => (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={clsx("flex w-16 shrink-0 flex-col items-center gap-0.5 pb-2 pt-2.5 text-[11px] font-medium", active ? "text-ink" : "text-ink-3")}
    >
      <Icon size={21} strokeWidth={active ? 2.2 : 1.7} />
      {label}
    </Link>
  );
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/90 backdrop-blur-md"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto flex max-w-xl items-center gap-1 px-2">
        {place("/", "Today", Newspaper, path === "/")}
        <Link
          href="/ask"
          data-tour="ask"
          aria-current={asking ? "page" : undefined}
          className={clsx(
            "flex h-11 min-w-0 flex-1 items-center gap-2 rounded-full border px-4 text-[14px]",
            asking ? "border-ink/30 bg-surface text-ink" : "border-line bg-surface-2 text-ink-2",
          )}
        >
          <Search size={16} className="shrink-0" />
          <span className="truncate">Ask FINN</span>
        </Link>
        {place("/portfolio", "Portfolio", PieChart, path.startsWith("/portfolio"))}
      </div>
    </nav>
  );
}
