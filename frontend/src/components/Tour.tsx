"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { X } from "lucide-react";
import { ProgressRing } from "./ProgressRing";
import { usePageLoadState } from "@/lib/pageload";

const PAGE_NAME: Record<string, string> = { "/": "Today", "/c/KAYNES": "Kaynes", "/portfolio": "Portfolio" };

const DONE_KEY = "finn.tour";

type Step = { href: string; target: string; title: string; body: string };

/** Six stops a first-time reviewer would otherwise miss. Each opens its page and outlines
 *  the thing it describes. Shown once, on a first visit to Today; the Tour button replays it. */
const STEPS: Step[] = [
  {
    href: "/",
    target: "[data-tour=lead]",
    title: "Your morning note",
    body: "Written in code from your filings, prices and positions: what needs you, what's worth knowing, and what was set aside and why. Listen plays it aloud on your phone.",
  },
  {
    href: "/",
    target: "[data-tour=card], [data-tour=row]",
    title: "Why it's here, and who to ask",
    body: "Each item gives its size in your portfolio and the rule that let it through. Open one for the evidence, and for the contact who can explain it, with two questions ready to send.",
  },
  {
    href: "/c/KAYNES",
    target: "#promises",
    title: "Did management deliver?",
    body: "Promises from four earnings calls, checked against the reported numbers. Numeric ones are judged by arithmetic, not AI. Compare with a peer sits just above.",
  },
  {
    href: "/portfolio",
    target: '[aria-label="View"]',
    title: "The whole portfolio",
    body: "Value, returns and the day's move up front; then risk by theme and holding, and a suggested re-weighting of the same stocks: built in code, then nudged by an AI review that has to cite a filing. Edit changes your holdings.",
  },
  {
    href: "/",
    target: "[data-tour=ask]",
    title: "Ask from anywhere",
    body: "A company, a person, a theme or a question. Watchlist and Network sit beside it, and every item names who in your network can explain it.",
  },
  {
    href: "/",
    target: 'a[href="/accuracy"]',
    title: "How accurate is FINN?",
    body: "Measured, not claimed: the checks are recomputed from today's data, and every hand-labelled filing is listed.",
  },
];

function done(): boolean {
  try {
    return localStorage.getItem(DONE_KEY) === "done";
  } catch {
    return true; // no storage (private mode, previews): never nag
  }
}

export function Tour() {
  const router = useRouter();
  const path = usePathname();
  const [step, setStep] = useState<number | null>(null);
  const [cardOnTop, setCardOnTop] = useState(false);
  const loading = usePageLoadState().active;

  useEffect(() => {
    // first visit to Today only: a shared link to a company page opens straight on it
    if (window.location.pathname === "/" && !done()) setStep(0);
    const replay = () => setStep(0);
    window.addEventListener("finn:tour", replay);
    return () => window.removeEventListener("finn:tour", replay);
  }, []);

  // the tour's pages are fetched ahead, so a step doesn't wait on code it could have had
  useEffect(() => {
    if (step === null) return;
    for (const h of new Set(STEPS.map((x) => x.href))) router.prefetch(h);
  }, [step === null, router]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (step === null) return;
    const s = STEPS[step];
    if (path !== s.href) {
      router.push(s.href);
      return;
    }
    let el: Element | null = null;
    let frame = 0;
    let settle: ReturnType<typeof setTimeout> | undefined;
    const t0 = performance.now();
    // Placed once, when the target exists; the card's side is chosen then and kept, so it
    // never jumps under a thumb reaching for Next. One quiet re-scroll only if late data
    // pushed the target well away.
    const place = (first: boolean) => {
      if (!el) return;
      const top = el.getBoundingClientRect().top;
      if (!first && Math.abs(top - 96) < 48) return;
      window.scrollTo({ top: Math.max(0, top + window.scrollY - 96), behavior: "instant" as ScrollBehavior });
      if (first) setCardOnTop(el.getBoundingClientRect().top > window.innerHeight * 0.45);
    };
    const look = () => {
      el = document.querySelector(s.target);
      if (el) {
        el.classList.add("tour-target");
        place(true);
        settle = setTimeout(() => place(false), 900);
        return;
      }
      if (performance.now() - t0 < 75000) frame = requestAnimationFrame(look); // a waking server can take a minute
    };
    frame = requestAnimationFrame(look);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(settle);
      el?.classList.remove("tour-target");
    };
  }, [step, path, router]);

  if (step === null) return null;
  const s = STEPS[step];
  const moving = path !== s.href || loading; // on its way, or its page still loading: say so
  const finish = () => {
    try {
      localStorage.setItem(DONE_KEY, "done");
    } catch {
      /* storage unavailable */
    }
    setStep(null);
  };
  const last = step === STEPS.length - 1;
  return (
    <div
      role="dialog"
      aria-label={`Tour, step ${step + 1} of ${STEPS.length}: ${s.title}`}
      className="fixed inset-x-0 z-50 mx-auto max-w-xl px-3"
      style={cardOnTop && !moving ? { top: "calc(12px + env(safe-area-inset-top))" } : { bottom: "calc(84px + env(safe-area-inset-bottom))" }}
    >
      <div className="rounded-2xl bg-ink p-4 text-bg shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <p className="text-[11px] font-medium uppercase tracking-wide opacity-70">
            {step + 1} of {STEPS.length}
          </p>
          <button onClick={finish} aria-label="Close the tour" className="-m-1 p-1 opacity-70">
            <X size={16} />
          </button>
        </div>
        <p className="mt-0.5 text-[16px] font-semibold">{s.title}</p>
        {moving ? (
          <p className="mt-1 flex items-center gap-2 text-[13px] opacity-85" role="status">
            <ProgressRing size={15} /> Opening {PAGE_NAME[s.href] ?? "the page"}…
          </p>
        ) : (
          <p className="mt-1 text-[13px] leading-snug opacity-85">{s.body}</p>
        )}
        <div className="mt-3 flex items-center justify-between">
          {last ? (
            <span />
          ) : (
            <button onClick={finish} className="text-[13px] opacity-70">
              Skip tour
            </button>
          )}
          <div className="flex gap-2">
            {step > 0 && (
              <button onClick={() => setStep(step - 1)} className="rounded-full border border-bg/30 px-3.5 py-1.5 text-[13px]">
                Back
              </button>
            )}
            <button
              onClick={() => (last ? finish() : setStep(step + 1))}
              className="rounded-full bg-bg px-4 py-1.5 text-[13px] font-semibold text-ink"
            >
              {last ? "Done" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
