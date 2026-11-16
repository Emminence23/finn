"use client";

import Link from "next/link";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { ArrowRight, Mail, MessageCircle, Phone, UserRoundSearch } from "lucide-react";
import clsx from "clsx";
import { type Contact, type Helper, type Link as NetLink, type Paths, type SameName, api } from "@/lib/api";
import { Avatar } from "./ui";

export function firstName(name: string): string {
  const parts = name.split(/\s+/);
  return /^(Dr|Mr|Mrs|Ms)\.?$/i.test(parts[0]) ? parts.slice(0, 2).join(" ") : parts[0];
}

/** The fit score in words: what it means for whether to call. */
function fitWords(s: number): string {
  return s >= 0.6 ? "best placed" : s >= 0.4 ? "well placed" : "worth a try";
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

const ACT_BTN =
  "inline-flex h-9 items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-[13px] font-medium text-ink active:opacity-70";

/** Ways to reach a contact that actually reach them: call and WhatsApp when FINN has a
 *  number, email (with the questions already written) when it has an address. */
export function ReachButtons({ contact, subject, body }: { contact: Contact; subject?: string; body?: string }) {
  const tel = contact.phone?.replace(/[^\d+]/g, "");
  const mail = contact.email
    ? `mailto:${contact.email}?subject=${encodeURIComponent(subject ?? "")}&body=${encodeURIComponent(body ?? "")}`
    : null;
  return (
    <>
      {tel && (
        <a href={`tel:${tel}`} className={ACT_BTN}>
          <Phone size={14} /> Call
        </a>
      )}
      {tel && (
        <a href={`https://wa.me/${tel.replace(/^\+/, "")}?text=${encodeURIComponent(body ?? "")}`} target="_blank" rel="noreferrer" className={ACT_BTN}>
          <MessageCircle size={14} /> WhatsApp
        </a>
      )}
      {mail && (
        <a href={mail} className={ACT_BTN}>
          <Mail size={14} /> Email
        </a>
      )}
    </>
  );
}

/** "Ask Karthik · ran EMS programmes at Kaynes", the two questions worth asking, and a
 *  way to actually ask them. One person, one reason, one tap to reach them. */
export function HelperLine({ helper, verb = "Ask", topic }: { helper: Helper; verb?: string; topic?: string }) {
  const c = helper.contact;
  const first = firstName(c.name);
  const ask = helper.ask ?? [];
  const body = [
    `Hi ${first},`,
    "",
    topic ?? "",
    ...(ask.length ? ["", ask.length === 1 ? "One thing I'd value your view on:" : "Two things I'd value your view on:", ...ask.map((q, i) => `${i + 1}. ${q}`)] : []),
    "",
  ].join("\n");
  return (
    <div className="rounded-xl bg-accent-soft/60 px-3 py-2.5">
      <Link href={`/people/${c.id}`} className="flex items-start gap-2.5 active:opacity-80">
        <Avatar name={c.name} size={30} />
        <span className="min-w-0 text-[13px] leading-snug">
          <span className="font-semibold text-ink">
            {verb} {first}
          </span>
          <span className="text-ink-2"> · {helper.why}</span>
          {c.context && <span className="block text-[12px] text-ink-2">{c.context}</span>}
          {helper.insider && <InsiderNote />}
        </span>
      </Link>
      {ask.length > 0 && (
        <ul className="mt-2 space-y-1 pl-10 text-[13px] leading-snug text-ink">
          {ask.map((q) => (
            <li key={q}>“{q}”</li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex flex-wrap gap-2 pl-10">
        <ReachButtons contact={c} subject={topic} body={body} />
        <Link href={`/people/${c.id}`} className="inline-flex h-9 items-center px-1 text-[13px] font-medium text-accent">
          How you know {first} →
        </Link>
      </div>
    </div>
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
                <span className="shrink-0 text-[11px] text-ink-2" title={`fit ${Math.round(h.score * 100)} of 100: how much they know, scaled by how close you are`}>
                  {fitWords(h.score)}
                </span>
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
      <li className="pt-2 text-[11px] leading-snug text-ink-3">
        Ordered by how much they know about the company, scaled by how close you are.
      </li>
    </ul>
  );
}

/** How the investor reaches a person: a shared past (direct) or through one contact. */
/** FR-NET-05: a shared name is a question for the investor, not a fact. "Possible" when only
 *  the name matches, "likely" when an employer or school also agrees; asserted only once the
 *  investor says so, and "Not them" hides it for good. */
function SameNameNote({ m, targetId, targetName }: { m: SameName; targetId: string; targetName: string }) {
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const answerable = !targetId.startsWith("auto_");
  const answer = async (verdict: "same" | "different") => {
    setBusy(true);
    await api(`/people/${targetId}/identity`, {
      method: "PUT",
      body: JSON.stringify({ contact: m.contact.id, verdict }),
    }).catch(() => null);
    await mutate(() => true, undefined, { revalidate: true });
    setBusy(false);
  };
  if (m.status === "confirmed") return null; // shown as a direct "your contact" link instead
  return (
    <div data-tour="samename" className="flex gap-2 rounded-xl bg-surface-2 px-3 py-2 text-[12px] leading-snug">
      <UserRoundSearch size={15} className="mt-0.5 shrink-0 text-warn" />
      <div className="min-w-0">
        <p className="text-ink">
          <span className="font-semibold">{m.status === "likely" ? "Likely" : "Possible"} match:</span> your contact{" "}
          <Link href={`/people/${m.contact.id}`} className="font-medium text-accent">
            {m.contact.name}
          </Link>{" "}
          {m.status === "likely"
            ? `shares this name and ${m.agrees.join(" and ")}.`
            : `shares this name, but nothing else in the two records agrees.`}{" "}
          <span className="text-ink-3">FINN doesn&apos;t assume they are the same {targetName}.</span>
        </p>
        {answerable && (
          <div className="mt-1.5 flex gap-2">
            <button disabled={busy} onClick={() => answer("same")} className="rounded-full border border-line bg-surface px-2.5 py-0.5 font-medium disabled:opacity-50">
              Same person
            </button>
            <button disabled={busy} onClick={() => answer("different")} className="rounded-full border border-line bg-surface px-2.5 py-0.5 font-medium disabled:opacity-50">
              Not them
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function PathView({ paths, compact }: { paths: Paths; compact?: boolean }) {
  const { direct, via, target } = paths;
  const same = (paths.same_name ?? []).filter((m) => m.status !== "confirmed");
  const first = firstName(target.name);
  const notes = same.map((m) => <SameNameNote key={m.contact.id} m={m} targetId={target.id} targetName={first} />);
  if (!direct.length && !via.length)
    return (
      <div className="space-y-2">
        {notes}
        <p className="text-[12px] text-ink-3">No path in your network yet.</p>
      </div>
    );
  return (
    <div className="space-y-2">
      {notes}
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
