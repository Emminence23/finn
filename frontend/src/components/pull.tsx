"use client";

import { useState } from "react";
import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import type { Cite, Claim, DocRef, QaAnswer, Verdict } from "@/lib/api";
import { CiteChips, CredibilityText, FinnRead, VERDICT, VerdictBar, VerdictPill, cleanClaim } from "./research";
import { AiTag } from "./ui";
import { ContactRow, type Contact } from "./signal";
import { BrokerBody, type Divergence, type Overview, type Revisions, type Track } from "./brokers";

// ------------------------------------------------------------------ types (backend app/research/pull.py)
export type LedgerItem = {
  id: string;
  group: "growth" | "margins" | "cash" | "funding" | "projects";
  target: string;
  quote: string;
  page: number;
  doc_id: string;
  horizon: string | null;
  segment: boolean;
  verdict: Verdict | "open" | "update";
  actual?: string | null;
  evidence?: string[];
  judged_by?: "code" | "ai";
  revision?: boolean;
  revised?: { to: string | null; in: string | null } | null;
};
export type LedgerCall = {
  doc_id: string;
  call: string;
  quarter: string | null;
  quarter_label: string | null;
  delivered: { period: string; revenue: number | null; revenue_yoy: number | null; margin_pct: number | null; pat: number | null; pat_yoy: number | null } | null;
  promised: LedgerItem[];
  updates: LedgerItem[];
};
export type Theme = {
  title: string;
  said: { quote: string; target: string; doc_id: string; page: number };
  numbers: string;
  flags: string[];
  read: string;
  tone: "positive" | "negative" | "neutral";
  evidence: { target: string; verdict: Verdict; actual: string | null }[];
};
export type GuidanceItem = { target: string; horizon: string | null; quote: string; doc_id: string; page: number; headline: boolean };
type Point = Claim & { tone?: string };
export type Block =
  | { type: "text"; text: string; cites?: Cite[] }
  | { type: "note"; text: string }
  | { type: "points"; title?: string; tone?: string; items: Point[] }
  | { type: "table"; title?: string; columns: string[]; rows: string[][] }
  | { type: "stats"; items: { label: string; value: string; sub?: string }[] }
  | { type: "ledger"; calls: LedgerCall[]; counts: Record<string, number>; summary: string[]; credibility: string | null; margin_label: string }
  | { type: "themes"; items: Theme[] }
  | { type: "guidance"; title: string; items: GuidanceItem[] }
  | ({ type: "answer" } & QaAnswer)
  | { type: "contacts"; items: Contact[]; topic: string; event: string | null }
  | { type: "brokers"; symbol: string; overview: Overview; revisions?: Revisions; divergence?: Divergence; track?: Track };

export type PullReply =
  | {
      kind: "reply";
      symbol: string | null; // null for a comparison or the portfolio
      symbols?: string[];
      planned_by?: "rules" | "model";
      company: string;
      intent: string;
      title: string;
      blocks: Block[];
      menu: { intent: string; label: string }[];
      documents: DocRef[];
      as_of: string | null;
      notice?: string;
      saved_at?: number | null; // epoch seconds: when this report was built (kept a week)
      from_saved?: boolean;
      refreshing?: boolean;
    }
  | { kind: "pick"; ready: { symbol: string; company: string }[] }
  | { kind: "not_built"; symbol: string; company: string | null; covered: boolean; builds_left: number };

// ------------------------------------------------------------------ blocks
const money = (x: number | null | undefined) => (x == null ? "–" : `${x < 0 ? "−" : ""}₹${Math.abs(x).toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`);
const sp = (x: number | null | undefined) => (x == null ? "–" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(0)}%`);

function SubTitle({ children }: { children: React.ReactNode }) {
  return <p className="mb-1.5 mt-4 text-[12px] font-semibold uppercase tracking-wide text-ink-3 first:mt-0">{children}</p>;
}

function Quote({ text, doc, page }: { text: string; doc: DocRef | undefined; page: number }) {
  return (
    <blockquote className="mt-1.5 border-l-2 border-line pl-3 text-[13px] italic leading-snug text-ink-2">
      &ldquo;{text}&rdquo;
      {doc && (
        <footer className="mt-0.5 text-[11px] not-italic text-ink-3">
          <a href={`${doc.url}#page=${page}`} target="_blank" rel="noreferrer" className="underline decoration-line underline-offset-2">
            {doc.label}, p.{page}
          </a>
        </footer>
      )}
    </blockquote>
  );
}

function Pill({ v }: { v: LedgerItem["verdict"] }) {
  if (v === "open") return <span className="shrink-0 rounded-full bg-mute-soft px-2 py-0.5 text-[11px] font-semibold text-ink-3">No date given</span>;
  if (v === "update") return null;
  return <VerdictPill v={v} />;
}

function Table({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="tnum w-full min-w-[300px] text-[12px]">
        <thead>
          <tr className="text-ink-3">
            {columns.map((c, i) => (
              <th key={i} className={clsx("px-1 pb-1 font-medium", i ? "text-right" : "text-left")}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r, j) => (
            <tr key={j}>
              {r.map((c, i) => (
                <td key={i} className={clsx("px-1 py-1.5", i ? "whitespace-nowrap text-right" : "text-left font-medium")}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LedgerRow({ p, docs, base }: { p: LedgerItem; docs: Map<string, DocRef>; base: string }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="py-2.5">
      <button onClick={() => setOpen(!open)} className="flex w-full items-start justify-between gap-2 text-left" aria-expanded={open}>
        <span className="text-[13px] font-medium leading-snug">
          {p.target}
          {p.horizon && <span className="font-normal text-ink-3"> · {p.horizon}</span>}
        </span>
        <Pill v={p.verdict} />
      </button>
      {p.actual && (p.verdict === "delivered" || p.verdict === "partly" || p.verdict === "missed" || p.verdict === "unclear") && (
        <p className="mt-1 text-[12px] leading-snug text-ink-2">
          {p.actual}
          <CiteChips cites={(p.evidence ?? []).filter((e) => /^(Q|FY):/.test(e)).map((doc) => ({ doc, page: null }))} docs={docs} base={base} />
          <span className="ml-1 text-[10px] uppercase tracking-wide text-ink-3">{p.judged_by === "code" ? "measured in code" : "judged by AI"}</span>
        </p>
      )}
      {p.revised?.to && <p className="mt-1 text-[12px] text-warn">Revised{p.revised.in ? ` in the ${p.revised.in.replace(/ \(.*\)$/, "")}` : ""}: {p.revised.to}</p>}
      {open ? (
        <Quote text={p.quote} doc={docs.get(p.doc_id)} page={p.page} />
      ) : (
        <button onClick={() => setOpen(true)} className="mt-0.5 text-[11px] text-ink-3 underline underline-offset-2">
          Their words, p.{p.page}
        </button>
      )}
    </li>
  );
}

function CallCard({ c, docs, base, marginLabel }: { c: LedgerCall; docs: Map<string, DocRef>; base: string; marginLabel: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? c.promised : c.promised.slice(0, 3);
  const d = c.delivered;
  return (
    <div className="rounded-2xl border border-line bg-bg p-3.5">
      <p className="flex items-baseline justify-between gap-2">
        <span className="text-[14px] font-semibold">{c.quarter_label}</span>
        <span className="text-[11px] text-ink-3">{c.call.replace(/^.*\((.*)\)$/, "$1 call")}</span>
      </p>
      {d && (
        <p className="tnum mt-1 text-[12px] leading-snug text-ink-2">
          <span className="font-medium text-ink">Delivered:</span> revenue {money(d.revenue)} ({sp(d.revenue_yoy)} YoY), {marginLabel.split(" (")[0].toLowerCase().replace("ebitda", "EBITDA")} {d.margin_pct ?? "–"}%, profit {sp(d.pat_yoy)} YoY
        </p>
      )}
      {c.promised.length > 0 ? (
        <>
          <p className="mt-2.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Promised on this call</p>
          <ul className="divide-y divide-line">
            {shown.map((p) => (
              <LedgerRow key={p.id} p={p} docs={docs} base={base} />
            ))}
          </ul>
          {c.promised.length > 3 && (
            <button onClick={() => setAll(!all)} className="mt-1 flex items-center gap-1 text-[12px] font-medium text-accent">
              {all ? "Fewer" : `${c.promised.length - 3} more`} <ChevronDown size={13} className={clsx(all && "rotate-180")} />
            </button>
          )}
        </>
      ) : (
        <p className="mt-2 text-[12px] text-ink-3">No new headline targets on this call.</p>
      )}
      {c.updates.length > 0 && (
        <>
          <p className="mt-2.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Said about earlier targets</p>
          <ul className="mt-1 space-y-1.5">
            {c.updates.slice(0, 3).map((u) => (
              <li key={u.id} className="text-[12px] leading-snug">
                {u.revision && <span className="mr-1 font-semibold text-warn">Revised:</span>}
                {u.target}
                <span className="text-ink-3"> · p.{u.page}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Ledger({ b, docs, base }: { b: Extract<Block, { type: "ledger" }>; docs: Map<string, DocRef>; base: string }) {
  const counts = Object.fromEntries(Object.entries(b.counts).filter(([k]) => k in VERDICT)) as Partial<Record<Verdict, number>>;
  return (
    <div>
      <FinnRead code label="Computed in code">
        <ul className="space-y-1.5">
          {b.summary.map((s, i) => (
            <li key={i} className="text-[14px] leading-snug">
              {s}
            </li>
          ))}
        </ul>
      </FinnRead>
      <div className="mt-3">
        <VerdictBar counts={counts} />
        {b.counts.open > 0 && <p className="mt-1 text-[12px] text-ink-3">{b.counts.open} more gave no date, so nothing falls due.</p>}
      </div>
      <SubTitle>Delivered, quarter by quarter</SubTitle>
      <Table
        columns={["Quarter", "Revenue", "YoY", "Margin", "Profit YoY"]}
        rows={b.calls
          .filter((c) => c.delivered)
          .map((c) => [c.quarter_label ?? "", money(c.delivered!.revenue), sp(c.delivered!.revenue_yoy), `${c.delivered!.margin_pct ?? "–"}%`, sp(c.delivered!.pat_yoy)])}
      />
      <SubTitle>Call by call: what they promised, what happened</SubTitle>
      <div className="space-y-2">
        {b.calls.map((c) => (
          <CallCard key={c.doc_id} c={c} docs={docs} base={base} marginLabel={b.margin_label} />
        ))}
      </div>
      {b.credibility && (
        <div className="mt-4">
          <FinnRead label="FINN's read of the track record (AI)">
            <CredibilityText text={b.credibility} docs={docs} />
          </FinnRead>
        </div>
      )}
    </div>
  );
}

const TONE: Record<string, string> = { positive: "text-good", negative: "text-bad", neutral: "text-ink-2" };

function Themes({ items, docs }: { items: Theme[]; docs: Map<string, DocRef> }) {
  return (
    <div className="space-y-2">
      {items.map((t) => (
        <div key={t.title} className="rounded-2xl border border-line bg-bg p-3.5">
          <p className="text-[14px] font-semibold">{t.title}</p>
          <p className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Management said</p>
          <Quote text={t.said.quote} doc={docs.get(t.said.doc_id)} page={t.said.page} />
          <p className="mt-2.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">The numbers</p>
          <p className="tnum mt-0.5 text-[13px] leading-snug">{t.numbers}</p>
          {t.flags.map((f) => (
            <p key={f} className="mt-0.5 text-[12px] leading-snug text-bad">
              {f}
            </p>
          ))}
          <div className="mt-2.5">
            <FinnRead code label="The read, from verdicts">
              <p className={clsx("text-[13px] font-medium leading-snug", TONE[t.tone])}>{t.read}</p>
              {t.evidence.slice(0, 3).map((e) => (
                <p key={e.target} className="mt-1 text-[12px] leading-snug text-ink-2">
                  <span className={clsx("font-semibold", VERDICT[e.verdict]?.text)}>{VERDICT[e.verdict]?.label}:</span> {e.target}
                  {e.actual && <span className="text-ink-3"> · {e.actual}</span>}
                </p>
              ))}
            </FinnRead>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Blocks({ blocks, docs, base }: { blocks: Block[]; docs: Map<string, DocRef>; base: string }) {
  return (
    <div className="space-y-3">
      {blocks.map((b, i) => {
        switch (b.type) {
          case "text":
            return (
              <p key={i} className="text-[14px] leading-relaxed">
                {cleanClaim(b.text)}
                {b.cites && <CiteChips cites={b.cites} docs={docs} base={base} />}
              </p>
            );
          case "note":
            return (
              <p key={i} className="text-[11px] leading-snug text-ink-3">
                {b.text}
              </p>
            );
          case "points":
            return (
              <div key={i}>
                {b.title && <SubTitle>{b.title}</SubTitle>}
                <ul className="space-y-1.5">
                  {b.items.map((p, j) => (
                    <li key={j} className="flex gap-2 text-[14px] leading-snug">
                      <span
                        className={clsx(
                          "mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full",
                          (p.tone ?? b.tone) === "positive" ? "bg-good" : (p.tone ?? b.tone) === "negative" ? "bg-bad" : "bg-ink-3",
                        )}
                      />
                      <span>
                        {cleanClaim(p.text)}
                        {p.cites?.length > 0 && <CiteChips cites={p.cites} docs={docs} base={base} />}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          case "table":
            return (
              <div key={i}>
                {b.title && <SubTitle>{b.title}</SubTitle>}
                <Table columns={b.columns} rows={b.rows} />
              </div>
            );
          case "stats":
            return (
              <div key={i} className="grid grid-cols-2 gap-2">
                {b.items.map((s) => (
                  <div key={s.label} className="rounded-xl bg-surface-2/60 px-3 py-2">
                    <p className="text-[11px] text-ink-3">{s.label}</p>
                    <p className="tnum text-[17px] font-semibold">{s.value}</p>
                    {s.sub && <p className="tnum text-[11px] leading-snug text-ink-3">{s.sub}</p>}
                  </div>
                ))}
              </div>
            );
          case "ledger":
            return <Ledger key={i} b={b} docs={docs} base={base} />;
          case "themes":
            return <Themes key={i} items={b.items} docs={docs} />;
          case "guidance":
            return (
              <div key={i}>
                <SubTitle>{b.title}</SubTitle>
                <ul className="divide-y divide-line">
                  {b.items.map((g, j) => (
                    <li key={j} className="py-2">
                      <p className="text-[13px] font-medium leading-snug">
                        {g.target}
                        {g.horizon && <span className="font-normal text-ink-3"> · {g.horizon}</span>}
                      </p>
                      <Quote text={g.quote} doc={docs.get(g.doc_id)} page={g.page} />
                    </li>
                  ))}
                </ul>
              </div>
            );
          case "contacts":
            return (
              <div key={i}>
                <p className="text-[13px] text-ink-2">People who may give context on {b.topic}:</p>
                {b.items.length === 0 ? (
                  <p className="mt-2 text-[13px]">No relevant match in your network. Try Network → Yours to add your own contacts.</p>
                ) : (
                  <ul className="divide-y divide-line">
                    {b.items.map((c) => (
                      <ContactRow key={c.person_id} c={c} />
                    ))}
                  </ul>
                )}
              </div>
            );
          case "brokers":
            return (
              <div key={i} className="-mx-4">
                <BrokerBody ov={b.overview} rev={b.revisions} div={b.divergence} track={b.track} symbol={b.symbol} compact />
              </div>
            );
          case "answer":
            return (
              <div key={i}>
                {b.answerable === "no" && <p className="mb-1 text-[13px] text-ink-2">The documents FINN has don&apos;t answer that directly.</p>}
                <ul className="space-y-2">
                  {b.points.map((p, j) => (
                    <li key={j} className="text-[14px] leading-snug">
                      {cleanClaim(p.text)}
                      <CiteChips cites={p.cites} docs={docs} base={base} />
                    </li>
                  ))}
                </ul>
                <p className="mt-2">
                  <AiTag from="cited pages only" model={b.model} />
                  {b.dropped > 0 && <span className="ml-2 text-[11px] text-ink-3">{b.dropped} uncited point{b.dropped > 1 ? "s" : ""} removed in code</span>}
                </p>
              </div>
            );
        }
      })}
    </div>
  );
}
