"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Newspaper, PieChart, Search, Users } from "lucide-react";
import clsx from "clsx";

const TABS = [
  { href: "/", label: "Today", icon: Newspaper, match: (p: string) => p === "/" },
  { href: "/ask", label: "Ask", icon: Search, match: (p: string) => p.startsWith("/ask") || p.startsWith("/c/") || p.startsWith("/compare") },
  { href: "/portfolio", label: "Portfolio", icon: PieChart, match: (p: string) => p.startsWith("/portfolio") },
  { href: "/people", label: "People", icon: Users, match: (p: string) => p.startsWith("/people") },
];

export function TabBar() {
  const path = usePathname();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/90 backdrop-blur-md"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto flex max-w-xl">
        {TABS.map(({ href, label, icon: Icon, match }) => {
          const active = match(path);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={clsx(
                "flex flex-1 flex-col items-center gap-0.5 pb-2 pt-2.5 text-[11px] font-medium",
                active ? "text-ink" : "text-ink-3",
              )}
            >
              <Icon size={21} strokeWidth={active ? 2.2 : 1.7} />
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
