"use client";

import Link from "next/link";
import { useState } from "react";
import clsx from "clsx";
import { Plus, RotateCcw, Star, X } from "lucide-react";
import { useSWRConfig } from "swr";
import { api, useApi } from "@/lib/api";
import { CATEGORY_LABEL, day, pct, price } from "@/lib/fmt";
import { detail, MoversStrip, shortCo, signedPrice, Spark, tone, type Watchlist } from "@/components/market";
import { ErrorNote, Header, Panel, Sheet, Skeleton, SlowHint } from "@/components/ui";
import { useTitle } from "@/lib/title";

type Addable = { symbol: string; name: string; held: boolean };

export default function WatchlistPage() {
  useTitle("Watchlist");
  const { data, error, mutate } = useApi<Watchlist & { addable: Addable[] }>("/watchlist");
  const { mutate: refresh } = useSWRConfig();
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const change = async (path: string, init: RequestInit) => {
    setNote(null);
    try {
      mutate(await api(path, init), { revalidate: false });
      refresh((k) => typeof k === "string" && k.startsWith("/movers"));
    } catch (e) {
      setNote(detail(e));
    }
  };

  return (
    <main className="pb-10">
      <Header
        title="Watchlist"
        sub={data ? `${data.items.length} ${data.items.length === 1 ? "company" : "companies"}${data.as_of ? ` · prices to ${day(data.as_of)}` : ""}` : " "}
        right={
          <button onClick={() => setAdding(true)} className="flex items-center gap-1 rounded-full border border-line px-3 py-1.5 text-[13px] font-medium text-ink-2">
            <Plus size={14} /> Add
          </button>
        }
      />
      {note && (
        <p role="status" className="mx-4 mb-2 rounded-xl bg-warn-soft/60 px-3 py-2 text-[13px]">
          {note}
        </p>
      )}
      {error && !data ? (
        <ErrorNote error={error} retry={() => mutate()} />
      ) : !data ? (
        <div className="space-y-2 px-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <SlowHint />
        </div>
      ) : data.items.length === 0 ? (
        <Panel className="p-5 text-center">
          <Star size={22} className="mx-auto text-ink-3" />
          <p className="mt-2 text-[14px] font-medium">Nothing on your watchlist</p>
          <p className="mt-1 text-[13px] text-ink-2">Tap Add, or Watch on any company page.</p>
        </Panel>
      ) : (
        <Panel>
          <ul className="divide-y divide-line">
            {data.items.map((w) => (
              <li key={w.symbol} className="flex items-stretch">
                <Link href={`/c/${w.symbol}`} className="min-w-0 flex-1 py-3 pl-4 active:bg-surface-2">
                  <div className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="flex items-baseline gap-1.5">
                        <span className="text-[14px] font-semibold">{w.symbol}</span>
                        {w.held && <span className="rounded-full bg-surface-2 px-1.5 text-[10px] font-medium text-ink-2">held</span>}
                      </p>
                      <p className="truncate text-[12px] text-ink-3">{shortCo(w.name)}</p>
                    </div>
                    <Spark values={w.spark} className="shrink-0" />
                    <div className="w-[76px] shrink-0 text-right">
                      <p className="tnum text-[14px] font-medium">{price(w.price)}</p>
                      {w.day_pct != null && w.day_change != null && (
                        <p className={clsx("tnum text-[11px] font-medium", tone(w.day_pct))}>
                          {signedPrice(w.day_change)} ({pct(w.day_pct, true, 2)})
                        </p>
                      )}
                    </div>
                  </div>
                  {w.latest_filing && (
                    <p className="mt-1.5 line-clamp-2 text-[12px] leading-snug text-ink-2">
                      <span className="text-ink-3">
                        {day(w.latest_filing.ts)} · {CATEGORY_LABEL[w.latest_filing.category ?? ""] ?? "Filing"}:
                      </span>{" "}
                      {w.latest_filing.text}
                    </p>
                  )}
                </Link>
                <button
                  onClick={() => change(`/watchlist/${encodeURIComponent(w.symbol)}`, { method: "DELETE" })}
                  aria-label={`Remove ${w.symbol} from watchlist`}
                  className="flex w-11 shrink-0 items-center justify-center text-ink-3 active:bg-surface-2"
                >
                  <X size={16} />
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <MoversStrip className="mt-5" />

      <p className="px-6 pt-4 text-center text-[11px] leading-snug text-ink-3">
        End-of-day closes; the line is the last 30 sessions. Under each, the company&apos;s latest filing that isn&apos;t routine paperwork. No AI on this page.
      </p>
      {data?.custom && (
        <p className="pt-2 text-center">
          <button onClick={() => change("/watchlist/reset", { method: "POST" })} className="inline-flex items-center gap-1 text-[12px] text-ink-3 underline underline-offset-2">
            <RotateCcw size={12} /> Restore the demo watchlist
          </button>
        </p>
      )}

      <Sheet open={adding} onClose={() => setAdding(false)} title="Add to watchlist">
        <AddList items={data?.addable ?? []} onAdd={(s) => change("/watchlist", { method: "POST", body: JSON.stringify({ symbol: s }) })} />
      </Sheet>
    </main>
  );
}

function AddList({ items, onAdd }: { items: Addable[]; onAdd: (s: string) => Promise<void> }) {
  const [q, setQ] = useState("");
  const l = q.trim().toLowerCase();
  const shown = items.filter((i) => !l || i.symbol.toLowerCase().includes(l) || i.name.toLowerCase().includes(l));
  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Filter by name or ticker"
        aria-label="Filter companies"
        className="w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] outline-none focus:border-accent"
      />
      <p className="mt-2 text-[12px] text-ink-3">
        This demo&apos;s price snapshot covers {items.length} more {items.length === 1 ? "company" : "companies"}. Research works on any NSE company from Ask.
      </p>
      <ul className="mt-2 divide-y divide-line">
        {shown.map((i) => (
          <li key={i.symbol}>
            <button onClick={() => onAdd(i.symbol)} className="flex w-full items-center gap-3 py-2.5 text-left active:bg-surface-2">
              <span className="min-w-0 flex-1">
                <span className="text-[14px] font-semibold">{i.symbol}</span>
                {i.held && <span className="ml-1.5 text-[11px] text-ink-3">held</span>}
                <span className="block truncate text-[12px] text-ink-3">{shortCo(i.name)}</span>
              </span>
              <Plus size={16} className="text-ink-2" />
            </button>
          </li>
        ))}
        {shown.length === 0 && <li className="py-3 text-[13px] text-ink-3">No match.</li>}
      </ul>
    </div>
  );
}
