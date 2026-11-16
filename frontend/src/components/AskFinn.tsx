"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, CircleSlash, Loader2 } from "lucide-react";
import { ApiError, api, type DocRef, type QaAnswer } from "@/lib/api";
import { CiteChips, cleanClaim } from "./research";
import { AiTag, Panel } from "./ui";

/** Ask FINN about one company. Answers come only from the documents and numbers FINN has
 *  read for it; every point carries its citation, and uncited points are removed by the API. */
export function AskFinn({
  symbol,
  docs,
  suggestions,
  initial,
}: {
  symbol: string;
  docs: Map<string, DocRef>;
  suggestions: string[];
  initial?: string;
}) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [thread, setThread] = useState<QaAnswer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const asked = useRef(false);

  const ask = async (question: string) => {
    const text = question.trim();
    if (text.length < 3 || busy) return;
    setBusy(text);
    setError(null);
    setQ("");
    try {
      const a = await api<QaAnswer>(`/research/${symbol}/ask`, {
        method: "POST",
        body: JSON.stringify({ question: text }),
      });
      setThread((t) => [a, ...t]);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 429
          ? "Today's questions are used up on this demo. The research below is still all there."
          : "FINN couldn't answer just now (the AI provider may be busy). Try again in a minute.",
      );
      setQ(text);
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    if (initial && !asked.current) {
      asked.current = true;
      ask(initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  const pages = (a: QaAnswer) => a.searched.reduce((n, s) => n + s.pages.length, 0);

  return (
    <Panel className="p-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(q);
        }}
      >
        <label className="flex items-center gap-2 rounded-xl border border-line bg-bg px-3 py-2 focus-within:outline-2 focus-within:outline-accent">
          <span className="sr-only">Ask a question about this company</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            maxLength={300}
            placeholder="Ask about this company…"
            className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-ink-3"
          />
          <button
            type="submit"
            disabled={q.trim().length < 3 || !!busy}
            aria-label="Ask"
            className="rounded-full bg-accent p-1.5 text-white disabled:opacity-30"
          >
            <ArrowUp size={15} />
          </button>
        </label>
      </form>

      {thread.length === 0 && !busy && suggestions.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button
              key={s}
              onClick={() => ask(s)}
              className="rounded-full border border-line px-2.5 py-1 text-left text-[12px] leading-snug text-ink-2 active:opacity-70"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {busy && (
        <div className="mt-3" role="status">
          <p className="text-[13px] font-medium">{busy}</p>
          <p className="mt-1 flex items-center gap-1.5 text-[12px] text-ink-3">
            <Loader2 size={13} className="animate-spin motion-reduce:animate-none" />
            Finding the relevant pages in the calls and annual report…
          </p>
        </div>
      )}
      {error && <p className="mt-3 text-[13px] text-ink-2">{error}</p>}

      {thread.map((a, i) => (
        <div key={`${a.question}-${i}`} className="mt-4 border-t border-line pt-3 first:mt-3">
          <p className="text-[13px] font-semibold">{a.question}</p>
          {a.answerable === "no" && (
            <p className="mt-1.5 flex items-center gap-1.5 text-[12px] text-ink-2">
              <CircleSlash size={13} className="text-ink-3" />
              The documents FINN read don&apos;t answer this.
            </p>
          )}
          <ul className="mt-1.5 space-y-1.5">
            {a.points.map((p, j) => (
              <li key={j} className="flex gap-2 text-[13px] leading-snug">
                <span className="mt-[7px] size-1 shrink-0 rounded-full bg-ink-3" aria-hidden />
                <span>
                  {cleanClaim(p.text)}
                  <CiteChips cites={p.cites} docs={docs} />
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-2">
            <AiTag from={`read ${pages(a)} pages`} model={a.model} />
            {a.dropped > 0 && (
              <span className="ml-1 text-[11px] text-ink-3">
                · {a.dropped} uncited {a.dropped === 1 ? "point" : "points"} removed
              </span>
            )}
          </div>
          {i === 0 && a.follow_ups.length > 0 && !busy && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {a.follow_ups.map((f) => (
                <button
                  key={f}
                  onClick={() => ask(f)}
                  className="rounded-full border border-line px-2.5 py-1 text-left text-[12px] leading-snug text-ink-2 active:opacity-70"
                >
                  {f}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </Panel>
  );
}
