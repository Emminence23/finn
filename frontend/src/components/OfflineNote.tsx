"use client";

import { useEffect, useState } from "react";
import { WifiOff } from "lucide-react";

/** Says when the app is showing a saved copy, and from when. */
export function OfflineNote() {
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const onSaved = (e: Event) => setSavedAt((e as CustomEvent<{ at: number }>).detail.at);
    const onBack = () => {
      setSavedAt(null);
      setOffline(false);
    };
    const onOff = () => setOffline(true);
    setOffline(!navigator.onLine);
    window.addEventListener("finn:offline", onSaved);
    window.addEventListener("finn:online", onBack);
    window.addEventListener("online", onBack);
    window.addEventListener("offline", onOff);
    return () => {
      window.removeEventListener("finn:offline", onSaved);
      window.removeEventListener("finn:online", onBack);
      window.removeEventListener("online", onBack);
      window.removeEventListener("offline", onOff);
    };
  }, []);
  if (!offline && savedAt == null) return null;
  const when = savedAt
    ? new Date(savedAt).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : null;
  return (
    <div role="status" className="sticky top-0 z-40 flex items-center justify-center gap-1.5 bg-ink px-4 py-1.5 pt-[calc(6px+env(safe-area-inset-top))] text-[12px] text-bg">
      <WifiOff size={13} aria-hidden />
      {when ? `Offline. Showing what FINN saved on ${when}.` : "Offline. Showing what FINN last saved."}
    </div>
  );
}
