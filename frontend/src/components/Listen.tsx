"use client";

import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Headphones, Square } from "lucide-react";
import { ProgressRing } from "./ProgressRing";

/** Reads a script aloud in the phone's own voice: free, private, no AI. Each screen builds
 *  its script in code from what the screen shows, so the voice never says anything the page
 *  doesn't. While playing, the line being read is shown with a ring of how far through it
 *  is. Hidden where the browser has no speech engine. */
export function Listen({ lines, className, tour }: { lines: string[] | null | undefined; className?: string; tour?: string }) {
  const [supported, setSupported] = useState(false);
  const [at, setAt] = useState<number | null>(null);
  const stopped = useRef(false);

  useEffect(() => {
    setSupported(typeof window !== "undefined" && "speechSynthesis" in window);
    return () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    };
  }, []);

  const script = (lines ?? []).map((l) => l.trim()).filter(Boolean);
  if (!supported || script.length === 0) return null;

  const words = script.join(" ").split(/\s+/).length;
  const mins = Math.max(1, Math.round(words / 160));
  const voice = () => {
    const vs = window.speechSynthesis.getVoices();
    return vs.find((v) => v.lang === "en-IN") ?? vs.find((v) => v.lang.startsWith("en-GB")) ?? vs.find((v) => v.lang.startsWith("en"));
  };
  const play = () => {
    const synth = window.speechSynthesis;
    synth.cancel();
    stopped.current = false;
    const say = (i: number) => {
      if (stopped.current || i >= script.length) return setAt(null);
      setAt(i);
      const u = new SpeechSynthesisUtterance(spoken(script[i]));
      const v = voice();
      if (v) u.voice = v;
      u.rate = 1.02;
      u.onend = () => say(i + 1);
      u.onerror = () => setAt(null);
      synth.speak(u);
    };
    say(0);
  };
  const stop = () => {
    stopped.current = true;
    window.speechSynthesis.cancel();
    setAt(null);
  };

  return (
    <div className={clsx(at === null ? "inline-block" : "block", className)} data-tour={tour}>
      {at === null ? (
        <button onClick={play} className="inline-flex h-9 items-center gap-2 rounded-full border border-line bg-surface px-3.5 text-left active:opacity-80">
          <Headphones size={15} className="text-accent" />
          <span className="text-[13px] font-medium">Listen</span>
          <span className="tnum text-[12px] text-ink-3">{mins} min</span>
        </button>
      ) : (
        <div className="flex items-start gap-2.5 rounded-2xl border border-accent/40 bg-accent-soft/50 px-4 py-2.5" aria-live="polite">
          <p className="min-w-0 flex-1 text-[13px] leading-snug text-ink">{script[at]}</p>
          <button onClick={stop} aria-label={`Stop. Line ${at + 1} of ${script.length}`} className="relative flex h-8 w-8 shrink-0 items-center justify-center text-accent">
            <ProgressRing value={(at + 1) / script.length} size={32} stroke={2.5} className="absolute inset-0" />
            <Square size={11} className="fill-current" />
          </button>
        </div>
      )}
    </div>
  );
}

/** Symbols a speech engine reads badly, in words. */
export function spoken(t: string): string {
  return t
    .replace(/₹\s?([\d,.]+)\s?L\b/g, "$1 lakh rupees")
    .replace(/₹\s?([\d,.]+)\s?Cr\b/g, "$1 crore rupees")
    .replace(/₹\s?([\d,.]+)/g, "$1 rupees")
    .replace(/−/g, "minus ")
    .replace(/\bP\/E\b/g, "P E")
    .replace(/\bYoY\b/g, "from a year ago")
    .replace(/\bFY(\d{2})\b/g, "F Y $1");
}
