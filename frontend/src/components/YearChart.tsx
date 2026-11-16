"use client";

import { useEffect, useRef, useState } from "react";
import { inr, pct } from "@/lib/fmt";

export type Point = { date: string; value: number; nifty?: number };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const H = 188;
const PAD = { top: 10, right: 46, bottom: 22, left: 34 };

function niceStep(span: number): number {
  const raw = span / 3;
  const mag = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
}

/** One year of the holdings' value next to the Nifty 50 from the same starting amount.
 *  Both lines are rupees, so they share one axis. Touch or hover for a day's values. */
export function YearChart({ series, invested }: { series: Point[]; invested?: number }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(340);
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  if (series.length < 2) return null;

  const hasNifty = series.some((p) => p.nifty != null);
  const all = series.flatMap((p) => (p.nifty != null ? [p.value, p.nifty] : [p.value]));
  const step = niceStep(Math.max(...all) - Math.min(...all) || 1);
  const lo = Math.floor(Math.min(...all) / step) * step;
  const hi = Math.ceil(Math.max(...all) / step) * step;
  const n = series.length - 1;
  const x = (i: number) => PAD.left + (i * (W - PAD.left - PAD.right)) / n;
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
  const path = (k: "value" | "nifty") =>
    series
      .map((p, i) => (p[k] == null ? null : `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[k] as number).toFixed(1)}`))
      .filter(Boolean)
      .join("");
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(v);
  const months = series
    .map((p, i) => ({ i, m: Number(p.date.slice(5, 7)), d: Number(p.date.slice(8, 10)) }))
    .filter((p, k, arr) => k > 0 && p.m !== arr[k - 1].m && p.m % 3 === 0);

  const first = series[0];
  const last = series[n];
  const ret = (v: number) => (v / first.value - 1) * 100;
  // end labels, nudged apart when the lines finish close together
  let yYou = y(last.value);
  let yNifty = last.nifty != null ? y(last.nifty) : null;
  if (yNifty != null && Math.abs(yYou - yNifty) < 15) {
    const mid = (yYou + yNifty) / 2;
    const up = yYou <= yNifty;
    yYou = mid + (up ? -8 : 8);
    yNifty = mid + (up ? 8 : -8);
  }
  const h = hover != null ? series[hover] : null;
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left - PAD.left) / (W - PAD.left - PAD.right)) * n);
    setHover(Math.max(0, Math.min(n, i)));
  };
  const label = (d: string) => {
    const [yy, mm, dd] = d.split("-");
    return `${Number(dd)} ${MONTHS[Number(mm) - 1]} ${yy}`;
  };

  return (
    <div ref={wrap} className="relative">
      <div className="flex items-center gap-3 text-[11px] text-ink-2" aria-hidden>
        <span className="flex items-center gap-1.5">
          <i className="inline-block h-[2px] w-4 rounded bg-accent" /> Your holdings
        </span>
        {hasNifty && (
          <span className="flex items-center gap-1.5">
            <svg width="16" height="2">
              <line x1="0" x2="16" y1="1" y2="1" stroke="var(--ink-3)" strokeWidth="2" strokeDasharray="3 3" />
            </svg>
            Nifty 50, same start
          </span>
        )}
      </div>
      <svg
        width={W}
        height={H}
        className="mt-2 block touch-none select-none"
        role="img"
        tabIndex={0}
        aria-label={`Value over the past year: ${inr(first.value)} to ${inr(last.value)} (${pct(ret(last.value))})${
          last.nifty != null ? `; the Nifty 50 from the same start would be ${inr(last.nifty)} (${pct(ret(last.nifty))})` : ""
        }.`}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setHover(null)}
        onBlur={() => setHover(null)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") setHover(Math.max(0, (hover ?? n) - 5));
          if (e.key === "ArrowRight") setHover(Math.min(n, (hover ?? n - 5) + 5));
        }}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
            <text x={PAD.left - 6} y={y(t) + 3.5} fontSize={10} fill="var(--ink-3)" textAnchor="end" className="tnum">
              {inr(t, true)}
            </text>
          </g>
        ))}
        {months.map((m) => (
          <text key={m.i} x={x(m.i)} y={H - 6} fontSize={10} fill="var(--ink-3)" textAnchor="middle">
            {MONTHS[m.m - 1]}
          </text>
        ))}
        {invested != null && invested >= lo && invested <= hi && (
          <line x1={PAD.left} x2={W - PAD.right} y1={y(invested)} y2={y(invested)} stroke="var(--ink-3)" strokeWidth={1} strokeDasharray="1 3" />
        )}
        {hasNifty && (
          <path d={path("nifty")} fill="none" stroke="var(--ink-3)" strokeWidth={2} strokeDasharray="4 3" strokeLinejoin="round" />
        )}
        <path d={path("value")} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover == null && (
          <>
            <circle cx={x(n)} cy={y(last.value)} r={4} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />
            <text x={x(n) + 8} y={yYou + 3.5} fontSize={11} fontWeight={600} fill="var(--ink)" className="tnum">
              {pct(ret(last.value))}
            </text>
            {yNifty != null && last.nifty != null && (
              <text x={x(n) + 8} y={yNifty + 3.5} fontSize={11} fill="var(--ink-2)" className="tnum">
                {pct(ret(last.nifty))}
              </text>
            )}
          </>
        )}
        {h && hover != null && (
          <>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top - 4} y2={H - PAD.bottom} stroke="var(--ink-3)" strokeWidth={1} />
            {h.nifty != null && <circle cx={x(hover)} cy={y(h.nifty)} r={4} fill="var(--ink-3)" stroke="var(--surface)" strokeWidth={2} />}
            <circle cx={x(hover)} cy={y(h.value)} r={4} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />
          </>
        )}
      </svg>
      {h && hover != null && (
        <div
          className="pointer-events-none absolute top-6 z-10 min-w-[150px] rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[11px] shadow-md"
          style={x(hover) > W / 2 ? { right: W - x(hover) + 8 } : { left: x(hover) + 8 }}
        >
          <p className="text-ink-3">{label(h.date)}</p>
          <p className="tnum flex justify-between gap-3">
            <span className="text-ink-2">Your holdings</span>
            <span className="font-semibold">
              {inr(h.value)} <span className="font-normal text-ink-2">{pct(ret(h.value))}</span>
            </span>
          </p>
          {h.nifty != null && (
            <p className="tnum flex justify-between gap-3">
              <span className="text-ink-2">Nifty 50</span>
              <span>
                {inr(h.nifty)} <span className="text-ink-2">{pct(ret(h.nifty))}</span>
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
