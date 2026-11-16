"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { type PersonProfile, api, useApi } from "@/lib/api";
import { day } from "@/lib/fmt";
import { InsiderNote, PathView, ReachButtons, firstName } from "@/components/network";
import { Listen } from "@/components/Listen";
import { PlanMeeting } from "@/components/meetings";
import { Avatar, ErrorNote, Panel, Pill, SectionTitle, Skeleton } from "@/components/ui";

export default function PersonPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: p, error, mutate } = useApi<PersonProfile>(`/people/${id}`);

  return (
    <main>
      <div className="px-3 pt-[calc(12px+env(safe-area-inset-top))]">
        <button onClick={() => router.back()} aria-label="Back" className="rounded-full p-2 text-ink-2 active:bg-surface-2">
          <ArrowLeft size={19} />
        </button>
      </div>
      {error && !p ? (
        <ErrorNote error={error} retry={() => mutate()} />
      ) : !p ? (
        <div className="space-y-3 px-4">
          <Skeleton className="h-16 w-16 rounded-full" />
          <Skeleton className="h-7 w-2/3" />
          <Skeleton className="h-28" />
        </div>
      ) : (
        <Profile p={p} />
      )}
    </main>
  );
}

function Profile({ p }: { p: PersonProfile }) {
  const first = firstName(p.name);
  const rel = p.relationship;
  return (
    <div>
      <header className="flex items-center gap-4 px-4 pb-2">
        <Avatar name={p.name} size={56} muted={!p.is_contact} />
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.02em]">{p.name}</h1>
          <p className="text-[13px] leading-snug text-ink-2">{p.current ?? p.headline}</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {p.is_contact ? (
              <Pill tone="accent">{rel?.type ?? "contact"}</Pill>
            ) : (
              <Pill>From an exchange filing</Pill>
            )}
            {rel?.last_contact && <Pill>last spoke {day(rel.last_contact)}</Pill>}
          </div>
        </div>
      </header>

      {rel?.context && (
        <p className="mx-4 mt-2 rounded-xl bg-surface-2 px-3 py-2 text-[13px] leading-snug text-ink-2">{rel.context}</p>
      )}
      {(rel?.email || rel?.phone) && (
        <div className="flex flex-wrap gap-2 px-4 pt-3">
          <ReachButtons
            contact={{ id: p.id, name: p.name, headline: p.headline, current: p.current, is_contact: p.is_contact, email: rel.email, phone: rel.phone }}
            subject="Catching up"
            body={`Hi ${first},\n\n`}
          />
        </div>
      )}
      {p.bio && <p className="px-4 pt-3 text-[14px] leading-relaxed">{p.bio}</p>}
      <Listen lines={personScript(p)} className="mx-4 mt-3" />

      {p.can_help_on && p.can_help_on.length > 0 && (
        <>
          <SectionTitle>Ask {first} about</SectionTitle>
          <Panel className="divide-y divide-line">
            {p.can_help_on.slice(0, 5).map((c) => (
              <Link key={c.symbol} href={`/c/${c.symbol}`} className="block px-4 py-2.5 active:bg-surface-2">
                <span className="text-[14px] font-semibold">{c.symbol}</span>
                {c.rank === 1 && <span className="ml-2 text-[11px] font-medium text-good">your best person</span>}
                <span className="block text-[12px] leading-snug text-ink-2">{c.why}</span>
              </Link>
            ))}
          </Panel>
        </>
      )}

      {p.knows && p.knows.length > 0 && (
        <>
          <SectionTitle>Can introduce you to</SectionTitle>
          <Panel className="divide-y divide-line">
            {p.knows.map((k) => (
              <Link key={k.person.id} href={`/people/${k.person.id}`} className="flex items-center gap-3 px-4 py-2.5 active:bg-surface-2">
                <Avatar name={k.person.name} size={30} muted />
                <span className="min-w-0">
                  <span className="block text-[14px] font-medium">{k.person.name}</span>
                  <span className="block text-[12px] leading-snug text-ink-3">{k.context ?? k.person.current}</span>
                </span>
              </Link>
            ))}
          </Panel>
        </>
      )}

      {!p.is_contact && p.paths && (
        <>
          <SectionTitle>How you reach {first}</SectionTitle>
          <Panel className="p-4">
            <PathView paths={p.paths} />
          </Panel>
        </>
      )}

      {p.overlaps_with_you.length > 0 && (
        <>
          <SectionTitle>You and {first}</SectionTitle>
          <Panel className="space-y-1.5 p-4">
            {p.overlaps_with_you.map((o, i) => (
              <p key={i} className="text-[13px] leading-snug">
                {o.detail}
                <span className="text-ink-3">
                  {" "}
                  · inferred, {o.confidence === "confirmed" ? "years overlap" : "years unknown"}
                </span>
              </p>
            ))}
          </Panel>
        </>
      )}

      <PlanMeeting personId={p.id} first={first} />
      <MeetingQuestions id={p.id} first={first} />

      <SectionTitle>Career</SectionTitle>
      <Panel className="p-4">
        <ol className="relative space-y-3 border-l border-line pl-4">
          {[...p.roles]
            .sort((a, b) => (b.end ?? 9999) - (a.end ?? 9999) || (b.start ?? 0) - (a.start ?? 0))
            .map((r, i) => (
              <li key={i} className="relative">
                <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-ink-3" aria-hidden />
                <p className="text-[14px] font-medium leading-snug">
                  {r.symbol ? (
                    <Link href={`/c/${r.symbol}`} className="text-accent">
                      {r.company}
                    </Link>
                  ) : (
                    r.company
                  )}
                </p>
                {r.title && <p className="text-[12px] leading-snug text-ink-2">{r.title}</p>}
                <p className="tnum text-[11px] text-ink-3">{r.span}</p>
              </li>
            ))}
        </ol>
        {p.education.length > 0 && (
          <div className="mt-4 border-t border-line pt-3">
            {p.education.map((e, i) => (
              <p key={i} className="text-[13px] leading-snug">
                {e.school}
                {e.program && <span className="text-ink-2"> · {e.program}</span>}
                {e.start && (
                  <span className="tnum text-[11px] text-ink-3">
                    {" "}
                    · {e.start}–{e.end ?? ""}
                  </span>
                )}
              </p>
            ))}
          </div>
        )}
      </Panel>

      {p.themes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pt-4">
          {p.themes.map((t) => (
            <Link key={t} href={`/people?theme=${encodeURIComponent(t)}`} className="rounded-full border border-line px-2.5 py-0.5 text-[12px] text-ink-2">
              {t}
            </Link>
          ))}
        </div>
      )}
      {p.is_contact && <RemoveContact id={p.id} name={first} />}
      <p className="px-6 pb-8 pt-3 text-center text-[11px] leading-snug text-ink-3">
        {p.is_contact
          ? "Private to you. Built from what you told FINN."
          : "Built only from the brief profile in the company's filing. Deleted 90 days after the event."}
      </p>
    </div>
  );
}

/** N-7: the investor can remove anyone. Their paths, overlaps, "who can help" and nudges go
 *  with them, because all of those are computed from the stored contact on every read. */
/** Before a call, in the car: who they are, how you know them, what to ask them about. */
function personScript(p: PersonProfile): string[] {
  const first = firstName(p.name);
  const rel = p.relationship;
  const out = [`${p.name}${p.current ?? p.headline ? `, ${p.current ?? p.headline}` : ""}.`];
  if (rel?.context) out.push(rel.context.endsWith(".") ? rel.context : `${rel.context}.`);
  if (rel?.last_contact) out.push(`You last spoke on ${day(rel.last_contact)}.`);
  const help = (p.can_help_on ?? []).slice(0, 3);
  if (help.length) out.push(`Ask ${first} about ${help.map((c) => c.symbol).join(", ")}.`, ...help.map((c) => `${c.symbol}: ${c.why}`));
  return out;
}

function RemoveContact({ id, name }: { id: string; name: string }) {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  return (
    <div className="px-4 pt-6 text-center">
      <button
        disabled={busy}
        onClick={async () => {
          if (!window.confirm(`Remove ${name} from your network? Every link through them goes too.`)) return;
          setBusy(true);
          try {
            await api(`/people/${id}`, { method: "DELETE" });
            await mutate(() => true, undefined, { revalidate: true });
            router.push("/people");
          } catch {
            setBusy(false);
          }
        }}
        className="rounded-full border border-line px-4 py-2 text-[13px] text-bad disabled:opacity-50"
      >
        {busy ? "Removing…" : "Remove from my network"}
      </button>
    </div>
  );
}

type QGroup = {
  symbol: string;
  company: string;
  relation: "current" | "former" | "peer";
  insider: boolean;
  questions: {
    question: string;
    basis: { kind: "promise" | "flag"; said_in?: string; doc_id?: string; page?: number; outcome?: string };
  }[];
};

const RELATION: Record<QGroup["relation"], string> = {
  current: "works there now",
  former: "worked there",
  peer: "knows the industry",
};

/** Questions worth asking before a meeting: built in code from FINN's research on companies
 *  this person knows, each showing what it rests on. No AI, and nothing about the person is
 *  sent anywhere. */
function MeetingQuestions({ id, first }: { id: string; first: string }) {
  const { data } = useApi<{ groups: QGroup[] }>(`/people/${id}/questions`);
  if (!data?.groups.length) return null;
  return (
    <>
      <SectionTitle aside="from FINN's research">Before you meet {first}</SectionTitle>
      <Panel className="divide-y divide-line">
        {data.groups.map((g) => (
          <div key={g.symbol} className="px-4 py-3">
            <p className="text-[12px] text-ink-3">
              <Link href={`/c/${g.symbol}#promises`} className="font-semibold text-ink">
                {g.company.replace(/ (Limited|Ltd)$/, "")}
              </Link>{" "}
              · {first} {RELATION[g.relation]}
            </p>
            {g.insider && <InsiderNote />}
            <ol className="mt-2 space-y-2.5">
              {g.questions.map((q, i) => (
                <li key={i} className="text-[14px] leading-snug">
                  {q.question}
                  <span className="mt-0.5 block text-[11px] text-ink-3">
                    {q.basis.kind === "promise"
                      ? `${q.basis.said_in}${q.basis.page ? `, p.${q.basis.page}` : ""}${q.basis.outcome ? ` · ${q.basis.outcome}` : ""}`
                      : "Computed from reported financials"}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </Panel>
    </>
  );
}
