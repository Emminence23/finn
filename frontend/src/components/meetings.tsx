"use client";

import Link from "next/link";
import { useState } from "react";
import { CalendarClock, X } from "lucide-react";
import { api, useApi } from "@/lib/api";
import { shortName } from "@/lib/fmt";
import { firstName } from "./network";

type Meeting = { id: number; day: string; when: string; note: string | null; person: { id: string; name: string } };
type Prep = Meeting & {
  companies: { symbol: string; relation: string }[];
  changed: { symbol: string; company: string; title: string; level: string }[];
  questions: string[];
};

/** On a person's page: note an upcoming meeting. Private to you; nothing goes to the AI. */
export function PlanMeeting({ personId, first }: { personId: string; first: string }) {
  const { data, mutate } = useApi<{ today: string; meetings: Meeting[] }>("/people/meetings");
  const [day, setDay] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (!data) return null;
  const mine = data.meetings.filter((m) => m.person.id === personId);
  const add = async () => {
    setErr(null);
    try {
      await api("/people/meetings", { method: "POST", body: JSON.stringify({ person: personId, day, note }) });
      setDay("");
      setNote("");
      await mutate();
    } catch {
      setErr("Pick today or a later date.");
    }
  };
  return (
    <div data-tour="meeting" className="mx-3 mt-3 rounded-2xl border border-line bg-surface p-3">
      <p className="flex items-center gap-1.5 text-[13px] font-medium">
        <CalendarClock size={15} className="text-accent" /> Meeting {first} soon?
      </p>
      {mine.map((m) => (
        <p key={m.id} className="mt-1.5 flex items-center gap-2 text-[13px] text-ink-2">
          <span className="font-medium text-ink">{m.when[0].toUpperCase() + m.when.slice(1)}</span>
          {m.note && <span className="truncate">· {m.note}</span>}
          <button
            aria-label="Remove meeting"
            onClick={async () => {
              await api(`/people/meetings/${m.id}`, { method: "DELETE" }).catch(() => null);
              await mutate();
            }}
            className="ml-auto p-1 text-ink-3"
          >
            <X size={14} />
          </button>
        </p>
      ))}
      <div className="mt-2 flex gap-1.5">
        <input
          type="date"
          aria-label="Meeting date"
          min={data.today}
          value={day}
          onChange={(e) => setDay(e.target.value)}
          className="min-w-0 flex-none rounded-lg border border-line bg-surface px-2 py-1.5 text-[13px]"
        />
        <input
          aria-label="What it's about"
          placeholder="About (optional)"
          maxLength={200}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[13px] outline-none placeholder:text-ink-3 focus:border-accent"
        />
        <button disabled={!day} onClick={add} className="shrink-0 rounded-full bg-ink px-3.5 text-[13px] font-medium text-bg disabled:opacity-40">
          Add
        </button>
      </div>
      <p className="mt-1.5 text-[11px] text-ink-3">
        {err ?? "Today will open with a prep card from two days before."}
      </p>
    </div>
  );
}

/** Top of Today: prep for meetings in the next two days. */
export function MeetingPrep() {
  const { data } = useApi<{ prep: Prep[] }>("/people/meetings/prep");
  if (!data?.prep.length) return null;
  return (
    <div className="mt-3 space-y-2">
      {data.prep.map((m) => {
        const first = firstName(m.person.name);
        return (
          <article key={m.id} className="mx-3 rounded-2xl border border-accent/40 bg-accent-soft/40 p-4">
            <p className="flex items-center gap-1.5 text-[13px] font-semibold text-accent">
              <CalendarClock size={15} /> Meeting {first} {m.when}
              {m.note && <span className="truncate font-normal text-ink-2">· {m.note}</span>}
            </p>
            {m.changed.length > 0 ? (
              <>
                <p className="mt-2 text-[12px] text-ink-3">What changed at companies {first} knows, last 30 days</p>
                <ul className="mt-1 space-y-1 text-[13px] leading-snug">
                  {m.changed.map((c, i) => (
                    <li key={i}>
                      <Link href={`/c/${c.symbol}`} className="font-semibold">
                        {shortName(c.company)}
                      </Link>{" "}
                      {c.title}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="mt-2 text-[13px] text-ink-2">Nothing material at the companies {first} knows in the last 30 days.</p>
            )}
            {m.questions.length > 0 && (
              <>
                <p className="mt-2.5 text-[12px] text-ink-3">Worth asking</p>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-[13px] leading-snug">
                  {m.questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              </>
            )}
            <Link href={`/people/${m.person.id}`} className="mt-2.5 block text-right text-[12px] font-medium text-accent">
              Full prep →
            </Link>
          </article>
        );
      })}
    </div>
  );
}
