"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import clsx from "clsx";
import { ArrowLeft, ArrowLeftRight, Info } from "lucide-react";
import { useApi } from "@/lib/api";
import { crore, pct, times } from "@/lib/fmt";
import { ErrorNote, Panel, SectionTitle, Skeleton } from "@/components/ui";

type Co = {
  symbol: string;
  name: string;
  short: string;
  fy: string | null;
  basis: string | null;
  is_lender: boolean;
  promises: { score: number | null; counts: Record<string, number> } | null;
};
type Metric = { key: string; label: string; unit: "cr" | "pct" | "x" | "days"; values: (number | null)[]; better: 0 | 1 | null };
type Comparison = { companies: Co[]; metrics: Metric[]; lines: string[]; wins: number[]; notes: string[] };
type Peer = { symbol: string; name: string; kind: string };

export default function ComparePage() {
  return (
    <Suspense>
      <Compare />
    </Suspense>
  );
}

function value(v: number | null, unit: Metric["unit"]): string {
  if (v == null) return "—";
  if (unit === "cr") return crore(v);
  if (unit === "pct") return pct(v, false);
  if (unit === "x") return times(v);
  return `${Math.round(v)}`;
}

/** Two companies side by side, computed in code from reported financials. The better side of
 *  each row is marked; size and valuation rows pick no side. */
function Compare() {
  const router = useRouter();
  const q = useSearchParams();
  const a = (q.get("a") ?? "").toUpperCase();
  const b = (q.get("b") ?? "").toUpperCase();
  const { data, error, mutate } = useApi<Comparison>(a && b ? `/compare?a=${a}&b=${b}` : null);
  const { data: peers } = useApi<{ peers: Peer[] }>(a ? `/compare/peers?symbol=${a}` : null);
  const go = (x: string, y: string) => router.replace(`/compare?a=${x}&b=${y}`, { scroll: false });

  return (
    <main className="pb-10">
      <div className="flex items-center gap-1 px-3 pt-[calc(12px+env(safe-area-inset-top))]">
        <button onClick={() => router.back()} aria-label="Back" className="rounded-full p-2 text-ink-2 active:bg-surface-2">
          <ArrowLeft size={19} />
        </button>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Compare</h1>
        {a && b && (
          <button onClick={() => go(b, a)} aria-label="Swap" className="ml-auto rounded-full border border-line p-2 text-ink-2">
            <ArrowLeftRight size={16} />
          </button>
        )}
      </div>

      {peers && peers.peers.length > 0 && (
        <div className="no-scrollbar mt-1 flex gap-1.5 overflow-x-auto px-4">
          <span className="shrink-0 self-center text-[12px] text-ink-3">{a} vs</span>
          {peers.peers.map((p) => (
            <button
              key={p.symbol}
              aria-pressed={p.symbol === b}
              onClick={() => go(a, p.symbol)}
              className={clsx(
                "shrink-0 rounded-full border px-3 py-1 text-[13px]",
                p.symbol === b ? "border-ink bg-ink text-surface" : "border-line bg-surface text-ink-2",
              )}
            >
              {p.symbol}
            </button>
          ))}
        </div>
      )}

      {error && !data ? (
        <div className="mt-4">
          <ErrorNote error={error} retry={() => mutate()} />
        </div>
      ) : !data ? (
        <div className="space-y-3 px-4 pt-4">
          <Skeleton className="h-16" />
          <Skeleton className="h-80" />
        </div>
      ) : (
        <Body d={data} />
      )}
    </main>
  );
}

function Body({ d }: { d: Comparison }) {
  const [x, y] = d.companies;
  return (
    <>
      <div className="mt-3 grid grid-cols-2 gap-2 px-3">
        {d.companies.map((c, i) => (
          <Link key={c.symbol} href={`/c/${c.symbol}`} className="rounded-2xl border border-line bg-surface p-3 active:opacity-80">
            <p className="truncate text-[15px] font-semibold">{c.short}</p>
            <p className="text-[11px] text-ink-3">
              {c.symbol} · FY to {c.fy?.slice(0, 7) ?? "?"}
            </p>
            <p className="tnum mt-1 text-[12px] text-ink-2">
              Better on <b className="text-ink">{d.wins[i]}</b> of {d.wins[0] + d.wins[1]}
            </p>
          </Link>
        ))}
      </div>

      {d.lines.length > 0 && (
        <ul className="mx-4 mt-3 space-y-1.5 text-[14px] leading-snug">
          {d.lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}

      <SectionTitle aside="₹ crore · computed from reported financials">Side by side</SectionTitle>
      <Panel className="divide-y divide-line">
        <div className="grid grid-cols-[1fr_5.5rem_5.5rem] gap-2 px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-ink-3">
          <span />
          <span className="truncate text-right">{x.short}</span>
          <span className="truncate text-right">{y.short}</span>
        </div>
        {d.metrics.map((m) => (
          <div key={m.key} className="grid grid-cols-[1fr_5.5rem_5.5rem] items-center gap-2 px-4 py-2.5">
            <span className="text-[13px] leading-snug text-ink-2">{m.label}</span>
            {m.values.map((v, i) => (
              <span
                key={i}
                className={clsx("tnum text-right text-[14px]", m.better === i ? "font-semibold text-ink" : m.better == null ? "text-ink" : "text-ink-3")}
              >
                {m.better === i && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-good align-middle" aria-label="better" />}
                {value(v, m.unit)}
              </span>
            ))}
          </div>
        ))}
        <div className="grid grid-cols-[1fr_5.5rem_5.5rem] items-center gap-2 px-4 py-2.5">
          <span className="text-[13px] leading-snug text-ink-2">Management delivery score</span>
          {d.companies.map((c) => (
            <span key={c.symbol} className="tnum text-right text-[14px]">
              {c.promises?.score != null ? (
                <Link href={`/c/${c.symbol}#promises`} className="text-accent">
                  {c.promises.score}/100
                </Link>
              ) : (
                <span className="text-[12px] text-ink-3">not built</span>
              )}
            </span>
          ))}
        </div>
      </Panel>

      {d.notes.map((n) => (
        <p key={n} className="mx-4 mt-3 flex gap-2 rounded-xl bg-surface-2 px-3 py-2 text-[12px] leading-snug text-ink-2">
          <Info size={14} className="mt-0.5 shrink-0" />
          {n}
        </p>
      ))}
      <p className="px-6 pt-4 text-center text-[11px] leading-snug text-ink-3">
        Every number is computed in code from screener.in&apos;s standardised tables of the reported financials, except where a note above says otherwise.
      </p>
    </>
  );
}
