"use client";

import { useEffect } from "react";

/** Registers the app-shell service worker (production builds only; dev reloads would fight it). */
export function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* offline support is a convenience */
    });
  }, []);
  return null;
}
