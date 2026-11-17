"use client";

import { useMemo, useState } from "react";
import clsx from "clsx";
import { Check, ChevronDown, FileText, Loader2, Upload } from "lucide-react";
import { api, getAccount, useApi } from "@/lib/api";
import { day, pct, price } from "@/lib/fmt";
import { AiTag, Panel, Pill, SectionTitle, Segmented, Sheet } from "./ui";

// ------------------------------------------------------------------ types (backend app/brokerage/service.py)
type Stats = { n: number; median: number; min: number; max: number; p25: number; p75: number };
type Evidence = { status: string; page?: number; excerpt?: string };
type Estimate = {
  metric: string;
  fiscal_period: string | null;
  value: number;
  unit: string;
  is_actual: number;
  verified: number;
  source_page: number | null;
  other_basis: boolean;
};
export type Obs = {
  id: string;
  report_id: string;
  brokerage_id: string;
  brokerage: string;
  analyst: string | null;
  published_at: string;
  title: string | null;
  rating: string | null;
  rating_raw: string | null;
  target_price: number | null;
  target_verified: boolean;
  reference_price: number | null;
  implied_return_pct: number | null;
  horizon: string;
  horizon_basis: string | null;
  horizon_bucket: string;
  thesis: string | null;
  risks: string[];
  valuation_method: string | null;
  estimates: Estimate[];
  basis: { status: string };
  evidence: Record<string, Evidence>;
  source: { type: string; url: string | null; pages: number; yours: boolean; extraction: string };
  confidence: number;
  needs_review: string[];
};
type Group = {
  horizon: string;
  brokerages: number;
  targets: Stats;
  median_implied_return_pct: number | null;
  median_vs_last_close_pct: number | null;
  consensus_label: boolean;
  who: string[];
};
export type Overview = {
  symbol: string;
  as_of: string;
  reports: number;
  brokerages: number;
  latest_report: string | null;
  latest_age_days: number | null;
  last_close: { date: string; price: number } | null;
  ratings: Record<string, number>;
  ratings_raw: Record<string, number>;
  targets: Group[];
  latest: Obs[];
  stale: Obs[];
  warnings: string[];
};
type Revision = {
  brokerage_id: string;
  brokerage: string;
  from: string;
  to: string;
  rating_from: string | null;
  rating_to: string | null;
  rating_move: string;
  target_from: number | null;
  target_to: number | null;
  target_change_pct: number | null;
  estimates: { metric: string; fiscal_period: string; unit: string; old: number; new: number; change_pct: number | null }[];
};
type Momentum = {
  days: number;
  brokerages: number;
  upgrades: number;
  downgrades: number;
  target_up: number;
  target_down: number;
  target_same: number;
  median_target_change_pct: number | null;
  median_eps_change_pct: Record<string, number>;
};
export type Revisions = { events: Revision[]; momentum: Momentum[]; note: string };
type Spread = {
  metric: string;
  fiscal_period: string;
  unit: string;
  spread_pct: number;
  values: { brokerage: string; value: number; page: number }[];
};
type Explain = {
  status: string;
  summary?: string | null;
  points?: { text: string; cites: { report_id: string; brokerage: string; date: string }[] }[];
  dropped?: unknown[];
};
export type Divergence = {
  brokerages: number;
  targets: { horizon: string; comparable: boolean; spread_pct: number | null; values: { brokerage: string; target: number }[] }[];
  estimates: Spread[];
  bullish_with_cuts: { brokerage: string; rating: string; eps_cuts: { fiscal_period: string; change_pct: number }[] }[];
  caveats: string[];
  explanation: Explain;
};
export type Track = {
  targets: { available: boolean; message: string; detail: string; eligible: number };
  forecasts: {
    eligible: number;
    note: string;
    rows: { brokerage: string; published_at: string; metric: string; fiscal_period: string; forecast: number; actual: number; abs_error_pct: number; caveat?: string }[];
  };
  method: { warning: string };
};

// ------------------------------------------------------------------ helpers
const short = (name: string) => name.replace(/\s*\(.*\)$/, "");
const TONE = { positive: "good", neutral: "neutral", negative: "bad" } as const;
const FINN = "Calculated by FINN";
/** Targets are whole rupees in every report. */
const rs = (v: number | null | undefined) => (v == null ? "—" : `₹${Math.round(v).toLocaleString("en-IN")}`);
const hz = (h: string) => (h === "12 months" ? "12-month" : h);

function value(v: number, unit: string) {
  if (/share|^INR$/i.test(unit)) return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 1 })}`;
  if (unit === "%") return `${v}%`;
  if (/crore/i.test(unit)) return `₹${Math.round(v).toLocaleString("en-IN")} Cr`;
  return `${v.toLocaleString("en-IN", { maximumFractionDigits: 1 })} ${unit}`;
}

function Verified({ e }: { e?: Evidence }) {
  if (!e) return null;
  return e.status === "verified" ? (
    <Check size={12} className="inline text-good" aria-label={`checked on page ${e.page}`} />
  ) : (
    <span className="text-[10px] text-warn">{e.status}</span>
  );
}

// ------------------------------------------------------------------ the target range
function RangeBar({ g, close }: { g: Group; close: number | null }) {
  const lo = Math.min(g.targets.min, close ?? g.targets.min) * 0.97;
  const hi = Math.max(g.targets.max, close ?? g.targets.max) * 1.03;
  const at = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="relative mt-3 h-7" aria-hidden>
      <div className="absolute inset-x-0 top-3 h-[2px] rounded bg-line" />
      <div
        className="absolute top-2 h-2 rounded-full bg-accent/30"
        style={{ left: at(g.targets.min), width: `calc(${at(g.targets.max)} - ${at(g.targets.min)})` }}
      />
      <div className="absolute top-1 h-4 w-[2px] rounded bg-accent" style={{ left: at(g.targets.median) }} />
      {close != null && (
        <div className="absolute top-0 flex flex-col items-center" style={{ left: at(close), transform: "translateX(-50%)" }}>
          <div className="h-6 w-[2px] rounded bg-ink-2" />
        </div>
      )}
    </div>
  );
}

function Targets({ ov }: { ov: Overview }) {
  const close = ov.last_close?.price ?? null;
  return (
    <div className="space-y-4">
      {ov.targets.map((g) => (
        <div key={g.horizon}>
          <p className="text-[12px] text-ink-3">
            Targets · {g.horizon === "not stated" ? "horizon not stated" : `${hz(g.horizon)} horizon`} · {g.brokerages} brokerage{g.brokerages > 1 ? "s" : ""}
          </p>
          {g.brokerages > 1 ? (
            <>
              <p className="tnum mt-0.5 text-[20px] font-semibold">
                {rs(g.targets.min)} – {rs(g.targets.max)}
              </p>
              <p className="tnum text-[12px] text-ink-2">
                median {rs(g.targets.median)}
                {g.median_vs_last_close_pct != null && <> · {pct(g.median_vs_last_close_pct)} vs last close {price(close)}</>}
              </p>
              <RangeBar g={g} close={close} />
              <p className="text-[11px] text-ink-3">
                <span className="inline-block h-2 w-2 rounded-full bg-accent/40 align-middle" /> range ·{" "}
                <span className="inline-block h-2.5 w-[2px] bg-accent align-middle" /> median ·{" "}
                <span className="inline-block h-2.5 w-[2px] bg-ink-2 align-middle" /> last close · {FINN}
              </p>
              {!g.consensus_label && <p className="mt-1 text-[11px] text-ink-3">Too few houses to call this a consensus; it is the range of the reports FINN has.</p>}
            </>
          ) : (
            <p className="tnum mt-0.5 text-[16px] font-semibold">
              {rs(g.targets.median)} <span className="text-[12px] font-normal text-ink-2">· {g.who.map(short).join(", ")}</span>
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ one brokerage's latest view
function Card({ o, open }: { o: Obs; open: (o: Obs) => void }) {
  return (
    <li className="py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-[14px] font-medium">{short(o.brokerage)}</p>
          <p className="text-[12px] text-ink-3">
            {day(o.published_at)} {o.published_at.slice(0, 4)} · {o.horizon_bucket === "12 months" ? "12-month target" : "horizon not stated"}
            {o.source.yours && " · yours"}
          </p>
        </div>
        <div className="text-right">
          <p className="tnum text-[15px] font-semibold">
            {o.target_price != null ? rs(o.target_price) : "—"} <Verified e={o.evidence.target_price} />
          </p>
          {o.rating_raw && (
            <Pill tone={TONE[o.rating as keyof typeof TONE] ?? "neutral"}>{o.rating_raw}</Pill>
          )}
        </div>
      </div>
      <div className="mt-1 flex items-center justify-between gap-2 text-[12px]">
        <span className="tnum text-ink-2">
          {o.implied_return_pct != null ? `${pct(o.implied_return_pct)} from its price ${rs(o.reference_price)}` : "no reference price"}
        </span>
        <button onClick={() => open(o)} className="inline-flex shrink-0 items-center gap-1 font-medium text-accent">
          <FileText size={12} /> Source
        </button>
      </div>
      {o.needs_review.length > 0 && <p className="mt-1 text-[11px] text-warn">Needs review: {o.needs_review.join(", ")}</p>}
    </li>
  );
}

function SourceSheet({ o, close }: { o: Obs | null; close: () => void }) {
  const fields: [string, string][] = [
    ["rating", "Rating"],
    ["target_price", "Target"],
    ["reference_price", "Price used"],
    ["horizon", "Horizon"],
    ["published_at", "Date"],
  ];
  return (
    <Sheet open={!!o} onClose={close} title={o ? short(o.brokerage) : ""}>
      {o && (
        <div className="space-y-3 text-[13px]">
          <p className="text-ink-2">
            {o.title} · {day(o.published_at)} {o.published_at.slice(0, 4)}
            {o.analyst && <> · {o.analyst}</>}
          </p>
          <ul className="divide-y divide-line">
            {fields.map(([k, label]) => {
              const e = o.evidence[k];
              return (
                <li key={k} className="py-2">
                  <p className="flex justify-between text-[12px] text-ink-3">
                    <span>{label}</span>
                    <span>{e?.status === "verified" ? `found on page ${e.page}` : e?.status ?? "—"}</span>
                  </p>
                  {e?.excerpt && <p className="mt-0.5 text-[12px] italic leading-snug">“{e.excerpt}”</p>}
                </li>
              );
            })}
          </ul>
          {o.valuation_method && <p><span className="text-ink-3">Valuation:</span> {o.valuation_method}</p>}
          {o.thesis && <p className="leading-snug"><span className="text-ink-3">Thesis (as the report puts it):</span> {o.thesis}</p>}
          {o.risks.length > 0 && <p className="leading-snug"><span className="text-ink-3">Risks it names:</span> {o.risks.join("; ")}</p>}
          <p className="text-[12px] text-ink-3">
            Estimates table: {o.basis.status === "other basis" ? "not on the reported consolidated basis, so FINN doesn't compare it with other houses" : o.basis.status}.
            {" "}{o.estimates.filter((e) => e.verified).length} of {o.estimates.length} figures found on their page.
            {" "}Read by AI ({o.source.extraction}), every field above checked in code against the page text.
          </p>
          {o.source.url && (
            <a href={o.source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent">
              <FileText size={13} /> Open the report ({o.source.pages} pages)
            </a>
          )}
        </div>
      )}
    </Sheet>
  );
}

// ------------------------------------------------------------------ revisions
function RevisionList({ rev, only }: { rev: Revisions; only: string | null }) {
  const [days, setDays] = useState<"30" | "90" | "180">("90");
  const m = rev.momentum.find((x) => String(x.days) === days);
  const events = rev.events.filter((e) => !only || e.brokerage_id === only);
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] text-ink-3">Last</p>
        <Segmented
          label="Look-back"
          value={days}
          onChange={setDays}
          options={[
            { value: "30", label: "30 days" },
            { value: "90", label: "90 days" },
            { value: "180", label: "180 days" },
          ]}
        />
      </div>
      {m && (
        <p className="tnum mt-2 text-[13px] leading-snug">
          {m.brokerages === 0 ? (
            "No revisions in this window."
          ) : (
            <>
              {m.brokerages} brokerage{m.brokerages > 1 ? "s" : ""} revised: targets up {m.target_up}, down {m.target_down}
              {m.target_same > 0 && `, same ${m.target_same}`}; median target change {pct(m.median_target_change_pct)}.
              {Object.keys(m.median_eps_change_pct).length > 0 && (
                <> Median EPS change {Object.entries(m.median_eps_change_pct).map(([fy, v]) => `${fy} ${pct(v)}`).join(", ")}.</>
              )}
              {(m.upgrades > 0 || m.downgrades > 0) && <> Ratings: {m.upgrades} up, {m.downgrades} down.</>}
            </>
          )}
          <span className="block text-[11px] text-ink-3">{FINN}, each house against its own previous report.</span>
        </p>
      )}
      <ol className="mt-3 space-y-3 border-l border-line pl-3">
        {events.slice().reverse().map((e) => {
          const eps = e.estimates.filter((x) => x.metric === "EPS" && x.change_pct != null);
          return (
            <li key={`${e.brokerage_id}-${e.to}`} className="relative">
              <span className="absolute -left-[17px] top-1.5 h-2 w-2 rounded-full bg-ink-3" />
              <p className="text-[12px] text-ink-3">
                {day(e.to)} {e.to.slice(0, 4)} · {short(e.brokerage)}
              </p>
              <p className="tnum text-[13px]">
                {e.target_from != null && e.target_to != null ? (
                  <>
                    {rs(e.target_from)} → {rs(e.target_to)}{" "}
                    <span className={clsx((e.target_change_pct ?? 0) < 0 ? "text-bad" : (e.target_change_pct ?? 0) > 0 ? "text-good" : "text-ink-2")}>
                      ({pct(e.target_change_pct)})
                    </span>
                  </>
                ) : (
                  "target not comparable"
                )}
                {e.rating_move !== "unchanged" && e.rating_move !== "not comparable" && (
                  <span className="text-ink-2"> · {e.rating_from} → {e.rating_to}</span>
                )}
              </p>
              {eps.length > 0 && (
                <p className="tnum text-[12px] text-ink-2">EPS {eps.map((x) => `${x.fiscal_period} ${pct(x.change_pct)}`).join(", ")}</p>
              )}
            </li>
          );
        })}
      </ol>
      {events.length === 0 && <p className="text-[13px] text-ink-2">No earlier report from this house to compare with.</p>}
    </div>
  );
}

// ------------------------------------------------------------------ disagreement
function Disagreement({ d }: { d: Divergence }) {
  const [more, setMore] = useState(false);
  const ex = d.explanation;
  const rows = more ? d.estimates : d.estimates.slice(0, 3);
  return (
    <div className="space-y-3">
      {d.targets.map((t) => (
        <p key={t.horizon} className="tnum text-[13px] leading-snug">
          {t.comparable && t.spread_pct != null ? (
            <>
              {hz(t.horizon)} targets differ by <b>{pct(t.spread_pct, false)}</b> (highest vs lowest):{" "}
              {t.values.map((v) => `${short(v.brokerage)} ${rs(v.target)}`).join(", ")}.
            </>
          ) : (
            <span className="text-ink-2">
              Horizon not stated, kept apart: {t.values.map((v) => `${short(v.brokerage)} ${rs(v.target)}`).join(", ")}.
            </span>
          )}
        </p>
      ))}
      {d.estimates.length > 0 && (
        <div>
          <p className="text-[12px] text-ink-3">Where their estimates differ most</p>
          <ul className="divide-y divide-line">
            {rows.map((e) => (
              <li key={`${e.metric}-${e.fiscal_period}`} className="flex items-baseline justify-between gap-2 py-1.5 text-[13px]">
                <span>
                  {e.metric} {e.fiscal_period}
                  <span className="block text-[11px] text-ink-3">
                    {e.values.map((v) => `${short(v.brokerage).split(" ")[0]} ${value(v.value, e.unit)}`).join(" · ")}
                  </span>
                </span>
                <span className="tnum shrink-0 font-medium">{pct(e.spread_pct, false)}</span>
              </li>
            ))}
          </ul>
          {d.estimates.length > 3 && (
            <button onClick={() => setMore(!more)} className="mt-1 inline-flex items-center gap-1 text-[12px] font-medium text-accent">
              {more ? "Fewer" : `All ${d.estimates.length}`} <ChevronDown size={12} className={clsx(more && "rotate-180")} />
            </button>
          )}
        </div>
      )}
      {d.bullish_with_cuts.map((b) => (
        <p key={b.brokerage} className="text-[13px] leading-snug">
          {short(b.brokerage)} keeps {b.rating} while cutting EPS ({b.eps_cuts.map((c) => `${c.fiscal_period} ${pct(c.change_pct)}`).join(", ")}).
        </p>
      ))}
      <p className="text-[11px] text-ink-3">{FINN} from each house&apos;s latest report. {d.caveats.join(" ")}</p>
      {ex.status === "done" && ex.points && ex.points.length > 0 && (
        <div className="rounded-xl bg-surface-2/60 p-3">
          <p className="text-[12px] font-medium text-ink-2">Why they differ</p>
          {ex.summary && <p className="mt-1 text-[13px] leading-snug">{ex.summary}</p>}
          <ul className="mt-2 space-y-2">
            {ex.points.map((p, i) => (
              <li key={i} className="text-[13px] leading-snug">
                {p.text}
                <span className="ml-1 text-[11px] text-ink-3">[{p.cites.map((c) => short(c.brokerage).split(" ")[0]).join(", ")}]</span>
              </li>
            ))}
          </ul>
          <p className="mt-2">
            <AiTag from="the reports' stated assumptions; every figure checked in code" />
          </p>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ track record
function TrackRecord({ t }: { t: Track }) {
  return (
    <div className="space-y-2 text-[13px]">
      <p className="font-medium">{t.targets.message}</p>
      <p className="text-[12px] leading-snug text-ink-3">{t.targets.detail}</p>
      {t.forecasts.rows.length > 0 && (
        <>
          <p className="pt-1 text-[12px] text-ink-3">{t.forecasts.note}</p>
          <ul className="divide-y divide-line">
            {t.forecasts.rows.map((r, i) => (
              <li key={i} className="flex items-baseline justify-between gap-2 py-1.5">
                <span>
                  {short(r.brokerage)} · {r.metric} {r.fiscal_period}
                  <span className="block text-[11px] text-ink-3">
                    forecast {day(r.published_at)} {r.published_at.slice(0, 4)}: {r.forecast.toLocaleString("en-IN")} vs reported {r.actual.toLocaleString("en-IN")}
                  </span>
                </span>
                <span className="tnum shrink-0">{pct(r.abs_error_pct, false)} off</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="text-[11px] text-ink-3">{t.method.warning}</p>
    </div>
  );
}

// ------------------------------------------------------------------ adding a report
function UploadSheet({ symbol, open, close, done }: { symbol: string; open: boolean; close: () => void; done: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [broker, setBroker] = useState("");
  const [ok, setOk] = useState(false);
  const [state, setState] = useState<string | null>(null);
  const sandbox = getAccount().startsWith("u_");
  async function send() {
    if (!file) return;
    setState("Uploading…");
    try {
      const buf = new Uint8Array(await file.arrayBuffer());
      let bin = "";
      for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
      const { job_id } = await api<{ job_id: string }>("/brokerage/reports/ingest", {
        method: "POST",
        body: JSON.stringify({ symbol, brokerage: broker, pdf_base64: btoa(bin), permitted: ok }),
      });
      for (let i = 0; i < 90; i++) {
        const s = await api<{ stage: string; status: string; why?: string; needs_review?: string[] }>(`/brokerage/ingest/${job_id}`);
        setState(`Reading: ${s.stage}…`);
        if (s.status === "done") {
          setState(s.needs_review?.length ? `Added. Check: ${s.needs_review.join(", ")}.` : "Added and checked.");
          done();
          return;
        }
        if (s.status !== "running") {
          setState(s.why ? `Not added: ${s.why}.` : "Not added.");
          return;
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      setState("Still reading; check back in a minute.");
    } catch (e) {
      setState(e instanceof Error ? e.message.replace(/^\{"detail":"|"\}$/g, "") : "Couldn't add it.");
    }
  }
  return (
    <Sheet open={open} onClose={close} title="Add a brokerage report">
      {!sandbox ? (
        <p className="text-[13px] leading-snug">
          Reports you add stay private to you, so they need your own space. Open Network → Yours to make one, then come back.
        </p>
      ) : (
        <div className="space-y-3 text-[13px]">
          <label className="block">
            <span className="text-[12px] text-ink-3">Brokerage</span>
            <input value={broker} onChange={(e) => setBroker(e.target.value)} placeholder="e.g. Motilal Oswal" className="mt-1 w-full rounded-xl border border-line bg-surface px-3 py-2" />
          </label>
          <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-[13px]" />
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} className="mt-0.5" />
            <span>I may use this report (my subscription or a public copy). It stays private to me.</span>
          </label>
          <button
            disabled={!file || broker.length < 2 || !ok || (state?.endsWith("…") ?? false)}
            onClick={send}
            className="w-full rounded-full bg-accent py-2.5 font-medium text-white disabled:opacity-40"
          >
            Read it
          </button>
          {state && (
            <p className="flex items-center gap-1.5 text-ink-2">
              {state.endsWith("…") && <Loader2 size={13} className="animate-spin" />}
              {state}
            </p>
          )}
          <p className="text-[11px] text-ink-3">AI reads the PDF; code checks every figure against its page. Anything it can&apos;t find is marked, never guessed.</p>
        </div>
      )}
    </Sheet>
  );
}

// ------------------------------------------------------------------ finding public reports
type FindStatus = {
  status: "idle" | "running" | "done" | "failed";
  stage?: "looking" | "reading" | "done" | "failed";
  tried?: number;
  total?: number;
  found?: string[];
  read?: number;
  added?: number;
  why?: string;
};

function findLabel(s: FindStatus): string {
  if (s.status === "failed") return s.why ? `Couldn't finish: ${s.why}.` : "Couldn't finish.";
  if (s.stage === "looking") return `Looking on brokerages' public servers… (${s.tried ?? 0} of ${s.total ?? "?"})`;
  if (s.stage === "reading") return `Found ${s.found?.length ?? 0}. Reading ${Math.min((s.read ?? 0) + 1, s.found?.length ?? 1)} of ${s.found?.length ?? 0}…`;
  if (s.status === "done")
    return s.added ? `Added ${s.added} report${s.added === 1 ? "" : "s"}.` : "No new public reports found. Paste a link if you have one.";
  return "";
}

/** One tap: FINN tries the file names ICICI Securities and PL Capital use for this company's
 * recent results, reads the newest few, and keeps them for everyone for a month. */
export function FindReports({ symbol, done }: { symbol: string; done: () => void }) {
  const [state, setState] = useState<FindStatus | null>(null);
  const [link, setLink] = useState("");
  const [broker, setBroker] = useState("");
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const base = `/companies/${symbol}/brokerage`;
  const busy = state?.status === "running";

  async function follow() {
    for (let i = 0; i < 150; i++) {
      const s = await api<FindStatus>(`${base}/find`);
      setState(s);
      if (s.status !== "running") {
        if (s.added) done();
        return;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  async function run(path: string, body?: object) {
    setErr(null);
    try {
      const s = await api<FindStatus>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      setState(s);
      await follow();
    } catch (e) {
      setErr(e instanceof Error ? e.message.replace(/^\{"detail":"|"\}$/g, "") : "Couldn't start.");
    }
  }
  return (
    <div className="space-y-3 text-[13px]">
      <button
        disabled={busy}
        onClick={() => run(`${base}/find`)}
        className="inline-flex w-full items-center justify-center gap-1.5 rounded-full bg-accent py-2.5 font-medium text-white disabled:opacity-50"
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />} Find public broker reports
      </button>
      {state && state.status !== "idle" && (
        <p className="flex items-center gap-1.5 text-ink-2">
          {busy && <Loader2 size={13} className="animate-spin" />}
          {findLabel(state)}
        </p>
      )}
      <details className="rounded-xl border border-line px-3 py-2">
        <summary className="cursor-pointer text-[12px] font-medium text-ink-2">Have a link to a report?</summary>
        <div className="mt-2 space-y-2">
          <input
            value={link}
            onChange={(e) => setLink(e.target.value)}
            placeholder="https://…/report.pdf"
            inputMode="url"
            className="w-full rounded-xl border border-line bg-surface px-3 py-2"
          />
          <input
            value={broker}
            onChange={(e) => setBroker(e.target.value)}
            placeholder="Brokerage (if the link isn't on its own site)"
            className="w-full rounded-xl border border-line bg-surface px-3 py-2"
          />
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} className="mt-0.5" />
            <span>It&apos;s a public copy, open without a login.</span>
          </label>
          <button
            disabled={busy || !ok || link.length < 12}
            onClick={() => run(`${base}/link`, { url: link, brokerage: broker || null, permitted: ok })}
            className="w-full rounded-full border border-line py-2 font-medium disabled:opacity-40"
          >
            Read it
          </button>
        </div>
      </details>
      {err && <p className="text-bad">{err}</p>}
      <p className="text-[11px] text-ink-3">
        Searches ICICI Securities and PL Capital&apos;s open research servers for the last four results. AI reads each PDF once;
        code checks every figure against its page.
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ the whole view
export function BrokerBody({
  ov,
  rev,
  div,
  track,
  symbol,
  compact = false,
  refresh,
}: {
  ov: Overview;
  rev?: Revisions;
  div?: Divergence;
  track?: Track;
  symbol: string;
  compact?: boolean;
  refresh?: () => void;
}) {
  const [only, setOnly] = useState<string | null>(null);
  const [src, setSrc] = useState<Obs | null>(null);
  const [tab, setTab] = useState<"revisions" | "differ" | "record">("revisions");
  const [adding, setAdding] = useState(false);
  const houses = useMemo(() => ov.latest.map((o) => ({ id: o.brokerage_id, name: short(o.brokerage) })), [ov.latest]);
  const cards = ov.latest.filter((o) => !only || o.brokerage_id === only);
  const rated = Object.entries(ov.ratings).filter(([, n]) => n > 0);

  if (ov.reports === 0 && ov.stale.length === 0) {
    return (
      <div className="p-4 text-[13px] leading-snug">
        <p className="mb-3">FINN has no brokerage reports on this company yet.</p>
        {!compact && <FindReports symbol={symbol} done={() => refresh?.()} />}
        {!compact && (
          <button onClick={() => setAdding(true)} className="mt-3 inline-flex items-center gap-1 text-[12px] font-medium text-accent">
            <Upload size={13} /> Or upload a PDF you have (private to you)
          </button>
        )}
        <UploadSheet symbol={symbol} open={adding} close={() => setAdding(false)} done={() => refresh?.()} />
      </div>
    );
  }
  return (
    <div>
      <div className="p-4">
        <p className="text-[12px] text-ink-3">
          {ov.brokerages} brokerages · {ov.reports} reports in the last year · latest {ov.latest_report && `${day(ov.latest_report)} (${ov.latest_age_days} days ago)`}
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {rated.map(([k, n]) => (
            <Pill key={k} tone={TONE[k as keyof typeof TONE] ?? "neutral"}>
              {n} {k}
            </Pill>
          ))}
          <span className="text-[11px] text-ink-3">
            as rated: {Object.entries(ov.ratings_raw).map(([k, n]) => `${k} ${n}`).join(", ")}
          </span>
        </div>
        <div className="mt-4">
          <Targets ov={ov} />
        </div>
      </div>

      <div className="border-t border-line px-4 pt-3">
        <div className="no-scrollbar flex gap-1.5 overflow-x-auto">
          {[{ id: null as string | null, name: "All" }, ...houses].map((h) => (
            <button
              key={h.id ?? "all"}
              onClick={() => setOnly(h.id)}
              className={clsx(
                "shrink-0 rounded-full border px-2.5 py-0.5 text-[12px] font-medium",
                only === h.id ? "border-ink bg-ink text-bg" : "border-line text-ink-2",
              )}
            >
              {h.name.split(" ")[0]}
            </button>
          ))}
        </div>
        <ul className="divide-y divide-line">
          {cards.map((o) => (
            <Card key={o.id} o={o} open={setSrc} />
          ))}
        </ul>
        {ov.stale.length > 0 && !only && (
          <p className="pb-3 text-[12px] leading-snug text-ink-3">
            Older than 120 days, left out of the ranges:{" "}
            {ov.stale.map((o, i) => (
              <button key={o.id} onClick={() => setSrc(o)} className="text-accent">
                {short(o.brokerage)} {rs(o.target_price)} ({day(o.published_at)}){i < ov.stale.length - 1 ? ", " : ""}
              </button>
            ))}
          </p>
        )}
      </div>

      {rev && div && track && (
        <div className="border-t border-line p-4">
          <Segmented
            label="Brokerage detail"
            value={tab}
            onChange={setTab}
            options={[
              { value: "revisions", label: "Revisions" },
              { value: "differ", label: "Disagreement" },
              { value: "record", label: "Track record" },
            ]}
          />
          <div className="mt-3">
            {tab === "revisions" && <RevisionList rev={rev} only={only} />}
            {tab === "differ" && <Disagreement d={div} />}
            {tab === "record" && <TrackRecord t={track} />}
          </div>
        </div>
      )}

      {!compact && (
        <details className="border-t border-line px-4 py-3">
          <summary className="cursor-pointer text-[12px] font-medium text-accent">Look for newer reports</summary>
          <div className="mt-3">
            <FindReports symbol={symbol} done={() => refresh?.()} />
          </div>
        </details>
      )}
      <div className="flex items-center justify-between gap-2 border-t border-line px-4 py-3 text-[11px] text-ink-3">
        <span>In the reports currently available to FINN, not the whole market.</span>
        {!compact && (
          <button onClick={() => setAdding(true)} className="inline-flex shrink-0 items-center gap-1 font-medium text-accent">
            <Upload size={12} /> Add a report
          </button>
        )}
      </div>
      <SourceSheet o={src} close={() => setSrc(null)} />
      <UploadSheet symbol={symbol} open={adding} close={() => setAdding(false)} done={() => refresh?.()} />
    </div>
  );
}

// ------------------------------------------------------------------ calls in the press
type NewsCall = {
  house_id: string;
  house: string;
  rating: string | null;
  target: number | null;
  previous_target: number | null;
  action: string | null;
  quote: string;
  date: string | null;
  headline: string;
  url: string;
  source: string;
  read: "article" | "headline";
};
type BrokerNews = {
  symbol: string;
  calls: NewsCall[];
  latest: NewsCall[];
  articles?: { title: string; url: string; date: string | null }[];
  summary?: { text: string; by: "ai" | "code" };
  saved_at?: number;
  job: { status: string; stage?: string; articles?: number; why?: string };
};

function ratingTone(r: string | null): "good" | "bad" | "neutral" {
  if (!r) return "neutral";
  if (/buy|overweight|outperform|add|accumulate|positive/i.test(r)) return "good";
  if (/sell|underweight|underperform|reduce|negative/i.test(r)) return "bad";
  return "neutral";
}

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? (s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : null;
};

/** Banks and brokers whose reports FINN can't read (Goldman Sachs, Morgan Stanley, JPMorgan,
 * Nomura, Jefferies, Citi…): their calls as the financial press reported them, each kept only
 * if code finds the house and the target in the article's own sentence. */
export function BankCalls({ symbol }: { symbol: string }) {
  const path = `/companies/${symbol}/brokerage/news`;
  const { data, mutate } = useApi<BrokerNews>(path, {
    refreshInterval: (d) => (d?.job?.status === "running" ? 4000 : 0),
  });
  const [open, setOpen] = useState<NewsCall | null>(null);
  const [all, setAll] = useState(false);
  if (!data) return null;
  const running = data.job?.status === "running";
  const rows = data.latest;
  const targets = rows.map((c) => c.target).filter((t): t is number => t != null);
  const shown = all ? rows : rows.slice(0, 8);
  return (
    <>
      <SectionTitle aside="as reported in the press">What banks and brokers say</SectionTitle>
      <Panel>
        {rows.length === 0 ? (
          <p className="flex items-center gap-1.5 p-4 text-[13px] text-ink-2">
            {running ? (
              <>
                <Loader2 size={13} className="animate-spin" />
                {data.job.stage === "reading" ? `Reading ${data.job.articles ?? ""} news articles…` : "Searching the financial press…"}
              </>
            ) : data.job?.status === "failed" ? (
              `Couldn't search right now${data.job.why ? `: ${data.job.why}` : ""}.`
            ) : (
              "No bank or broker calls on this company in the press in the last six months."
            )}
          </p>
        ) : (
          <div>
            <div className="p-4 pb-2">
              {data.summary?.text && (
                <div className="mb-2">
                  {data.summary.by === "ai" && <AiTag from="figures checked by code" />}
                  <p className="mt-1 text-[14px] leading-relaxed">{data.summary.text}</p>
                </div>
              )}
              <p className="text-[12px] text-ink-3">
                {rows.length} houses · {targets.length} with a target
                {targets.length > 1 && (
                  <>
                    {" "}
                    · {rs(Math.min(...targets))} to {rs(Math.max(...targets))}, median {rs(median(targets))}
                  </>
                )}
              </p>
            </div>
            <ul className="divide-y divide-line px-4">
              {shown.map((c) => (
                <li key={c.house_id}>
                  <button onClick={() => setOpen(c)} className="flex w-full items-center gap-2 py-2.5 text-left">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-medium">{c.house}</span>
                      <span className="block truncate text-[11px] text-ink-3">
                        {c.date ? day(c.date) : ""} · {c.source}
                        {c.action && c.action !== "other" ? ` · ${c.action}` : ""}
                      </span>
                    </span>
                    {c.rating && <Pill tone={ratingTone(c.rating)}>{c.rating[0].toUpperCase() + c.rating.slice(1)}</Pill>}
                    <span className="w-[76px] shrink-0 text-right text-[14px] tabular-nums">
                      {rs(c.target)}
                      {c.previous_target != null && c.target != null && (
                        <span className={clsx("block text-[11px]", c.target >= c.previous_target ? "text-good" : "text-bad")}>
                          from {rs(c.previous_target)}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {rows.length > 8 && (
              <button onClick={() => setAll((v) => !v)} className="px-4 pb-2 text-[12px] font-medium text-accent">
                {all ? "Show fewer" : `Show all ${rows.length}`}
              </button>
            )}
            <div className="flex items-center justify-between gap-2 border-t border-line px-4 py-3 text-[11px] text-ink-3">
              <span>Second-hand: read from news articles, not the reports, and kept apart from the report figures above.</span>
              <button
                disabled={running}
                onClick={async () => {
                  await api(`${path}/refresh`, { method: "POST" });
                  mutate();
                }}
                className="inline-flex shrink-0 items-center gap-1 font-medium text-accent disabled:opacity-50"
              >
                {running && <Loader2 size={12} className="animate-spin" />} Check again
              </button>
            </div>
          </div>
        )}
      </Panel>
      <Sheet open={!!open} onClose={() => setOpen(null)} title={open ? `${open.house} on ${symbol}` : ""}>
        {open && (
          <div className="space-y-3 text-[13px] leading-snug">
            <blockquote className="border-l-2 border-line pl-3 italic">“{open.quote}”</blockquote>
            <p className="text-ink-3">
              {open.read === "article" ? "From the article" : "From the headline (the article itself couldn't be opened)"}:{" "}
              <a href={open.url} target="_blank" rel="noreferrer" className="text-accent">
                {open.headline}
              </a>{" "}
              · {open.source} · {open.date ? day(open.date) : ""}
            </p>
            <p className="text-[11px] text-ink-3">AI found this call; code checked the house and the target are in that sentence.</p>
          </div>
        )}
      </Sheet>
    </>
  );
}

/** The company-page section: fetches its four parts. */
export function BrokerSection({ symbol }: { symbol: string }) {
  const base = `/companies/${symbol}/brokerage`;
  const ov = useApi<Overview>(`${base}/overview`);
  const rev = useApi<Revisions>(`${base}/revisions`);
  const div = useApi<Divergence>(`${base}/divergence`);
  const track = useApi<Track>(`${base}/track-record`);
  if (!ov.data) return null;
  const refresh = () => [ov, rev, div, track].forEach((r) => r.mutate());
  return (
    <>
      <SectionTitle aside="read from their reports" tour="brokers">
        What brokers expect
      </SectionTitle>
      <Panel>
        <BrokerBody ov={ov.data} rev={rev.data} div={div.data} track={track.data} symbol={symbol} refresh={refresh} />
      </Panel>
      <BankCalls symbol={symbol} />
    </>
  );
}
