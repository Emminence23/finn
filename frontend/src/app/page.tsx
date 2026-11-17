"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Compass, FileText, SlidersHorizontal, Target, TrendingDown, TrendingUp } from "lucide-react";
import clsx from "clsx";
import { type Alert, type Card, type CarryItem, type Digest, useApi } from "@/lib/api";
import { CATEGORY_LABEL, day, pct } from "@/lib/fmt";
import { type CardRead, FeedCard, NoteRow, sessionMoves } from "@/components/cards";
import { useReadState } from "@/lib/seen";
import { useSlow } from "@/lib/slow";
import { ListenBrief } from "@/components/ListenBrief";
import { MoversStrip } from "@/components/market";
import { MeetingPrep } from "@/components/meetings";
import { AlertSettings } from "@/components/AlertSettings";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ReachButtons, firstName } from "@/components/network";
import { AiTag, Avatar, ErrorNote, Panel, Segmented, Skeleton, SlowHint } from "@/components/ui";
import { useTitle } from "@/lib/title";

type Win = "24h" | "3d" | "7d" | "14d" | "21d" | "30d" | "custom";
const WINDOWS: { value: Win; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "3d", label: "3d" },
  { value: "7d", label: "7d" },
  { value: "14d", label: "14d" },
  { value: "21d", label: "21d" },
  { value: "30d", label: "30d" },
  { value: "custom", label: "Dates" },
];
type Range = { from: string; to: string };

/** "2026-11-15" minus n days, as YYYY-MM-DD (date-only, no time-zone drift). */
function minusDays(d: string, n: number): string {
  const t = new Date(`${d}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() - n);
  return t.toISOString().slice(0, 10);
}
const WIN_KEY = "finn.window";
/** "2026-11-17T11:47" (IST, as the API sends it) -> "11:47" */
const clock = (ts: string) => ts.slice(11, 16);
const ICON_BTN = "flex h-9 w-9 items-center justify-center rounded-full border border-line bg-surface text-ink-2";

export default function Today() {
  useTitle("Today");
  const [win, setWin] = useState<Win>("24h");
  const [settings, setSettings] = useState(false);
  const [range, setRange] = useState<Range | null>(null);
  const [lastEnd, setLastEnd] = useState<string | null>(null);
  useEffect(() => {
    try {
      const w = localStorage.getItem(WIN_KEY) as Win | null;
      if (w && w !== "custom" && WINDOWS.some((x) => x.value === w)) setWin(w);
    } catch {
      /* default window */
    }
  }, []);
  const choose = (w: Win) => {
    setWin(w);
    if (w === "custom") {
      // default to the two weeks before the data's "now", e.g. to reach an older event
      const to = (lastEnd ?? new Date().toISOString()).slice(0, 10);
      setRange((r) => r ?? { from: minusDays(to, 14), to });
      return;
    }
    try {
      localStorage.setItem(WIN_KEY, w);
    } catch {
      /* not remembered */
    }
  };

  const path =
    win === "custom" && range
      ? `/digest?start=${range.from}T00:00:00&end=${range.to}T23:59:59`
      : `/digest?window=${win === "custom" ? "7d" : win}`;
  const { data, error, isLoading, mutate } = useApi<Digest>(path, {
    refreshInterval: (d) => (d?.lead_ai_pending ? 6000 : 0), // pick up the AI note once written
  });
  const now = data?.window.end ?? new Date().toISOString();
  useEffect(() => {
    if (data?.window.name) setLastEnd((e) => e ?? data.window.end);
  }, [data]);

  const slow = useSlow(isLoading || !data);
  // the clock is the phone's, so these are set after hydration (a prerender can't know them)
  const [hello, setHello] = useState({ greeting: "Today", date: "" });
  useEffect(() => setHello({ greeting: greeting(), date: todayLabel() }), []);

  return (
    <main>
      <div className="flex items-center gap-1.5 px-4 pt-[calc(10px+env(safe-area-inset-top))]">
        <p className="min-w-0 flex-1 truncate text-[12px] text-ink-2">
          {hello.date}
          {data && <>{hello.date ? " · " : ""}filings to {day(data.freshness?.filings_as_of ?? data.window.end)}</>}
        </p>
        <button onClick={() => window.dispatchEvent(new Event("finn:tour"))} aria-label="Tour" title="Tour" className={ICON_BTN}>
          <Compass size={17} />
        </button>
        <Link href="/accuracy" aria-label="How accurate is FINN" title="Accuracy" className={ICON_BTN}>
          <Target size={17} />
        </Link>
        <ThemeToggle className={ICON_BTN} />
        <button onClick={() => setSettings(true)} aria-label="Alert settings" title="Alert settings" className={ICON_BTN}>
          <SlidersHorizontal size={17} />
        </button>
      </div>
      <header className="px-4 pt-3" data-tour="lead">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">{hello.greeting}</h1>
        {data && !isLoading ? (
          <Summary lead={data.lead_ai?.text ?? data.lead ?? ""} ai={!!data.lead_ai} />
        ) : (
          <div className="mt-3 space-y-2" aria-label="Reading your portfolio's filings">
            <Skeleton className="h-5 w-11/12" />
            <Skeleton className="h-5 w-4/5" />
            <Skeleton className="h-5 w-2/3" />
            {slow && <SlowHint retry={() => mutate()} />}
          </div>
        )}
        {data && !isLoading && (
          <div className="mt-3">
            <ListenBrief query={path.split("?")[1]} />
          </div>
        )}
      </header>
      <div className="px-4 pt-4">
        <Segmented label="Time window" value={win} options={WINDOWS} onChange={choose} />
        {win === "custom" && range && <RangePicker range={range} onChange={setRange} />}
      </div>
      {data?.freshness?.stale && <StaleNote f={data.freshness} />}

      {error && !data ? (
        <div className="mt-4">
          <ErrorNote error={error} retry={() => mutate()} />
        </div>
      ) : !data || isLoading ? (
        <FeedSkeleton />
      ) : (
        <Note d={data} now={now} />
      )}
      <AlertSettings open={settings} onClose={() => setSettings(false)} onSaved={() => mutate()} />
    </main>
  );
}

/** By the clock in India, wherever the phone is: morning from 4 am, afternoon from noon,
 *  evening from 4 pm, and something for the small hours that isn't "good night". */
function greeting(): string {
  const h = Number(new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: "Asia/Kolkata" }).format(new Date()));
  if (h >= 4 && h < 12) return "Good morning.";
  if (h >= 12 && h < 16) return "Good afternoon.";
  if (h >= 16 && h < 22) return "Good evening.";
  return "Up late?";
}

const SUMMARY_KEY = "finn.summary.open";

/** The day's summary, folded by default: a tap away, never in the way. */
function Summary({ lead, ai }: { lead: string; ai: boolean }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    try {
      setOpen(localStorage.getItem(SUMMARY_KEY) === "1");
    } catch {
      /* storage unavailable: folded */
    }
  }, []);
  const paras = lead.split("\n\n").filter(Boolean);
  if (!paras.length) return null;
  const toggle = () => {
    setOpen(!open);
    try {
      localStorage.setItem(SUMMARY_KEY, open ? "0" : "1");
    } catch {
      /* storage unavailable */
    }
  };
  return (
    <div className="mt-2">
      <button onClick={toggle} aria-expanded={open} className="flex w-full items-start gap-2 text-left">
        <span className={open ? "text-[13px] font-medium text-ink-2" : "line-clamp-1 min-w-0 flex-1 text-[15px] text-ink-2"}>{open ? "Hide the summary" : paras[0]}</span>
        <ChevronDown size={16} className={`mt-0.5 shrink-0 text-ink-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-2 space-y-2.5">
          {ai && <AiTag from="written from FINN's ranking; every figure checked by code" />}
          {paras.map((para, i) => (
            <p key={i} className={i === 0 ? "text-[18px] leading-[1.45] tracking-[-0.01em] text-ink" : "text-[16px] leading-[1.5] text-ink"}>
              {para}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function todayLabel(): string {
  return new Date().toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

/** Today as a note: what needs you, what's worth knowing, what was set aside and why.
 *  The bands are decided in code (intel/note.py); each band says its rule. */
function Note({ d, now }: { d: Digest; now: string }) {
  // one card per stock: a company's other items sit under its card, not beside it
  const actAll = d.cards.filter((c) => c.band === "act");
  const act = actAll.filter((c, i) => actAll.findIndex((x) => x.symbol === c.symbol) === i);
  const alsoFor = (c: Card) => actAll.filter((x) => x.symbol === c.symbol && x.id !== c.id);
  const know = d.cards.filter((c) => c.band === "know");
  const aside = d.cards.filter((c) => c.band === "aside");
  const ids = useMemo(() => d.cards.map((c) => String(c.id)), [d.cards]);
  const rs = useReadState(ids);
  const helped = new Set<string>();
  const readOf = (c: Card) => {
    const id = String(c.id);
    return { isNew: rs.isNew(id), opened: rs.opened(id), onOpen: () => rs.markOpened(id) };
  };
  const firstFor = (c: Card) => {
    const f = !helped.has(c.symbol);
    helped.add(c.symbol);
    return f;
  };
  return (
    <>
      <MeetingPrep />
      {(act.length > 0 || (d.carry?.length ?? 0) > 0) && (
        <>
          {act.length > 0 ? (
            <Band title="Needs you" rule="Important, at a position of real size (at least half an equal share). One card per stock." count={act.length} />
          ) : (
            <Band title="Still open" rule="Nothing new needs you. These events at your larger positions, from the two weeks before, still might." />
          )}
          <div className="space-y-3">
            {act.slice(0, ACT_TOP).map((c) => (
              <div key={c.id}>
                <FeedCard card={c} now={now} showHelper={firstFor(c)} read={readOf(c)} />
                {alsoFor(c).length > 0 && (
                  <Panel className="mx-3 mt-1.5 divide-y divide-line">
                    <p className="px-4 pt-2.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Also from {c.short ?? c.company}</p>
                    {alsoFor(c).map((x) => (
                      <NoteRow key={x.id} card={x} now={now} read={readOf(x)} />
                    ))}
                  </Panel>
                )}
              </div>
            ))}
          </div>
          {act.length > ACT_TOP && <MoreActs cards={act.slice(ACT_TOP).flatMap((c) => [c, ...alsoFor(c)])} now={now} readOf={readOf} />}
          {(d.carry?.length ?? 0) > 0 && <Carry items={d.carry!} first={act.length === 0} />}
        </>
      )}
      <Moves alerts={d.alerts} />
      {know.length > 0 && (
        <>
          <Band title="Worth knowing" rule="Everything else that made the cut. Tap a line for the detail." count={know.length} />
          <Feed cards={know} now={now} readOf={readOf} firstFor={firstFor} newCount={rs.newCount} />
        </>
      )}
      {act.length === 0 && know.length === 0 && !(d.carry?.length) && (
        <Panel className="mt-6 p-4 text-[14px] text-ink-2">Nothing material in this window. Quiet is good.</Panel>
      )}
      {d.nudges.length > 0 && <Nudges d={d} />}
      <SetAside d={d} aside={aside} now={now} />
      <MoversStrip className="mt-6" />
      <p className="px-4 pb-6 pt-4 text-center text-[11px] text-ink-3">
        NSE filings to {day(d.freshness?.filings_as_of ?? now)},{" "}
        {new Date(d.freshness?.filings_as_of ?? now).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
        {d.freshness?.prices_live_at ? (
          <> · prices live at {clock(d.freshness.prices_live_at)}</>
        ) : (
          d.freshness?.prices_as_of && <> · closing prices to {day(d.freshness.prices_as_of)}</>
        )}
        {d.freshness?.checked_at && <> · checked {clock(d.freshness.checked_at)}</>}
      </p>
    </>
  );
}

const ACT_TOP = 3;

function Band({ title, rule, count }: { title: string; rule: string; count?: number }) {
  return (
    <div className="px-4 pb-2 pt-7">
      <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
        {title}
        {count ? <span className="tnum font-normal text-ink-3"> · {count}</span> : null}
      </h2>
      <p className="text-[12px] leading-snug text-ink-3">{rule}</p>
    </div>
  );
}

function MoreActs({ cards, now, readOf }: { cards: Card[]; now: string; readOf: (c: Card) => CardRead }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3">
      {open ? (
        <div className="space-y-3">
          {cards.map((c) => (
            <FeedCard key={c.id} card={c} now={now} read={readOf(c)} />
          ))}
        </div>
      ) : (
        <Panel className="divide-y divide-line">
          {cards.slice(0, 5).map((c) => (
            <NoteRow key={c.id} card={c} now={now} read={readOf(c)} />
          ))}
          {cards.length > 5 && (
            <button onClick={() => setOpen(true)} className="flex w-full items-center justify-center gap-1 py-3 text-[13px] font-medium text-ink-2">
              {cards.length - 5} more that need you <ChevronDown size={14} />
            </button>
          )}
        </Panel>
      )}
    </div>
  );
}

/** Still open from the two weeks before the window: an event at a real position doesn't
 *  stop mattering because the window moved on. */
function Carry({ items, first }: { items: CarryItem[]; first: boolean }) {
  return (
    <div className={first ? "" : "mt-4"}>
      {!first && <p className="px-4 pb-1.5 text-[12px] font-medium text-ink-2">Still open from the last two weeks</p>}
      <Panel className="divide-y divide-line">
        {items.map((c) => (
          <div key={c.id} className="px-4 py-3">
            <p className="text-[14px] leading-snug">{c.line}</p>
            {c.update && <p className="mt-0.5 text-[13px] leading-snug text-ink-2">{c.update}</p>}
            <p className="mt-1 flex items-center gap-3 text-[12px] text-ink-3">
              <span className="tnum">
                {day(c.ts)} · {c.weight < 1 ? c.weight.toFixed(1) : Math.round(c.weight)}% of your portfolio
              </span>
              {c.pdf_url && (
                <a href={c.pdf_url} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 text-ink-2">
                  <FileText size={13} /> Filing
                </a>
              )}
              <Link href={`/c/${c.symbol}`} className="ml-auto inline-flex h-8 items-center font-medium text-accent">
                Research →
              </Link>
            </p>
          </div>
        ))}
      </Panel>
    </div>
  );
}

/** What FINN set aside, counted and named: routine paperwork and low-rated items. */
function SetAside({ d, aside, now }: { d: Digest; aside: Card[]; now: string }) {
  const [open, setOpen] = useState(false);
  const s = d.set_aside;
  if (!s || s.count === 0) return null;
  const kinds = s.by_kind
    .slice(0, 3)
    .map((k) => `${k.count} ${(CATEGORY_LABEL[k.category] ?? k.category).toLowerCase()}`)
    .join(", ");
  return (
    <div className="mt-6">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="mx-3 flex w-[calc(100%-1.5rem)] items-start gap-2 rounded-2xl border border-dashed border-line px-4 py-3 text-left text-[13px] leading-snug text-ink-2">
        <span className="min-w-0 flex-1">
          <span className="font-medium text-ink">Set aside: {s.count}</span>
          {kinds && <> ({kinds}{s.low_rated ? `, ${s.low_rated} rated low` : ""})</>}. {s.rule}
        </span>
        <ChevronDown size={15} className={clsx("mt-0.5 shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="mx-3 mt-1 divide-y divide-line">
          {aside.map((c) => (
            <li key={c.id} className="flex gap-2 px-1 py-2 text-[12px]">
              <span className="w-[74px] shrink-0 font-medium text-ink-2">{c.symbol}</span>
              <a href={c.pdf_url ?? undefined} target="_blank" rel="noreferrer" className="min-w-0 flex-1 text-ink-2">
                {c.title}
              </a>
              <span className="tnum shrink-0 text-ink-3">rated {c.materiality}</span>
            </li>
          ))}
          {d.routine.items.map((r) => (
            <li key={r.id} className="flex gap-2 px-1 py-2 text-[12px]">
              <span className="w-[74px] shrink-0 font-medium text-ink-2">{r.symbol}</span>
              <a href={r.pdf_url ?? undefined} target="_blank" rel="noreferrer" className="min-w-0 flex-1 text-ink-2">
                {r.title}
              </a>
              <span className="shrink-0 text-ink-3">{CATEGORY_LABEL[r.category] ?? r.category}</span>
            </li>
          ))}
        </ul>
      )}
      <span className="sr-only">{now}</span>
    </div>
  );
}

/** Custom dates (PU-1). Native date inputs: the phone's own picker, no extra library. */
function RangePicker({ range, onChange }: { range: Range; onChange: (r: Range) => void }) {
  const set = (k: keyof Range, v: string) => {
    if (!v) return;
    const next = { ...range, [k]: v };
    onChange(next.from > next.to ? { from: next.to, to: next.from } : next);
  };
  // our own day-first label ("1 Oct 2026") over the native picker, which follows the
  // browser's locale (mm/dd/yyyy on a US-set phone); tapping still opens the native picker
  const box = "tnum relative min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1.5 text-[13px] text-ink";
  const long = (iso: string) => `${day(iso)} ${iso.slice(0, 4)}`;
  const field = (k: keyof Range, label: string, extra: { min?: string; max?: string }) => (
    <label className={box}>
      <span className="sr-only">{label} </span>
      {long(range[k])}
      <input
        type="date"
        value={range[k]}
        {...extra}
        onChange={(e) => set(k, e.target.value)}
        onClick={(e) => {
          try {
            e.currentTarget.showPicker?.();
          } catch {}
        }}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />
    </label>
  );
  return (
    <div className="mt-2 flex items-center gap-2">
      {field("from", "From", { max: range.to })}
      <span className="text-[12px] text-ink-3">to</span>
      {field("to", "To", { min: range.from })}
    </div>
  );
}

/** Q-3: say so when prices are behind, instead of showing old moves as today's. */
function StaleNote({ f }: { f: NonNullable<Digest["freshness"]> }) {
  const n = f.sessions_behind;
  return (
    <p className="mx-4 mt-2 rounded-lg bg-warn-soft px-3 py-2 text-[12px] text-warn">
      {f.prices_as_of
        ? `Prices are ${n} trading ${n === 1 ? "session" : "sessions"} behind (last close ${day(f.prices_as_of)}). Moves below may be old.`
        : "No price data loaded yet."}
    </p>
  );
}

const TOP = 8;

/** Worth knowing: one line each, opened in place; the long tail one tap away. */
function Feed({
  cards,
  now,
  readOf,
  firstFor,
  newCount,
}: {
  cards: Card[];
  now: string;
  readOf: (c: Card) => { isNew: boolean; opened: boolean; onOpen: () => void };
  firstFor: (c: Card) => boolean;
  newCount: number;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? cards : cards.slice(0, TOP);
  return (
    <>
      {newCount > 0 && (
        <p className="px-4 pb-1.5 text-[12px] text-ink-2">
          <span className="font-semibold text-accent">{newCount} new</span> since you last looked
        </p>
      )}
      <Panel className="divide-y divide-line">
        {shown.map((c) => (
          <NoteRow key={c.id} card={c} now={now} read={readOf(c)} showHelper={firstFor(c)} />
        ))}
        {cards.length > TOP && (
          <button onClick={() => setAll(!all)} aria-expanded={all} className="flex w-full items-center justify-center gap-1 py-3 text-[13px] font-medium text-ink-2">
            {all ? "Show fewer" : `${cards.length - TOP} more`}
            <ChevronDown size={15} className={clsx("transition-transform", all && "rotate-180")} />
          </button>
        )}
      </Panel>
    </>
  );
}

/** Price/volume alerts only; category alerts already are the cards below. */
function Moves({ alerts }: { alerts: Alert[] }) {
  const moves = useMemo(() => {
    // one tile per stock: its most recent session, with that session's price and volume
    const bySymbol = new Map<string, Alert[]>();
    for (const a of alerts) if (a.kind !== "category") bySymbol.set(a.symbol, [...(bySymbol.get(a.symbol) ?? []), a]);
    return [...bySymbol.entries()]
      .map(([symbol, list]) => {
        const s = sessionMoves(list);
        return { symbol, ts: s[0].ts, vol: s.find((a) => a.kind === "volume"), price: s.find((a) => a.kind === "price") };
      })
      .sort((a, b) => (b.ts > a.ts ? 1 : b.ts < a.ts ? -1 : 0));
  }, [alerts]);
  if (!moves.length) return null;
  return (
    <>
      <Band title="Unusual moves" rule="Closing price or volume outside your alert rules, newest session per stock." />
      <div className="no-scrollbar flex gap-2 overflow-x-auto px-3 pb-1">
        {moves.map((m) => {
          const chg = m.price?.value ?? m.vol?.price_change_pct ?? 0;
          const Icon = chg >= 0 ? TrendingUp : TrendingDown;
          return (
            <Link
              key={m.symbol}
              href={`/c/${m.symbol}`}
              className="flex min-w-[132px] shrink-0 flex-col rounded-xl border border-line bg-surface px-3 py-2 active:opacity-80"
            >
              <span className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-semibold">{m.symbol}</span>
                <span className="tnum text-[11px] text-ink-3">{day(m.ts)}</span>
              </span>
              <span className={clsx("tnum mt-0.5 flex items-center gap-1 text-[13px] font-medium", chg >= 0 ? "text-good" : "text-bad")}>
                <Icon size={13} /> {pct(chg)}
              </span>
              {m.vol && (
                <span className="tnum text-[11px] text-ink-2">
                  Volume {+m.vol.value.toFixed(2)}× avg{m.vol.low ? ", quiet" : ""}
                </span>
              )}
            </Link>
          );
        })}
      </div>
    </>
  );
}

function Nudges({ d }: { d: Digest }) {
  return (
    <>
      <Band title="People worth a call" rule="Contacts you haven't spoken to in a while, with a reason in this window's filings." />
      <Panel className="divide-y divide-line">
        {d.nudges.slice(0, 4).map((n) => {
          const first = firstName(n.contact.name);
          const since = n.contact.last_contact
            ? new Date(n.contact.last_contact).toLocaleDateString("en-IN", { month: "long", year: "numeric" })
            : null;
          const why = n.reason.replace(/^Last spoke [^.]+\.\s*/, "");
          return (
            <div key={n.contact.id} className="flex gap-3 px-4 py-3">
              <Avatar name={n.contact.name} size={34} />
              <div className="min-w-0 flex-1 text-[13px] leading-snug">
                <Link href={`/people/${n.contact.id}`} className="block active:opacity-80">
                  <span className="font-semibold">{first}</span>
                  <span className="text-ink-2">
                    {" "}
                    · {since ? `you last spoke in ${since}` : `${n.days_since_contact} days since you spoke`}. {why}
                  </span>
                  {n.contact.context && <span className="mt-0.5 block text-[12px] text-ink-3">{n.contact.context}</span>}
                </Link>
                <div className="mt-1.5 flex flex-wrap gap-2">
                  <ReachButtons contact={n.contact} subject={`Catching up: ${n.event.title.slice(0, 60)}`} body={`Hi ${first},\n\nIt's been a while. ${why}\n\nWould love your read on it.\n`} />
                </div>
              </div>
            </div>
          );
        })}
      </Panel>
    </>
  );
}

function FeedSkeleton() {
  return (
    <div className="mt-6 space-y-3 px-3">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-44" />
      ))}
    </div>
  );
}
