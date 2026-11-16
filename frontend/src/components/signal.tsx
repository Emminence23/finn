"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import clsx from "clsx";
import { Calculator, ChevronRight, FileText, ThumbsDown, ThumbsUp } from "lucide-react";
import { api, type Attention } from "@/lib/api";
import { ProgressRing } from "./ProgressRing";
import { ErrorNote, Sheet } from "./ui";

/** Task C, Signal-to-Network: a filing's 0-100 attention score, the facts it rests on, and
 *  who in your own network may help, each with why and what is unknown. Built in code
 *  (intel/signal.py, network/match.py); the only AI inputs are the triage category and
 *  summary, and the names read from management-change filings, all labelled. */

export type Contact = {
  person_id: string;
  display_name: string;
  headline: string | null;
  connection_degree: 1 | 2;
  path: string[] | null;
  relevance_score: number;
  breakdown: Record<string, number>;
  match_reasons: string[];
  experience_period: { start: number | null; end: number | null } | null;
  confidence: "high" | "medium" | "low";
  explanation: string;
  unknown: string[];
  insider: boolean;
  introduced_by?: { id: string; name: string; context: string };
};
type Fact = { field: string; value: string | number; unit?: string; role?: string; source_quote: string; source: string };
type Signal = {
  announcement_id: string;
  company: { name: string; ticker: string };
  source: { title: string; url: string | null; published_at: string; document_type: string | null };
  event: { category: string; category_name: string; secondary_categories: string[]; confidence: number; classified_by: string | null; summary: string };
  facts: Fact[];
  materiality: { score: number; priority: Attention["priority"]; breakdown: Record<string, number | null>; max: Record<string, number>; labels: Record<string, string>; explanation: string[]; unknown_components: string[] };
  network_matches: Contact[];
  network_note: string | null;
  rule_version: string;
};

const BAND: Record<Attention["priority"], { label: string; cls: string }> = {
  critical: { label: "Critical", cls: "bg-bad-soft text-bad" },
  high: { label: "High", cls: "bg-warn-soft text-warn" },
  medium: { label: "Medium", cls: "bg-accent-soft text-accent" },
  low: { label: "Low", cls: "bg-mute-soft text-ink-2" },
  routine: { label: "Routine", cls: "bg-mute-soft text-ink-3" },
};

export function BandPill({ p, score }: { p: Attention["priority"]; score: number }) {
  return (
    <span className={clsx("tnum inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", BAND[p].cls)}>
      {score} · {BAND[p].label}
    </span>
  );
}

export function AttentionButton({ id, attention }: { id: string; attention: Attention }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)} className="mt-2 inline-flex items-center gap-1.5 text-[12px] text-ink-3 active:opacity-70">
        <span>Attention</span>
        <BandPill p={attention.priority} score={attention.score} />
        <span className="underline underline-offset-2">Why, and who can help</span>
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Why this matters">
        {open && <SignalView id={id} />}
      </Sheet>
    </>
  );
}

function Breakdown({ m }: { m: Signal["materiality"] }) {
  return (
    <ul className="space-y-1.5">
      {Object.keys(m.max).map((k) => {
        const v = m.breakdown[k];
        const max = m.max[k];
        return (
          <li key={k} className="grid grid-cols-[1fr_auto] items-center gap-x-3 text-[12px]">
            <span className="text-ink-2">{m.labels[k]}</span>
            <span className="tnum text-right text-ink-3">{v == null ? "unknown" : `${v} / ${max}`}</span>
            <span className="col-span-2 mt-0.5 flex h-1.5 overflow-hidden rounded-full bg-surface-2">
              {v != null && <span className="rounded-full bg-accent" style={{ width: `${(v / max) * 100}%` }} />}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function ContactRow({ c, onFeedback }: { c: Contact; onFeedback?: (kind: string, id: string) => void }) {
  const [voted, setVoted] = useState<string | null>(null);
  return (
    <li className="py-3">
      <div className="flex items-start justify-between gap-2">
        <Link href={`/people/${c.person_id}`} className="min-w-0 active:opacity-70">
          <span className="block text-[14px] font-semibold">{c.display_name}</span>
          <span className="block text-[11px] text-ink-3">{c.connection_degree === 1 ? "First-degree contact" : `Second degree: ${c.path?.join(" → ")}`}</span>
        </Link>
        <span className="tnum shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-semibold text-ink-2">{c.relevance_score}</span>
      </div>
      <p className="mt-1.5 text-[13px] leading-snug">{c.explanation.replace(/^(A first-degree contact|One introduction away, through [^.]+)\. /, "")}</p>
      {c.insider && <p className="mt-1 text-[12px] text-warn">Works there now: keep it to public information.</p>}
      <ul className="mt-1.5 space-y-0.5">
        {c.match_reasons.map((r) => (
          <li key={r} className="text-[12px] leading-snug text-ink-2">
            · {r}
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[11px] text-ink-3">
        Confidence {c.confidence}. Unknown: {c.unknown.join(" ").toLowerCase()}
      </p>
      {onFeedback && (
        <p className="mt-1.5 flex gap-3 text-[12px] text-ink-3">
          {voted ? (
            <span>Thanks, noted for your network only.</span>
          ) : (
            <>
              <button onClick={() => (setVoted("y"), onFeedback("relevant_contact", c.person_id))} className="underline underline-offset-2">
                Relevant
              </button>
              <button onClick={() => (setVoted("n"), onFeedback("irrelevant_contact", c.person_id))} className="underline underline-offset-2">
                Not relevant
              </button>
            </>
          )}
        </p>
      )}
    </li>
  );
}

const FIELD: Record<string, string> = {
  amount: "Amount",
  percentage: "Percentage",
  effective_date: "Effective",
  date: "Date",
  incoming_person: "Incoming",
  outgoing_person: "Outgoing",
  named_person: "Named",
};

function SignalView({ id }: { id: string }) {
  const [s, setS] = useState<Signal | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [voted, setVoted] = useState<string | null>(null);
  const load = () => {
    setError(null);
    api<Signal>("/announcements/analyze", { method: "POST", body: JSON.stringify({ announcement_id: id }) })
      .then(setS)
      .catch(setError);
  };
  useEffect(load, [id]);
  const feedback = (kind: string, person_id?: string) => {
    api(`/signals/${id}/feedback`, { method: "POST", body: JSON.stringify({ kind, person_id }) }).catch(() => {});
  };
  if (error && !s) return <ErrorNote error={error} retry={load} />;
  if (!s)
    return (
      <p className="flex items-center gap-2 py-6 text-[13px] text-ink-2" role="status">
        <ProgressRing size={16} /> Scoring the filing and searching your network…
      </p>
    );
  const m = s.materiality;
  return (
    <div className="space-y-5 pb-4">
      <div>
        <p className="flex flex-wrap items-center gap-2 text-[12px] text-ink-3">
          <span className="font-semibold uppercase tracking-wide">{s.company.ticker} · {s.event.category_name}</span>
          <BandPill p={m.priority} score={m.score} />
        </p>
        <p className="mt-1.5 text-[15px] font-medium leading-snug">{s.event.summary}</p>
        <p className="mt-1 text-[11px] text-ink-3">
          Category by {s.event.classified_by === "rules" ? "rules" : "AI"} (confidence {Math.round(s.event.confidence * 100)}%).
          {s.source.url && (
            <>
              {" "}
              <a href={s.source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 font-medium text-accent">
                <FileText size={11} /> Open the filing
              </a>
            </>
          )}
        </p>
      </div>

      <section>
        <p className="mb-2 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
          <Calculator size={11} /> Attention {m.score} of 100, computed in code
        </p>
        <Breakdown m={m} />
        <ul className="mt-3 space-y-1">
          {m.explanation.map((e) => (
            <li key={e} className="text-[13px] leading-snug">
              {e}
            </li>
          ))}
        </ul>
        {m.unknown_components.length > 0 && <p className="mt-1.5 text-[12px] text-ink-3">Not scored: {m.unknown_components.join(" ")}</p>}
      </section>

      {s.facts.length > 0 && (
        <section>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Facts, with where they came from</p>
          <ul className="divide-y divide-line">
            {s.facts.slice(0, 6).map((f, i) => (
              <li key={i} className="py-1.5 text-[12px] leading-snug">
                <span className="font-semibold">{FIELD[f.field] ?? f.field}:</span> {f.field === "amount" ? `₹${Number(f.value).toLocaleString("en-IN")} Cr` : f.field === "percentage" ? `${f.value}%` : String(f.value)}
                {f.role && <span className="text-ink-2"> ({f.role})</span>}
                <span className="block text-ink-3">
                  “{f.source_quote}” · {f.source}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Who in your network may help</p>
        {s.network_note && <p className="text-[12px] text-warn">{s.network_note}</p>}
        {s.network_matches.length === 0 ? (
          <p className="text-[13px] text-ink-2">No relevant match in your network for this one.</p>
        ) : (
          <ul className="divide-y divide-line">
            {s.network_matches.map((c) => (
              <ContactRow key={c.person_id} c={c} onFeedback={feedback} />
            ))}
          </ul>
        )}
        <Link href={`/ask?q=${encodeURIComponent(`Who can help me understand ${s.company.ticker}?`)}`} className="mt-1 inline-flex items-center gap-0.5 text-[12px] font-medium text-accent">
          Ask about another angle <ChevronRight size={13} />
        </Link>
      </section>

      <section className="border-t border-line pt-3">
        <p className="text-[12px] text-ink-3">Was this worth your attention?</p>
        {voted ? (
          <p className="mt-1 text-[13px]">Thanks. Kept for your account only, to tune the rules.</p>
        ) : (
          <div className="mt-1.5 flex flex-wrap gap-2">
            {[
              ["useful", "Useful", ThumbsUp],
              ["not_useful", "Not useful", ThumbsDown],
              ["wrong_category", "Wrong category", null],
            ].map(([k, label, Icon]) => (
              <button
                key={k as string}
                onClick={() => (setVoted(k as string), feedback(k as string))}
                className="inline-flex items-center gap-1 rounded-full border border-line px-3 py-1 text-[12px] active:opacity-70"
              >
                {Icon && <Icon size={12} />} {label as string}
              </button>
            ))}
          </div>
        )}
        <p className="mt-2 text-[10px] text-ink-3">Rules {s.rule_version}. Weights are the starting point from the spec, checked against 100 hand-labelled filings.</p>
      </section>
    </div>
  );
}
