// Read state for Today, per viewer: which cards this browser has already shown, and which
// ones the viewer acted on. A personal convenience only, so browser storage is enough; the
// feed works the same when storage is unavailable (nothing is marked).
import { useCallback, useEffect, useRef, useState } from "react";

const SEEN_KEY = "finn.seen";
const OPENED_KEY = "finn.opened";
const MAX = 500; // keep storage bounded: the most recent ids win

function read(key: string): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(key) ?? "[]");
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

function write(key: string, ids: string[]) {
  try {
    localStorage.setItem(key, JSON.stringify(ids.slice(-MAX)));
  } catch {
    /* storage unavailable: read state lasts for this page only */
  }
}

export type ReadState = {
  /** null until storage has been read, and on a first visit (nothing to compare with) */
  isNew: (id: string) => boolean;
  opened: (id: string) => boolean;
  markOpened: (id: string) => void;
  newCount: number;
  firstVisit: boolean;
};

export function useReadState(ids: string[]): ReadState {
  const before = useRef<Set<string> | null>(null);
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [ready, setReady] = useState(false);
  const key = ids.join(",");

  useEffect(() => {
    if (before.current === null) {
      before.current = new Set(read(SEEN_KEY)); // snapshot from earlier visits, taken once
      setOpened(new Set(read(OPENED_KEY)));
      setReady(true);
    }
    const seen = read(SEEN_KEY);
    const merged = [...seen.filter((x) => !ids.includes(x)), ...ids];
    write(SEEN_KEY, merged);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const prev = before.current;
  const firstVisit = !ready || !prev || prev.size === 0;
  const isNew = useCallback((id: string) => !firstVisit && !!prev && !prev.has(id), [firstVisit, prev]);
  const markOpened = useCallback((id: string) => {
    setOpened((o) => {
      const next = new Set(o).add(id);
      write(OPENED_KEY, [...next]);
      return next;
    });
  }, []);
  return {
    isNew,
    opened: (id) => opened.has(id),
    markOpened,
    newCount: firstVisit ? 0 : ids.filter((id) => !prev!.has(id)).length,
    firstVisit,
  };
}
