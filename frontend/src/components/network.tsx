"use client";

import Link from "next/link";
import { ArrowRight, Phone } from "lucide-react";
import clsx from "clsx";
import type { Helper, Link as NetLink, Paths } from "@/lib/api";
import { Avatar } from "./ui";

export function firstName(name: string): string {
  const parts = name.split(/\s+/);
  return /^(Dr|Mr|Mrs|Ms)\.?$/i.test(parts[0]) ? parts.slice(0, 2).join(" ") : parts[0];
}

function strengthWord(s: number): string {
  return s >= 0.45 ? "strong link" : s >= 0.25 ? "fair link" : "weak link";
}

/** N-2: say how FINN knows a link. Declared links were recorded by the investor; inferred
 *  ones come from two career records overlapping, and say whether the years are known. */
function Confidence({ link }: { link: Pick<NetLink, "confidence" | "basis" | "kind"> }) {
  const declared = link.basis === "declared" || link.kind === "contact" || link.kind === "knows";
  if (declared) return <span className="text-good">declared</span>;
  return link.confidence === "confirmed" ? (
    <span className="text-ink-2">inferred, years overlap</span>
  ) : (
    <span className="text-ink-3">inferred, years unknown</span>
  );
}

/** N-4: a current employee can be called, but not for unpublished price-sensitive facts. */
export function InsiderNote() {
  return (
    <span className="mt-0.5 block text-[11px] font-medium text-warn">
      Works there now: keep it to public information
    </span>
  );
}

/** "Call Ritu: ran channel sales at Polycab 2014–21." One line, one person, one reason. */
export function HelperLine({ helper, verb = "Call" }: { helper: Helper; verb?: string }) {
  const c = helper.contact;
  return (
    <Link
      href={`/people/${c.id}`}
      className="flex items-start gap-2.5 rounded-xl bg-accent-soft/60 px-3 py-2.5 active:opacity-80"
    >
      <span className="mt-0.5 text-accent">
        <Phone size={15} strokeWidth={2} />
      </span>
      <span className="min-w-0 text-[13px] leading-snug">
        <span className="font-semibold text-ink">
          {verb} {firstName(c.name)}
        </span>
        <span className="text-ink-2"> · {helper.why}</span>
        {c.context && <span className="block text-[12px] text-ink-3">{c.context}</span>}
        {helper.insider && <InsiderNote />}
      </span>
    </Link>
  );
}

export function HelperList({ helpers, max = 3 }: { helpers: Helper[]; max?: number }) {
  if (!helpers.length) return <p className="text-[13px] text-ink-3">No one in your network maps to this company yet.</p>;
  return (
    <ul className="divide-y divide-line">
      {helpers.slice(0, max).map((h) => (
        <li key={h.contact.id}>
          <Link href={`/people/${h.contact.id}`} className="flex items-start gap-3 py-3 active:opacity-80">
            <Avatar name={h.contact.name} size={34} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate text-[14px] font-semibold">{h.contact.name}</p>
                <span className="tnum shrink-0 text-[11px] text-ink-3">{Math.round(h.score * 100)}</span>
              </div>
              <p className="text-[13px] leading-snug text-ink-2">{h.why}</p>
              {h.insider && <InsiderNote />}
              {h.reasons.slice(1, 3).map((r) => (
                <p key={r} className="text-[12px] leading-snug text-ink-3">
                  {r}
                </p>
              ))}
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** How the investor reaches a person: a shared past (direct) or through one contact. */
export function PathView({ paths, compact }: { paths: Paths; compact?: boolean }) {
  const { direct, via, target } = paths;
  if (!direct.length && !via.length)
    return <p className="text-[12px] text-ink-3">No path in your network yet.</p>;
  const first = firstName(target.name);
  return (
    <div className="space-y-2">
      {direct.slice(0, compact ? 1 : 3).map((l, i) => (
        <div key={`d${i}`} className="text-[13px] leading-snug">
          <span className="font-semibold">You</span>
          <span className="text-ink-2"> · {l.kind === "contact" ? `${l.detail}` : l.detail.replace(/^Both/, `You and ${first} both`)}</span>
          <span className="text-[12px]"> · <Confidence link={l} /></span>
        </div>
      ))}
      {via.slice(0, compact ? (direct.length ? 1 : 2) : 4).map((v) => (
        <div key={v.contact.id} className="text-[13px] leading-snug">
          <div className="flex flex-wrap items-center gap-1">
            <span className="font-semibold">You</span>
            <ArrowRight size={12} className="text-ink-3" />
            <Link href={`/people/${v.contact.id}`} className="font-semibold text-accent">
              {v.contact.name}
            </Link>
            <ArrowRight size={12} className="text-ink-3" />
            <span className="font-semibold">{first}</span>
            <span className={clsx("ml-1 text-[11px]", v.strength >= 0.45 ? "text-good" : "text-ink-3")}>
              {strengthWord(v.strength)}
            </span>
          </div>
          <p className="text-[12px] text-ink-2">
            {v.link.detail} · <Confidence link={v.link} />
            {v.other_links[0] && <span className="text-ink-3"> · also: {v.other_links[0].detail}</span>}
          </p>
        </div>
      ))}
    </div>
  );
}
