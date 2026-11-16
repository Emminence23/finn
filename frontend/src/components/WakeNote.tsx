"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { BASE } from "@/lib/api";

/** The free API host sleeps when idle and takes up to a minute to wake. If the health check
 *  is slow, say so, so a cold start doesn't read as a broken app. */
export function WakeNote() {
  const [slow, setSlow] = useState(false);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    // offline is not a sleeping server: the offline note speaks instead
    const sync = () => setOffline(!navigator.onLine);
    sync();
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);
  useEffect(() => {
    let done = false;
    const t = setTimeout(() => !done && setSlow(true), 2500);
    const ping = async () => {
      for (let i = 0; i < 20 && !done; i++) {
        try {
          const r = await fetch(`${BASE}/health`, { cache: "no-store" });
          if (r.ok) break;
        } catch {
          /* still waking */
        }
        await new Promise((r) => setTimeout(r, 3000));
      }
      done = true;
      setSlow(false);
    };
    ping();
    return () => {
      done = true;
      clearTimeout(t);
    };
  }, []);
  if (!slow || offline) return null;
  return (
    <div
      role="status"
      className="sticky top-0 z-30 flex items-center justify-center gap-2 bg-accent-soft px-4 py-2 text-[12px] text-ink-2"
    >
      <Loader2 size={13} className="animate-spin motion-reduce:animate-none" />
      Waking the server after a quiet spell, up to a minute
    </div>
  );
}
