"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Briefcase, ChevronRight, Compass, Newspaper, Search, Users, X } from "lucide-react";
import { ProgressRing } from "./ProgressRing";
import { usePageLoadState } from "@/lib/pageload";

const DONE_KEY = "finn.tour";

type Step = { href: string; target: string; title: string; body: string };
type Track = { id: string; title: string; blurb: string; Icon: typeof Compass; steps: Step[] };

const VIVEK = "/people/c_vivek_rao";
const DABUR_CFO = "/people/fp_ankush_jain_dabur";

/** Tours by what the person wants to do. The Tour button asks first, then each tour opens
 *  its pages and outlines the thing each step describes. */
export const TRACKS: Track[] = [
  {
    id: "morning",
    title: "Check my morning",
    blurb: "What changed overnight, what needs you, and who to call",
    Icon: Newspaper,
    steps: [
      {
        href: "/",
        target: "[data-tour=lead]",
        title: "The note",
        body: "Three short paragraphs written in code from your filings, prices and positions: how the portfolio closed, what came in and whether it needs a decision, and what is still open.",
      },
      {
        href: "/",
        target: "[data-tour=listen]",
        title: "Listen on the way in",
        body: "The same brief read aloud by your phone's own voice. Company pages, Portfolio, Watchlist and profiles have their own Listen.",
      },
      {
        href: "/",
        target: '[aria-label="Time window"]',
        title: "Any window",
        body: "The last day by default. Pick up to 30 days, or any dates: 1 to 15 November has Dabur's CEO change.",
      },
      {
        href: "/",
        target: "[data-tour=card], [data-tour=row]",
        title: "Each item, and who to ask",
        body: "Its size in your portfolio and the rule that let it through. Open one for the evidence and the contact who can explain it, with two questions ready to send.",
      },
      {
        href: "/",
        target: '[aria-label="Alert settings"]',
        title: "Your alert rules",
        body: "Volume, price and filing thresholds are yours. Change them and the note re-ranks.",
      },
      {
        href: "/",
        target: "[data-tour=movers]",
        title: "The day's movers",
        body: "The biggest rises and falls across your holdings and watchlist, at the foot of the note.",
      },
    ],
  },
  {
    id: "research",
    title: "Research a company",
    blurb: "Did management deliver, the numbers, and questions with sources",
    Icon: Search,
    steps: [
      {
        href: "/ask",
        target: "[data-tour=askbox]",
        title: "Ask for anything",
        body: "A ticker, a company, a person or a plain question. A company FINN hasn't read yet is read live, after it asks you.",
      },
      {
        href: "/c/LT",
        target: "#promises",
        title: "Did management deliver?",
        body: "Every promise from four earnings calls, with its quote and page, against the reported number. Numeric promises are judged by arithmetic, not AI.",
      },
      {
        href: "/c/LT",
        target: "#numbers",
        title: "The numbers",
        body: "Growth, margins, cash conversion and the balance sheet. Compare with puts L&T beside BHEL or another peer, row by row.",
      },
      {
        href: "/c/LT",
        target: "[data-tour=askfinn]",
        title: "Ask about L&T",
        body: "Try “Why did receivables go up?”. Answers cite the call pages they came from, and points without a source are removed by code.",
      },
      {
        href: "/c/LT",
        target: "[data-tour=whoyouknow]",
        title: "Who you know",
        body: "People in your network who can explain this company, and how you know them.",
      },
      {
        href: "/c/LT",
        target: "[data-tour=watch]",
        title: "Watch it",
        body: "Adds the company to your Watchlist with its price, the day's move and its latest filing.",
      },
    ],
  },
  {
    id: "portfolio",
    title: "Review my portfolio",
    blurb: "Returns, risk, warnings, and a suggested re-weighting",
    Icon: Briefcase,
    steps: [
      {
        href: "/portfolio",
        target: 'section[aria-label="Holdings summary"]',
        title: "Where you stand",
        body: "Current value, what you invested, total returns, and the last day's move in rupees.",
      },
      {
        href: "/portfolio",
        target: "[data-tour=movers]",
        title: "Top movers",
        body: "The day's gainers and losers among your holdings and watchlist. Tap one for its research.",
      },
      {
        href: "/portfolio",
        target: 'section[aria-label="Holdings"]',
        title: "Every holding",
        body: "Shares, average price, last price and gain. Sort by value, returns or the day's move.",
      },
      {
        href: "/portfolio",
        target: "[data-tour=flags]",
        title: "Warnings",
        body: "Holdings outside your own limits, a theme that's too big, risk out of line with size, pairs that move together.",
      },
      {
        href: "/portfolio",
        target: '[aria-label="View"]',
        title: "A suggested re-weighting",
        body: "Suggested keeps the same stocks and re-weights them in code, then an AI review that must cite a filing nudges a few, within limits code enforces.",
      },
      {
        href: "/portfolio",
        target: "[data-tour=edit]",
        title: "Make it yours",
        body: "Change share counts with − and +. Today, alerts and the suggestion follow. Reset to the demo at any time.",
      },
      {
        href: "/watchlist",
        target: "[data-tour=watchlist]",
        title: "Your watchlist",
        body: "Companies you follow without holding: price, the day's move, a month's line and the latest filing that isn't paperwork.",
      },
    ],
  },
  {
    id: "network",
    title: "Use my network",
    blurb: "Who can explain a company, and what to ask them",
    Icon: Users,
    steps: [
      {
        href: "/people",
        target: '[aria-label="Search your network"]',
        title: "Search first",
        body: "A name, a company, or a topic such as EMS or private banking.",
      },
      {
        href: "/people",
        target: "[data-tour=worthcall]",
        title: "Worth a call",
        body: "People you haven't spoken to in a while who know something about your holdings right now.",
      },
      {
        href: VIVEK,
        target: "[data-tour=askabout]",
        title: "What to ask them about",
        body: "The companies this person can help with, and why: here, Vivek's years running projects at L&T.",
      },
      {
        href: VIVEK,
        target: "[data-tour=beforemeet]",
        title: "Before you meet",
        body: "Questions built from FINN's research, each with its source, so you walk in with management's own numbers.",
      },
      {
        href: VIVEK,
        target: "[data-tour=meeting]",
        title: "Meeting soon?",
        body: "Note a date. From two days before, Today opens with a prep card for it.",
      },
      {
        href: DABUR_CFO,
        target: "[data-tour=samename]",
        title: "Same name, not assumed",
        body: "Dabur's CFO, newly named Compliance Officer too, shares a name with one of your contacts. FINN asks you to confirm instead of assuming they're the same person.",
      },
      {
        href: "/people",
        target: "[data-tour=whose]",
        title: "Bring your own network",
        body: "Switch to Yours, add where you worked and studied, and upload the Connections.csv LinkedIn lets you export. It stays private to your browser.",
      },
    ],
  },
  {
    id: "overview",
    title: "A quick look at everything",
    blurb: "Six stops across the app",
    Icon: Compass,
    steps: [
      {
        href: "/",
        target: "[data-tour=lead]",
        title: "Your morning note",
        body: "Written in code from your filings, prices and positions: what needs you, what's worth knowing, and what was set aside. Listen plays it aloud.",
      },
      {
        href: "/",
        target: "[data-tour=card], [data-tour=row]",
        title: "Why it's here, and who to ask",
        body: "Each item gives its size in your portfolio and the rule that let it through. Open one for the evidence and the contact who can explain it.",
      },
      {
        href: "/c/LT",
        target: "#promises",
        title: "Did management deliver?",
        body: "Promises from four earnings calls, checked against the reported numbers. Numeric ones are judged by arithmetic, not AI.",
      },
      {
        href: "/portfolio",
        target: '[aria-label="View"]',
        title: "The whole portfolio",
        body: "Value, returns and the day's move up front; risk by theme and holding; and a suggested re-weighting of the same stocks.",
      },
      {
        href: "/",
        target: "[data-tour=ask]",
        title: "Ask from anywhere",
        body: "A company, a person, a theme or a question. Watchlist and Network sit beside it.",
      },
      {
        href: "/",
        target: 'a[href="/accuracy"]',
        title: "How accurate is FINN?",
        body: "Measured, not claimed: the checks are recomputed from today's data, and every hand-labelled filing is listed.",
      },
    ],
  },
];

function pageName(href: string): string {
  if (href === "/") return "Today";
  if (href === VIVEK) return "Vivek's profile";
  if (href === DABUR_CFO) return "Ankush Jain's profile";
  if (href.startsWith("/c/")) return href.slice(3);
  return ({ "/portfolio": "Portfolio", "/watchlist": "Watchlist", "/people": "your network", "/ask": "Ask" } as Record<string, string>)[href] ?? "the page";
}

function done(): boolean {
  try {
    return localStorage.getItem(DONE_KEY) === "done";
  } catch {
    return true; // no storage (private mode, previews): never nag
  }
}

function remember() {
  try {
    localStorage.setItem(DONE_KEY, "done");
  } catch {
    /* storage unavailable */
  }
}

export function Tour() {
  const router = useRouter();
  const path = usePathname();
  const [picking, setPicking] = useState(false);
  const [track, setTrack] = useState<Track | null>(null);
  const [step, setStep] = useState(0);
  const [cardOnTop, setCardOnTop] = useState(false);
  const loading = usePageLoadState().active;

  useEffect(() => {
    // first visit to Today only: a shared link to a company page opens straight on it
    if (window.location.pathname === "/" && !done()) setPicking(true);
    const replay = () => {
      setTrack(null);
      setPicking(true);
    };
    window.addEventListener("finn:tour", replay);
    return () => window.removeEventListener("finn:tour", replay);
  }, []);

  // the chosen tour's pages are fetched ahead, so a step doesn't wait on code it could have had
  useEffect(() => {
    if (!track) return;
    for (const h of new Set(track.steps.map((x) => x.href))) router.prefetch(h);
  }, [track, router]);

  useEffect(() => {
    if (!track) return;
    const s = track.steps[step];
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
  }, [track, step, path, router, loading]);

  const close = () => {
    remember();
    setPicking(false);
    setTrack(null);
  };

  if (picking) {
    return (
      <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center" onClick={close}>
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Choose a tour"
          onClick={(e) => e.stopPropagation()}
          className="w-full max-w-xl rounded-t-3xl bg-surface px-4 pb-[calc(16px+env(safe-area-inset-bottom))] pt-4 shadow-xl sm:rounded-3xl"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[18px] font-semibold tracking-[-0.01em]">What would you like to do?</p>
              <p className="mt-0.5 text-[13px] text-ink-2">Pick one and FINN walks you through it, about a minute each.</p>
            </div>
            <button onClick={close} aria-label="Close" className="-m-1 rounded-full p-1.5 text-ink-3">
              <X size={18} />
            </button>
          </div>
          <ul className="mt-3 space-y-2">
            {TRACKS.map((t) => (
              <li key={t.id}>
                <button
                  onClick={() => {
                    remember();
                    setPicking(false);
                    setStep(0);
                    setTrack(t);
                  }}
                  className="flex w-full items-center gap-3 rounded-2xl border border-line bg-bg px-3.5 py-3 text-left active:bg-surface-2"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                    <t.Icon size={18} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[15px] font-medium">{t.title}</span>
                    <span className="block text-[12px] leading-snug text-ink-2">{t.blurb}</span>
                  </span>
                  <span className="tnum shrink-0 text-[11px] text-ink-3">{t.steps.length} steps</span>
                  <ChevronRight size={16} className="shrink-0 text-ink-3" />
                </button>
              </li>
            ))}
          </ul>
          <button onClick={close} className="mt-3 w-full py-2 text-center text-[13px] text-ink-3">
            Not now. The Tour button on Today brings this back.
          </button>
        </div>
      </div>
    );
  }

  if (!track) return null;
  const s = track.steps[step];
  const moving = path !== s.href || loading; // on its way, or its page still loading: say so
  const last = step === track.steps.length - 1;
  return (
    <div
      role="dialog"
      aria-label={`${track.title}, step ${step + 1} of ${track.steps.length}: ${s.title}`}
      className="fixed inset-x-0 z-50 mx-auto max-w-xl px-3"
      style={cardOnTop && !moving ? { top: "calc(12px + env(safe-area-inset-top))" } : { bottom: "calc(84px + env(safe-area-inset-bottom))" }}
    >
      <div className="rounded-2xl bg-ink p-4 text-bg shadow-xl">
        <div className="flex items-center justify-between gap-3">
          <p className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide opacity-70">
            <ProgressRing value={(step + 1) / track.steps.length} size={14} stroke={2} />
            {track.title} · {step + 1} of {track.steps.length}
          </p>
          <button onClick={close} aria-label="Close the tour" className="-m-1 p-1 opacity-70">
            <X size={16} />
          </button>
        </div>
        <p className="mt-1 text-[16px] font-semibold">{s.title}</p>
        {moving ? (
          <p className="mt-1 flex items-center gap-2 text-[13px] opacity-85" role="status">
            <ProgressRing size={15} /> Opening {pageName(s.href)}…
          </p>
        ) : (
          <p className="mt-1 text-[13px] leading-snug opacity-85">{s.body}</p>
        )}
        <div className="mt-3 flex items-center justify-between">
          {last ? (
            <button
              onClick={() => {
                setTrack(null);
                setPicking(true);
              }}
              className="text-[13px] underline underline-offset-2 opacity-80"
            >
              Another tour
            </button>
          ) : (
            <button onClick={close} className="text-[13px] opacity-70">
              Skip tour
            </button>
          )}
          <div className="flex gap-2">
            {step > 0 && (
              <button onClick={() => setStep(step - 1)} className="rounded-full border border-bg/30 px-3.5 py-1.5 text-[13px]">
                Back
              </button>
            )}
            <button onClick={() => (last ? close() : setStep(step + 1))} className="rounded-full bg-bg px-4 py-1.5 text-[13px] font-semibold text-ink">
              {last ? "Done" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
