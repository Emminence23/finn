"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Building2, Search, Sparkles, User } from "lucide-react";
import { type Company, type Contact, type ResearchSummary, useApi } from "@/lib/api";
import { shortName } from "@/lib/fmt";
import { VerdictBar } from "@/components/research";
import { Header, Panel, SectionTitle, Skeleton } from "@/components/ui";

function useDebounced<T>(v: T, ms = 160) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

export default function Ask() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const { data: companies } = useApi<Company[]>(dq.length >= 2 ? `/companies?q=${encodeURIComponent(dq)}&limit=6` : null);
  const { data: people } = useApi<Contact[]>("/people");
  const { data: ready } = useApi<ResearchSummary[]>("/research");

  const lower = dq.toLowerCase();
  const themes = useMemo(() => {
    const all = new Set<string>();
    people?.forEach((p) => p.themes?.forEach((t) => all.add(t)));
    return [...all];
  }, [people]);
  const themeHits = lower.length >= 2 ? themes.filter((t) => t.toLowerCase().includes(lower)).slice(0, 3) : [];
  const personHits =
    lower.length >= 2
      ? (people ?? []).filter((p) => p.name.toLowerCase().includes(lower) || (p.current ?? "").toLowerCase().includes(lower)).slice(0, 3)
      : [];

  return (
    <main>
      <Header title="Ask" sub="Any NSE company, a person, or a theme" />
      <form
        className="px-3"
        onSubmit={(e) => {
          e.preventDefault();
          const top = companies?.[0];
          if (top) router.push(`/c/${top.symbol}`);
          else if (dq) router.push(`/c/${dq.toUpperCase().replace(/\s+/g, "")}`);
        }}
      >
        <label className="flex items-center gap-2 rounded-2xl border border-line bg-surface px-3.5 py-3 focus-within:border-accent">
          <Search size={18} className="text-ink-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Kaynes, TATAELXSI, semiconductors, Meera…"
            className="w-full bg-transparent text-[16px] outline-none placeholder:text-ink-3"
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="search"
            aria-label="Search companies, people and themes"
          />
        </label>
      </form>

      {dq.length >= 2 && (
        <Panel className="mt-2 divide-y divide-line">
          {(companies ?? []).map((c) => (
            <Link key={c.symbol} href={`/c/${c.symbol}`} className="flex items-center gap-3 px-4 py-2.5 active:bg-surface-2">
              <Building2 size={16} className="shrink-0 text-ink-3" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium">{shortName(c.name)}</span>
                <span className="text-[12px] text-ink-3">
                  {c.symbol}
                  {c.in_portfolio ? " · in your portfolio" : c.in_research_set ? " · research set" : ""}
                </span>
              </span>
              <span className="text-[12px] text-accent">Research</span>
            </Link>
          ))}
          {themeHits.map((t) => (
            <Link key={t} href={`/people?theme=${encodeURIComponent(t)}`} className="flex items-center gap-3 px-4 py-2.5 active:bg-surface-2">
              <Sparkles size={16} className="shrink-0 text-ink-3" />
              <span className="flex-1 text-[14px]">
                Who knows <span className="font-medium">{t}</span>?
              </span>
            </Link>
          ))}
          {personHits.map((p) => (
            <Link key={p.id} href={`/people/${p.id}`} className="flex items-center gap-3 px-4 py-2.5 active:bg-surface-2">
              <User size={16} className="shrink-0 text-ink-3" />
              <span className="min-w-0 flex-1">
                <span className="block text-[14px] font-medium">{p.name}</span>
                <span className="block truncate text-[12px] text-ink-3">{p.current}</span>
              </span>
            </Link>
          ))}
          {companies && !companies.length && !themeHits.length && !personHits.length && (
            <p className="px-4 py-3 text-[13px] text-ink-3">No match. Try a ticker like DIXON or a theme like EMS.</p>
          )}
        </Panel>
      )}

      <SectionTitle aside="ready to read">Management track records</SectionTitle>
      {!ready ? (
        <div className="space-y-2 px-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : (
        <div className="space-y-2">
          {ready.map((r) => (
            <Link key={r.symbol} href={`/c/${r.symbol}`} className="mx-3 block rounded-2xl border border-line bg-surface p-4 active:opacity-80">
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-[15px] font-semibold">{shortName(r.company)}</p>
                <span className="text-[12px] text-ink-3">{r.symbol}</span>
              </div>
              {r.headline && (
                <p className="mt-1 line-clamp-2 text-[13px] leading-snug text-ink-2">
                  <span className="font-semibold text-bad">Missed: </span>
                  {r.headline}
                </p>
              )}
              <div className="mt-2.5">
                <VerdictBar counts={r.counts} />
              </div>
            </Link>
          ))}
        </div>
      )}
      <p className="px-6 pb-8 pt-4 text-center text-[12px] leading-snug text-ink-3">
        Any other NSE ticker is read live from its annual report and last four earnings calls.
      </p>
    </main>
  );
}
