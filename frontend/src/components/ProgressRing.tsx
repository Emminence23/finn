"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

/** A progress circle. With `value` (0..1) it fills; without, it spins. Decorative: the text
 *  beside it says what's happening, so screen readers get words, not a shape. */
export function ProgressRing({ value, size = 18, stroke = 2.5, className }: { value?: number; size?: number; stroke?: number; className?: string }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const known = value != null;
  const v = Math.max(0, Math.min(1, value ?? 0.28));
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden
      className={clsx("shrink-0 -rotate-90", !known && "animate-spin motion-reduce:animate-none", className)}
    >
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeOpacity={0.18} strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - v)}
        style={known ? { transition: "stroke-dashoffset 400ms ease-out" } : undefined}
      />
    </svg>
  );
}

/** Seconds since `active` became true (0 when inactive): drives "12 s" next to a ring. */
export function useElapsed(active: boolean): number {
  const [s, setS] = useState(0);
  useEffect(() => {
    if (!active) {
      setS(0);
      return;
    }
    const t0 = Date.now();
    const id = setInterval(() => setS(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [active]);
  return s;
}

/** A centred "loading" block: a ring and what is being fetched; after a few seconds, the
 *  elapsed time, so a slow wait still visibly moves. */
export function Loading({ what, className }: { what: string; className?: string }) {
  const s = useElapsed(true);
  return (
    <div role="status" className={clsx("flex items-center justify-center gap-2.5 py-8 text-[13px] text-ink-2", className)}>
      <ProgressRing size={20} className="text-accent" />
      <span>
        {what}
        {s >= 3 && <span className="tnum text-ink-3"> · {s} s</span>}
      </span>
    </div>
  );
}
