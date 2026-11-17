"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Building2, ChevronRight, RotateCcw, User, Users, X } from "lucide-react";
import { api, stream, type Contact, type ResearchSummary, useApi } from "@/lib/api";
import { shortName } from "@/lib/fmt";
import { Blocks, type PullReply } from "@/components/pull";
import { ProgressRing, useElapsed } from "@/components/ProgressRing";
import { Header } from "@/components/ui";
import { SavedNote } from "@/components/saved";
import { useTitle } from "@/lib/title";
import { explain } from "@/lib/errors";

/** Pull (FR-PULL-13): ask about a company in plain words and FINN answers in the thread, from
 *  the company's annual report, last four earnings calls and reported numbers. Code decides
 *  which analysis a message asks for and builds it; only open questions go to the model, and
 *  its answer keeps cited points only. A follow-up stays on the company in the conversation. */

type Msg =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "finn"; asked: string; reply: PullReply }
  | { id: string; role: "finn"; asked: string; people: Contact[]; themes: string[] }
  | { id: string; role: "finn"; asked: string; error: string; detail?: string; retry?: boolean; code?: string };

const KEY = "finn.pull";
const STARTERS = [
  "Should I buy Trent?",
  "Compare TCS and Infosys",
  "How was HDFC Bank's latest quarter?",
  "L&T: promised vs delivered over the last four quarters",
  "Is Titan expensive?",
  "How is my portfolio doing?",
];

const uid = () => Math.random().toString(36).slice(2, 10);

/** After a dropped stream: the server keeps reading and caches the result, so check back
 *  every few seconds for up to four minutes instead of giving up. */
async function waitForBuild(sym: string, say: (m: string) => void): Promise<boolean> {
  const until = Date.now() + 4 * 60_000;
  while (Date.now() < until) {
    say("Still reading. The connection dropped, so FINN is checking back…");
    await new Promise((r) => setTimeout(r, 5000));
    try {
      await api(`/research/${sym}`);
      return true;
    } catch {
      /* not built yet */
    }
  }
  return false;
}

function load(): { msgs: Msg[]; symbol: string | null } {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* storage unavailable: start empty */
  }
  return { msgs: [], symbol: null };
}

function save(msgs: Msg[], symbol: string | null) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ msgs: msgs.slice(-24), symbol }));
  } catch {
    /* storage full or unavailable: the thread is a convenience */
  }
}

export default function Ask() {
  useTitle("Ask");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [symbol, setSymbol] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<{ text: string; open: boolean } | null>(null);
  const [building, setBuilding] = useState<{ symbol: string; message: string } | null>(null);
  const { data: ready } = useApi<ResearchSummary[]>("/research");
  const { data: people } = useApi<Contact[]>("/people");
  const end = useRef<HTMLDivElement>(null);
  const lastReply = useRef<HTMLDivElement>(null);
  const restored = useRef(false);

  useEffect(() => {
    const s = load();
    setMsgs(s.msgs);
    setSymbol(s.symbol);
    restored.current = true;
    const asked = new URLSearchParams(window.location.search).get("q");
    if (asked) {
      window.history.replaceState(null, "", "/ask");
      setTimeout(() => send(asked), 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (restored.current) save(msgs, symbol);
  }, [msgs, symbol]);

  const themes = useMemo(() => {
    const all = new Set<string>();
    people?.forEach((p) => p.themes?.forEach((t) => all.add(t)));
    return [...all];
  }, [people]);

  /** A message that names no company may name a person or a theme in the network. */
  const network = useCallback(
    (text: string) => {
      const words = text.toLowerCase().match(/[a-z][a-z.&-]{2,}/g) ?? [];
      const hit = (s: string | null | undefined) => !!s && words.some((w) => s.toLowerCase().split(/[\s,]+/).includes(w));
      const ps = (people ?? []).filter((p) => p.is_contact && (hit(p.name) || hit(p.current))).slice(0, 4);
      const ts = themes.filter((t) => words.some((w) => t.toLowerCase().includes(w) && w.length >= 3)).slice(0, 3);
      return { ps, ts };
    },
    [people, themes],
  );

  const send = useCallback(
    async (text: string, opts: { intent?: string; label?: string; symbol?: string | null } = {}) => {
      const t = text.trim();
      if (!t || busy) return;
      const ctx = opts.symbol !== undefined ? opts.symbol : symbol;
      setQ("");
      setMsgs((m) => [...m, { id: uid(), role: "user", text: opts.label ?? t }]);
      setBusy({ text: t, open: !opts.intent && /^\s*(why|how|explain|what caused|what drove)/i.test(t) });
      requestAnimationFrame(() => end.current?.scrollIntoView({ block: "end" }));
      try {
        const reply = await api<PullReply>("/pull/chat", {
          method: "POST",
          body: JSON.stringify({ message: t, symbol: ctx, intent: opts.intent }),
          signal: AbortSignal.timeout(150_000), // longer than any answer FINN builds
        });
        if (reply.kind === "pick") {
          const { ps, ts } = network(t);
          if (ps.length || ts.length) {
            setMsgs((m) => [...m, { id: uid(), role: "finn", asked: t, people: ps, themes: ts }]);
            return;
          }
        }
        if (reply.kind === "reply" && reply.symbol) setSymbol(reply.symbol);
        setMsgs((m) => [...m, { id: uid(), role: "finn", asked: t, reply }]);
      } catch (e) {
        const x = explain(e);
        setMsgs((m) => [...m, { id: uid(), role: "finn", asked: t, error: x.title, detail: x.detail, retry: x.retry, code: x.code }]);
      } finally {
        setBusy(null);
        requestAnimationFrame(() => lastReply.current?.scrollIntoView({ block: "start", behavior: "smooth" }));
      }
    },
    [busy, symbol, network],
  );

  const readLive = useCallback(
    async (sym: string, asked: string) => {
      setBuilding({ symbol: sym, message: "Starting…" });
      let ok = false;
      let failed = false;
      try {
        await stream(`/research/${sym}/stream`, (event, data) => {
          const d = data as Record<string, unknown>;
          if (event === "progress") setBuilding({ symbol: sym, message: String(d.message) });
          else if (event === "result") ok = true;
          else if (event === "error") {
            failed = true;
            setMsgs((m) => [...m, { id: uid(), role: "finn", asked, error: String(d.message) }]);
          }
        });
      } catch {
        /* the connection dropped (a phone locking, a proxy); the read carries on server-side */
      }
      if (!ok && !failed) ok = await waitForBuild(sym, (message) => setBuilding({ symbol: sym, message }));
      setBuilding(null);
      if (ok) send(asked, { symbol: sym, label: `Read ${sym}, then: ${asked}` });
      else if (!failed)
        setMsgs((m) => [...m, { id: uid(), role: "finn", asked, error: `Still reading ${sym}. Ask again in a minute and FINN will pick it up where it is.` }]);
    },
    [send],
  );

  const lastFinn = [...msgs].reverse().find((m) => m.role === "finn")?.id;
  const company = msgs.findLast?.((m) => m.role === "finn" && "reply" in m && m.reply.kind === "reply" && m.reply.symbol === symbol);
  const companyName = company && "reply" in company && company.reply.kind === "reply" ? shortName(company.reply.company) : symbol;

  return (
    <main className="pb-[150px]">
      <Header
        title="Ask FINN"
        sub="Research a company from its annual report, calls and numbers"
        right={
          msgs.length > 0 && (
            <button
              onClick={() => {
                setMsgs([]);
                setSymbol(null);
              }}
              className="flex items-center gap-1 rounded-full border border-line px-3 py-1.5 text-[13px] font-medium text-ink-2"
            >
              <RotateCcw size={13} /> New
            </button>
          )
        }
      />

      {msgs.length === 0 && (
        <div className="px-3">
          <div className="rounded-2xl border border-line bg-surface p-4">
            <p className="text-[15px] font-semibold">Ask about any listed company</p>
            <p className="mt-1 text-[13px] leading-snug text-ink-2">
              Any NSE stock, in your own words: buy or sell, results, valuation, bull vs bear, a comparison, your portfolio. FINN fetches today&apos;s reported numbers, prices and filings and works the answer out in code, so every figure is computed, not written by a model.
            </p>
            <p className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Try</p>
            <div className="mt-1.5 flex flex-col items-start gap-1.5">
              {STARTERS.map((s) => (
                <button key={s} onClick={() => send(s)} className="rounded-2xl border border-line bg-bg px-3 py-1.5 text-left text-[13px] active:opacity-70">
                  {s}
                </button>
              ))}
            </div>
          </div>
          {ready && ready.length > 0 && (
            <>
              <p className="mt-4 px-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Ready to read</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {ready.map((r) => (
                  <button
                    key={r.symbol}
                    onClick={() => send(shortName(r.company), { symbol: r.symbol, intent: "overview" })}
                    className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-[13px] active:opacity-70"
                  >
                    <Building2 size={13} className="text-ink-3" /> {shortName(r.company)}
                  </button>
                ))}
              </div>
            </>
          )}
          <Link href="/people" className="mt-4 flex items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3 active:opacity-80">
            <Users size={18} className="shrink-0 text-accent" />
            <span className="min-w-0 flex-1">
              <span className="block text-[14px] font-medium">Your network</span>
              <span className="block text-[12px] text-ink-2">Or ask here: a name, or a theme such as EMS</span>
            </span>
            <ChevronRight size={16} className="shrink-0 text-ink-3" />
          </Link>
        </div>
      )}

      <div className="space-y-3 px-3">
        {msgs.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl rounded-br-md bg-ink px-3.5 py-2 text-[14px] leading-snug text-bg">{m.text}</p>
            </div>
          ) : (
            <div key={m.id} ref={m.id === lastFinn ? lastReply : undefined} className="scroll-mt-3">
              <FinnMessage
                m={m}
                latest={m.id === lastFinn}
                send={send}
                readLive={readLive}
                building={building}
                replace={(reply) => setMsgs((all) => all.map((x) => (x.id === m.id ? { ...x, reply } : x)))}
              />
            </div>
          ),
        )}
        {busy && <Thinking open={busy.open} />}
        <div ref={end} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(q);
        }}
        className="fixed inset-x-0 z-30 mx-auto max-w-xl px-3"
        style={{ bottom: "calc(72px + env(safe-area-inset-bottom))" }}
      >
        {symbol && (
          <p className="mb-1.5 flex justify-start">
            <span className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-0.5 text-[12px] text-ink-2 shadow-sm">
              About {companyName}
              <button type="button" onClick={() => setSymbol(null)} aria-label="Stop asking about this company" className="-mr-1 p-0.5 text-ink-3">
                <X size={12} />
              </button>
            </span>
          </p>
        )}
        <label data-tour="askbox" className="flex items-center gap-2 rounded-2xl border border-line bg-surface py-1.5 pl-3.5 pr-1.5 shadow-lg focus-within:border-accent">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={symbol ? `Ask about ${companyName}…` : "A company, or a question about one…"}
            className="min-w-0 flex-1 bg-transparent py-1.5 text-[16px] outline-none placeholder:text-ink-3"
            enterKeyHint="send"
            aria-label="Ask FINN"
          />
          <button type="submit" disabled={!q.trim() || !!busy} aria-label="Send" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-white disabled:opacity-40">
            <ArrowUp size={18} />
          </button>
        </label>
      </form>
    </main>
  );
}

function Thinking({ open }: { open: boolean }) {
  const s = useElapsed(true);
  const stage = !open
    ? s < 2
      ? "Fetching the reported numbers, prices and filings…"
      : "Working out the figures and writing the report…"
    : s < 3
      ? "Finding the relevant pages in the calls and annual report…"
      : s < 9
        ? "Reading those pages and the reported numbers…"
        : "Checking every point has a source…";
  return (
    <div className="flex items-center gap-2.5 rounded-2xl border border-line bg-surface px-4 py-3 text-[13px] text-ink-2" role="status">
      <ProgressRing size={16} /> {stage}
      {s >= 3 && <span className="tnum ml-auto text-[12px] text-ink-3">{s} s</span>}
    </div>
  );
}

function FinnMessage({
  m,
  latest,
  send,
  readLive,
  building,
  replace,
}: {
  m: Exclude<Msg, { role: "user" }>;
  replace: (reply: PullReply) => void;
  latest: boolean;
  send: (t: string, o?: { intent?: string; label?: string; symbol?: string | null }) => void;
  readLive: (sym: string, asked: string) => void;
  building: { symbol: string; message: string } | null;
}) {
  const docs = useMemo(() => new Map(("reply" in m && m.reply.kind === "reply" ? m.reply.documents : []).map((d) => [d.id, d])), [m]);
  const card = "rounded-2xl border border-line bg-surface p-4";

  if ("error" in m)
    return (
      <div className={card} role="alert" data-error-code={m.code}>
        <p className="text-[14px] font-medium leading-snug">{m.error}</p>
        {m.detail && <p className="mt-1 text-[12px] leading-snug text-ink-3">{m.detail}</p>}
        {m.retry && latest && (
          <button onClick={() => send(m.asked)} className="mt-2 text-[13px] font-medium text-accent">
            Try again
          </button>
        )}
      </div>
    );

  if ("people" in m)
    return (
      <div className={card}>
        <p className="text-[13px] text-ink-2">From your network:</p>
        <ul className="mt-2 divide-y divide-line">
          {m.people.map((p) => (
            <li key={p.id}>
              <Link href={`/people/${p.id}`} className="flex items-center gap-3 py-2 active:opacity-70">
                <User size={15} className="shrink-0 text-ink-3" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-medium">{p.name}</span>
                  <span className="block truncate text-[12px] text-ink-3">{p.current}</span>
                </span>
                <ChevronRight size={15} className="text-ink-3" />
              </Link>
            </li>
          ))}
          {m.themes.map((t) => (
            <li key={t}>
              <Link href={`/people?theme=${encodeURIComponent(t)}`} className="flex items-center gap-3 py-2 text-[14px] active:opacity-70">
                <Users size={15} className="shrink-0 text-ink-3" /> Who knows <span className="font-medium">{t}</span>?
              </Link>
            </li>
          ))}
        </ul>
      </div>
    );

  const r = m.reply;
  if (r.kind === "pick")
    return (
      <div className={card}>
        <p className="text-[14px] leading-snug">Which company? Type its name or NSE ticker (any listed company works), or pick one FINN has read:</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {r.ready.map((c) => (
            <button key={c.symbol} onClick={() => send(m.asked, { symbol: c.symbol, label: `${shortName(c.company)}: ${m.asked}` })} className="rounded-full border border-line bg-bg px-3 py-1 text-[13px] active:opacity-70">
              {shortName(c.company)}
            </button>
          ))}
        </div>
      </div>
    );

  if (r.kind === "not_built") {
    const mine = building?.symbol === r.symbol;
    return (
      <div className={card}>
        {!r.covered ? (
          <p className="text-[14px] leading-snug">{r.symbol} isn&apos;t an NSE-listed company FINN knows. Check the ticker, or try one FINN has read.</p>
        ) : (
          <>
            <p className="text-[14px] leading-snug">
              FINN hasn&apos;t read {r.company ? shortName(r.company) : r.symbol} yet. Reading its latest annual report and last four earnings calls takes about two minutes.
            </p>
            {mine ? (
              <p className="mt-2 flex items-center gap-2 text-[13px] text-ink-2" role="status">
                <ProgressRing size={15} /> {building.message}
              </p>
            ) : r.builds_left > 0 ? (
              <button onClick={() => readLive(r.symbol, m.asked)} disabled={!!building} className="mt-3 rounded-full bg-accent px-4 py-1.5 text-[13px] font-semibold text-white disabled:opacity-40">
                Read it now · {r.builds_left} left today
              </button>
            ) : (
              <p className="mt-2 text-[13px] text-ink-3">Today&apos;s live reads are used up on this demo.</p>
            )}
          </>
        )}
      </div>
    );
  }

  const base = r.symbol ? `/c/${r.symbol}` : "/";
  return (
    <div className={card}>
      <p className="flex items-baseline justify-between gap-2">
        <span className="text-[16px] font-semibold tracking-[-0.01em]">
          {r.symbol ? shortName(r.company) : r.company}
          <span className="font-normal text-ink-3"> · {r.title}</span>
        </span>
        {r.symbol && (
          <Link href={base} className="shrink-0 text-[12px] font-medium text-accent">
            Full page →
          </Link>
        )}
      </p>
      {r.symbol && r.saved_at && r.from_saved && (
        <div className="mt-1">
          <SavedNote<PullReply> key={r.saved_at} savedAt={r.saved_at} refreshing={r.refreshing} kind={r.intent} symbol={r.symbol} onFresh={replace} />
        </div>
      )}
      {r.notice && <p className="mt-2 rounded-xl bg-warn-soft/60 px-3 py-2 text-[12px] leading-snug">{r.notice}</p>}
      <div className="mt-3">
        <Blocks blocks={r.blocks} docs={docs} base={base} />
      </div>
      {latest && (
        <div className="mt-4 border-t border-line pt-3">
          {r.blocks[0]?.type === "answer" && r.blocks[0].follow_ups.length > 0 && (
            <div className="mb-2 flex flex-col items-start gap-1.5">
              {r.blocks[0].follow_ups.map((f) => (
                <button key={f} onClick={() => send(f, { symbol: r.symbol })} className="rounded-2xl border border-line bg-bg px-3 py-1.5 text-left text-[13px] active:opacity-70">
                  {f}
                </button>
              ))}
            </div>
          )}
          {r.menu.length > 0 && <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">More on {shortName(r.company)}</p>}
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {r.menu.map((x) => (
              <button
                key={x.intent}
                onClick={() => send(x.label, { intent: x.intent, symbol: r.symbol })}
                className={`rounded-full border px-3 py-1 text-[12px] active:opacity-70 ${x.intent === "ledger" ? "border-accent/50 bg-accent-soft font-medium text-accent" : "border-line bg-bg text-ink-2"}`}
              >
                {x.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
