"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Listen } from "./Listen";

type Brief = { lines: { id: string; text: string }[]; seconds: number };

/** FR-PUSH-11: Today read aloud. The script is written in code on the server from the same
 *  digest, so it says what the cards say and costs nothing. */
export function ListenBrief({ query }: { query: string }) {
  const [lines, setLines] = useState<string[] | null>(null);
  useEffect(() => {
    let live = true;
    api<Brief>(`/digest/brief?${query}`)
      .then((b) => live && setLines(b.lines.map((l) => l.text)))
      .catch(() => live && setLines(null));
    return () => {
      live = false;
    };
  }, [query]);
  return <Listen lines={lines} tour="listen" />;
}
