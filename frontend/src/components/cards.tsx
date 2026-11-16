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
      {a.kind === "volume" ? `Vol ${a.value.toFixed(1)}× avg` : `${pct(a.value)} day`}
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

function CardShell({ card, now, read, children }: { card: Card; now: string; read?: CardRead; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const moves = dedupeMoves(card.alerts);
  return (
    <article
      className={clsx(
        "mx-3 rounded-2xl border border-line bg-surface p-4 transition-opacity",
        read?.opened && "opacity-60",
      )}
    >
      <div className="flex items-center gap-2">
        <Link href={`/c/${card.symbol}`} className="min-w-0 truncate text-[15px] font-semibold active:opacity-70">
          {shortName(card.company)}
        </Link>
        {card.unsure ? (
          <Pill tone="warn">Unclassified</Pill>
        ) : (
          <Pill>{CATEGORY_LABEL[card.category] ?? card.category}</Pill>
        )}
        {card.level === "important" && <Pill tone="strong">Important</Pill>}
        {!card.in_portfolio && <Pill tone="accent">Research</Pill>}
        <span className="tnum ml-auto shrink-0 text-[12px] text-ink-3">
          {read?.isNew ? (
            <span className="mr-1.5 inline-flex items-center gap-1 font-semibold text-accent">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
              New
            </span>
          ) : read?.opened ? (
            <span className="mr-1.5">Opened ·</span>
          ) : null}
          {ago(card.ts, now)}
        </span>
      </div>
      <p className="mt-1.5 text-[14px] leading-snug text-ink">
        {(card.results && resultsTakeaway(card.results)) ?? card.title}
      </p>
      {card.level_reason && (
        <p className="mt-1 text-[12px] leading-snug text-ink-3">
          <span className="sr-only">{card.level === "important" ? "Important" : "Notable"} because: </span>
          {card.level_reason}
        </p>
      )}
      {moves.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {moves.map((a) => (
            <AlertChip key={a.id} a={a} />
          ))}
        </div>
      )}
      <div className="mt-3 space-y-3">{children}</div>
      <div className="mt-3 flex items-center gap-3 text-[12px] text-ink-3">
        {card.pdf_url && (
          <a href={card.pdf_url} target="_blank" rel="noreferrer" onClick={read?.onOpen} className="inline-flex shrink-0 items-center gap-1 active:opacity-70">
            <FileText size={13} /> Filing
          </a>
        )}
        {card.related.length > 0 && (
          <button onClick={() => setOpen(!open)} className="inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap" aria-expanded={open}>
            {card.related.length} related
            <ChevronDown size={13} className={clsx("transition-transform", open && "rotate-180")} />
          </button>
        )}
        <ShareButton build={() => shareCard(card)} />
        <NextAction card={card} onOpen={read?.onOpen} />
      </div>
      {open && (
        <ul className="mt-2 space-y-1.5 border-t border-line pt-2">
          {card.related.map((r) => (
            <li key={r.id} className="text-[12px] leading-snug text-ink-2">
              <a href={r.pdf_url ?? undefined} target="_blank" rel="noreferrer">
                {r.title}
              </a>
            </li>
          ))}
        </ul>
      )}
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

/** One chip per (kind) with the most recent move: the feed is not a price ticker. */
function dedupeMoves(alerts: Alert[]): Alert[] {
  const seen = new Map<string, Alert>();
  for (const a of alerts) if (a.kind !== "category" && !seen.has(a.kind)) seen.set(a.kind, a);
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
}: {
  card: Card;
  now: string;
  showHelper?: boolean;
  read?: CardRead;
}) {
  const best = showHelper ? card.helpers[0] : undefined;
  return (
    <CardShell card={card} now={now} read={read}>
      {card.kind === "results" && card.results && <ResultsTable r={card.results} />}
      {card.kind === "management_change" &&
        sortPeople(card.people ?? [])
          .slice(0, 3)
          .map((p) => <PersonBlock key={`${p.name}-${p.direction}`} p={p} />)}
      {best && (card.kind !== "filing" || best.score >= 0.5) && (
        <HelperLine helper={best} verb={card.kind === "material_event" ? "Call" : "Ask"} />
      )}
    </CardShell>
  );
}

function sortPeople(ps: CardPerson[]) {
  const order: Record<string, number> = { incoming: 0, reappointed: 1, outgoing: 2 };
  return [...ps].sort((a, b) => (order[a.direction] ?? 3) - (order[b.direction] ?? 3));
}
