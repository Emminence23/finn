"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import clsx from "clsx";
import { AlertTriangle, Calculator, ChevronDown, Minus, Pencil, Plus, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { NumberSlider } from "@/components/NumberSlider";
import { useSWRConfig } from "swr";
import { api, useApi } from "@/lib/api";
import { day, inr, pct, price } from "@/lib/fmt";
import { type Point, YearChart } from "@/components/YearChart";
import { ErrorNote, Header, Panel, SectionTitle, Segmented, Sheet, Skeleton, SlowHint } from "@/components/ui";
import { useTitle } from "@/lib/title";
import { HoldingsCard, MoversStrip, signedInr, tone } from "@/components/market";
import { Listen } from "@/components/Listen";

type Holding = {
  symbol: string;
  name: string;
  theme: string;
  weight: number;
  return_6m: number;
  return_1m: number;
  contribution_6m: number;
  volatility: number;
  risk_share: number;
  pe: number | null;
  roe: number | null;
  is_lender: boolean;
  delivery: number | null;
  qty: number;
  price: number;
  value: number;
  avg_cost: number;
  gain_pct: number;
  gain: number;
  invested: number;
  day_change: number;
  day_pct: number;
};
type Stats = {
  volatility: number;
  effective_holdings: number;
  top5: number;
  largest_theme: { theme: string; weight: number };
  pe: number | null;
  roe: number | null;
  revenue_growth_3y: number | null;
};
type Overview = {
  as_of: string | null;
  days: number;
  custom: boolean;
  summary: Stats & {
    holdings: number;
    value: number;
    invested: number;
    gain: number;
    gain_pct: number;
    day_gain: number;
    day_gain_pct: number;
    return_6m: number;
    return_1m: number;
    return_1y: number;
    nifty_1y: number | null;
    max_drawdown: number;
  };
  history: { series: Point[]; start: string | null; return: number; nifty_return: number | null };
  holdings: Holding[];
  themes: { theme: string; weight: number; risk_share: number; contribution_6m: number; symbols: string[] }[];
  correlated: { a: string; b: string; corr: number }[];
  flags: string[];
};
type SugRow = { symbol: string; name: string; theme: string; current: number; suggested: number; change: number; reason: string };
type Source = { id: string; symbol: string; what: string; date?: string };
type Review =
  | { status: "not_run"; events: number }
  | { status: "off"; events: number }
  | {
      status: "done";
      events: number;
      summary: string;
      adjustments: { symbol: string; delta: number; asked: number; applied: number; reason: string; sources: Source[] }[];
      dropped: { symbol: string; why: string }[];
      weights: Record<string, number>;
    };
type Suggestion = {
  holdings: SugRow[];
  before: Stats;
  after: Stats;
  turnover: number;
  rules: {
    min: number;
    max: number;
    theme_cap: number;
    max_step: number;
    days: number;
    tilt: number;
    notes: string[];
    settings: Settings;
  };
  review: Review;
};

type Settings = {
  min_pct: number | null;
  max_pct: number | null;
  theme_cap_pct: number | null;
  max_step_pct: number | null;
  tilt: number;
  risk_days: number;
  ai_nudge_pct: number;
  ai_max_adjust: number;
  lot_pct: number;
  new_holding_pct: number;
};
const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
const one = (v: number | null | undefined, unit = "%") => (v == null ? "—" : `${v.toFixed(1)}${unit}`);

export default function PortfolioPage() {
  useTitle("Portfolio");
  const [tab, setTab] = useState<"now" | "suggested">("now");
  const [editing, setEditing] = useState(false);
  const { data, error, mutate } = useApi<Overview>("/portfolio");
  const { mutate: refresh } = useSWRConfig();
  const reload = () => refresh(() => true); // Today, alerts and both tabs follow the holdings
  // a reset can be undone for a while: the API returned the exact positions it replaced
  const [undo, setUndo] = useState<Record<string, [number, number]> | null>(null);
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const offerUndo = (u: Record<string, [number, number]> | null) => {
    setUndo(u);
    if (undoTimer.current) clearTimeout(undoTimer.current);
    if (u) undoTimer.current = setTimeout(() => setUndo(null), 20000);
  };
  const doUndo = async () => {
    if (!undo) return;
    await api("/portfolio/holdings/restore", { method: "POST", body: JSON.stringify({ positions: undo }) });
    offerUndo(null);
    reload();
  };

  return (
    <main className="pb-10">
      <Header
        title="Portfolio"
        sub={data ? `${inr(data.summary.value)} · ${data.summary.holdings} holdings${data.custom ? " · edited by you" : ""} · prices to ${data.as_of ? day(data.as_of) : "—"}` : " "}
        right={
          <button onClick={() => setEditing(true)} data-tour="edit" className="flex items-center gap-1 rounded-full border border-line px-3 py-1.5 text-[13px] font-medium text-ink-2">
            <Pencil size={13} /> Edit
          </button>
        }
      />
      <div className="px-4">
        <Segmented
          label="View"
          value={tab}
          onChange={setTab}
          options={[
            { value: "now", label: "As it stands" },
            { value: "suggested", label: "Suggested" },
          ]}
        />
      </div>
      {error && !data ? (
        <div className="mt-4">
          <ErrorNote error={error} retry={() => mutate()} />
        </div>
      ) : !data ? (
        <div className="space-y-3 px-4 pt-4">
          <Skeleton className="h-28" />
          <Skeleton className="h-72" />
          <SlowHint />
        </div>
      ) : tab === "now" ? (
        <Now d={data} />
      ) : (
        <Suggested onApplied={reload} />
      )}
      <EditSheet open={editing} onClose={() => setEditing(false)} onSaved={reload} onReset={offerUndo} />
      {undo && (
        <div role="status" className="fixed inset-x-3 bottom-20 z-30 mx-auto flex max-w-md items-center gap-3 rounded-xl bg-ink px-4 py-3 text-[13px] text-bg shadow-lg">
          <span className="flex-1">Holdings reset to the demo.</span>
          <button onClick={doUndo} className="font-semibold underline underline-offset-2">
            Undo
          </button>
        </div>
      )}
    </main>
  );
}

// ------------------------------------------------------------------ as it stands
function Tile({ label, value, sub }: { label: string; value: string; sub?: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface p-3">
      <p className="text-[11px] text-ink-3">{label}</p>
      <p className="tnum mt-0.5 truncate text-[19px] font-semibold leading-tight tracking-[-0.01em]">{value}</p>
      {sub && <p className="tnum truncate text-[11px] text-ink-3">{sub}</p>}
    </div>
  );
}

function Bar({ value, max, tone = "accent" }: { value: number; max: number; tone?: "accent" | "muted" }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-surface-2" aria-hidden>
      <div
        className={clsx("h-1.5 rounded-full", tone === "accent" ? "bg-accent" : "bg-ink-3/60")}
        style={{ width: `${Math.max(2, Math.min(100, (value / max) * 100))}%` }}
      />
    </div>
  );
}

/** A section that stays folded until asked for, so the page leads with what matters. */
function Fold({ title, aside, children, open: start = false }: { title: string; aside?: string; children: React.ReactNode; open?: boolean }) {
  const [open, setOpen] = useState(start);
  return (
    <div className="mx-3 mt-3 rounded-2xl border border-line bg-surface">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left">
        <span className="text-[14px] font-semibold">{title}</span>
        <span className="flex items-center gap-1.5 text-[12px] text-ink-3">
          {aside}
          <ChevronDown size={16} className={clsx("transition-transform", open && "rotate-180")} />
        </span>
      </button>
      {open && <div className="border-t border-line">{children}</div>}
    </div>
  );
}

function Now({ d }: { d: Overview }) {
  const s = d.summary;
  const maxTheme = Math.max(...d.themes.map((t) => t.weight));
  const months = Math.round(d.days / 21);
  const table: [string, string][] = [
    [`Return, ${months} months`, pct(s.return_6m)],
    ["Return, last month", pct(s.return_1m)],
    ["Return, past year", pct(s.return_1y)],
    ["Nifty 50, past year", pct(s.nifty_1y)],
    ["Volatility, a year", one(s.volatility)],
    ["Worst fall, past year", pct(s.max_drawdown)],
    ["Effective holdings", `${s.effective_holdings.toFixed(1)} of ${s.holdings}`],
    ["Top 5 holdings", `${s.top5.toFixed(0)}%`],
    ["Largest theme", `${cap(s.largest_theme.theme)}, ${s.largest_theme.weight.toFixed(0)}%`],
    ["P/E, weighted", `${s.pe?.toFixed(1) ?? "—"}×`],
    ["ROE, weighted", one(s.roe)],
    ["Sales growth, 3 years", one(s.revenue_growth_3y)],
  ];
  // from the rounded figures on screen, so +7.5% and -2.8% read as 10.3 pts, never 10.4
  const r1 = (v: number) => Math.round(v * 10) / 10;
  const beat = s.nifty_1y != null ? r1(s.return_1y) - r1(s.nifty_1y) : null;
  return (
    <>
      <Listen lines={portfolioScript(d)} className="mx-3 mt-3" />
      <HoldingsCard value={s.value} invested={s.invested} gain={s.gain} gainPct={s.gain_pct} dayGain={s.day_gain} dayPct={s.day_gain_pct} asOf={d.as_of} />
      <MoversStrip className="mt-4" />
      <HoldingsList holdings={d.holdings} />

      <Panel className="mt-3 p-4">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-[14px] font-semibold">Past year</p>
          <p className="tnum text-[12px] text-ink-2">
            <b className={clsx(s.return_1y >= 0 ? "text-good" : "text-bad")}>{pct(s.return_1y)}</b>
            {beat != null && <> · {Math.abs(beat).toFixed(1)} pts {beat >= 0 ? "ahead of" : "behind"} the Nifty</>}
          </p>
        </div>
        <div className="mt-2">
          <YearChart series={d.history.series} invested={d.custom ? undefined : s.invested} />
        </div>
        <p className="mt-1 text-[11px] leading-snug text-ink-3">
          {d.custom
            ? "Today's holdings held for the whole year, so it shows how this mix would have done, not what you made."
            : `The demo holdings were bought on ${day(d.history.start ?? "")} ${(d.history.start ?? "").slice(0, 4)} at that day's close (dotted line: the amount invested).`}
        </p>
      </Panel>

      {d.flags.length > 0 && (
        <ul data-tour="flags" className="mx-3 mt-3 space-y-1.5 rounded-2xl bg-warn-soft/60 px-3.5 py-3">
          {d.flags.map((f) => (
            <li key={f} className="flex gap-2 text-[13px] leading-snug">
              <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warn" aria-hidden />
              {f}
            </li>
          ))}
        </ul>
      )}

      <SectionTitle>More numbers</SectionTitle>
      <Panel>
        <table className="w-full text-[13px]">
          <tbody className="divide-y divide-line">
            {table.map(([k, v]) => (
              <tr key={k}>
                <th scope="row" className="px-4 py-2 text-left font-normal text-ink-2">{k}</th>
                <td className="tnum px-4 py-2 text-right font-medium">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Fold title="By theme" aside={`${d.themes.length} themes`}>
        <div className="divide-y divide-line">
          {d.themes.map((t) => (
            <div key={t.theme} className="px-4 py-2.5">
              <div className="flex items-baseline justify-between gap-2 text-[13px]">
                <span className="min-w-0 truncate font-medium capitalize">{t.theme}</span>
                <span className="tnum shrink-0 text-ink-2">
                  {t.weight.toFixed(0)}% · <span className="text-ink-3">{t.risk_share.toFixed(0)}% of risk</span>
                </span>
              </div>
              <div className="mt-1.5">
                <Bar value={t.weight} max={maxTheme} />
              </div>
              <p className="mt-1 truncate text-[11px] text-ink-3">{t.symbols.join(", ")}</p>
            </div>
          ))}
        </div>
      </Fold>

      {d.correlated.length > 0 && (
        <Fold title="Move together most" aside="6 months">
          <div className="divide-y divide-line">
            {d.correlated.map((c) => (
              <Link key={c.a + c.b} href={`/compare?a=${c.a}&b=${c.b}`} className="flex items-center justify-between px-4 py-2.5 text-[13px] active:bg-surface-2">
                <span>
                  <span className="font-semibold">{c.a}</span> and <span className="font-semibold">{c.b}</span>
                </span>
                <span className="tnum text-ink-2">correlation {c.corr.toFixed(2)} · compare →</span>
              </Link>
            ))}
          </div>
        </Fold>
      )}
      <p className="px-6 pt-4 text-center text-[11px] leading-snug text-ink-3">
        Computed in code from end-of-day prices (a year for the chart, {months} months for risk) and the reported financials. Share counts are demo data. No AI on this page.
      </p>
    </>
  );
}

/** The page's top in words: value and returns, the last day, the biggest holdings, and
 *  the warnings. Computed figures only. */
function portfolioScript(d: Overview): string[] {
  const s = d.summary;
  const out = [
    `Your portfolio is worth ${inr(s.value)}, against ${inr(s.invested)} invested: ${s.gain >= 0 ? "up" : "down"} ${Math.abs(s.gain_pct).toFixed(1)}%.`,
  ];
  if (d.as_of) out.push(`On ${day(d.as_of)}, the last close, it moved ${s.day_gain >= 0 ? "up" : "down"} ${Math.abs(s.day_gain_pct).toFixed(1)}%, ${inr(Math.abs(s.day_gain))}.`);
  if (s.nifty_1y != null) out.push(`Over the past year, ${pct(s.return_1y)} against the Nifty's ${pct(s.nifty_1y)}.`);
  const top = [...d.holdings].sort((a, b) => b.weight - a.weight).slice(0, 3);
  out.push(`Largest holdings: ${top.map((h) => `${h.symbol} ${h.weight.toFixed(0)}%`).join(", ")}.`);
  const moves = [...d.holdings].sort((a, b) => Math.abs(b.day_pct) - Math.abs(a.day_pct)).filter((h) => Math.abs(h.day_pct) >= 1).slice(0, 2);
  if (moves.length) out.push(`Biggest moves that day: ${moves.map((h) => `${h.symbol} ${h.day_pct >= 0 ? "up" : "down"} ${Math.abs(h.day_pct).toFixed(1)}%`).join(", ")}.`);
  out.push(...d.flags.slice(0, 3));
  return out;
}

type SortKey = "value" | "returns" | "day";

/** Groww-style rows: what you hold and what it's worth, then the gain; 1D on a tap. */
function HoldingsList({ holdings }: { holdings: Holding[] }) {
  const [sort, setSort] = useState<SortKey>("value");
  const by: Record<SortKey, (h: Holding) => number> = { value: (h) => h.value, returns: (h) => h.gain_pct, day: (h) => h.day_pct };
  const rows = [...holdings].sort((a, b) => by[sort](b) - by[sort](a));
  const showDay = sort === "day";
  return (
    <section aria-label="Holdings" className="mt-5">
      <div className="flex items-center justify-between gap-2 px-4">
        <h2 className="text-[15px] font-semibold">Holdings ({holdings.length})</h2>
        <Segmented
          label="Sort holdings"
          value={sort}
          onChange={setSort}
          options={[
            { value: "value", label: "Value" },
            { value: "returns", label: "Returns" },
            { value: "day", label: "1D" },
          ]}
        />
      </div>
      <Panel className="mt-2">
        <ul className="divide-y divide-line">
          {rows.map((h) => (
            <li key={h.symbol}>
              <Link href={`/c/${h.symbol}`} className="flex items-start gap-3 px-4 py-3 active:bg-surface-2">
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] font-semibold">{h.symbol}</p>
                  <p className="tnum truncate text-[12px] text-ink-3">
                    {h.qty.toLocaleString("en-IN")} shares · avg {price(h.avg_cost)}
                  </p>
                  <p className="tnum text-[12px] text-ink-3">
                    {h.weight.toFixed(1)}% · LTP {price(h.price)}{" "}
                    <span className={tone(h.day_pct)}>({pct(h.day_pct, true, 2)})</span>
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="tnum text-[14px] font-medium">{inr(h.value)}</p>
                  {showDay ? (
                    <p className={clsx("tnum text-[12px] font-medium", tone(h.day_change))}>
                      {signedInr(h.day_change)} today
                    </p>
                  ) : (
                    <p className={clsx("tnum text-[12px] font-medium", tone(h.gain))}>
                      {signedInr(h.gain)} ({pct(h.gain_pct)})
                    </p>
                  )}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </Panel>
    </section>
  );
}

// ------------------------------------------------------------------ suggested
function Suggested({ onApplied }: { onApplied: () => void }) {
  const { data, error, mutate } = useApi<Suggestion>("/portfolio/suggested");
  const [withAi, setWithAi] = useState(true);
  const [running, setRunning] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [howOpen, setHowOpen] = useState(false);
  const [allRows, setAllRows] = useState(false);
  const { mutate: refreshAll } = useSWRConfig();
  if (error && !data) return <div className="mt-4"><ErrorNote error={error} retry={() => mutate()} /></div>;
  if (!data) return <div className="px-4 pt-4"><Skeleton className="h-96" /><SlowHint retry={() => mutate()} /></div>;

  const rv = data.review;
  const reviewed = rv.status === "done" && withAi;
  const weight = (r: SugRow) => (reviewed ? rv.weights[r.symbol] : r.suggested);
  const max = Math.max(...data.holdings.map((r) => Math.max(r.current, weight(r))));
  const runReview = async () => {
    setRunning(true);
    setRunErr(null);
    try {
      await api("/portfolio/suggested/review", { method: "POST" });
      await mutate();
    } catch {
      setRunErr("The AI review isn't available right now (free-tier quota). The code's suggestion stands on its own.");
    } finally {
      setRunning(false);
    }
  };
  const apply = async () => {
    const weights = Object.fromEntries(data.holdings.map((r) => [r.symbol, weight(r)]));
    await api("/portfolio/holdings", { method: "PUT", body: JSON.stringify({ weights }) });
    setApplied(true);
    onApplied();
  };
  const b = data.before;
  const a = data.after;

  const changes = data.holdings.map((r) => ({ r, ch: weight(r) - r.current }));
  const cuts = changes.filter((x) => x.ch <= -0.25).length;
  const adds = changes.filter((x) => x.ch >= 0.25).length;
  // the rows worth reading: a change of a point or more, or one the AI touched
  const BIG = 1;
  const nudged = (s: string) => reviewed && rv.adjustments.some((x) => x.symbol === s && Math.abs(x.applied) >= 0.05);
  const ordered = [...changes].sort((x, y) => Math.abs(y.ch) - Math.abs(x.ch));
  const main = ordered.filter((x) => Math.abs(x.ch) >= BIG || nudged(x.r.symbol));
  const rest = ordered.filter((x) => !main.includes(x));
  const rows = allRows ? ordered : main;

  return (
    <>
      <div className="px-4 pt-3">
        <p className="text-[17px] leading-snug tracking-[-0.01em]">
          Trim {cuts} and add to {adds}. {one(data.turnover)} of the portfolio changes hands; a year&apos;s volatility goes from{" "}
          {one(b.volatility)} to {one(a.volatility)}.
        </p>
        <div className="mt-2 flex items-center gap-3 text-[13px]">
          <button onClick={() => setHowOpen(!howOpen)} aria-expanded={howOpen} className="flex items-center gap-1 font-medium text-accent">
            <Calculator size={13} /> How this is built
            <ChevronDown size={13} className={clsx("transition-transform", howOpen && "rotate-180")} />
          </button>
          <button onClick={() => setRulesOpen(true)} className="ml-auto flex min-h-9 shrink-0 items-center gap-1 rounded-full border border-line px-3 text-[13px] font-medium text-ink-2">
            <SlidersHorizontal size={13} /> Your rules
          </button>
        </div>
      </div>
      {howOpen && (
      <div className="mx-3 mt-2 rounded-2xl border border-line bg-surface p-3.5 text-[13px] leading-snug">
        <ol className="list-decimal space-y-1 pl-4 text-ink-2">
          <li><b className="text-ink">Balance risk.</b> Every holding gets the same share of the portfolio&apos;s swings, from {data.rules.days} days of prices.</li>
          <li><b className="text-ink">Lean towards quality.</b> Returns on capital, growth, cash conversion, debt, valuation and management&apos;s delivery record tilt each weight.</li>
          <li><b className="text-ink">Your limits.</b> {limitsText(data.rules.settings)}</li>
          <li><b className="text-ink">AI review.</b> {data.rules.settings.ai_max_adjust === 0 || data.rules.settings.ai_nudge_pct === 0 ? "Off." : <>The AI reads the last 30 days of filings and may move up to {data.rules.settings.ai_max_adjust} holdings by up to {data.rules.settings.ai_nudge_pct} points each, citing the filing. Code enforces the limits.</>}</li>
        </ol>
        {data.rules.notes.length > 0 && (
          <p className="mt-1.5 rounded-lg bg-warn-soft px-2.5 py-1.5 text-[12px] text-warn">{data.rules.notes.join(" ")}</p>
        )}
        <p className="mt-2 text-[12px] text-ink-2">It does not forecast returns. Same holdings, different proportions.</p>
      </div>
      )}
      <RulesSheet
        open={rulesOpen}
        onClose={() => setRulesOpen(false)}
        onSaved={() => {
          setApplied(false);
          refreshAll(() => true);
        }}
      />

      <div className="mt-3 grid grid-cols-2 gap-2 px-3">
        <Tile label="Volatility, a year" value={`${one(b.volatility)} → ${one(a.volatility)}`} />
        <Tile label="Largest theme" value={`${b.largest_theme.weight.toFixed(0)}% → ${a.largest_theme.weight.toFixed(0)}%`} sub={a.largest_theme.theme} />
        <Tile label="P/E · ROE" value={`${a.pe?.toFixed(1) ?? "—"}× · ${one(a.roe)}`} sub={`from ${b.pe?.toFixed(1) ?? "—"}× · ${one(b.roe)}`} />
        <Tile label="Turnover" value={`${data.turnover.toFixed(1)}%`} sub="changes hands" />
      </div>

      <SectionTitle aside={rv.status === "done" ? `${rv.events} filings read` : undefined}>AI review</SectionTitle>
      <Panel className="p-4">
        {rv.status === "off" ? (
          <p className="text-[13px] leading-snug text-ink-2">Switched off in your rules. The code&apos;s suggestion stands on its own.</p>
        ) : rv.status === "not_run" ? (
          <>
            <p className="text-[13px] leading-snug text-ink-2">
              Not run for this portfolio yet. It reads {rv.events} recent filings for things the numbers can&apos;t see: management exits, regulatory action, orders.
            </p>
            <button onClick={runReview} disabled={running} className="mt-3 flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-[13px] font-medium text-bg disabled:opacity-50">
              <Sparkles size={14} /> {running ? "Reading filings…" : "Ask AI to review"}
            </button>
            {runErr && <p className="mt-2 text-[12px] text-ink-3">{runErr}</p>}
          </>
        ) : (
          <>
            <p className="text-[13px] leading-snug">{rv.summary}</p>
            {rv.adjustments.length > 0 && (
              <ul className="mt-3 space-y-2.5 border-t border-line pt-3">
                {rv.adjustments.map((x) => (
                  <li key={x.symbol} className="text-[13px] leading-snug">
                    <span className="font-semibold">{x.symbol}</span>{" "}
                    <Nudge x={x} />. {x.reason}
                    <span className="mt-0.5 block text-[11px] text-ink-3">
                      Source: {x.sources.map((s) => (s.date ? `${day(s.date)} filing: ${s.what}` : s.what)).join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {rv.dropped.length > 0 && (
              <p className="mt-2 text-[11px] text-ink-3">
                Ignored: {rv.dropped.map((x) => `${x.symbol} (${x.why})`).join(", ")}.
              </p>
            )}
            <div className="mt-3 flex items-center justify-between gap-2 border-t border-line pt-3">
              <span className="flex items-center gap-1 text-[11px] text-ink-3">
                <Sparkles size={11} className="text-accent" /> AI · nudges within limits code enforces
              </span>
              <Segmented
                label="Weights shown"
                value={withAi ? "ai" : "code"}
                onChange={(v) => setWithAi(v === "ai")}
                options={[
                  { value: "code", label: "Code" },
                  { value: "ai", label: "+ AI" },
                ]}
              />
            </div>
          </>
        )}
      </Panel>

      <SectionTitle
        aside={
          <span className="flex items-center gap-2.5">
            <span className="flex items-center gap-1"><i className="inline-block h-1.5 w-3 rounded-full bg-ink-3/60" /> now</span>
            <span className="flex items-center gap-1"><i className="inline-block h-1.5 w-3 rounded-full bg-accent" /> suggested</span>
          </span>
        }
      >
        Weights
      </SectionTitle>
      <Panel className="divide-y divide-line">
        {rows.map(({ r }) => {
          const w = weight(r);
          const ch = w - r.current;
          const nudge = reviewed ? rv.adjustments.find((x) => x.symbol === r.symbol && Math.abs(x.applied) >= 0.05) : undefined;
          return (
            <div key={r.symbol} className="px-4 py-2.5">
              <div className="flex items-baseline justify-between gap-2 text-[13px]">
                <Link href={`/c/${r.symbol}`} className="min-w-0 truncate font-semibold">
                  {r.symbol}
                  {nudge && <Sparkles size={11} className="ml-1 inline text-accent" aria-label="adjusted by the AI review" />}
                </Link>
                <span className="tnum shrink-0">
                  <span className="text-ink-3">{r.current.toFixed(1)}%</span> → <b>{w.toFixed(1)}%</b>{" "}
                  <span className={clsx("inline-block w-12 text-right", Math.abs(ch) < 0.25 ? "text-ink-3" : "text-ink-2")}>
                    {Math.abs(ch) < 0.05 ? "—" : `${ch > 0 ? "+" : ""}${ch.toFixed(1)}`}
                  </span>
                </span>
              </div>
              <div className="mt-1.5 space-y-0.5">
                <Bar value={r.current} max={max} tone="muted" />
                <Bar value={w} max={max} />
              </div>
              <p className="mt-1 text-[12px] leading-snug text-ink-3">
                {r.reason}
                {nudge && (
                  <span className="block text-ink-2">
                    {/* the code's change and the AI's are two numbers, so the step limit above still holds */}
                    Code {signedPts(r.suggested - r.current)}, then AI review <Nudge x={nudge} />. {nudge.reason}
                  </span>
                )}
              </p>
            </div>
          );
        })}
        {rest.length > 0 && (
          <button onClick={() => setAllRows(!allRows)} aria-expanded={allRows} className="flex w-full items-center justify-center gap-1 py-3 text-[13px] font-medium text-ink-2">
            {allRows ? "Show only the larger changes" : `${rest.length} smaller changes, under a point each`}
            <ChevronDown size={14} className={clsx("transition-transform", allRows && "rotate-180")} />
          </button>
        )}
      </Panel>

      <div className="px-4 pt-4">
        <button onClick={apply} disabled={applied} className="w-full rounded-full bg-ink py-2.5 text-[14px] font-medium text-bg disabled:opacity-50">
          {applied ? "Applied. Today now uses these weights" : `Use these weights${reviewed ? " (with AI review)" : ""}`}
        </button>
        <p className="mt-2 text-center text-[11px] text-ink-3">Changes FINN&apos;s view of your holdings only. Nothing is traded. Edit or reset any time.</p>
      </div>
    </>
  );
}

function signedPts(v: number): string {
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)} pts`;
}

/** What the AI asked for and what the limits let through, in words. */
function Nudge({ x }: { x: { asked: number; delta: number; applied: number } }) {
  const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)} pts`;
  if (Math.abs(x.applied) < 0.05)
    return (
      <span className="text-ink-2">
        asked {signed(x.asked)}, <span className="text-ink-3">no room within the limits</span>
      </span>
    );
  const limited = Math.abs(x.applied) < Math.abs(x.asked) - 0.05;
  return (
    <span>
      <span className="tnum font-medium">{signed(x.applied)}</span>
      {limited && <span className="text-ink-3"> (asked {signed(x.asked)}; the limits allowed {signed(x.applied)})</span>}
    </span>
  );
}

function limitsText(st: Settings): string {
  const parts = [];
  if (st.min_pct != null && st.max_pct != null) parts.push(`${st.min_pct}–${st.max_pct}% per holding`);
  else if (st.max_pct != null) parts.push(`at most ${st.max_pct}% per holding`);
  else if (st.min_pct != null) parts.push(`at least ${st.min_pct}% per holding`);
  else parts.push("no limit per holding");
  parts.push(st.theme_cap_pct != null ? `${st.theme_cap_pct}% per theme` : "no theme cap");
  parts.push(st.max_step_pct != null ? `at most ${st.max_step_pct} points of change at a time` : "straight to target");
  return `${parts.join(", ")}. Change any of them under Your rules.`;
}

type Spec = { key: keyof Settings; label: string; hint: string; min: number; max: number; hardMax?: number; unit: string; decimals?: number; off?: string };
const SPECS: Spec[] = [
  { key: "max_pct", label: "Largest holding", hint: "No single stock above this", min: 1, max: 30, hardMax: 100, unit: "%", off: "No maximum" },
  { key: "min_pct", label: "Smallest holding", hint: "Keep every stock at least this big", min: 0, max: 10, hardMax: 50, unit: "%", off: "No minimum" },
  { key: "theme_cap_pct", label: "Largest theme", hint: "Also the line for concentration warnings", min: 5, max: 60, hardMax: 100, unit: "%", off: "No cap" },
  { key: "max_step_pct", label: "Most change at a time", hint: "Per holding, per suggestion, to keep trading small", min: 0.5, max: 10, hardMax: 100, unit: " pts", off: "Straight to target" },
  { key: "tilt", label: "Quality tilt", hint: "0 balances risk only; higher leans harder towards quality", min: 0, max: 1, hardMax: 2, unit: "" },
  { key: "risk_days", label: "Risk measured over", hint: "Trading sessions of daily prices", min: 20, max: 250, unit: " days", decimals: 0 },
  { key: "ai_nudge_pct", label: "AI may move a holding by", hint: "0 turns the AI review off", min: 0, max: 5, hardMax: 20, unit: " pts" },
  { key: "ai_max_adjust", label: "AI may adjust up to", hint: "Holdings per review; 0 turns it off", min: 0, max: 10, hardMax: 20, unit: " stocks", decimals: 0 },
];

/** The investor's own rules for the suggestion. Nothing is fixed in code. */
function RulesSheet({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { data, mutate } = useApi<{ settings: Settings; defaults: Settings }>(open ? "/portfolio/settings" : null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const st = draft ?? data?.settings ?? null;
  const close = () => {
    setDraft(null);
    setErr(null);
    onClose();
  };
  const save = async (body: object, path = "/portfolio/settings", method = "PUT") => {
    setErr(null);
    try {
      await api(path, { method, body: JSON.stringify(body) });
      await mutate();
      onSaved();
      close();
    } catch (e) {
      let msg = e instanceof Error ? e.message : "Couldn't save.";
      try {
        msg = JSON.parse(msg).detail ?? msg;
      } catch {
        /* plain text */
      }
      setErr(String(msg));
    }
  };
  return (
    <Sheet open={open} onClose={close} title="Your rules">
      {!st || !data ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="space-y-4 pb-2">
          <p className="text-[12px] leading-snug text-ink-3">
            The suggestion follows these. Defaults are a common discipline for 15–20 stocks; set your own, or switch a limit off.
          </p>
          {SPECS.map((sp) => {
            const v = st[sp.key];
            const off = v == null;
            return (
              <div key={sp.key}>
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-[14px] font-medium">{sp.label}</p>
                  {sp.off && (
                    <button
                      onClick={() => setDraft({ ...st, [sp.key]: off ? data.defaults[sp.key] : null })}
                      aria-pressed={off}
                      className={clsx("rounded-full border px-2.5 py-0.5 text-[12px]", off ? "border-ink bg-ink text-bg" : "border-line text-ink-2")}
                    >
                      {sp.off}
                    </button>
                  )}
                </div>
                <p className="mb-1.5 text-[12px] text-ink-3">{sp.hint}</p>
                <NumberSlider
                  label={sp.label}
                  value={off ? (data.defaults[sp.key] as number) : (v as number)}
                  disabled={off}
                  min={sp.min}
                  max={sp.max}
                  hardMax={sp.hardMax}
                  step={sp.decimals === 0 ? 1 : 0.1}
                  decimals={sp.decimals ?? 2}
                  unit={sp.unit}
                  onChange={(x) => setDraft({ ...st, [sp.key]: x })}
                />
              </div>
            );
          })}
          {err && <p className="text-[12px] text-bad">{err}</p>}
          <div className="flex gap-2">
            <button onClick={() => save({}, "/portfolio/settings/reset", "POST")} className="rounded-full border border-line px-4 py-2 text-[13px] text-ink-2">
              Defaults
            </button>
            <button onClick={() => save(st)} disabled={!draft} className="flex-1 rounded-full bg-ink py-2 text-[14px] font-medium text-bg disabled:opacity-40">
              Save
            </button>
          </div>
        </div>
      )}
    </Sheet>
  );
}

// ------------------------------------------------------------------ edit
type Position = { symbol: string; name: string; qty: number; price: number; avg_cost: number; value: number; weight: number };
type HoldingsData = {
  positions: Position[];
  value: number;
  invested: number;
  custom: boolean;
  candidates: { symbol: string; name: string; price: number }[];
};

/** The lot for the − / + buttons: shares worth about `pct` of the portfolio (your setting),
 *  rounded to 1, 2, 5, 10, 25, 50… so a tap is a round number of shares. */
function lotSize(px: number, total: number, pct: number): number {
  const raw = Math.max(1, ((pct / 100) * total) / px);
  const steps = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000];
  return steps.reduce((best, s) => (Math.abs(Math.log(s / raw)) < Math.abs(Math.log(best / raw)) ? s : best), 1);
}

function EditSheet({
  open,
  onClose,
  onSaved,
  onReset,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  onReset: (undo: Record<string, [number, number]> | null) => void;
}) {
  const { data, mutate } = useApi<HoldingsData>(open ? "/portfolio/holdings" : null);
  const { data: sd, mutate: mutateSettings } = useApi<{ settings: Settings }>(open ? "/portfolio/settings" : null);
  const lotPct = sd?.settings.lot_pct ?? 0.5;
  const newPct = sd?.settings.new_holding_pct ?? 3;
  const saveSize = (k: "lot_pct" | "new_holding_pct", v: number) => {
    if (!sd) return;
    mutateSettings({ settings: { ...sd.settings, [k]: v } }, false);
    pending.current = { ...pending.current, [k]: v }; // both sizes go in one save
    clearTimeout(sizeTimer.current);
    sizeTimer.current = setTimeout(() => {
      const body = pending.current;
      pending.current = {};
      api("/portfolio/settings", { method: "PUT", body: JSON.stringify(body) }).catch(() => mutateSettings());
    }, 400);
  };
  const sizeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pending = useRef<Record<string, number>>({});
  const [draft, setDraft] = useState<Record<string, number> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const saved = data ? Object.fromEntries(data.positions.map((p) => [p.symbol, p.qty])) : null;
  const qty = draft ?? saved;
  const px: Record<string, number> = data
    ? Object.fromEntries([...data.positions.map((p) => [p.symbol, p.price]), ...data.candidates.map((c) => [c.symbol, c.price])])
    : {};
  const oldW = data ? Object.fromEntries(data.positions.map((p) => [p.symbol, p.weight * 100])) : {};
  // everything below is arithmetic on the draft: value = shares × latest close, weight = value / total
  const total = qty ? Object.entries(qty).reduce((a, [s, q]) => a + q * (px[s] ?? 0), 0) : 0;
  const order = data ? [...data.positions.map((p) => p.symbol), ...Object.keys(qty ?? {}).filter((s) => !(s in (saved ?? {})))] : [];
  const changed = !!draft && JSON.stringify(draft) !== JSON.stringify(saved);
  const bought = qty && saved ? Object.entries(qty).reduce((a, [s, q]) => a + Math.max(0, q - (saved[s] ?? 0)) * px[s], 0) : 0;
  const sold = qty && saved ? Object.entries(saved).reduce((a, [s, q]) => a + Math.max(0, q - (qty[s] ?? 0)) * px[s], 0) : 0;
  const lots = data ? Object.fromEntries(Object.keys(px).map((s) => [s, lotSize(px[s], data.value, lotPct)])) : {};
  const set = (s: string, q: number) => qty && setDraft({ ...qty, [s]: Math.max(0, Math.round(q)) });
  const close = () => {
    setDraft(null);
    setErr(null);
    onClose();
  };
  const save = async () => {
    if (!qty) return;
    setErr(null);
    setSaving(true);
    try {
      await api("/portfolio/holdings", {
        method: "PUT",
        body: JSON.stringify({ qty: Object.fromEntries(Object.entries(qty).filter(([, q]) => q > 0)) }),
      });
      await mutate();
      onSaved();
      close();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  };
  const reset = async () => {
    const r = await api<{ undo: Record<string, [number, number]> | null }>("/portfolio/holdings/reset", { method: "POST" });
    await mutate();
    onSaved();
    onReset(r.undo);
    close();
  };
  const addable = data && qty ? data.candidates.filter((c) => !(c.symbol in qty)) : [];
  const held = qty ? Object.values(qty).filter((q) => q > 0).length : 0;
  return (
    <Sheet open={open} onClose={close} title="Edit holdings">
      {!qty || !data ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <p className="text-[12px] leading-snug text-ink-3">
            Change shares with − and +, or type a number. Weights are worked out from today&apos;s closing prices as you go. Private to this account; nothing is traded.
          </p>
          <ul className="mt-2 divide-y divide-line">
            {order.map((s) => {
              const q = qty[s] ?? 0;
              const w = total ? ((q * px[s]) / total) * 100 : 0;
              const dw = w - (oldW[s] ?? 0);
              const lot = lots[s] ?? 1;
              return (
                <li key={s} className={clsx("py-2", q === 0 && "opacity-50")}>
                  <div className="flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[14px] font-semibold">{s}</p>
                      <p className="tnum truncate text-[11px] text-ink-3">
                        {price(px[s])} · {inr(q * px[s])}
                      </p>
                    </div>
                    <div className="flex items-center rounded-full border border-line">
                      <button aria-label={`Sell ${lot} ${s}`} onClick={() => set(s, q - lot)} disabled={q === 0} className="p-2 text-ink-2 disabled:opacity-30">
                        <Minus size={14} />
                      </button>
                      <input
                        aria-label={`${s} shares`}
                        inputMode="numeric"
                        value={q}
                        onChange={(e) => set(s, parseInt(e.target.value.replace(/\D/g, "") || "0", 10))}
                        className="tnum w-14 bg-transparent text-center text-[14px] outline-none"
                      />
                      <button aria-label={`Buy ${lot} ${s}`} onClick={() => set(s, q + lot)} className="p-2 text-ink-2">
                        <Plus size={14} />
                      </button>
                    </div>
                    <div className="tnum w-[52px] shrink-0 text-right">
                      <p className="text-[13px] font-medium">{w.toFixed(1)}%</p>
                      <p className={clsx("text-[11px]", Math.abs(dw) < 0.05 ? "text-ink-3" : dw > 0 ? "text-good" : "text-bad")}>
                        {Math.abs(dw) < 0.05 ? "—" : `${dw > 0 ? "+" : "−"}${Math.abs(dw).toFixed(1)}`}
                      </p>
                    </div>
                    <button aria-label={q === 0 ? `Keep ${s}` : `Sell all ${s}`} onClick={() => set(s, q === 0 ? (saved?.[s] ?? lot) : 0)} className="p-1 text-ink-3">
                      {q === 0 ? <Plus size={15} /> : <X size={15} />}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="mt-3 space-y-2.5 rounded-xl border border-line p-3">
            <div>
              <p className="mb-1 text-[12px] text-ink-2">− and + move a holding by shares worth about</p>
              <NumberSlider label="Lot size, percent of portfolio" value={lotPct} min={0.1} max={5} hardMax={25} step={0.1} unit="%" onChange={(v) => saveSize("lot_pct", v)} />
            </div>
            <div>
              <p className="mb-1 text-[12px] text-ink-2">A company you add comes in at about</p>
              <NumberSlider label="New holding size, percent of portfolio" value={newPct} min={0.5} max={10} hardMax={50} step={0.1} unit="%" onChange={(v) => saveSize("new_holding_pct", v)} />
            </div>
          </div>
          <div className="tnum mt-2 flex items-baseline justify-between rounded-xl bg-surface-2 px-3 py-2 text-[12px]">
            <span className="text-ink-2">
              {changed ? (
                <>
                  {bought > 0 && <>Buy {inr(bought)}</>}
                  {bought > 0 && sold > 0 && " · "}
                  {sold > 0 && <>Sell {inr(sold)}</>}
                </>
              ) : (
                "No changes yet"
              )}
            </span>
            <span>
              Total <b>{inr(total)}</b>
            </span>
          </div>
          {addable.length > 0 && (
            <>
              <p className="mt-3 text-[12px] font-medium text-ink-2">Add a company FINN covers</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {addable.map((c) => (
                  <button
                    key={c.symbol}
                    onClick={() => set(c.symbol, Math.max(1, Math.round((((newPct / 100) / (1 - newPct / 100)) * total) / c.price)))}
                    className="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[12px] text-ink-2"
                    title={`${c.name}: adds about ${newPct}% of the portfolio`}
                  >
                    <Plus size={12} /> {c.symbol}
                  </button>
                ))}
              </div>
            </>
          )}
          {err && <p className="mt-2 text-[12px] text-bad">{err}</p>}
          <div className="mt-4 flex gap-2">
            {data.custom && (
              <button onClick={reset} className="rounded-full border border-line px-4 py-2 text-[13px] text-ink-2">
                Reset to demo
              </button>
            )}
            <button onClick={save} disabled={!changed || held === 0 || saving} className="flex-1 rounded-full bg-ink py-2 text-[14px] font-medium text-bg disabled:opacity-40">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </>
      )}
    </Sheet>
  );
}
