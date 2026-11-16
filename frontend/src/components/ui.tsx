"use client";

import clsx from "clsx";
import { useEffect, useRef } from "react";
import { Sparkles, X } from "lucide-react";
import { initials, modelName } from "@/lib/fmt";

export function Header({ title, sub, right }: { title: string; sub?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <header className="flex items-end justify-between gap-3 px-4 pb-3 pt-[calc(18px+env(safe-area-inset-top))]">
      <div className="min-w-0">
        <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em]">{title}</h1>
        {sub && <p className="mt-0.5 text-[13px] text-ink-2">{sub}</p>}
      </div>
      {right}
    </header>
  );
}

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between px-4 pb-2 pt-6">
      <h2 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-3">{children}</h2>
      {aside && <div className="text-[12px] text-ink-3">{aside}</div>}
    </div>
  );
}

export function Panel({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={clsx("mx-3 rounded-2xl border border-line bg-surface", className)}>{children}</div>
  );
}

export function Pill({
  children,
  tone = "neutral",
  className,
}: {
  children: React.ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "accent";
  className?: string;
}) {
  const tones = {
    neutral: "bg-mute-soft text-ink-2",
    good: "bg-good-soft text-good",
    warn: "bg-warn-soft text-warn",
    bad: "bg-bad-soft text-bad",
    accent: "bg-accent-soft text-accent",
  };
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium leading-4",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Avatar({ name, size = 32, muted }: { name: string; size?: number; muted?: boolean }) {
  return (
    <span
      aria-hidden
      className={clsx(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold",
        muted ? "bg-surface-2 text-ink-3" : "bg-accent-soft text-accent",
      )}
      style={{ width: size, height: size, fontSize: size * 0.36 }}
    >
      {initials(name)}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} />;
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <Panel className="p-4 text-[14px]">
      <p className="font-medium">Couldn&apos;t reach FINN&apos;s API.</p>
      <p className="mt-1 break-words text-[12px] text-ink-3">{msg.slice(0, 160)}</p>
      {retry && (
        <button onClick={retry} className="mt-3 text-[13px] font-medium text-accent">
          Try again
        </button>
      )}
    </Panel>
  );
}

/** Bottom sheet: the mobile-native place for settings and details. */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/35" onClick={onClose}>
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[88dvh] w-full max-w-xl overflow-y-auto rounded-t-3xl bg-surface pb-[calc(20px+env(safe-area-inset-bottom))] outline-none"
      >
        <div className="sticky top-0 flex items-center justify-between bg-surface px-5 pb-2 pt-4">
          <p className="text-[17px] font-semibold">{title}</p>
          <button onClick={onClose} aria-label="Close" className="rounded-full bg-surface-2 p-1.5 text-ink-2">
            <X size={16} />
          </button>
        </div>
        <div className="px-5">{children}</div>
      </div>
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-full bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "rounded-full px-3 py-1 text-[13px] font-medium transition-colors",
            value === o.value ? "bg-surface text-ink shadow-sm" : "text-ink-2",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Marks text an LLM wrote, and with what. Computed numbers never carry it. */
export function AiTag({ from, model }: { from?: string; model?: string | null }) {
  const name = modelName(model);
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-ink-3" title={model ?? undefined}>
      <Sparkles size={11} className="text-accent" aria-hidden />
      <span>
        <span className="font-medium text-ink-2">AI</span>
        {from && <> · {from}</>}
        {name && <> · {name}</>}
      </span>
    </span>
  );
}
