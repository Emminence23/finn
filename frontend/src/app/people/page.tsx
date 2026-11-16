"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { Search } from "lucide-react";
import { useSWRConfig } from "swr";
import { type Account, type Contact, type Nudge, api, getAccount, setAccount, useApi } from "@/lib/api";
import { firstName } from "@/components/network";
import { Avatar, Header, Panel, SectionTitle, Segmented, Skeleton } from "@/components/ui";

const ACCOUNTS = [
  { value: "demo", label: "Your network" },
  { value: "demo2", label: "Second investor" },
];

/** N-7, shown not claimed: switch to a second demo investor and every list, path and
 *  "who can help" changes, because each account only ever sees its own contacts. */
function AccountSwitch() {
  const { mutate } = useSWRConfig();
  const [acct, setAcct] = useState("demo");
  useEffect(() => setAcct(getAccount()), []); // after hydration: storage is client-only
  const { data } = useApi<Account>("/people/account");
  const choose = (v: string) => {
    setAccount(v);
    setAcct(v);
    mutate(() => true, undefined, { revalidate: true }); // drop every cached view
  };
  return (
    <div className="px-4">
      <Segmented label="Demo account" value={acct} options={ACCOUNTS} onChange={choose} />
      <p className="mt-1.5 text-[11px] leading-snug text-ink-3">
        {data && data.account === acct ? `${data.contacts} contacts. ` : ""}
        Each account sees only its own contacts. People named in public filings are shared.
      </p>
    </div>
  );
}

function ResetNetwork() {
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  return (
    <button
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        await api("/people/reset", { method: "POST" }).catch(() => null);
        await mutate(() => true, undefined, { revalidate: true });
        setBusy(false);
      }}
      className="mx-auto mt-1 block text-[12px] font-medium text-accent disabled:opacity-50"
    >
      {busy ? "Restoring…" : "Restore the demo network"}
    </button>
  );
}

type Expertise = { theme: string; contacts: { contact: Contact; themes: string[]; score: number }[] };

export default function PeoplePage() {
  return (
    <Suspense>
      <People />
    </Suspense>
  );
}

function People() {
  const router = useRouter();
  const params = useSearchParams();
  const theme = params.get("theme");
  const [q, setQ] = useState("");
  const { data: people } = useApi<Contact[]>("/people");
  const { data: nudges } = useApi<{ nudges: Nudge[] }>("/people/nudges");
  const { data: experts } = useApi<Expertise>(theme ? `/people/expertise?theme=${encodeURIComponent(theme)}` : null);

  const contacts = useMemo(() => (people ?? []).filter((p) => p.is_contact), [people]);
  const themes = useMemo(() => {
    const n = new Map<string, number>();
    contacts.forEach((c) => c.themes?.forEach((t) => n.set(t, (n.get(t) ?? 0) + 1)));
    return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [contacts]);
  const shown = useMemo(() => {
    const l = q.trim().toLowerCase();
    const list = l
      ? contacts.filter((c) => [c.name, c.current, c.headline, c.context, ...(c.themes ?? [])].some((x) => x?.toLowerCase().includes(l)))
      : contacts;
    return [...list].sort((a, b) => (b.strength ?? 0) - (a.strength ?? 0));
  }, [contacts, q]);

  return (
    <main>
      <Header title="People" sub={people ? `${contacts.length} people you know, and what they know` : "Your network"} />
      <AccountSwitch />

      <SectionTitle>Who knows what</SectionTitle>
      <div className="no-scrollbar flex flex-wrap gap-1.5 px-3">
        {themes.length === 0 && <Skeleton className="h-8 w-full" />}
        {themes.map(([t, n]) => (
          <button
            key={t}
            aria-pressed={theme === t}
            onClick={() => router.replace(theme === t ? "/people" : `/people?theme=${encodeURIComponent(t)}`, { scroll: false })}
            className={clsx(
              "rounded-full border px-3 py-1 text-[13px]",
              theme === t ? "border-ink bg-ink text-surface" : "border-line bg-surface text-ink-2",
            )}
          >
            {t}
            <span className={clsx("tnum ml-1 text-[11px]", theme === t ? "text-surface/70" : "text-ink-3")}>{n}</span>
          </button>
        ))}
      </div>
      {theme && (
        <Panel className="mt-3 divide-y divide-line">
          <p className="px-4 pb-2 pt-3 text-[12px] text-ink-3">Your go-to people for {theme}</p>
          {!experts ? (
            <Skeleton className="m-4 h-16" />
          ) : (
            experts.contacts.map((e) => <ContactRow key={e.contact.id} c={e.contact} />)
          )}
        </Panel>
      )}

      {nudges && nudges.nudges.length > 0 && (
        <>
          <SectionTitle>Worth a call this week</SectionTitle>
          <Panel className="divide-y divide-line">
            {nudges.nudges.slice(0, 4).map((n) => (
              <Link key={n.contact.id} href={`/people/${n.contact.id}`} className="flex gap-3 p-3 active:opacity-80">
                <Avatar name={n.contact.name} size={34} />
                <div className="min-w-0 text-[13px] leading-snug">
                  <p className="font-semibold">{firstName(n.contact.name)}</p>
                  <p className="text-ink-2">{n.reason}</p>
                </div>
              </Link>
            ))}
          </Panel>
        </>
      )}

      <SectionTitle aside="closest first">Everyone</SectionTitle>
      <div className="px-3">
        <label className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 focus-within:border-accent">
          <Search size={16} className="text-ink-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Name, company or theme"
            className="w-full bg-transparent text-[15px] outline-none placeholder:text-ink-3"
            aria-label="Filter your network"
          />
        </label>
      </div>
      <Panel className="mt-2 divide-y divide-line">
        {!people ? (
          <Skeleton className="m-4 h-40" />
        ) : shown.length === 0 ? (
          <p className="p-4 text-[13px] text-ink-3">No one matches “{q}”.</p>
        ) : (
          shown.map((c) => <ContactRow key={c.id} c={c} />)
        )}
      </Panel>
      <p className="px-6 pb-2 pt-4 text-center text-[11px] leading-snug text-ink-3">
        Your network stays private to you. It is never sent to an AI model.
      </p>
      <div className="pb-8">
        <ResetNetwork />
      </div>
    </main>
  );
}

function ContactRow({ c }: { c: Contact }) {
  return (
    <Link href={`/people/${c.id}`} className="flex items-center gap-3 px-4 py-2.5 active:bg-surface-2">
      <Avatar name={c.name} size={34} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-medium">{c.name}</p>
        <p className="truncate text-[12px] text-ink-3">{c.current ?? c.headline}</p>
      </div>
      {c.relationship && <span className="shrink-0 text-[11px] text-ink-3">{c.relationship}</span>}
    </Link>
  );
}
