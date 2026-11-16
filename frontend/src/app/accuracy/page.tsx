"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import clsx from "clsx";
import { ArrowLeft, Check, Minus, X } from "lucide-react";
import { useApi } from "@/lib/api";
import { day, shortName } from "@/lib/fmt";
import { Panel, Pill, SectionTitle, Skeleton } from "@/components/ui";

type Live = { what: string; result: string; target: string | null; passes: boolean | null; how: string; detail?: string };
type Measured = { what: string; result: string; how: string; when: string };
type Labelled = {
  id: string;
  symbol: string | null;
  ts: string | null;
  title: string;
  pdf_url: string | null;
  material: boolean;
  finn_level: string;
  agrees: boolean;
};

/** The measurements behind FINN, inside the app. Live rows are recomputed from the current
 *  data on every visit; the labelled filings can be checked one by one. */
export default function AccuracyPage() {
  const router = useRouter();
  const { data } = useApi<{ live: Live[]; measured: Measured[] }>("/eval");
  return (
    <main className="pb-10">
      <div className="flex items-center gap-1 px-3 pt-[calc(12px+env(safe-area-inset-top))]">
        <button onClick={() => router.back()} aria-label="Back" className="rounded-full p-2 text-ink-2 active:bg-surface-2">
          <ArrowLeft size={19} />
        </button>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">How accurate is FINN?</h1>
      </div>
      <p className="px-4 text-[13px] leading-snug text-ink-2">
        What FINN gets right, measured rather than claimed. The first group is recomputed from today&apos;s data every time you open this page.
      </p>
      {!data ? (
        <Skeleton className="mx-4 mt-4 h-64" />
      ) : (
        <>
          <SectionTitle aside="recomputed now">Live checks</SectionTitle>
          <Panel className="divide-y divide-line">
            {data.live.map((x) => (
              <Row key={x.what} what={x.what} result={x.result} how={x.how} detail={x.detail} target={x.target} passes={x.passes} />
            ))}
          </Panel>
          <SectionTitle aside="at build time">Measured while building</SectionTitle>
          <Panel className="divide-y divide-line">
            {data.measured.map((x) => (
              <Row key={x.what} what={x.what} result={x.result} how={`${x.how} (${x.when})`} />
            ))}
          </Panel>
          <Labels />
        </>
      )}
    </main>
  );
}

function Row({ what, result, how, detail, target, passes }: { what: string; result: string; how: string; detail?: string; target?: string | null; passes?: boolean | null }) {
  return (
    <div className="px-4 py-3">
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 text-[13px] text-ink-2">{what}</p>
        {passes === true && <Check size={15} className="mt-0.5 shrink-0 text-good" aria-label="meets target" />}
        {passes === false && <X size={15} className="mt-0.5 shrink-0 text-bad" aria-label="misses target" />}
      </div>
      <p className="tnum mt-0.5 text-[16px] font-semibold leading-snug">{result}</p>
      {target && <p className="text-[12px] text-ink-3">Target: {target}</p>}
      <p className="mt-1 text-[12px] leading-snug text-ink-3">
        {how}
        {detail ? `. ${detail}.` : "."}
      </p>
    </div>
  );
}

const LEVEL: Record<string, string> = { important: "Important", notable: "Notable", routine: "Routine" };

function Labels() {
  const { data } = useApi<{ definition: string; filings: Labelled[] }>("/eval/labels");
  const [only, setOnly] = useState<"material" | "all">("material");
  if (!data) return null;
  const rows = data.filings.filter((f) => only === "all" || f.material);
  return (
    <>
      <SectionTitle aside={`${data.filings.length} filings`}>Check the labels yourself</SectionTitle>
      <p className="px-4 text-[12px] leading-snug text-ink-3">{data.definition}</p>
      <div className="mt-2 flex gap-1.5 px-4">
        {(["material", "all"] as const).map((k) => (
          <button
            key={k}
            aria-pressed={only === k}
            onClick={() => setOnly(k)}
            className={clsx("rounded-full border px-3 py-1 text-[12px]", only === k ? "border-ink bg-ink text-surface" : "border-line bg-surface text-ink-2")}
          >
            {k === "material" ? "Labelled material" : "All 100"}
          </button>
        ))}
      </div>
      <Panel className="mt-2 divide-y divide-line">
        {rows.map((f) => (
          <a key={f.id} href={f.pdf_url ?? undefined} target="_blank" rel="noreferrer" className="flex gap-2.5 px-4 py-2.5 active:bg-surface-2">
            <span className="mt-0.5 shrink-0">
              {f.agrees ? <Check size={14} className="text-good" aria-label="FINN agrees" /> : <Minus size={14} className="text-ink-3" aria-label="FINN differs" />}
            </span>
            <span className="min-w-0 flex-1 text-[13px] leading-snug">
              <span className="font-semibold">{f.symbol ? shortName(f.symbol) : ""}</span> {f.title}
              <span className="mt-0.5 flex flex-wrap items-center gap-1 text-[11px] text-ink-3">
                {f.ts && day(f.ts)} · labelled {f.material ? "material" : "not material"} · FINN:
                <Pill tone={f.finn_level === "important" ? "strong" : "neutral"}>{LEVEL[f.finn_level] ?? f.finn_level}</Pill>
              </span>
            </span>
          </a>
        ))}
      </Panel>
    </>
  );
}
