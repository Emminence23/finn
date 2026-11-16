"use client";

import { useEffect, useState } from "react";
import { setPasscode } from "@/lib/api";

/** FR-APP-04: the demo API is passcode-protected (it spends LLM budget). The gate only
 *  appears after the API answers 401, so a local, unprotected API never shows it. */
export function Gate({ children }: { children: React.ReactNode }) {
  const [locked, setLocked] = useState(false);
  const [value, setValue] = useState("");

  useEffect(() => {
    const onUnauthorized = () => setLocked(true);
    window.addEventListener("finn:unauthorized", onUnauthorized);
    return () => window.removeEventListener("finn:unauthorized", onUnauthorized);
  }, []);

  // locked: the passcode screen alone, not the 401 errors and the tour behind it
  return (
    <>
      {!locked && children}
      {locked && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg p-4">
          <form
            className="w-full max-w-sm rounded-2xl border border-line bg-surface p-5"
            onSubmit={(e) => {
              e.preventDefault();
              setPasscode(value.trim());
              window.location.reload();
            }}
          >
            <p className="text-[22px] font-semibold tracking-[-0.02em]">FINN</p>
            <p className="mt-1 text-[14px] leading-snug text-ink-2">
              Your morning brief: what changed in your portfolio, and who you know who can explain it.
            </p>
            <p className="mt-4 text-[13px] font-medium">Demo passcode</p>
            <p className="text-[12px] text-ink-2">It&apos;s in the covering note, and keeps the shared AI budget for reviewers.</p>
            <input
              autoFocus
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="mt-2 w-full rounded-xl border border-line bg-bg px-3 py-2.5 text-[15px] outline-none focus:border-accent"
              aria-label="Passcode"
            />
            <button className="mt-3 w-full rounded-xl bg-ink py-2.5 text-[15px] font-medium text-surface">
              Unlock
            </button>
          </form>
        </div>
      )}
    </>
  );
}
