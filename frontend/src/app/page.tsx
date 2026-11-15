"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, SlidersHorizontal, TrendingDown, TrendingUp } from "lucide-react";
import clsx from "clsx";
import { type Alert, type Digest, useApi } from "@/lib/api";
import { CATEGORY_LABEL, ago, day, pct } from "@/lib/fmt";
import { FeedCard } from "@/components/cards";
import { AlertSettings } from "@/components/AlertSettings";
import { firstName } from "@/components/network";
import { Avatar, ErrorNote, Header, Panel, SectionTitle, Segmented, Skeleton } from "@/components/ui";

type Win = "24h" | "7d" | "30d";
const WINDOWS: { value: Win; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];
const WIN_KEY = "finn.window";

export default function Today() {
  const [win, setWin] = useState<Win>("24h");
  const [settings, setSettings] = useState(false);
  useEffect(() => {
    try {
      const w = localStorage.getItem(WIN_KEY) as Win | null;
      if (w && WINDOWS.some((x) => x.value === w)) setWin(w);
    } catch {
      /* default window */
    }
  }, []);
  const choose = (w: Win) => {
    setWin(w);
    try {
      localStorage.setItem(WIN_KEY, w);
    } catch {
      /* not remembered */
    }
  };

  const { data, error, isLoading, mutate } = useApi<Digest>(`/digest?window=${win}`);
  const now = data?.window.end ?? new Date().toISOString();

  return (
    <main>
      <Header
        title="Today"
        sub={data ? <Summary d={data} /> : "Reading your portfolio's filings…"}
        right={
          <button
            onClick={() => setSettings(true)}
            aria-label="Alert settings"
            className="mb-1 rounded-full border border-line bg-surface p-2 text-ink-2"
          >
            <SlidersHorizontal size={17} />
          </button>
        }
      />
      <div className="px-4">
        <Segmented label="Time window" value={win} options={WINDOWS} onChange={choose} />
      </div>

      {error && !data ? (
        <div className="mt-4">
          <ErrorNote error={error} retry={() => mutate()} />
        </div>
      ) : !data || isLoading ? (
        <FeedSkeleton />
      ) : (
        <>
          <Moves alerts={data.alerts} now={now} />
          <SectionTitle aside={`from ${data.counts.filings} filings`}>What matters</SectionTitle>
          {data.cards.length === 0 ? (
            <Panel className="p-4 text-[14px] text-ink-2">Nothing material in this window. Quiet is good.</Panel>
          ) : (
            <Feed cards={data.cards} now={now} />
          )}
          {data.nudges.length > 0 && <Nudges d={data} />}
          <Routine d={data} />
          <p className="px-4 pb-6 pt-4 text-center text-[11px] text-ink-3">
            As of {day(now)}, {new Date(now).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })} · NSE
            filings and EOD prices
          </p>
        </>
      )}
      <AlertSettings open={settings} onClose={() => setSettings(false)} onSaved={() => mutate()} />
    </main>
  );
}

const TOP = 8;

/** A brief, not a dashboard: the top items in full, the long tail one tap away. Each
 *  company's "who to ask" appears once, on its most important card. */
function Feed({ cards, now }: { cards: Digest["cards"]; now: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? cards : cards.slice(0, TOP);
  const helped = new Set<string>();
  return (
    <div className="space-y-3">
      {shown.map((c) => {
        const first = !helped.has(c.symbol);
        helped.add(c.symbol);
        return <FeedCard key={c.id} card={c} now={now} showHelper={first} />;
      })}
      {cards.length > TOP && (
        <button
          onClick={() => setAll(!all)}
          aria-expanded={all}
          className="mx-3 flex w-[calc(100%-1.5rem)] items-center justify-center gap-1 rounded-2xl border border-line bg-surface py-3 text-[13px] font-medium text-ink-2"
        >
          {all ? "Show fewer" : `${cards.length - TOP} more, lower priority`}
          <ChevronDown size={15} className={clsx("transition-transform", all && "rotate-180")} />
        </button>
      )}
    </div>
  );
}

function Summary({ d }: { d: Digest }) {
  const n = d.cards.length;
  const lead =
    n === 0 ? "Nothing needs you" : n === 1 ? "1 thing matters" : n <= TOP ? `${n} things matter` : `${TOP} things matter most`;
  return (
    <>
      {day(d.window.end)} · {lead}
      {d.counts.routine > 0 && <> · {d.counts.routine} routine folded away</>}
    </>
  );
}

/** Price/volume alerts only; category alerts already are the cards below. */
function Moves({ alerts, now }: { alerts: Alert[]; now: string }) {
  const moves = useMemo(() => {
    const bySymbol = new Map<string, { symbol: string; ts: string; vol?: Alert; price?: Alert }>();
    for (const a of alerts) {
      if (a.kind === "category") continue;
      const m = bySymbol.get(a.symbol) ?? { symbol: a.symbol, ts: a.ts };
      if (a.kind === "volume" && !m.vol) m.vol = a;
      if (a.kind === "price" && !m.price) m.price = a;
      if (a.ts > m.ts) m.ts = a.ts;
      bySymbol.set(a.symbol, m);
    }
    return [...bySymbol.values()].sort((a, b) => (b.ts > a.ts ? 1 : -1));
  }, [alerts]);
  if (!moves.length) return null;
  return (
    <>
      <SectionTitle aside="EOD">Unusual moves</SectionTitle>
      <div className="no-scrollbar flex gap-2 overflow-x-auto px-3 pb-1">
        {moves.map((m) => {
          const chg = m.price?.value ?? m.vol?.price_change_pct ?? 0;
          const Icon = chg >= 0 ? TrendingUp : TrendingDown;
          return (
            <Link
              key={m.symbol}
              href={`/c/${m.symbol}`}
              className="flex min-w-[132px] shrink-0 flex-col rounded-xl border border-line bg-surface px-3 py-2 active:opacity-80"
            >
              <span className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-semibold">{m.symbol}</span>
                <span className="tnum text-[11px] text-ink-3">{ago(m.ts, now)}</span>
              </span>
              <span className={clsx("tnum mt-0.5 flex items-center gap-1 text-[13px] font-medium", chg >= 0 ? "text-good" : "text-bad")}>
                <Icon size={13} /> {pct(chg)}
              </span>
              {m.vol && <span className="tnum text-[11px] text-ink-2">Volume {m.vol.value.toFixed(1)}× avg</span>}
            </Link>
          );
        })}
      </div>
    </>
  );
}

function Nudges({ d }: { d: Digest }) {
  return (
    <>
      <SectionTitle>Good reasons to reconnect</SectionTitle>
      <Panel className="divide-y divide-line">
        {d.nudges.slice(0, 4).map((n) => (
          <Link key={n.contact.id} href={`/people/${n.contact.id}`} className="flex gap-3 p-3 active:opacity-80">
            <Avatar name={n.contact.name} size={34} />
            <div className="min-w-0 text-[13px] leading-snug">
              <p>
                <span className="font-semibold">{firstName(n.contact.name)}</span>
                <span className="text-ink-2"> · {Math.round(n.days_since_contact / 30)} months since you spoke</span>
              </p>
              <p className="text-ink-2">{n.reason.replace(/^Last spoke [^.]+\.\s*/, "")}</p>
            </div>
          </Link>
        ))}
      </Panel>
    </>
  );
}

function Routine({ d }: { d: Digest }) {
  const [open, setOpen] = useState(false);
  if (!d.routine.count) return null;
  return (
    <div className="mt-6">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="mx-3 flex w-[calc(100%-1.5rem)] items-center justify-between rounded-2xl border border-dashed border-line px-4 py-3 text-[13px] text-ink-2"
      >
        <span>
          Routine · <span className="tnum">{d.routine.count}</span> {d.routine.count === 1 ? "filing" : "filings"}
        </span>
        <ChevronDown size={15} className={clsx("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="mx-3 mt-1 divide-y divide-line">
          {d.routine.items.map((r) => (
            <li key={r.id} className="flex gap-2 px-1 py-2 text-[12px]">
              <span className="w-[74px] shrink-0 font-medium text-ink-2">{r.symbol}</span>
              <a href={r.pdf_url ?? undefined} target="_blank" rel="noreferrer" className="min-w-0 flex-1 text-ink-2">
                {r.title}
              </a>
              <span className="shrink-0 text-ink-3">{CATEGORY_LABEL[r.category] ?? r.category}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FeedSkeleton() {
  return (
    <div className="mt-6 space-y-3 px-3">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-44" />
      ))}
    </div>
  );
}
