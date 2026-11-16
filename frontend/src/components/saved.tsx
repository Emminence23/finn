"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { ProgressRing } from "@/components/ProgressRing";

/** How old a saved report is, in words. */
export function savedAgo(savedAt: number): string {
  const mins = Math.max(0, Math.round((Date.now() / 1000 - savedAt) / 60));
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins} minutes ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h} hour${h > 1 ? "s" : ""} ago`;
  const d = Math.round(h / 24);
  return `${d} day${d > 1 ? "s" : ""} ago`;
}

type Fresh = { saved_at?: number | null; refreshing?: boolean };

/** "Saved 3 days ago · Get a fresh one" (FR-PULL-19). A report FINN built in the last week is
 *  shown straight away; a fresh one is built in the background while the saved one stays on
 *  screen, and replaces it when it lands. */
export function SavedNote<T>({
  savedAt,
  refreshing = false,
  kind,
  symbol,
  onFresh,
}: {
  savedAt: number;
  refreshing?: boolean;
  kind: string;
  symbol: string;
  onFresh: (r: T) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const poll = async () => {
    setBusy(true);
    setFailed(false);
    const until = Date.now() + 3 * 60_000;
    while (live.current && Date.now() < until) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const r = await api<T & Fresh>(`/report/${symbol}?kind=${kind}`);
        if ((r.saved_at ?? 0) > savedAt) {
          if (live.current) onFresh(r);
          setBusy(false);
          return;
        }
        if (!r.refreshing) break; // the rebuild ended without saving (a source was down)
      } catch {
        /* server waking up: keep checking */
      }
    }
    if (live.current) {
      setBusy(false);
      setFailed(true);
    }
  };

  const start = async () => {
    try {
      await api("/report/refresh", { method: "POST", body: JSON.stringify({ kind, tickers: [symbol] }) });
    } catch {
      setFailed(true);
      return;
    }
    poll();
  };

  useEffect(() => {
    if (refreshing) poll(); // someone already asked for a fresh one: wait for it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-3" role="status">
      <span>Saved {savedAgo(savedAt)}</span>
      <span aria-hidden>·</span>
      {busy ? (
        <span className="flex items-center gap-1.5 text-ink-2">
          <ProgressRing size={12} /> Building a fresh one in the background
        </span>
      ) : (
        <button onClick={start} className="flex items-center gap-1 font-medium text-accent">
          <RefreshCw size={11} /> Get a fresh one
        </button>
      )}
      {failed && !busy && <span className="text-warn">Couldn&apos;t refresh just now; this saved one stands.</span>}
    </p>
  );
}
