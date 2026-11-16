"use client";

import Link from "next/link";
import { useState } from "react";
import clsx from "clsx";
import { AlertTriangle, Calculator, Pencil, Plus, Sparkles, X } from "lucide-react";
import { useSWRConfig } from "swr";
import { api, useApi } from "@/lib/api";
import { day, pct } from "@/lib/fmt";
import { ErrorNote, Header, Panel, SectionTitle, Segmented, Sheet, Skeleton } from "@/components/ui";

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
  summary: Stats & { holdings: number; return_6m: number; return_1m: number; max_drawdown: number };
  holdings: Holding[];
  themes: { theme: string; weight: number; risk_share: number; contribution_6m: number; symbols: string[] }[];
  correlated: { a: string; b: string; corr: number }[];
  flags: string[];
};
type SugRow = { symbol: string; name: string; theme: string; current: number; suggested: number; change: number; reason: string };
type Source = { id: string; symbol: string; what: string; date?: string };
type Review =
  | { status: "not_run"; events: number }
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
  rules: { min: number; max: number; theme_cap: number; max_step: number; days: number };
  review: Review;
};

const one = (v: number | null | undefined, unit = "%") => (v == null ? "—" : `${v.toFixed(1)}${unit}`);

export default function PortfolioPage() {
  const [tab, setTab] = useState<"now" | "suggested">("now");
  const [editing, setEditing] = useState(false);
  const { data, error, mutate } = useApi<Overview>("/portfolio");
  const { mutate: refresh } = useSWRConfig();
  const reload = () => refresh(() => true); // Today, alerts and both tabs follow the holdings

  return (
    <main className="pb-10">
      <Header
        title="Portfolio"
        sub={data ? `${data.summary.holdings} holdings${data.custom ? " · edited by you" : ""} · prices to ${data.as_of ? day(data.as_of) : "—"}` : " "}
        right={
          <button onClick={() => setEditing(true)} className="flex items-center gap-1 rounded-full border border-line px-3 py-1.5 text-[13px] font-medium text-ink-2">
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
        </div>
      ) : tab === "now" ? (
        <Now d={data} />
      ) : (
        <Suggested onApplied={reload} />
      )}
      <EditSheet open={editing} onClose={() => setEditing(false)} onSaved={reload} />
    </main>
  );
}

// ------------------------------------------------------------------ as it stands
function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-3">
      <p className="text-[11px] text-ink-3">{label}</p>
      <p className="tnum mt-0.5 text-[20px] font-semibold leading-tight tracking-[-0.01em]">{value}</p>
      {sub && <p className="text-[11px] text-ink-3">{sub}</p>}
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

function Now({ d }: { d: Overview }) {
  const s = d.summary;
  const maxTheme = Math.max(...d.themes.map((t) => t.weight));
  const maxW = Math.max(...d.holdings.map((h) => h.weight));
  return (
    <>
      <div className="mt-3 grid grid-cols-2 gap-2 px-3">
        <Tile label={`Return, last ${Math.round(d.days / 21)} months`} value={pct(s.return_6m)} sub={`${pct(s.return_1m)} in the last month`} />
        <Tile label="Volatility, a year" value={one(s.volatility)} sub={`worst fall ${pct(s.max_drawdown)}`} />
        <Tile label="Spread" value={`${s.effective_holdings.toFixed(1)} of ${s.holdings}`} sub={`effective holdings · top 5 = ${s.top5.toFixed(0)}%`} />
        <Tile label="Valuation and quality" value={`${s.pe?.toFixed(1) ?? "—"}× P/E`} sub={`ROE ${one(s.roe)} · 3y sales growth ${one(s.revenue_growth_3y)}`} />
      </div>

      {d.flags.length > 0 && (
        <ul className="mx-3 mt-3 space-y-1.5 rounded-2xl bg-warn-soft/60 px-3.5 py-3">
          {d.flags.map((f) => (
            <li key={f} className="flex gap-2 text-[13px] leading-snug">
              <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warn" aria-hidden />
              {f}
            </li>
          ))}
        </ul>
      )}

      <SectionTitle aside="weight · share of risk">By theme</SectionTitle>
      <Panel className="divide-y divide-line">
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
      </Panel>

      <SectionTitle aside="weight · 6-month return">Holdings</SectionTitle>
      <Panel className="divide-y divide-line">
        {d.holdings.map((h) => (
          <Link key={h.symbol} href={`/c/${h.symbol}`} className="block px-4 py-2.5 active:bg-surface-2">
            <div className="flex items-baseline justify-between gap-2 text-[13px]">
              <span className="min-w-0 truncate">
                <span className="font-semibold">{h.symbol}</span> <span className="text-ink-3 capitalize">{h.theme}</span>
              </span>
              <span className="tnum shrink-0">
                {h.weight.toFixed(1)}% · <span className="text-ink-2">{pct(h.return_6m)}</span>
              </span>
            </div>
            <div className="mt-1.5">
              <Bar value={h.weight} max={maxW} />
            </div>
            <p className="tnum mt-1 text-[11px] text-ink-3">
              {h.risk_share.toFixed(1)}% of risk · volatility {h.volatility.toFixed(0)}%
              {h.pe ? ` · P/E ${h.pe.toFixed(0)}` : ""}
              {h.delivery != null ? ` · delivery ${h.delivery}/100` : ""}
            </p>
          </Link>
        ))}
      </Panel>

      {d.correlated.length > 0 && (
        <>
          <SectionTitle aside="daily returns, 6 months">Move together most</SectionTitle>
          <Panel className="divide-y divide-line">
            {d.correlated.map((c) => (
              <Link key={c.a + c.b} href={`/compare?a=${c.a}&b=${c.b}`} className="flex items-center justify-between px-4 py-2.5 text-[13px] active:bg-surface-2">
                <span>
                  <span className="font-semibold">{c.a}</span> and <span className="font-semibold">{c.b}</span>
                </span>
                <span className="tnum text-ink-2">correlation {c.corr.toFixed(2)} · compare →</span>
              </Link>
            ))}
          </Panel>
        </>
      )}
      <p className="px-6 pt-4 text-center text-[11px] leading-snug text-ink-3">
        Computed in code from {d.days} days of end-of-day prices and the reported financials. No AI on this page.
      </p>
    </>
  );
}

// ------------------------------------------------------------------ suggested
function Suggested({ onApplied }: { onApplied: () => void }) {
  const { data, error, mutate } = useApi<Suggestion>("/portfolio/suggested");
  const [withAi, setWithAi] = useState(true);
  const [running, setRunning] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  if (error && !data) return <div className="mt-4"><ErrorNote error={error} retry={() => mutate()} /></div>;
  if (!data) return <div className="px-4 pt-4"><Skeleton className="h-96" /></div>;

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

  return (
    <>
      <div className="mx-3 mt-3 rounded-2xl border border-line bg-surface p-3.5 text-[13px] leading-snug">
        <p className="flex items-center gap-1.5 font-semibold">
          <Calculator size={14} className="text-accent" /> How this is built
        </p>
        <ol className="mt-1.5 list-decimal space-y-1 pl-4 text-ink-2">
          <li><b className="text-ink">Balance risk.</b> Every holding gets the same share of the portfolio&apos;s swings, from {data.rules.days} days of prices.</li>
          <li><b className="text-ink">Lean towards quality.</b> Returns on capital, growth, cash conversion, debt, valuation and management&apos;s delivery record tilt each weight.</li>
          <li><b className="text-ink">Stay investable.</b> {data.rules.min}–{data.rules.max}% per holding, {data.rules.theme_cap}% per theme, at most {data.rules.max_step} points of change at a time.</li>
          <li><b className="text-ink">AI review.</b> The AI reads the last 30 days of filings and may move a holding by up to 2 points, citing the filing. Code enforces the limits.</li>
        </ol>
        <p className="mt-1.5 text-[12px] text-ink-3">It does not forecast returns. Same holdings, different proportions.</p>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 px-3">
        <Tile label="Volatility, a year" value={`${one(b.volatility)} → ${one(a.volatility)}`} />
        <Tile label="Largest theme" value={`${b.largest_theme.weight.toFixed(0)}% → ${a.largest_theme.weight.toFixed(0)}%`} sub={a.largest_theme.theme} />
        <Tile label="P/E · ROE" value={`${a.pe?.toFixed(1) ?? "—"}× · ${one(a.roe)}`} sub={`from ${b.pe?.toFixed(1) ?? "—"}× · ${one(b.roe)}`} />
        <Tile label="Turnover" value={`${data.turnover.toFixed(1)}%`} sub="of the portfolio changes hands" />
      </div>

      <SectionTitle aside={rv.status === "done" ? `${rv.events} filings read` : undefined}>AI review</SectionTitle>
      <Panel className="p-4">
        {rv.status === "not_run" ? (
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
                    <span className="tnum font-medium">{x.applied > 0 ? "+" : ""}{x.applied.toFixed(1)} pts</span>
                    {Math.abs(x.asked) > 2 && <span className="text-ink-3"> (asked {x.asked}, capped at 2)</span>}. {x.reason}
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
        {data.holdings.map((r) => {
          const w = weight(r);
          const ch = w - r.current;
          const nudge = reviewed ? rv.adjustments.find((x) => x.symbol === r.symbol) : undefined;
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
                    AI review: {nudge.applied > 0 ? "+" : ""}
                    {nudge.applied.toFixed(1)} pts. {nudge.reason}
                  </span>
                )}
              </p>
            </div>
          );
        })}
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

// ------------------------------------------------------------------ edit
function EditSheet({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { data, mutate } = useApi<{ holdings: Record<string, number>; custom: boolean; candidates: { symbol: string; name: string }[] }>(
    open ? "/portfolio/holdings" : null,
  );
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const rows = draft ?? (data ? Object.fromEntries(Object.entries(data.holdings).map(([s, w]) => [s, (w * 100).toFixed(1)])) : null);
  const total = rows ? Object.values(rows).reduce((a, v) => a + (parseFloat(v) || 0), 0) : 0;
  const close = () => {
    setDraft(null);
    setErr(null);
    onClose();
  };
  const save = async () => {
    if (!rows) return;
    setErr(null);
    try {
      await api("/portfolio/holdings", {
        method: "PUT",
        body: JSON.stringify({ weights: Object.fromEntries(Object.entries(rows).map(([s, v]) => [s, parseFloat(v) || 0])) }),
      });
      await mutate();
      onSaved();
      close();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't save.");
    }
  };
  const reset = async () => {
    await api("/portfolio/holdings/reset", { method: "POST" });
    await mutate();
    onSaved();
    close();
  };
  const held = rows ? new Set(Object.keys(rows)) : new Set<string>();
  return (
    <Sheet open={open} onClose={close} title="Edit holdings">
      {!rows || !data ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <p className="text-[12px] leading-snug text-ink-3">
            Weights in percent. They don&apos;t have to add to 100: FINN scales them. Today, alerts and this page follow your list. Private to this account.
          </p>
          <ul className="mt-2 divide-y divide-line">
            {Object.entries(rows).map(([s, v]) => (
              <li key={s} className="flex items-center gap-2 py-1.5">
                <span className="min-w-0 flex-1 text-[14px] font-medium">{s}</span>
                <input
                  aria-label={`${s} weight`}
                  inputMode="decimal"
                  value={v}
                  onChange={(e) => setDraft({ ...rows, [s]: e.target.value })}
                  className="tnum w-16 rounded-lg border border-line bg-surface px-2 py-1 text-right text-[14px] outline-none focus:border-accent"
                />
                <span className="text-[13px] text-ink-3">%</span>
                <button
                  aria-label={`Remove ${s}`}
                  onClick={() => {
                    const next = { ...rows };
                    delete next[s];
                    setDraft(next);
                  }}
                  className="p-1.5 text-ink-3"
                >
                  <X size={15} />
                </button>
              </li>
            ))}
          </ul>
          <p className="tnum mt-1 text-right text-[12px] text-ink-3">Total {total.toFixed(1)}%</p>
          {data.candidates.filter((c) => !held.has(c.symbol)).length > 0 && (
            <>
              <p className="mt-3 text-[12px] font-medium text-ink-2">Add a company FINN covers</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {data.candidates
                  .filter((c) => !held.has(c.symbol))
                  .map((c) => (
                    <button
                      key={c.symbol}
                      onClick={() => setDraft({ ...rows, [c.symbol]: "3.0" })}
                      className="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[12px] text-ink-2"
                      title={c.name}
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
            <button onClick={save} disabled={Object.keys(rows).length === 0} className="flex-1 rounded-full bg-ink py-2 text-[14px] font-medium text-bg disabled:opacity-40">
              Save
            </button>
          </div>
        </>
      )}
    </Sheet>
  );
}
