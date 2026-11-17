"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useSWRConfig } from "swr";
import { ArrowLeft, Lock, Plus, Upload, X } from "lucide-react";
import { api, getSandbox, setAccount, setSandbox } from "@/lib/api";
import { explainLine } from "@/lib/errors";
import { Panel, SectionTitle } from "@/components/ui";

type Row = { name: string; title: string; from: string; to: string };
const EMPTY: Row = { name: "", title: "", from: "", to: "" };
const BOX =
  "min-w-0 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[14px] outline-none placeholder:text-ink-3 focus:border-accent";
const INPUT = `${BOX} w-full flex-1`;
const YEAR = `${BOX} w-[4.5rem] flex-none`;

/** Bring your own network: a private sandbox for this browser, your own career, and the
 *  people you know, by hand or from LinkedIn's Connections.csv. Deleted after 7 days. */
export default function SetupPage() {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const [jobs, setJobs] = useState<Row[]>([{ ...EMPTY }]);
  const [schools, setSchools] = useState<Row[]>([{ ...EMPTY }]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // a returning visitor sees the career they saved, not blank rows
  useEffect(() => {
    const box = getSandbox();
    if (!box) return;
    setAccount(box);
    type Saved = {
      roles: { company: string; title: string | null; start: number | null; end: number | null }[];
      education: { school: string; program: string | null; start: number | null; end: number | null }[];
    };
    api<Saved>(`/people/${encodeURIComponent(`me@${box}`)}`)
      .then((me) => {
        const y = (v: number | null) => (v == null ? "" : String(v));
        if (me.roles.length) setJobs(me.roles.map((r) => ({ name: r.company, title: r.title ?? "", from: y(r.start), to: y(r.end) })));
        if (me.education.length)
          setSchools(me.education.map((e) => ({ name: e.school, title: e.program ?? "", from: y(e.start), to: y(e.end) })));
      })
      .catch(() => null);
  }, []);

  /** The sandbox is created on the first save, so just looking costs nothing. */
  const ensure = async (): Promise<void> => {
    let box = getSandbox();
    if (!box) {
      box = (await api<{ account: string }>("/people/mine", { method: "POST" })).account;
      setSandbox(box);
    }
    setAccount(box);
  };
  const refresh = () => mutate(() => true, undefined, { revalidate: true });

  const run = async (what: () => Promise<string>) => {
    setBusy(true);
    setMsg(null);
    try {
      await ensure();
      setMsg(await what());
      await refresh();
    } catch (e) {
      setMsg(explainLine(e));
    } finally {
      setBusy(false);
    }
  };

  const saveCareer = () =>
    run(async () => {
      const r = await api<{ roles: number; education: number }>("/people/mine/career", {
        method: "PUT",
        body: JSON.stringify({
          roles: jobs.map((j) => ({ company: j.name, title: j.title, start_year: j.from, end_year: j.to })),
          education: schools.map((s) => ({ school: s.name, program: s.title, start_year: s.from, end_year: s.to })),
        }),
      });
      return `Saved ${r.roles} employers and ${r.education} schools.`;
    });

  const upload = (file: File) =>
    run(async () => {
      const csv = await file.text();
      const r = await api<{ imported: number; skipped: number }>("/people/mine/linkedin", {
        method: "POST",
        body: JSON.stringify({ csv }),
      });
      return `Imported ${r.imported} connections${r.skipped ? ` (${r.skipped} without a company skipped)` : ""}. E-mail addresses and profile links were dropped.`;
    });

  return (
    <main className="pb-10">
      <div className="flex items-center gap-1 px-3 pt-[calc(12px+env(safe-area-inset-top))]">
        <button onClick={() => router.back()} aria-label="Back" className="rounded-full p-2 text-ink-2 active:bg-surface-2">
          <ArrowLeft size={19} />
        </button>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Your own network</h1>
      </div>
      <p className="mx-4 mt-1 flex gap-2 rounded-xl bg-surface-2 px-3 py-2 text-[12px] leading-snug text-ink-2">
        <Lock size={14} className="mt-0.5 shrink-0" />
        Private to this browser and deleted after 7 days. Only names, employers, titles and years are kept. Nothing here is sent to an AI model.
      </p>

      <SectionTitle>Where you worked</SectionTitle>
      <Rows rows={jobs} setRows={setJobs} name="Company" title="Title (optional)" />
      <SectionTitle>Where you studied</SectionTitle>
      <Rows rows={schools} setRows={setSchools} name="School" title="Programme (optional)" />
      <div className="px-4 pt-3">
        <button disabled={busy} onClick={saveCareer} className="w-full rounded-full bg-ink py-2.5 text-[14px] font-medium text-bg disabled:opacity-50">
          Save my career
        </button>
      </div>

      <SectionTitle>People you know</SectionTitle>
      <Panel className="space-y-2 p-4 text-[13px] leading-snug">
        <p className="text-ink-2">
          Fastest: your LinkedIn connections. On LinkedIn go to <b>Settings → Data privacy → Get a copy of your data → Connections</b>; the e-mail arrives in minutes. Upload the <code>Connections.csv</code> inside.
        </p>
        <label className="flex cursor-pointer items-center justify-center gap-2 rounded-full border border-line py-2.5 font-medium text-accent">
          <Upload size={15} /> Upload Connections.csv
          <input
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            disabled={busy}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload(f);
              e.target.value = "";
            }}
          />
        </label>
      </Panel>
      <AddContact busy={busy} run={run} />

      {msg && (
        <p role="status" className="mx-4 mt-3 rounded-xl bg-accent-soft/60 px-3 py-2 text-[13px] text-ink">
          {msg}
        </p>
      )}
      <div className="mt-5 flex items-center justify-between px-4">
        <DeleteMine />
        <Link href="/people" className="rounded-full bg-accent px-5 py-2 text-[14px] font-medium text-white">
          See my network →
        </Link>
      </div>
    </main>
  );
}

function Rows({ rows, setRows, name, title }: { rows: Row[]; setRows: (r: Row[]) => void; name: string; title: string }) {
  const set = (i: number, k: keyof Row, v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <Panel className="space-y-3 p-3">
      {rows.map((r, i) => (
        <div key={i} className="space-y-1.5">
          <div className="flex gap-1.5">
            <input aria-label={name} placeholder={name} value={r.name} onChange={(e) => set(i, "name", e.target.value)} className={INPUT} />
            {rows.length > 1 && (
              <button aria-label="Remove" onClick={() => setRows(rows.filter((_, j) => j !== i))} className="shrink-0 p-1 text-ink-3">
                <X size={16} />
              </button>
            )}
          </div>
          <div className="flex gap-1.5">
            <input aria-label={title} placeholder={title} value={r.title} onChange={(e) => set(i, "title", e.target.value)} className={INPUT} />
            <input aria-label="From year" placeholder="From" inputMode="numeric" maxLength={4} value={r.from} onChange={(e) => set(i, "from", e.target.value)} className={YEAR} />
            <input aria-label="To year" placeholder="To" inputMode="numeric" maxLength={4} value={r.to} onChange={(e) => set(i, "to", e.target.value)} className={YEAR} />
          </div>
        </div>
      ))}
      <button onClick={() => setRows([...rows, { ...EMPTY }])} className="flex items-center gap-1 text-[13px] font-medium text-accent">
        <Plus size={14} /> Add another
      </button>
    </Panel>
  );
}

function AddContact({ busy, run }: { busy: boolean; run: (f: () => Promise<string>) => Promise<void> }) {
  const [c, setC] = useState({ name: "", company: "", title: "", from: "", to: "", how: "", closeness: "good" });
  const set = (k: keyof typeof c) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setC({ ...c, [k]: e.target.value });
  const add = () =>
    run(async () => {
      await api("/people/mine/contacts", {
        method: "POST",
        body: JSON.stringify({ name: c.name, company: c.company, title: c.title, start_year: c.from, end_year: c.to, how: c.how, closeness: c.closeness }),
      });
      const who = c.name;
      setC({ ...c, name: "", company: "", title: "", from: "", to: "", how: "" });
      return `Added ${who}.`;
    });
  return (
    <Panel className="mt-3 space-y-1.5 p-3">
      <p className="px-1 text-[12px] text-ink-3">Or add someone by hand</p>
      <input aria-label="Name" placeholder="Name" value={c.name} onChange={set("name")} className={INPUT} />
      <div className="flex gap-1.5">
        <input aria-label="Company" placeholder="Company" value={c.company} onChange={set("company")} className={INPUT} />
        <input aria-label="Title" placeholder="Title" value={c.title} onChange={set("title")} className={INPUT} />
      </div>
      <div className="flex gap-1.5">
        <input aria-label="How you know them" placeholder="How you know them" value={c.how} onChange={set("how")} className={INPUT} />
        <input aria-label="From year" placeholder="From" inputMode="numeric" maxLength={4} value={c.from} onChange={set("from")} className={YEAR} />
        <input aria-label="To year" placeholder="To" inputMode="numeric" maxLength={4} value={c.to} onChange={set("to")} className={YEAR} />
      </div>
      <div className="flex gap-1.5">
        <select aria-label="How close" value={c.closeness} onChange={set("closeness")} className={INPUT}>
          <option value="close">Close: I can call any time</option>
          <option value="good">Good: we stay in touch</option>
          <option value="acquaintance">Acquaintance</option>
        </select>
        <button disabled={busy || !c.name.trim() || !c.company.trim()} onClick={add} className="shrink-0 rounded-full bg-ink px-4 text-[13px] font-medium text-bg disabled:opacity-40">
          Add
        </button>
      </div>
    </Panel>
  );
}

function DeleteMine() {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const [has, setHas] = useState(false);
  useEffect(() => setHas(!!getSandbox()), []);
  if (!has) return <span />;
  return (
    <button
      onClick={async () => {
        if (!window.confirm("Delete your network from FINN now?")) return;
        await api("/people/mine", { method: "DELETE" }).catch(() => null);
        setSandbox(null);
        setAccount("demo");
        await mutate(() => true, undefined, { revalidate: true });
        router.push("/people");
      }}
      className="text-[13px] text-bad"
    >
      Delete my network
    </button>
  );
}
