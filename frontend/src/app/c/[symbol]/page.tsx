"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, ChevronDown, Loader2, TriangleAlert } from "lucide-react";
import clsx from "clsx";
import { ApiError, api, type Research, stream, useApi } from "@/lib/api";
import { ShareButton } from "@/components/ShareButton";
import { WatchStar } from "@/components/market";
import { Listen } from "@/components/Listen";
import { crore, day, fq, pct, shortName, times } from "@/lib/fmt";
import { HelperList } from "@/components/network";
import {
  ClaimList,
  CredibilityText,
  FinnRead,
  PENDING,
  PromiseRow,
  StatTile,
  VerdictBar,
  VoiceLegend,
  useDocs,
} from "@/components/research";
import { AiTag, Panel, SectionTitle, Skeleton } from "@/components/ui";
import { AskFinn } from "@/components/AskFinn";
import { BrokerSection } from "@/components/brokers";
import { Blocks, type Block } from "@/components/pull";
import { SavedNote } from "@/components/saved";
import { ContactNotes } from "@/components/notes";
import { useTitle } from "@/lib/title";
import { usePageLoading } from "@/lib/pageload";

const STEPS = [
  { step: "fundamentals", label: "Reported financials" },
  { step: "documents", label: "Annual report and 4 earnings calls" },
  { step: "guidance", label: "What management promised" },
  { step: "promises", label: "Promised vs delivered" },
  { step: "narrative", label: "Business and bull vs bear" },
];

/** The computed full report (GET /report/{symbol}): the same one Ask builds, for any listed
 *  company. FINN's deeper reading and the brokerage views sit under it on the same page. */
type Report = {
  symbol: string;
  company: string;
  blocks: Block[];
  researched: boolean;
  builds_left: number;
  saved_at: number | null;
  from_saved: boolean;
  refreshing: boolean;
};

type State =
  | { kind: "loading" }
  | { kind: "building"; done: string[]; message: string }
  | { kind: "ready"; view: Research }
  | { kind: "unread"; name: string | null; left: number }
  | { kind: "error"; message: string; notCovered?: boolean; limit?: boolean };

export default function CompanyPage() {
  const { symbol: raw } = useParams<{ symbol: string }>();
  const symbol = decodeURIComponent(raw).toUpperCase();
  useTitle(symbol);
  const initialQ = useSearchParams().get("q") ?? undefined;
  const [state, setState] = useState<State>({ kind: "loading" });
  const abort = useRef<AbortController | null>(null);
  const router = useRouter();
  const report = useApi<Report>(`/report/${symbol}`);
  // a fresh read of a company FINN has read before runs behind the saved one, which stays up
  const [rereading, setRereading] = useState<string | null>(null);
  const viewRef = useRef<Research | null>(null);
  if (state.kind === "ready") viewRef.current = state.view;
  usePageLoading(state.kind === "loading"); // a live read has its own progress, so not that

  const build = useCallback(
    async (force = false) => {
      abort.current?.abort();
      const ctl = new AbortController();
      abort.current = ctl;
      const done: string[] = [];
      const behind = force && viewRef.current != null;
      if (behind) setRereading("Starting…");
      else setState({ kind: "building", done, message: "Starting…" });
      try {
        await stream(
          `/research/${symbol}/stream${force ? "?force=true" : ""}`,
          (event, data) => {
            const d = data as Record<string, unknown>;
            if (event === "progress" && behind) setRereading(String(d.message));
            else if (event === "result" && behind) {
              setRereading(null);
              setState({ kind: "ready", view: d as unknown as Research });
            } else if (event === "error" && behind) setRereading(`Couldn't finish the fresh read (${String(d.message).slice(0, 80)}). The saved one stands.`);
            else if (event === "progress") {
              const i = STEPS.findIndex((s) => s.step === d.step);
              const finished = i > 0 ? STEPS.slice(0, i).map((s) => s.step) : d.step === "done" ? STEPS.map((s) => s.step) : [];
              setState({ kind: "building", done: finished, message: String(d.message) });
            } else if (event === "result") setState({ kind: "ready", view: d as unknown as Research });
            else if (event === "error")
              setState({
                kind: "error",
                message: String(d.message),
                notCovered: d.kind === "not_covered",
                limit: d.kind === "limit",
              });
          },
          ctl.signal,
        );
      } catch (e) {
        if (behind) setRereading("The connection dropped. The fresh read carries on at FINN; reopen the page in a couple of minutes.");
        else if (!ctl.signal.aborted) setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
      }
    },
    [symbol],
  );

  useEffect(() => {
    let live = true;
    api<Research>(`/research/${symbol}`)
      .then((view) => live && setState({ kind: "ready", view }))
      .catch((e) => {
        if (!live) return;
        if (e instanceof ApiError && e.status === 404) {
          // ask first: a live read spends the day's shared AI budget
          let d: { covered?: { name: string } | null; builds_left?: number } = {};
          try {
            d = JSON.parse(e.message).detail ?? {};
          } catch {}
          setState({ kind: "unread", name: d.covered?.name ?? null, left: d.builds_left ?? 0 });
        } else setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      live = false;
      abort.current?.abort();
    };
  }, [symbol, build]);

  return (
    <main>
      <div className="flex items-center gap-2 px-3 pt-[calc(12px+env(safe-area-inset-top))]">
        <button
          aria-label="Back"
          onClick={() => (window.history.length > 1 ? router.back() : router.push("/"))}
          className="rounded-full p-2 text-ink-2 active:bg-surface-2"
        >
          <ArrowLeft size={19} />
        </button>
        <span className="text-[13px] font-medium text-ink-3">{symbol}</span>
      </div>
      {state.kind === "ready" ? (
        <ResearchView
          v={state.view}
          rebuild={() => build(true)}
          rereading={rereading}
          initialQ={initialQ}
          computed={report.data}
          onFresh={(r) => report.mutate(r, false)}
        />
      ) : report.error && !report.data ? (
        <UnreadView symbol={symbol} name={null} left={0} read={() => {}} />
      ) : !report.data ? (
        <LoadingView />
      ) : (
        <div>
          <header className="px-4 pb-1 pt-1">
            <div className="flex items-start justify-between gap-3">
              <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em]">{shortName(report.data.company)}</h1>
              <div className="mt-1.5 shrink-0">
                <WatchStar symbol={symbol} />
              </div>
            </div>
            <p className="mt-1 text-[12px] text-ink-3">From reported financials, NSE prices and filings, and brokerage reports where FINN has them.</p>
            {report.data.saved_at && (
              <div className="mt-1.5">
                <SavedNote<Report> key={report.data.saved_at} savedAt={report.data.saved_at} refreshing={report.data.refreshing} kind="full" symbol={symbol} onFresh={(r) => report.mutate(r, false)} />
              </div>
            )}
          </header>
          <Computed report={report.data} />
          <BrokerSection symbol={symbol} />
          <SectionTitle aside="annual report and calls">Go deeper</SectionTitle>
          {state.kind === "loading" && <Skeleton className="mx-3 h-24" />}
          {state.kind === "unread" && <UnreadView symbol={symbol} name={state.name ?? report.data.company} left={state.left} read={() => build()} />}
          {state.kind === "building" && <BuildingView symbol={symbol} done={state.done} message={state.message} />}
      {state.kind === "error" && (
        <Panel className="mt-4 p-4">
          <p className="text-[15px] font-semibold">
            {state.notCovered
              ? `No filings data for ${symbol}`
              : state.limit
                ? "Live analysis is paused for today"
                : `I couldn't finish reading ${symbol}`}
          </p>
          <p className="mt-1 text-[13px] text-ink-2">
            {state.notCovered
              ? state.message.includes("isn't an NSE")
                ? `${state.message} Check the ticker, or search by the company's name.`
                : "There's nothing for FINN to read yet: no standardised financials or earnings-call transcripts for this ticker."
              : `Nothing was guessed or saved. ${/network|fetch/i.test(state.message) ? "The connection dropped partway." : state.message.slice(0, 160)}`}
          </p>
          {!state.notCovered && !state.limit && (
            <button onClick={() => build(true)} className="mt-3 text-[13px] font-medium text-accent">
              Try again
            </button>
          )}
          {state.limit && (
            <Link href="/ask" className="mt-3 inline-block text-[13px] font-medium text-accent">
              See ready companies →
            </Link>
          )}
        </Panel>
      )}
        </div>
      )}
    </main>
  );
}

function LoadingView() {
  return (
    <div className="space-y-3 px-4 pt-2">
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="mt-6 h-48" />
      <Skeleton className="h-32" />
    </div>
  );
}

/** The rule-based points of the computed report's bull or bear case (the call-read ones are
 *  already in the cited list above them). */
function rulePoints(r: Report | undefined, title: string): string[] {
  const b = r?.blocks.find((x) => x.type === "points" && x.title === title);
  return b && b.type === "points" ? b.items.map((i) => i.text).filter((t) => !t.startsWith("From the calls:")) : [];
}

function RulePoints({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="mt-2 space-y-1.5">
      {items.map((t) => (
        <li key={t} className="text-[13px] leading-snug text-ink">
          {t} <span className="text-[11px] text-ink-3">from the numbers</span>
        </li>
      ))}
    </ul>
  );
}

/** The computed report's blocks. The brokerage summary is left out: the brokerage section
 *  under it shows the same reports in full. */
function Computed({ report, deep = false }: { report: Report; deep?: boolean }) {
  const blocks = report.blocks.filter(
    (b) => !(b.type === "points" && (b.title === "Brokerage views FINN holds" || (deep && (b.title === "Bull case" || b.title === "Bear case")))),
  );
  return (
    <Panel className="mt-3 p-4">
      <Blocks blocks={blocks} docs={new Map()} base={`/c/${report.symbol}`} />
    </Panel>
  );
}

function UnreadView({ symbol, name, left, read }: { symbol: string; name: string | null; left: number; read: () => void }) {
  if (!name)
    return (
      <Panel className="mt-4 p-4">
        <p className="text-[15px] font-semibold">I don&apos;t know {symbol}</p>
        <p className="mt-1 text-[13px] text-ink-2">It isn&apos;t an NSE-listed company in FINN&apos;s list. Check the ticker, or search by the company&apos;s name.</p>
        <Link href="/ask" className="mt-3 inline-block text-[13px] font-medium text-accent">
          Search →
        </Link>
      </Panel>
    );
  return (
    <Panel className="p-4">
      <p className="text-[14px] leading-relaxed text-ink">
        FINN hasn&apos;t read {shortName(name)}&apos;s annual report and last four earnings calls yet. Reading them adds promised vs delivered,
        a cited bull vs bear, the business, and questions answered with page references. About a minute.
      </p>
      {left > 0 ? (
        <>
          <button onClick={read} className="mt-4 w-full rounded-xl bg-ink py-3 text-[15px] font-medium text-surface active:opacity-80">
            Read it now
          </button>
          <p className="mt-2 text-center text-[12px] text-ink-2">
            Uses 1 of the {left} live reads left today on this demo
          </p>
        </>
      ) : (
        <p className="mt-4 rounded-lg bg-warn-soft px-3 py-2 text-[13px] text-warn">
          Today&apos;s live reads on this demo are used up. The ready companies are on the Ask screen.
        </p>
      )}
    </Panel>
  );
}

function BuildingView({ symbol, done, message }: { symbol: string; done: string[]; message: string }) {
  const current = STEPS.find((s) => !done.includes(s.step));
  return (
    <div className="px-4 pt-2">
      <h1 className="text-[24px] font-semibold tracking-[-0.02em]">Reading {symbol}</h1>
      <p className="mt-1 text-[13px] text-ink-2">
        Reading the annual report and the last four earnings calls, and nothing else. About a minute.
      </p>
      <ol className="mt-6 space-y-3">
        {STEPS.map((s) => {
          const isDone = done.includes(s.step);
          const isNow = current?.step === s.step;
          return (
            <li key={s.step} className="flex items-start gap-3">
              <span
                className={clsx(
                  "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                  isDone ? "bg-good-soft text-good" : isNow ? "text-accent" : "text-ink-3",
                )}
              >
                {isDone ? <Check size={13} strokeWidth={3} /> : isNow ? <Loader2 size={15} className="animate-spin" /> : <span className="h-1.5 w-1.5 rounded-full bg-line" />}
              </span>
              <span>
                <span className={clsx("text-[14px]", isDone || isNow ? "text-ink" : "text-ink-3")}>{s.label}</span>
                {isNow && <span className="block text-[12px] text-ink-3">{message}</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function ResearchView({
  v,
  rebuild,
  rereading,
  initialQ,
  computed,
  onFresh,
}: {
  v: Research;
  rebuild: () => void;
  rereading: string | null;
  initialQ?: string;
  computed?: Report;
  onFresh: (r: Report) => void;
}) {
  const docs = useDocs(v.documents);
  const f = v.financials;
  const s = f.snapshot;
  const p = v.promises;
  const [showEarly, setShowEarly] = useState(false);
  const judged = p.items.filter((i) => !PENDING.includes(i.verdict));
  const early = p.items.filter((i) => PENDING.includes(i.verdict));
  const q = f.trajectory.quarterly;
  const a = f.trajectory.annual;
  const last = f.balance_sheet.annual.at(-1);
  const transcripts = v.documents.filter((d) => d.kind === "transcript");
  // a card's next action can link straight to a section (#promises, #numbers): the view
  // renders after data loads, so the browser's own jump to the anchor has already missed
  useEffect(() => {
    const id = window.location.hash.slice(1);
    if (id) document.getElementById(id)?.scrollIntoView({ block: "start" });
  }, []);
  const ask = (
    <>
      <SectionTitle aside="answers cite their pages" tour="askfinn">Ask FINN</SectionTitle>
      <AskFinn symbol={v.symbol} docs={docs} suggestions={v.suggested_questions ?? []} initial={initialQ} />
    </>
  );

  return (
    <div>
      <header className="px-4 pb-1 pt-1">
        <div className="flex items-start justify-between gap-3">
          <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em]">{shortName(v.company)}</h1>
          <div className="mt-1.5 flex shrink-0 items-center gap-1.5">
          <WatchStar symbol={v.symbol} />
          <ShareButton
            withText
            className="rounded-full border border-line px-3 py-1 text-[13px] text-ink-2"
            build={() => {
              const p = v.promises;
              const missed = p.items.filter((i) => i.verdict === "missed").slice(0, 3);
              return {
                title: `${shortName(v.company)} (${v.symbol})`,
                lines: [
                  `${shortName(v.company)} (${v.symbol})${s.price != null ? ` · ₹${s.price.toLocaleString("en-IN")}` : ""}${s.pe != null ? ` · P/E ${s.pe}` : ""}`,
                  p.items.length > 0 && `Management record: ${headline(p.counts)}${p.score != null ? ` Delivery score ${p.score}/100.` : ""}`,
                  ...missed.map((i) => `• ${i.target}: ${i.actual}`),
                  `From ${transcripts.length} earnings calls and the annual report.`,
                  "Shared from FINN",
                ],
                url: typeof window !== "undefined" ? window.location.href.split("#")[0] : null,
              };
            }}
          />
          </div>
        </div>
        {/* the computed panel below has today's price, market cap and P/E; this line is the read's own copy */}
        {!computed && (
          <p className="tnum mt-1 text-[13px] text-ink-2">
            {s.price != null && <>₹{s.price.toLocaleString("en-IN")} · </>}
            {s.market_cap_cr != null && <>mcap {crore(s.market_cap_cr)} · </>}
            {s.pe != null && <>P/E {s.pe}</>}
          </p>
        )}
        <p className="mt-1 text-[12px] text-ink-3">
          From {transcripts.length} earnings calls and the annual report
          {v.filed_results ? `, plus the ${fq(v.filed_results.period)} results filed ${day(v.filed_results.filed)}` : ""}{computed ? ", reported financials, NSE prices and filings, and brokerage reports where FINN has them" : ""}.
        </p>
        <Listen lines={companyScript(v)} className="mt-2.5" />
        {v.freshness?.status === "stale" && (
          <p className="mt-2 rounded-lg bg-warn-soft px-3 py-2 text-[12px] leading-snug text-warn">
            Out of date: {v.freshness.reason}{" "}
            <button onClick={rebuild} className="font-medium underline underline-offset-2">
              Rebuild
            </button>
          </p>
        )}
        {computed?.saved_at && (
          <div className="mt-2">
            <SavedNote<Report> key={computed.saved_at} savedAt={computed.saved_at} refreshing={computed.refreshing} kind="full" symbol={v.symbol} onFresh={onFresh} />
          </div>
        )}
        <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[12px] text-ink-3" role="status">
          <span>Calls and annual report read {new Date(v.generated_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
          <span aria-hidden>·</span>
          {rereading ? (
            <span className="text-ink-2">Reading them again in the background: {rereading}</span>
          ) : (
            <button onClick={rebuild} className="font-medium text-accent">
              Read them again
            </button>
          )}
        </p>
        <VoiceLegend />
      </header>
      {computed && <Computed report={computed} deep={!!v.bull_bear} />}

      {v.incomplete.length > 0 && (
        <Panel className="mt-3 flex items-start gap-2 p-3 text-[13px]">
          <TriangleAlert size={16} className="mt-0.5 shrink-0 text-warn" />
          <div>
            <p>
              Some sections are missing ({v.incomplete.map((x) => x.split(":")[0]).join(", ")}): the AI quota ran out
              mid-build. Nothing is guessed in their place.
            </p>
            <button onClick={rebuild} className="mt-1 font-medium text-accent">
              Retry now
            </button>
          </div>
        </Panel>
      )}

      {initialQ && ask}

      {/* ---------------------------------------------------------------- the hero */}
      <SectionTitle aside={`last ${transcripts.length} calls`}>
        <span id="promises">Did management deliver?</span>
      </SectionTitle>
      <Panel className="p-4">
        {p.items.length === 0 ? (
          <p className="text-[13px] text-ink-2">No checkable promises found in the last four calls.</p>
        ) : (
          <>
            <div className="flex items-end justify-between gap-3">
              <p className="text-[15px] font-semibold leading-snug">
                {headline(p.counts)}
              </p>
              {p.score != null && (
                <p className="shrink-0 text-right">
                  <span className="text-[28px] font-semibold leading-none tracking-[-0.02em]">
                    {p.score}
                    <span className="text-[13px] font-medium text-ink-3">/100</span>
                  </span>
                  <span className="block text-[11px] text-ink-2">delivery score</span>
                </p>
              )}
            </div>
            <div className="mt-3">
              <VerdictBar counts={p.counts} />
            </div>
            {(() => {
              const due = p.items.filter((i) => !["too_early", "not_measurable"].includes(i.verdict));
              const byCode = due.filter((i) => i.judged_by === "code").length;
              return due.length > 0 ? (
                <p className="mt-2 text-[12px] leading-snug text-ink-3">
                  Score: each promise delivered counts 1, partly delivered ½, out of the promises that came due.{" "}
                  {byCode} of {due.length} judged by arithmetic on reported numbers; {due.length - byCode === 0 ? "none" : due.length - byCode} left to the AI because no reported figure measures {due.length - byCode === 1 ? "it" : "them"}.
                </p>
              ) : null;
            })()}
            {p.credibility && (
              <div className="mt-4 border-t border-line pt-3">
                <FinnRead label="FINN's read on their record">
                  <CredibilityText text={p.credibility} docs={docs} />
                </FinnRead>
              </div>
            )}
            <ul className="mt-2 divide-y divide-line border-t border-line">
              {judged.map((i) => (
                <PromiseRow key={i.promise_ids.join()} p={i} docs={docs} />
              ))}
            </ul>
            {early.length > 0 && (
              <>
                <button
                  onClick={() => setShowEarly(!showEarly)}
                  aria-expanded={showEarly}
                  className="mt-1 flex w-full items-center justify-between border-t border-line pt-3 text-[13px] text-ink-2"
                >
                  <span>
                    {early.length} {early.length === 1 ? "promise" : "promises"} not yet due
                    {early.some((i) => i.verdict === "not_measurable") && " or not checkable"}
                  </span>
                  <ChevronDown size={15} className={clsx("transition-transform", showEarly && "rotate-180")} />
                </button>
                {showEarly && (
                  <ul className="divide-y divide-line">
                    {early.map((i) => (
                      <PromiseRow key={i.promise_ids.join()} p={i} docs={docs} />
                    ))}
                  </ul>
                )}
              </>
            )}
            <div className="mt-3 border-t border-line pt-2.5">
              <AiTag
                from={`promises read by AI from ${transcripts.length} calls; numeric ones judged in code`}
                model={v.models?.promise_vs_delivery}
              />
            </div>
          </>
        )}
      </Panel>

      {!initialQ && ask}

      {/* ---------------------------------------------------------------- network, woven in */}
      <SectionTitle tour="whoyouknow">Who you know</SectionTitle>
      <Panel className="px-4 py-1">
        <HelperList helpers={v.helpers} max={3} />
      </Panel>
      <SectionTitle aside="private">What they told you</SectionTitle>
      <ContactNotes symbol={v.symbol} helpers={v.helpers} />

      {/* ---------------------------------------------------------------- numbers */}
      <SectionTitle aside={`${f.basis} · ₹ crore`}>
        <span id="numbers">The numbers</span>
      </SectionTitle>
      <ComparePeers symbol={v.symbol} />
      <div className="grid grid-cols-2 gap-2 px-3">
        <StatTile
          label={`Revenue ${s.fy ? fq(s.fy, true) : ""}`}
          value={crore(s.revenue)}
          sub={f.trajectory.cagr.revenue_3y != null ? `${pct(f.trajectory.cagr.revenue_3y)} 3-yr CAGR` : undefined}
          points={a.map((x) => ({ label: fq(x.period, true), value: x.revenue }))}
          format={crore}
        />
        <StatTile
          label={s.margin_label}
          value={s.margin_pct != null ? `${s.margin_pct}%` : "—"}
          sub={q.at(-1)?.margin_pct != null ? `${q.at(-1)!.margin_pct}% in ${fq(q.at(-1)!.period)}` : undefined}
          points={q.map((x) => ({ label: fq(x.period), value: x.margin_pct }))}
          format={(v) => `${v}%`}
        />
        <StatTile
          label={`Net profit ${s.fy ? fq(s.fy, true) : ""}`}
          value={crore(s.pat)}
          sub={f.trajectory.cagr.pat_3y != null ? `${pct(f.trajectory.cagr.pat_3y)} 3-yr CAGR` : undefined}
          points={a.map((x) => ({ label: fq(x.period, true), value: x.pat }))}
          format={crore}
        />
        {f.is_lender ? (
          <StatTile
            label="Gross NPA"
            value={f.balance_sheet.asset_quality?.at(-1)?.gross_npa_pct != null ? `${f.balance_sheet.asset_quality!.at(-1)!.gross_npa_pct}%` : "—"}
            sub={`ROE ${pct(s.roe_pct, false)}`}
            points={(f.balance_sheet.asset_quality ?? []).map((x) => ({ label: fq(x.period), value: x.gross_npa_pct }))}
            format={(v) => `${v}%`}
          />
        ) : (
          <StatTile
            label="Cash conversion (3 yr)"
            value={times(f.cash_quality.cfo_to_pat_3y)}
            sub="operating cash flow ÷ profit"
            points={f.cash_quality.annual.map((x) => ({ label: fq(x.period, true), value: x.cfo }))}
            format={(v) => `CFO ${crore(v)}`}
          />
        )}
        {!f.is_lender && (
          <>
            <StatTile
              label="Debt / equity"
              value={times(s.debt_to_equity)}
              sub={`ROCE ${pct(s.roce_pct, false)} · ROE ${pct(s.roe_pct, false)}`}
              points={f.balance_sheet.annual.map((x) => ({ label: fq(x.period, true), value: x.debt_to_equity }))}
              format={times}
            />
            <StatTile
              label="Working capital"
              value={last?.working_capital_days != null ? `${last.working_capital_days} days` : "—"}
              sub={last?.debtor_days != null ? `debtors ${last.debtor_days} days` : undefined}
              points={f.balance_sheet.annual.map((x) => ({ label: fq(x.period, true), value: x.working_capital_days ?? null }))}
              format={(v) => `${v} days`}
            />
          </>
        )}
      </div>
      {f.flags.length > 0 && (
        <Panel className="mt-2 p-4">
          <ul className="space-y-1.5">
            {f.flags.map((fl) => (
              <li key={fl.id} className="flex gap-2 text-[13px] leading-snug">
                <span className={clsx("mt-[3px] text-[10px] font-bold", fl.tone === "positive" ? "text-good" : "text-bad")}>
                  {fl.tone === "positive" ? "▲" : "▼"}
                </span>
                <span className="sr-only">{fl.tone === "positive" ? "Positive:" : "Concern:"}</span>
                {fl.text}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-ink-3">Computed from reported financials, not by AI.</p>
        </Panel>
      )}

      <BrokerSection symbol={v.symbol} />

      {/* ---------------------------------------------------------------- judgement */}
      {v.bull_bear && (
        <>
          <SectionTitle>Bull vs bear</SectionTitle>
          <Panel className="divide-y divide-line">
            <div className="p-4">
              <p className="mb-2 text-[12px] font-semibold text-good">Bull</p>
              <ClaimList claims={v.bull_bear.bull} docs={docs} />
              <RulePoints items={rulePoints(computed, "Bull case")} />
            </div>
            <div className="p-4">
              <p className="mb-2 text-[12px] font-semibold text-bad">Bear</p>
              <ClaimList claims={v.bull_bear.bear} docs={docs} />
              <RulePoints items={rulePoints(computed, "Bear case")} />
            </div>
            {v.bull_bear.watch.length > 0 && (
              <div className="p-4">
                <p className="mb-2 text-[12px] font-semibold text-ink-2">Watch next quarter</p>
                <ClaimList claims={v.bull_bear.watch} docs={docs} />
              </div>
            )}
            <div className="px-4 py-2.5">
              <AiTag from="from the last two calls and the flags above; points marked “from the numbers” are FINN's fixed rules" model={v.models?.bull_bear} />
            </div>
          </Panel>
        </>
      )}

      {v.business && (
        <>
          <SectionTitle>The business</SectionTitle>
          <Panel className="space-y-4 p-4">
            {v.business.what_they_do && <ClaimList claims={[v.business.what_they_do]} docs={docs} />}
            {v.business.segments.length > 0 && (
              <ul className="flex flex-wrap gap-1.5">
                {v.business.segments.map((sg) => (
                  <li key={sg.name} className="rounded-lg bg-surface-2 px-2 py-1 text-[12px]">
                    {sg.name}
                    {sg.share && <span className="tnum ml-1 font-semibold">{sg.share}</span>}
                  </li>
                ))}
              </ul>
            )}
            {v.business.customers_and_markets.length > 0 && <ClaimList claims={v.business.customers_and_markets} docs={docs} />}
            {v.business.recent_developments.length > 0 && (
              <div>
                <p className="mb-2 text-[12px] font-semibold text-ink-2">Recently</p>
                <ClaimList claims={v.business.recent_developments} docs={docs} />
              </div>
            )}
            <AiTag from="from the annual report and latest call" model={v.models?.business_snapshot} />
          </Panel>
        </>
      )}

      <SectionTitle>Sources</SectionTitle>
      <Panel className="divide-y divide-line">
        {v.documents.map((d) => (
          <a key={d.id} href={d.url} target="_blank" rel="noreferrer" className="flex items-center justify-between px-4 py-2.5 text-[13px]">
            <span>{d.label}</span>
            <span className="tnum text-[12px] text-ink-3">{d.pages} pages</span>
          </a>
        ))}
      </Panel>
      <p className="px-4 pb-8 pt-3 text-center text-[11px] text-ink-3">
        Built {new Date(v.generated_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} · quotes are
        checked word-for-word against the source page
      </p>
    </div>
  );
}

/** What the page says, in order, for Listen: price, the latest quarter, the delivery record
 *  and the promises missed. Numbers and verdicts only, no AI-written text. */
function companyScript(v: Research): string[] {
  const name = shortName(v.company);
  const s = v.financials.snapshot;
  const q = v.financials.trajectory.quarterly.at(-1);
  const move = (x: number | null, what: string) => (x == null ? null : `${what} ${x >= 0 ? "up" : "down"} ${Math.abs(x).toFixed(0)}%`);
  const p = v.promises;
  const parts = [
    `${name}.${s.price != null ? ` Share price ₹${Math.round(s.price).toLocaleString("en-IN")}` : ""}${s.pe != null ? `, P/E ${Math.round(s.pe)}` : ""}.`,
  ];
  if (q) {
    const bits = [move(q.revenue_yoy, "revenue"), move(q.pat_yoy, "profit")].filter(Boolean);
    if (bits.length) parts.push(`In ${fq(q.period)}, ${bits.join(" and ")} from a year ago.`);
  }
  if (p.items.length) parts.push(`Management's record over the last ${v.documents.filter((d) => d.kind === "transcript").length} earnings calls: ${headline(p.counts)}${p.score != null ? ` Delivery score ${p.score} out of 100.` : ""}`);
  for (const i of p.items.filter((x) => x.verdict === "missed").slice(0, 3)) parts.push(`Missed: ${i.target}. Reported: ${i.actual}.`);
  if (v.helpers?.length) parts.push(`${v.helpers.length === 1 ? "One person" : `${v.helpers.length} people`} in your network can help with ${name}; they're listed under Who you know.`);
  return parts;
}

function headline(c: Research["promises"]["counts"]): string {
  const missed = c.missed ?? 0;
  const delivered = (c.delivered ?? 0) + (c.partly ?? 0);
  const judged = missed + delivered;
  if (!judged) return "Nothing due yet. Most promises run to FY27 or later.";
  if (missed > delivered) return `Missed ${missed} of ${judged} promises that came due.`;
  if (missed === 0) return `Delivered on all ${judged} promises that came due.`;
  return `Kept ${delivered} of ${judged} promises that came due.`;
}

/** Entry to the side-by-side comparison: named competitors first, then the same sector. */
function ComparePeers({ symbol }: { symbol: string }) {
  const { data } = useApi<{ peers: { symbol: string; kind: string }[] }>(`/compare/peers?symbol=${symbol}`);
  if (!data?.peers.length) return null;
  return (
    <div className="no-scrollbar mb-2 flex items-center gap-1.5 overflow-x-auto px-4">
      <span className="shrink-0 text-[12px] text-ink-3">Compare with</span>
      {data.peers.map((p) => (
        <Link
          key={p.symbol}
          href={`/compare?a=${symbol}&b=${p.symbol}`}
          className="shrink-0 rounded-full border border-line bg-surface px-2.5 py-0.5 text-[12px] font-medium text-accent"
        >
          {p.symbol}
        </Link>
      ))}
    </div>
  );
}
