"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { ArrowLeft, Search } from "lucide-react";
import { useSWRConfig } from "swr";
import { type Account, type Contact, type Nudge, api, getAccount, getSandbox, setAccount, useApi } from "@/lib/api";
import { firstName } from "@/components/network";
import { Avatar, Header, Panel, SectionTitle, Segmented, Skeleton } from "@/components/ui";
import { useTitle } from "@/lib/title";

const ACCOUNTS = [
  { value: "demo", label: "Demo" },
  { value: "demo2", label: "Second investor" },
  { value: "mine", label: "Yours" },
];

/** N-7, shown not claimed: switch to a second demo investor and every list, path and
 *  "who can help" changes, because each account only ever sees its own contacts. */
function AccountSwitch() {
  const { mutate } = useSWRConfig();
  const router = useRouter();
  const [acct, setAcct] = useState("demo");
  useEffect(() => setAcct(getAccount().startsWith("u_") ? "mine" : getAccount()), []); // storage is client-only
  const { data } = useApi<Account>("/people/account");
  const choose = (v: string) => {
    if (v === "mine") {
      const box = getSandbox();
      if (!box) return router.push("/people/setup");
      v = box;
    }
    setAccount(v);
    setAcct(v.startsWith("u_") ? "mine" : v);
    mutate(() => true, undefined, { revalidate: true }); // drop every cached view
  };
  const mine = acct === "mine";
  return (
    <div className="px-4">
      <Segmented label="Demo account" value={acct} options={ACCOUNTS} onChange={choose} />
      <p className="mt-1.5 text-[11px] leading-snug text-ink-3">
        {data && (data.account === acct || (mine && data.account.startsWith("u_"))) ? `${data.contacts} contacts. ` : ""}
        Each account sees only its own contacts. People named in public filings are shared.{" "}
        {mine ? (
          <Link href="/people/setup" className="font-medium text-accent">
            Edit your network
          </Link>
        ) : (
          <Link href="/people/setup" className="font-medium text-accent">
            Try it with your own
          </Link>
        )}
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
  useTitle("Your network");
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

  const [allThemes, setAllThemes] = useState(false);
  const themeChips = allThemes ? themes : themes.slice(0, 8);

  return (
    <main>
      <div className="flex items-center gap-2 px-3 pt-[calc(12px+env(safe-area-inset-top))]">
        <Link href="/ask" aria-label="Back" className="rounded-full p-2 text-ink-2 active:bg-surface-2">
          <ArrowLeft size={19} />
        </Link>
      </div>
      <Header title="Your network" sub={people ? `${contacts.length} people you know, and what they know` : "People you know"} />
      <div className="px-3">
        <label className="flex items-center gap-2 rounded-2xl border border-line bg-surface px-3.5 py-3 focus-within:border-accent">
          <Search size={17} className="text-ink-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Name, company or what they know"
            className="w-full bg-transparent text-[16px] outline-none placeholder:text-ink-3"
            aria-label="Search your network"
          />
        </label>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {themes.length === 0 && <Skeleton className="h-8 w-full" />}
          {themeChips.map(([th, n]) => (
            <button
              key={th}
              aria-pressed={theme === th}
              onClick={() => router.replace(theme === th ? "/people" : `/people?theme=${encodeURIComponent(th)}`, { scroll: false })}
              className={clsx(
                "min-h-8 rounded-full border px-3 py-1 text-[13px]",
                theme === th ? "border-ink bg-ink text-surface" : "border-line bg-surface text-ink-2",
              )}
            >
              {th}
              <span className={clsx("tnum ml-1 text-[11px]", theme === th ? "text-surface/70" : "text-ink-3")}>{n}</span>
            </button>
          ))}
          {themes.length > 8 && (
            <button onClick={() => setAllThemes(!allThemes)} className="min-h-8 px-2 text-[13px] font-medium text-accent">
              {allThemes ? "Fewer" : `All ${themes.length} topics`}
            </button>
          )}
        </div>
      </div>
      {theme && (
        <Panel className="mt-3 divide-y divide-line">
          <p className="px-4 pb-2 pt-3 text-[13px] text-ink-2">Who you&apos;d ask about {theme}</p>
          {!experts ? (
            <Skeleton className="m-4 h-16" />
          ) : (
            experts.contacts.map((e) => <ContactRow key={e.contact.id} c={e.contact} />)
          )}
        </Panel>
      )}

      {!q && nudges && nudges.nudges.length > 0 && (
        <>
          <SectionTitle tour="worthcall">Worth a call this week</SectionTitle>
          <Panel className="divide-y divide-line">
            {nudges.nudges.slice(0, 4).map((n) => (
              <Link key={n.contact.id} href={`/people/${n.contact.id}`} className="flex gap-3 px-4 py-3 active:opacity-80">
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

      <SectionTitle aside="closest first">{q ? `Matching “${q}”` : "Everyone"}</SectionTitle>
      <Panel className="divide-y divide-line">
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
      <SectionTitle tour="whose">Whose network</SectionTitle>
      <AccountSwitch />
      <div className="pb-8 pt-3">
        <ResetNetwork />
      </div>
    </main>
  );
}

/** A person as you'd describe them: how you know them first, their job second. */
function ContactRow({ c }: { c: Contact }) {
  return (
    <Link href={`/people/${c.id}`} className="flex items-start gap-3 px-4 py-3 active:bg-surface-2">
      <Avatar name={c.name} size={34} />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-medium">{c.name}</p>
        {c.context && <p className="text-[13px] leading-snug text-ink-2">{c.context}</p>}
        <p className="truncate text-[12px] text-ink-3">
          {c.current ?? c.headline}
          {c.relationship ? ` · ${c.relationship}` : ""}
        </p>
      </div>
    </Link>
  );
}
