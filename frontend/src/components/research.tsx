"use client";

import { useMemo, useState } from "react";
import clsx from "clsx";
import { Check, CircleDashed, CircleHelp, CircleSlash, Minus, RotateCcw, Sparkles, X, Calculator } from "lucide-react";
import type { Cite, Claim, DocRef, PromiseItem, Verdict } from "@/lib/api";
import { fq } from "@/lib/fmt";

// ------------------------------------------------------------------ verdicts
export const VERDICT: Record<
  Verdict,
  { label: string; icon: typeof Check; text: string; soft: string; bar: string }
> = {
  delivered: { label: "Delivered", icon: Check, text: "text-good", soft: "bg-good-soft", bar: "var(--good)" },
  partly: { label: "Partly", icon: Minus, text: "text-warn", soft: "bg-warn-soft", bar: "var(--warn)" },
  missed: { label: "Missed", icon: X, text: "text-bad", soft: "bg-bad-soft", bar: "var(--bad)" },
  revised: { label: "Revised", icon: RotateCcw, text: "text-warn", soft: "bg-warn-soft", bar: "var(--warn)" },
  unclear: { label: "Can't tell", icon: CircleHelp, text: "text-ink-2", soft: "bg-mute-soft", bar: "var(--ink-3)" },
  too_early: { label: "Not yet due", icon: CircleDashed, text: "text-ink-3", soft: "bg-mute-soft", bar: "var(--line)" },
  not_measurable: { label: "Not checkable", icon: CircleSlash, text: "text-ink-3", soft: "bg-mute-soft", bar: "var(--line)" },
};
const ORDER: Verdict[] = ["delivered", "partly", "missed", "revised", "unclear", "too_early", "not_measurable"];

const TYPE_LABEL: Record<string, string> = {
  number: "Numeric target",
  direction: "Directional",
  milestone: "Dated milestone",
  not_measurable: "Nothing to measure",
};
/** Verdicts that are not a judgement of delivery, folded under the judged ones */
export const PENDING: Verdict[] = ["too_early", "not_measurable"];

export function VerdictPill({ v }: { v: Verdict }) {
  const s = VERDICT[v];
  const Icon = s.icon;
  return (
    <span className={clsx("inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold", s.soft, s.text)}>
      <Icon size={12} strokeWidth={2.5} />
      {s.label}
    </span>
  );
}

/** Thin segmented bar (no text on it) + a legend that carries the counts. */
export function VerdictBar({ counts }: { counts: Partial<Record<Verdict, number>> }) {
  const total = ORDER.reduce((s, v) => s + (counts[v] ?? 0), 0);
  if (!total) return null;
  const parts = ORDER.filter((v) => (counts[v] ?? 0) > 0);
  return (
    <div>
      <div
        className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full"
        role="img"
        aria-label={parts.map((v) => `${counts[v]} ${VERDICT[v].label.toLowerCase()}`).join(", ")}
      >
        {parts.map((v) => (
          <span key={v} style={{ flexGrow: counts[v], background: VERDICT[v].bar }} title={`${VERDICT[v].label}: ${counts[v]}`} />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-ink-2">
        {parts.map((v) => {
          const Icon = VERDICT[v].icon;
          return (
            <li key={v} className="inline-flex items-center gap-1">
              <Icon size={12} strokeWidth={2.5} className={VERDICT[v].text} />
              <span className="tnum font-semibold text-ink">{counts[v]}</span> {VERDICT[v].label.toLowerCase()}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ citations
/** Models sometimes start an inline citation ("… {", "… [T1") before the structured one. */
export function cleanClaim(t: string): string {
  return t.replace(/[\s{(\[]+$/, "").replace(/\s*\[(T\d|AR)[^\]]*\]\s*$/, "");
}

export function useDocs(docs: DocRef[]) {
  return useMemo(() => new Map(docs.map((d) => [d.id, d])), [docs]);
}

function shortLabel(d: DocRef): string {
  return d.kind === "annual_report" ? `AR ${d.period.replace("FY20", "FY")}` : d.label.replace(/ \(.*\)$/, "");
}

export function CiteChips({ cites, docs, base = "" }: { cites: Cite[]; docs: Map<string, DocRef>; base?: string }) {
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {cites.slice(0, 3).map((c, i) => {
        if (/^(fin:|Q:|FY:)/.test(c.doc))
          return (
            <a key={i} href={`${base}#numbers`} className="rounded bg-surface-2 px-1 text-[10px] font-medium text-ink-3">
              {c.doc.startsWith("fin:") ? "financials" : c.doc.startsWith("Q:") ? `${fq(c.doc.slice(2))} reported` : `${fq(c.doc.slice(3), true)} reported`}
            </a>
          );
        if (/^P\d+$/.test(c.doc))
          return (
            <a key={i} href={`${base}#promises`} className="rounded bg-surface-2 px-1 text-[10px] font-medium text-ink-3">
              scorecard
            </a>
          );
        const d = docs.get(c.doc);
        if (!d) return null;
        return (
          <a
            key={i}
            href={`${d.url}#page=${c.page ?? 1}`}
            target="_blank"
            rel="noreferrer"
            className="rounded bg-surface-2 px-1 text-[10px] font-medium text-ink-3"
            title={`${d.label}, page ${c.page}`}
          >
            {shortLabel(d)} p{c.page}
          </a>
        );
      })}
    </span>
  );
}

// ------------------------------------------------------------------ three voices (PL-7)
/* Reported figures are plain tabular numbers with no rule. Management's words are italic
   quotes on a grey rule. FINN's interpretation sits on an accent rule. The legend under the
   company header says so once, so a reader never has to tap to tell them apart. */
export const READ_RULE = "border-l-2 border-accent/60 pl-3";

export function FinnRead({ children, label = "FINN's read", code = false }: { children: React.ReactNode; label?: string; code?: boolean }) {
  const Icon = code ? Calculator : Sparkles;
  return (
    <div className={READ_RULE}>
      <p className="mb-0.5 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-accent">
        <Icon size={10} aria-hidden /> {label}
      </p>
      {children}
    </div>
  );
}

export function VoiceLegend() {
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-3" aria-label="How to read this page">
      <span className="tnum font-medium text-ink-2">₹ Reported figures</span>
      <span className="border-l-2 border-line pl-1.5 italic">&ldquo;Management&apos;s words&rdquo;</span>
      <span className="border-l-2 border-accent/60 pl-1.5 text-ink-2">FINN&apos;s read</span>
    </p>
  );
}

export function ClaimList({ claims, docs, marker }: { claims: Claim[]; docs: Map<string, DocRef>; marker?: React.ReactNode }) {
  return (
    <ul className={clsx("space-y-2", READ_RULE)}>
      {claims.map((c, i) => (
        <li key={i} className="flex gap-2 text-[13px] leading-snug">
          {marker && <span className="mt-0.5 shrink-0">{marker}</span>}
          <span>
            {cleanClaim(c.text)}
            <CiteChips cites={c.cites} docs={docs} />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Credibility text cites promise ids like [T3.1]; render them as call names. */
export function CredibilityText({ text, docs }: { text: string; docs: Map<string, DocRef> }) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return (
    <p className="text-[14px] leading-relaxed">
      {parts.map((p, i) => {
        const m = p.match(/^\[([^\]]+)\]$/);
        if (!m) return <span key={i}>{p}</span>;
        const labels = [...new Set(m[1].split(/,\s*/).map((id) => docs.get(id.split(".")[0])).filter(Boolean).map((d) => shortLabel(d!)))];
        return (
          <span key={i} className="whitespace-nowrap rounded bg-surface-2 px-1 text-[11px] text-ink-3">
            {labels.join(", ") || m[1]}
          </span>
        );
      })}
    </p>
  );
}

/** The reported figures a verdict rests on, as chips that jump to the numbers. */
function reportedCites(evidence: string[]): Cite[] {
  return evidence.filter((e) => /^(Q|FY):/.test(e)).map((doc) => ({ doc, page: null }));
}

// ------------------------------------------------------------------ promise row
export function PromiseRow({ p, docs }: { p: PromiseItem; docs: Map<string, DocRef> }) {
  const d = docs.get(p.doc_id);
  return (
    <li className="py-3.5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[14px] font-semibold leading-snug">{p.target}</p>
        <VerdictPill v={p.verdict} />
      </div>
      <blockquote className="mt-2 border-l-2 border-line pl-3 text-[13px] italic leading-snug text-ink-2">
        &ldquo;{p.quote}&rdquo;
        <footer className="mt-1 text-[11px] not-italic text-ink-3">
          {d ? (
            <a href={`${d.url}#page=${p.page}`} target="_blank" rel="noreferrer" className="underline decoration-line underline-offset-2">
              {p.said_in}, p.{p.page}
            </a>
          ) : (
            p.said_in
          )}
          {p.repeated_in.length > 0 && <> · repeated in {p.repeated_in.map((x) => x.replace(/ \(.*\)$/, "")).join(", ")}</>}
        </footer>
      </blockquote>
      {p.revised && (
        <p className="mt-2 text-[13px] leading-snug">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-warn">Revised </span>
          {p.revised.in && <>in the {p.revised.in.replace(/ \(.*\)$/, "")}: </>}
          {p.revised.to}
          {p.verdict !== "revised" && <span className="text-ink-3"> (judged against the outcome below)</span>}
        </p>
      )}
      <div className="mt-2">
        <FinnRead code={p.judged_by === "code"} label={p.judged_by === "code" ? "Measured against reported numbers" : "FINN's read (AI)"}>
          {!PENDING.includes(p.verdict) && p.verdict !== "revised" && (
            <p className="text-[13px] leading-snug">
              {p.actual}
              <CiteChips cites={reportedCites(p.evidence)} docs={docs} />
            </p>
          )}
          <p className="mt-0.5 text-[12px] leading-snug text-ink-3">
            {p.statement_type && <>{TYPE_LABEL[p.statement_type]} · </>}
            {p.verdict === "too_early" && p.horizon ? `Due ${p.horizon}. ` : ""}
            {p.verdict === "not_measurable" ? "No number, direction or date to check it against, so no verdict." : p.note}
            {p.guard && <span className="italic"> (Held back: {p.guard}.)</span>}
          </p>
        </FinnRead>
      </div>
    </li>
  );
}

// ------------------------------------------------------------------ stat tile + sparkline
export type Point = { label: string; value: number | null };

export function StatTile({
  label,
  value,
  sub,
  points,
  format,
}: {
  label: string;
  value: string;
  sub?: React.ReactNode;
  points?: Point[];
  format?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const pts = (points ?? []).filter((p) => p.value != null) as { label: string; value: number }[];
  const shown = hover != null && pts[hover] && format ? pts[hover] : null;
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <p className="text-[11px] font-medium text-ink-3">{label}</p>
      <p className="mt-0.5 text-[19px] font-semibold leading-tight tracking-[-0.01em]">
        {shown ? format!(shown.value) : value}
      </p>
      <p className="h-4 text-[11px] text-ink-3">{shown ? shown.label : sub}</p>
      {pts.length >= 3 && <Spark pts={pts} hover={hover} setHover={setHover} label={label} format={format} />}
    </div>
  );
}

function Spark({
  pts,
  hover,
  setHover,
  label,
  format,
}: {
  pts: { label: string; value: number }[];
  hover: number | null;
  setHover: (i: number | null) => void;
  label: string;
  format?: (v: number) => string;
}) {
  const W = 150; // ~ the tile width on a phone, so the meet-scaled chart barely letterboxes
  const H = 34;
  const vals = pts.map((p) => p.value);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const x = (i: number) => 4 + (i * (W - 8)) / (pts.length - 1);
  const y = (v: number) => 4 + (1 - (v - lo) / span) * (H - 8);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const last = pts.length - 1;
  const crossesZero = lo < 0 && hi > 0;
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.round((((e.clientX - r.left) / r.width) * W - 4) / ((W - 8) / (pts.length - 1)));
    setHover(Math.max(0, Math.min(last, i)));
  };
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="mt-1.5 h-[34px] w-full touch-none overflow-visible"
      tabIndex={0}
      role="img"
      aria-label={`${label}: ${pts.map((p) => `${p.label} ${format ? format(p.value) : p.value}`).join(", ")}`}
      onPointerMove={onMove}
      onPointerDown={onMove}
      onPointerLeave={() => setHover(null)}
      onBlur={() => setHover(null)}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") setHover(Math.max(0, (hover ?? last) - 1));
        if (e.key === "ArrowRight") setHover(Math.min(last, (hover ?? last - 1) + 1));
      }}
    >
      {crossesZero && <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="var(--line)" strokeWidth={1} vectorEffect="non-scaling-stroke" />}
      <path d={d} fill="none" stroke="var(--spark)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {hover != null && (
        <line x1={x(hover)} x2={x(hover)} y1={0} y2={H} stroke="var(--ink-3)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      )}
      <circle cx={x(hover ?? last)} cy={y(pts[hover ?? last].value)} r={3.5} fill="var(--accent)" stroke="var(--surface)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
