"use client";

import Link from "next/link";
import { useState } from "react";
import clsx from "clsx";
import { Star, TrendingDown, TrendingUp } from "lucide-react";
import { useSWRConfig } from "swr";
import { api, useApi } from "@/lib/api";
import { day, inr, pct, price } from "@/lib/fmt";
import { Segmented } from "@/components/ui";

export type Mover = {
  symbol: string;
  name: string;
  price: number;
  day_pct: number;
  day_change: number;
  held: boolean;
};
export type Movers = {
  as_of: string | null;
  /** while the market is open: the time of the prices, IST */
  live_at?: string | null;
  gainers: Mover[];
  losers: Mover[];
  count: number;
};
export type WatchItem = {
  symbol: string;
  name: string;
  held: boolean;
  price: number | null;
  day_change: number | null;
  day_pct: number | null;
  spark: number[];
  filings_7d: number;
  latest_filing: { ts: string; text: string; category: string | null } | null;
};
export type Watchlist = {
  items: WatchItem[];
  custom: boolean;
  as_of: string | null;
};

/** Green for up, red for down, plain for flat. Always with a sign, so it never rests on colour alone. */
export const tone = (v: number | null | undefined) =>
  v == null || Math.abs(v) < 0.005
    ? "text-ink-2"
    : v > 0
      ? "text-good"
      : "text-bad";
export const signedInr = (v: number) =>
  `${v > 0 ? "+" : v < 0 ? "−" : ""}${inr(Math.abs(v)).replace("−", "")}`;
export const signedPrice = (v: number) =>
  `${v > 0 ? "+" : v < 0 ? "−" : ""}${price(Math.abs(v))}`;

export function shortCo(name: string): string {
  return name
    .replace(/\s+(Limited|Ltd\.?)$/i, "")
    .replace(/\s+and\s+Industrial Solutions/i, "");
}

/** A month of closes as one line, coloured by where it ended against where it began. */
export function Spark({
  values,
  className,
}: {
  values: number[];
  className?: string;
}) {
  if (values.length < 2)
    return (
      <span className={clsx("inline-block h-7 w-16", className)} aria-hidden />
    );
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const w = 64;
  const h = 28;
  const pts = values
    .map(
      (v, i) =>
        `${((i / (values.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - lo) / (hi - lo || 1)) * (h - 4)).toFixed(1)}`,
    )
    .join(" ");
  const up = values.at(-1)! >= values[0];
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width={w}
      height={h}
      className={clsx(up ? "text-good" : "text-bad", className)}
      aria-hidden
    >
      <polyline
        points={pts}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.6}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Groww-style header: value now, then invested, total returns and the day's returns. */
export function HoldingsCard({
  value,
  invested,
  gain,
  gainPct,
  dayGain,
  dayPct,
  asOf,
}: {
  value: number;
  invested: number;
  gain: number;
  gainPct: number;
  dayGain: number;
  dayPct: number;
  asOf: string | null;
}) {
  return (
    <section
      aria-label="Holdings summary"
      className="mx-3 mt-3 rounded-2xl border border-line bg-surface p-4"
    >
      <p className="text-[12px] text-ink-3">Current value</p>
      <p className="tnum mt-0.5 text-[30px] font-semibold leading-tight tracking-[-0.02em]">
        {inr(value)}
      </p>
      <dl className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3 text-[12px]">
        <div className="min-w-0">
          <dt className="text-ink-3">Invested</dt>
          <dd className="tnum mt-0.5 truncate text-[14px] font-medium">
            {inr(invested)}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-ink-3">Total returns</dt>
          <dd
            className={clsx(
              "tnum mt-0.5 truncate text-[14px] font-medium",
              tone(gain),
            )}
          >
            {signedInr(gain)}
          </dd>
          <dd className={clsx("tnum text-[11px]", tone(gain))}>
            {pct(gainPct)}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-ink-3">1D returns</dt>
          <dd
            className={clsx(
              "tnum mt-0.5 truncate text-[14px] font-medium",
              tone(dayGain),
            )}
          >
            {signedInr(dayGain)}
          </dd>
          <dd className={clsx("tnum text-[11px]", tone(dayGain))}>
            {pct(dayPct, true, 2)}
          </dd>
        </div>
      </dl>
      {asOf && (
        <p className="mt-2 text-[11px] text-ink-3">
          End-of-day prices to {day(asOf)}. 1D is that day&apos;s close against
          the one before.
        </p>
      )}
    </section>
  );
}

/** The day's biggest rises and falls across your holdings and watchlist. */
export function MoversStrip({ className }: { className?: string }) {
  const [side, setSide] = useState<"gainers" | "losers">("gainers");
  const { data } = useApi<Movers>("/movers?limit=5");
  if (!data || (data.gainers.length === 0 && data.losers.length === 0))
    return null;
  const rows = data[side];
  return (
    <section aria-label="Top movers" data-tour="movers" className={className}>
      <div className="flex items-center justify-between gap-2 px-4">
        <h2 className="text-[15px] font-semibold">
          Top movers
          {data.live_at ? (
            <span className="font-normal text-ink-3"> · live {data.live_at.slice(11, 16)}</span>
          ) : (
            data.as_of && <span className="font-normal text-ink-3"> · {day(data.as_of)}</span>
          )}
        </h2>
        <Segmented
          label="Movers"
          value={side}
          onChange={setSide}
          options={[
            { value: "gainers", label: "Gainers" },
            { value: "losers", label: "Losers" },
          ]}
        />
      </div>
      {rows.length === 0 ? (
        <p className="px-4 pt-2 text-[13px] text-ink-3">
          Nothing you follow {side === "gainers" ? "rose" : "fell"} that day.
        </p>
      ) : (
        <ul className="no-scrollbar mt-2 flex snap-x gap-2 overflow-x-auto px-4 pb-1">
          {rows.map((m) => (
            <li
              key={m.symbol}
              className="w-[38%] min-w-[128px] shrink-0 snap-start"
            >
              <Link
                href={`/c/${m.symbol}`}
                className="block rounded-2xl border border-line bg-surface p-3 active:bg-surface-2"
              >
                <p className="flex items-center gap-1 text-[13px] font-semibold">
                  {m.day_pct >= 0 ? (
                    <TrendingUp size={14} className="text-good" aria-hidden />
                  ) : (
                    <TrendingDown size={14} className="text-bad" aria-hidden />
                  )}
                  <span className="truncate">{m.symbol}</span>
                </p>
                <p className="mt-0.5 truncate text-[11px] text-ink-3">
                  {m.held ? "You hold it" : "Watchlist"}
                </p>
                <p className="tnum mt-2 text-[14px] font-medium">
                  {price(m.price)}
                </p>
                <p
                  className={clsx(
                    "tnum text-[12px] font-medium",
                    tone(m.day_pct),
                  )}
                >
                  {signedPrice(m.day_change)} ({pct(m.day_pct, true, 2)})
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function detail(e: unknown): string {
  const m = e instanceof Error ? e.message : "";
  try {
    return JSON.parse(m).detail ?? m;
  } catch {
    return m || "Couldn't update the watchlist";
  }
}

/** Star a company: adds it to (or removes it from) the watchlist. */
export function WatchStar({
  symbol,
  className,
}: {
  symbol: string;
  className?: string;
}) {
  const { data, mutate } = useApi<Watchlist>("/watchlist");
  const { mutate: refresh } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const on = !!data?.items.some((i) => i.symbol === symbol);
  const toggle = async () => {
    setBusy(true);
    setNote(null);
    try {
      const next = await api<Watchlist>(
        on ? `/watchlist/${encodeURIComponent(symbol)}` : "/watchlist",
        on
          ? { method: "DELETE" }
          : { method: "POST", body: JSON.stringify({ symbol }) },
      );
      mutate(next, { revalidate: false });
      refresh((k) => typeof k === "string" && k.startsWith("/movers"));
    } catch (e) {
      setNote(detail(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="relative inline-flex" data-tour="watch">
      <button
        onClick={toggle}
        disabled={busy || !data}
        aria-pressed={on}
        aria-label={
          on ? `Remove ${symbol} from watchlist` : `Add ${symbol} to watchlist`
        }
        title={on ? "On your watchlist" : "Add to watchlist"}
        className={clsx(
          "flex items-center gap-1 rounded-full border px-3 py-1 text-[13px]",
          on ? "border-accent/40 text-ink" : "border-line text-ink-2",
          className,
        )}
      >
        <Star
          size={14}
          className={on ? "fill-accent text-accent" : ""}
          aria-hidden
        />
        {on ? "Watching" : "Watch"}
      </button>
      {note && (
        <span
          role="status"
          className="absolute right-0 top-full z-10 mt-1 w-56 rounded-lg bg-ink px-2.5 py-1.5 text-[11px] text-bg shadow"
        >
          {note}
        </span>
      )}
    </span>
  );
}
