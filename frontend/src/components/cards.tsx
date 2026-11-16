"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronDown, FileText, TrendingDown, TrendingUp } from "lucide-react";
import clsx from "clsx";
import { ShareButton } from "./ShareButton";
import type { Alert, Card, CardPerson, ResultsCard } from "@/lib/api";
import { CATEGORY_LABEL, ago, crore, day, fq, pct, shortName } from "@/lib/fmt";
import { HelperLine, PathView } from "./network";
import { AiTag, Pill } from "./ui";

export function AlertChip({ a }: { a: Alert }) {
  if (a.kind === "category") return null; // the card itself is the category alert
  const up = a.kind === "price" ? a.value > 0 : (a.price_change_pct ?? 0) >= 0;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <Pill tone="warn">
      <Icon size={12} />
      {a.kind === "volume" ? `Vol ${+a.value.toFixed(2)}× avg` : pct(a.value)} on {day(a.ts)}
    </Pill>
  );
}

/** Results cards lead with what the numbers say, not the filing's boilerplate subject. */
export function resultsTakeaway(r: ResultsCard): string | null {
  const get = (m: string) => r.rows.find((x) => x.metric === m)?.yoy ?? null;
  const p = get("pat");
  const v = get("revenue");
  const top = r.revenue_label === "Interest earned" ? "interest income" : "revenue";
  const patNote = r.rows.find((x) => x.metric === "pat")?.yoy_note;
  if (p == null && patNote && v != null)
    return `${patNote[0].toUpperCase() + patNote.slice(1)} YoY; ${top} ${v >= 0 ? "up" : "down"} ${Math.abs(v).toFixed(0)}%`;
  if (p == null || v == null) return null;
  const P = `${Math.abs(p).toFixed(0)}%`;
  const V = `${Math.abs(v).toFixed(0)}%`;
  if (p < 0 && v >= 0) return `Profit down ${P} YoY even as ${top} grew ${V}`;
  if (p >= 0 && v < 0) return `Profit up ${P} YoY despite ${top} falling ${V}`;
  if (p < 0) return `${top[0].toUpperCase() + top.slice(1)} down ${V}, profit down ${P} YoY`;
  return `Profit up ${P} YoY on ${V} ${top} growth`;
}

function NextAction({ card, onOpen }: { card: Card; onOpen?: () => void }) {
  const a = card.next_action ?? { label: "Research", href: `/c/${card.symbol}`, why: "" };
  const cls = "ml-auto min-w-0 truncate text-right font-medium text-accent";
  const label = `${a.label} →`;
  return a.href.startsWith("http") ? (
    <a href={a.href} target="_blank" rel="noreferrer" className={cls} title={a.why} onClick={onOpen}>
      {label}
    </a>
  ) : (
    <Link href={a.href} className={cls} title={a.why} onClick={onOpen}>
      {label}
    </Link>
  );
}

export type CardRead = { isNew: boolean; opened: boolean; onOpen: () => void };

/** What the fold under a card holds, in words. */
function evidenceLabel(card: Card): string {
  if (card.kind === "results" && card.results) return "The numbers";
  if (card.kind === "management_change" && card.people?.length) return "Who they are";
  return card.related.length ? `${card.related.length + 1} filings` : "";
}

/** One item of the note: the sentence first, its size and why it's here, the person to ask,
 *  then the evidence folded beneath. */
function CardShell({
  card,
  now,
  read,
  evidence,
  helper,
  openEvidence = false,
}: {
  card: Card;
  now: string;
  read?: CardRead;
  evidence?: React.ReactNode;
  helper?: React.ReactNode;
  openEvidence?: boolean;
}) {
  const [open, setOpen] = useState(openEvidence);
  const moves = sessionMoves(card.alerts);
  const label = evidenceLabel(card);
  const hasEvidence = Boolean(evidence) || card.related.length > 0;
  return (
    <article
      data-tour="card"
      className={clsx("mx-3 rounded-2xl border border-line bg-surface p-4 transition-opacity", read?.opened && !open && "opacity-70")}
    >
      <p className="flex items-center gap-1.5 text-[12px] text-ink-2">
        <Link href={`/c/${card.symbol}`} className="min-w-0 truncate font-semibold text-ink active:opacity-70">
          {card.short ?? shortName(card.company)}
        </Link>
        <span aria-hidden>·</span>
        <span className={clsx("shrink-0", card.unsure && "text-warn")}>{card.unsure ? "Unclassified" : (CATEGORY_LABEL[card.category] ?? card.category)}</span>
        <span className="tnum ml-auto flex shrink-0 items-center gap-1 text-ink-3">
          {read?.isNew && (
            <span className="inline-flex items-center gap-1 font-semibold text-accent">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
              New ·
            </span>
          )}
          {ago(card.ts, now)} ago
        </span>
      </p>
      <p className="mt-1.5 text-[16px] font-medium leading-snug tracking-[-0.005em] text-ink">
        {card.line ?? (card.results && resultsTakeaway(card.results)) ?? card.title}
      </p>
      <p className="mt-1 text-[13px] leading-snug text-ink-2">
        {card.stake && <>{card.stake} </>}
        {card.level_reason && (
          <span className="text-ink-3">
            {card.level === "important" ? "Important" : "Notable"} because: {card.level_reason}.
          </span>
        )}
      </p>
      {moves.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {moves.map((a) => (
            <AlertChip key={a.id} a={a} />
          ))}
        </div>
      )}
      {helper && <div className="mt-3">{helper}</div>}
      {open && (
        <div className="mt-3 space-y-3 border-t border-line pt-3">
          {evidence}
          {card.related.length > 0 && (
            <ul className="space-y-1.5">
              {card.related.map((r) => (
                <li key={r.id} className="text-[12px] leading-snug text-ink-2">
                  <a href={r.pdf_url ?? undefined} target="_blank" rel="noreferrer">
                    {r.title}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="mt-2 flex min-h-9 items-center gap-4 text-[13px] text-ink-2">
        {hasEvidence && label && (
          <button onClick={() => { setOpen(!open); read?.onOpen(); }} aria-expanded={open} className="inline-flex h-9 shrink-0 items-center gap-1 font-medium">
            {open ? "Hide" : label}
            <ChevronDown size={14} className={clsx("transition-transform", open && "rotate-180")} />
          </button>
        )}
        {card.pdf_url && (
          <a href={card.pdf_url} target="_blank" rel="noreferrer" onClick={read?.onOpen} className="inline-flex h-9 shrink-0 items-center gap-1 active:opacity-70">
            <FileText size={14} /> Filing
          </a>
        )}
        <ShareButton build={() => shareCard(card)} />
        <NextAction card={card} onOpen={read?.onOpen} />
      </div>
    </article>
  );
}

/** A card as plain text for WhatsApp or mail: what happened, why it matters, the source. */
function shareCard(card: Card) {
  const head = [shortName(card.company), CATEGORY_LABEL[card.category] ?? card.category, card.level === "important" && "Important"]
    .filter(Boolean)
    .join(" · ");
  const r = card.results;
  const nums = r?.rows
    .filter((x) => x.value != null && (x.metric === "revenue" || x.metric === "pat"))
    .map((x) => `${x.metric === "revenue" ? r.revenue_label : "PAT"} ${crore(x.value)}${x.yoy != null ? ` (${pct(x.yoy)} YoY)` : ""}`)
    .join(", ");
  return {
    title: head,
    lines: [
      `${head}, ${day(card.ts)}`,
      (r && resultsTakeaway(r)) ?? card.title,
      card.level_reason && `Why it matters: ${card.level_reason}`,
      nums && r && `${fq(r.period)}: ${nums}`,
      card.pdf_url && `Filing: ${card.pdf_url}`,
      "Shared from FINN",
    ],
  };
}

/** The moves of one session: the most recent day with a price or volume alert. Volume and
 * price from different days are never shown side by side. */
export function sessionMoves(alerts: Alert[]): Alert[] {
  const moves = alerts.filter((a) => a.kind !== "category");
  if (!moves.length) return [];
  const last = moves.reduce((d, a) => (a.ts.slice(0, 10) > d ? a.ts.slice(0, 10) : d), "");
  const seen = new Map<string, Alert>();
  for (const a of moves) if (a.ts.startsWith(last) && !seen.has(a.kind)) seen.set(a.kind, a);
  return [...seen.values()];
}

const METRIC_LABEL: Record<string, string> = { ebitda: "EBITDA", pbt: "PBT", pat: "PAT" };

function Delta({ v, note }: { v: number | null; note?: string | null }) {
  // Off a loss or zero base there is no meaningful %: say what happened instead (PU-8)
  if (v == null && note)
    return <span className={/profitable|narrowed|break-even|up from/.test(note) ? "text-good" : "text-bad"}>{note}</span>;
  if (v == null) return <span className="text-ink-3">—</span>;
  return <span className={v >= 0 ? "text-good" : "text-bad"}>{pct(v)}</span>;
}

export function ResultsTable({ r }: { r: ResultsCard }) {
  const rows = r.rows.filter((x) => x.value != null);
  return (
    <div>
      <table className="tnum w-full text-[13px]">
        <caption className="sr-only">Quarterly results, {r.unit}</caption>
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-ink-3">
            <th className="pb-1 font-medium">{fq(r.period)}</th>
            <th className="pb-1 text-right font-medium">Value</th>
            <th className="pb-1 text-right font-medium">QoQ</th>
            <th className="pb-1 text-right font-medium">YoY</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((x) => (
            <tr key={x.metric} className="border-t border-line">
              <td className="py-1.5 text-ink-2">{x.metric === "revenue" ? r.revenue_label : METRIC_LABEL[x.metric]}</td>
              <td className="py-1.5 text-right font-medium">{crore(x.value)}</td>
              <td className="py-1.5 text-right">
                <Delta v={x.qoq} note={x.qoq_note} />
              </td>
              <td className="py-1.5 text-right">
                <Delta v={x.yoy} note={x.yoy_note} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1.5 text-[11px] text-ink-3">
        {r.ebitda_margin != null && <>EBITDA margin {r.ebitda_margin}% · </>}
        {r.basis}
        {(r.cross_check.status !== "unavailable" || r.source.startsWith("screener")) && " · "}
        {r.cross_check.status === "match" ? (
          <span className="text-good">✓ matches screener.in</span>
        ) : r.cross_check.status === "pat_basis" ? (
          <span className="text-ink-2">
            ✓ revenue and PBT match screener.in; PAT {(r.cross_check.diffs?.pat ?? 0).toFixed(1)}% (owners&apos; share vs
            total)
          </span>
        ) : r.cross_check.status === "differs" ? (
          <span className="text-warn">
            ≠ screener on{" "}
            {Object.entries(r.cross_check.diffs ?? {})
              .filter(([, d]) => Math.abs(d) > 1)
              .map(([k, d]) => `${k.toUpperCase()} ${d.toFixed(1)}%`)
              .join(", ")}
          </span>
        ) : r.source.startsWith("screener") ? (
          <span>from screener.in (filing not parsed)</span>
        ) : null}
      </p>
      {!r.source.startsWith("screener") && (
        <div className="mt-1">
          <AiTag from="figures read from the results filing; % changes computed" />
        </div>
      )}
    </div>
  );
}

function PersonBlock({ p }: { p: CardPerson }) {
  const tone = p.direction === "incoming" ? "accent" : "neutral";
  const background = [...p.prior.slice(0, 3).map((x) => `ex-${shortName(x)}`), ...p.education.slice(0, 2)];
  return (
    <div className="rounded-xl bg-bg p-3">
      <div className="flex items-center gap-2">
        <Pill tone={tone}>{p.direction === "reappointed" ? "Re-appointed" : p.direction === "incoming" ? "Incoming" : "Outgoing"}</Pill>
        {p.id ? (
          <Link href={`/people/${p.id}`} className="truncate text-[14px] font-semibold">
            {p.name}
          </Link>
        ) : (
          <span className="truncate text-[14px] font-semibold">{p.name}</span>
        )}
      </div>
      <p className="mt-1 text-[12px] text-ink-2">{p.role}</p>
      {p.bio && <p className="mt-1.5 line-clamp-3 text-[13px] leading-snug">{p.bio}</p>}
      {background.length > 0 && <p className="mt-1.5 text-[12px] text-ink-3">{background.join(" · ")}</p>}
      <div className="mt-2.5 border-t border-line pt-2.5">
        <PathView paths={p.paths} compact />
      </div>
      <div className="mt-2">
        {p.source.includes("AI") ? (
          <AiTag from="bio read from the filing" />
        ) : (
          <span className="text-[11px] text-ink-3">From the filing, checked by hand</span>
        )}
      </div>
    </div>
  );
}

export function FeedCard({
  card,
  now,
  showHelper = true,
  read,
  openEvidence,
}: {
  card: Card;
  now: string;
  showHelper?: boolean;
  read?: CardRead;
  openEvidence?: boolean;
}) {
  const best = showHelper ? card.helpers[0] : undefined;
  const evidence =
    card.kind === "results" && card.results ? (
      <ResultsTable r={card.results} />
    ) : card.kind === "management_change" && card.people?.length ? (
      <>
        {sortPeople(card.people)
          .slice(0, 3)
          .map((p) => (
            <PersonBlock key={`${p.name}-${p.direction}`} p={p} />
          ))}
      </>
    ) : null;
  const helper =
    best && (card.kind !== "filing" || best.score >= 0.5) ? (
      <HelperLine helper={best} verb="Ask" topic={card.line ?? card.title} />
    ) : null;
  return <CardShell card={card} now={now} read={read} evidence={evidence} helper={helper} openEvidence={openEvidence} />;
}

/** A Know item: one line, opened into the full card. */
export function NoteRow({ card, now, read, showHelper }: { card: Card; now: string; read?: CardRead; showHelper?: boolean }) {
  const [open, setOpen] = useState(false);
  if (open)
    return (
      <div className="py-2">
        <FeedCard card={card} now={now} read={read} showHelper={showHelper} openEvidence />
        <button onClick={() => setOpen(false)} className="mx-3 mt-1 h-9 px-1 text-[13px] font-medium text-ink-2">
          Fold it back
        </button>
      </div>
    );
  return (
    <button
      onClick={() => {
        setOpen(true);
        read?.onOpen();
      }}
      data-tour="row"
      className="flex w-full items-start gap-3 px-4 py-3 text-left active:bg-surface-2"
    >
      <span className="min-w-0 flex-1 text-[14px] leading-snug text-ink">
        {read?.isNew && <span className="mr-1.5 inline-block h-1.5 w-1.5 -translate-y-0.5 rounded-full bg-accent" aria-label="new" />}
        {card.line ?? card.title}
        <span className="mt-0.5 block text-[12px] text-ink-3">
          {CATEGORY_LABEL[card.category] ?? card.category} · {ago(card.ts, now)} ago
          {card.in_portfolio && card.weight != null ? ` · ${card.weight < 1 ? card.weight.toFixed(1) : Math.round(card.weight)}% of your portfolio` : " · you follow it"}
        </span>
      </span>
      <ChevronDown size={15} className="mt-1 shrink-0 text-ink-3" />
    </button>
  );
}

function sortPeople(ps: CardPerson[]) {
  const order: Record<string, number> = { incoming: 0, reappointed: 1, outgoing: 2 };
  return [...ps].sort((a, b) => (order[a.direction] ?? 3) - (order[b.direction] ?? 3));
}
