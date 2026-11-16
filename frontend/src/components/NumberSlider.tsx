"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

/** A slider for quick changes and a box for an exact value (up to two decimals). The slider
 *  covers the common range; the box accepts anything from `min` to `hardMax`. */
export function NumberSlider({
  label,
  value,
  onChange,
  min,
  max,
  hardMax = max,
  step = 0.01,
  unit = "",
  prefix = "",
  disabled = false,
  decimals = 2,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  hardMax?: number;
  step?: number;
  unit?: string;
  prefix?: string;
  disabled?: boolean;
  decimals?: number;
}) {
  const [text, setText] = useState(String(value));
  const [bad, setBad] = useState(false);
  useEffect(() => setText(String(+value.toFixed(decimals))), [value, decimals]);
  const commit = (t: string) => {
    const v = Number(t.replace(",", "."));
    if (t.trim() === "" || !Number.isFinite(v) || v < min || v > hardMax) {
      setBad(true);
      return;
    }
    setBad(false);
    onChange(+v.toFixed(decimals));
  };
  return (
    <div className={clsx("flex items-center gap-3", disabled && "opacity-40")}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={Math.min(max, Math.max(min, value))}
        disabled={disabled}
        onChange={(e) => onChange(+Number(e.target.value).toFixed(decimals))}
        className="min-w-0 flex-1 accent-[var(--accent)]"
        aria-label={`${label}, slider`}
      />
      <label
        className={clsx(
          "flex shrink-0 items-center rounded-lg border bg-surface px-2 py-1 text-[14px] font-semibold",
          bad ? "border-bad" : "border-line focus-within:border-accent",
        )}
      >
        {prefix && <span className="text-ink-3">{prefix}</span>}
        <input
          inputMode="decimal"
          aria-label={label}
          aria-invalid={bad}
          disabled={disabled}
          value={text}
          onChange={(e) => {
            const t = e.target.value.replace(/[^0-9.,]/g, "");
            const [, frac] = t.replace(",", ".").split(".");
            if (frac && frac.length > decimals) return; // two decimals at most
            setText(t);
            commit(t);
          }}
          onBlur={() => setText(String(+value.toFixed(decimals)))}
          className="tnum w-12 bg-transparent text-right outline-none"
        />
        {unit && <span className="ml-0.5 text-ink-3">{unit}</span>}
      </label>
    </div>
  );
}
