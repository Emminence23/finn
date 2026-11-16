"use client";

import { useEffect, useId, useSyncExternalStore } from "react";

/** Whole pages, not pieces: every component that fetches data for a page registers while its
 *  first load is in flight, and the page stays behind a loading bar until none is left. The
 *  bar counts those loads as they finish. Loads that start after the page appeared (a sheet
 *  opened, a question asked) never bring the bar back: they show their own progress. */

type State = { active: boolean; pending: number; peak: number; started: number };

const pending = new Set<string>();
let state: State = { active: true, pending: 0, peak: 0, started: 0 };
const listeners = new Set<() => void>();
let settle: ReturnType<typeof setTimeout> | undefined;
let cap: ReturnType<typeof setTimeout> | undefined;
/** A link was tapped: hold the bar until the new route has mounted and registered. */
let awaiting: string | null = null;

/** Long enough for a component that mounts once its parent's data arrives to register. */
const SETTLE_MS = 160;
/** A sleeping free server can take a minute; past that, show what there is. */
const CAP_MS = 70_000;

function emit(next: Partial<State>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

function check() {
  clearTimeout(settle);
  if (!state.active || awaiting) return;
  if (pending.size === 0) settle = setTimeout(() => pending.size === 0 && finish(), SETTLE_MS);
}

function finish() {
  clearTimeout(cap);
  emit({ active: false, pending: 0 });
}

/** A link to another page was tapped: the bar shows at once, before the route's code. */
export function startNavigation(path: string) {
  awaiting = path;
  clearTimeout(cap);
  clearTimeout(settle);
  emit({ active: true, pending: 0, peak: 0, started: Date.now() });
  cap = setTimeout(() => {
    awaiting = null;
    finish();
  }, CAP_MS);
}

/** A new page has mounted: show the bar until its loads are done. */
export function beginPage() {
  awaiting = null;
  clearTimeout(cap);
  const started = state.active && state.started ? state.started : Date.now();
  emit({ active: true, pending: pending.size, peak: pending.size, started });
  cap = setTimeout(finish, CAP_MS);
  check();
}

function add(id: string) {
  pending.add(id);
  if (state.active) emit({ pending: pending.size, peak: Math.max(state.peak, pending.size) });
  check();
}

function remove(id: string) {
  if (!pending.delete(id)) return;
  if (state.active) emit({ pending: pending.size });
  check();
}

export function usePageLoadState(): State {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
    () => state,
  );
}

/** Call with true while this component's first data is loading. */
export function usePageLoading(loading: boolean) {
  const id = useId();
  useEffect(() => {
    if (!loading) return;
    add(id);
    return () => remove(id);
  }, [loading, id]);
}
