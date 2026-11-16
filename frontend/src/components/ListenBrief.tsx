"use client";

import { useEffect, useRef, useState } from "react";
import { Headphones, Square } from "lucide-react";
import { api } from "@/lib/api";

type Brief = { lines: { id: string; text: string }[]; seconds: number };

/** FR-PUSH-11: Today read aloud by the phone's own voice. The script is written in code on
 *  the server from the same digest, so it says what the cards say and costs nothing. Hidden
 *  where the browser has no speech engine. */
export function ListenBrief({ query }: { query: string }) {
  const [supported, setSupported] = useState(false);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const stopped = useRef(false);

  useEffect(() => {
    setSupported(typeof window !== "undefined" && "speechSynthesis" in window);
    return () => {
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    };
  }, []);
  useEffect(() => {
    let live = true;
    api<Brief>(`/digest/brief?${query}`)
      .then((b) => live && setBrief(b))
      .catch(() => live && setBrief(null));
    return () => {
      live = false;
    };
  }, [query]);

  if (!supported || !brief) return null;

  const voice = () => {
    const vs = window.speechSynthesis.getVoices();
    return vs.find((v) => v.lang === "en-IN") ?? vs.find((v) => v.lang.startsWith("en-GB")) ?? vs.find((v) => v.lang.startsWith("en"));
  };
  const play = () => {
    const synth = window.speechSynthesis;
    synth.cancel();
    stopped.current = false;
    const say = (i: number) => {
      if (stopped.current || i >= brief.lines.length) return setAt(null);
      setAt(i);
      const u = new SpeechSynthesisUtterance(brief.lines[i].text);
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
  const mins = Math.max(1, Math.round(brief.seconds / 60));

  return (
    <div className="mx-3 mt-3" data-tour="listen">
      {at === null ? (
        <button
          onClick={play}
          className="flex w-full items-center gap-2.5 rounded-2xl border border-line bg-surface px-4 py-2.5 text-left active:opacity-80"
        >
          <Headphones size={17} className="text-accent" />
          <span className="text-[14px] font-medium">Listen to the brief</span>
          <span className="tnum ml-auto text-[12px] text-ink-3">about {mins} min</span>
        </button>
      ) : (
        <div className="flex items-start gap-2.5 rounded-2xl border border-accent/40 bg-accent-soft/50 px-4 py-2.5" aria-live="polite">
          <Headphones size={17} className="mt-0.5 shrink-0 animate-pulse text-accent" />
          <p className="min-w-0 flex-1 text-[13px] leading-snug text-ink">{brief.lines[at].text}</p>
          <button onClick={stop} aria-label="Stop" className="shrink-0 rounded-full border border-line bg-surface p-1.5">
            <Square size={12} />
          </button>
        </div>
      )}
    </div>
  );
}
