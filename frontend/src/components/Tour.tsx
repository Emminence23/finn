"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { X } from "lucide-react";

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

  useEffect(() => {
    // first visit to Today only: a shared link to a company page opens straight on it
    if (window.location.pathname === "/" && !done()) setStep(0);
    const replay = () => setStep(0);
    window.addEventListener("finn:tour", replay);
    return () => window.removeEventListener("finn:tour", replay);
  }, []);

  useEffect(() => {
    if (step === null) return;
    const s = STEPS[step];
    if (path !== s.href) {
      router.push(s.href);
      return;
    }
    let el: Element | null = null;
    let tries = 0;
    const find = setInterval(() => {
      el = document.querySelector(s.target);
      if (el || ++tries > 40) {
        clearInterval(find);
        if (!el) return;
        const target = el;
        target.classList.add("tour-target");
        // near the top, clear of the card; if the page can't scroll that far, move the card up.
        // Run again once late data (meeting prep, alerts) has settled the layout.
        const place = () => {
          const top = target.getBoundingClientRect().top + window.scrollY - 96;
          window.scrollTo({ top: Math.max(0, top), behavior: "instant" as ScrollBehavior });
          setCardOnTop(target.getBoundingClientRect().top > window.innerHeight * 0.45);
        };
        place();
        settle = setTimeout(place, 700);
      }
    }, 150);
    let settle: ReturnType<typeof setTimeout> | undefined;
    return () => {
      clearInterval(find);
      clearTimeout(settle);
      el?.classList.remove("tour-target");
    };
  }, [step, path, router]);

  if (step === null) return null;
  const s = STEPS[step];
  if (path !== s.href) return null; // on its way to the step's page: don't hang over this one
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
      style={cardOnTop ? { top: "calc(12px + env(safe-area-inset-top))" } : { bottom: "calc(84px + env(safe-area-inset-bottom))" }}
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
        <p className="mt-1 text-[13px] leading-snug opacity-85">{s.body}</p>
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
