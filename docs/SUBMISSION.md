# Submission notes (17 Nov 2026)

## What to open
- **Prototype (responsive web, made for a phone):** https://finn-iota-murex.vercel.app. Passcode in the covering email. Add it to the home screen for the app feel. The free API host sleeps when idle, so the first load can take up to a minute; the page says so.
- **Repository:** https://github.com/Emminence23/finn. Start with the README's 60-second tour.
- **AI build history:** see "How I worked with the AI" below.

## Covering-email writeup

**What I built.** FINN is a mobile-first companion for a portfolio manager, in three layers.
- *Push:* a morning note written in code from the day's exchange filings, prices and positions. It opens with how the portfolio closed and what needs a decision, then sorts the rest into Needs you, Worth knowing and Set aside, each with its rule in one sentence. Alert thresholds are the user's own, and Listen reads the note aloud.
- *Pull:* a chat on Ask that digs into any NSE company from its annual report, last four earnings calls and reported numbers. Its centrepiece is the worked example from the brief: for the last four quarters, what management promised on headline numbers and growth, against what was delivered. Each verdict is measured in code wherever the reported numbers settle it. The rest of the menu (business, financial snapshot, trajectory, balance sheet, cash quality, narrative vs numbers, guidance, bull vs bear) is one tap away.
- *Network:* who in your own network can explain a company, how you know them, and what to ask them before a meeting.

Portfolio, Watchlist and Top movers round it out in a Groww-like layout.

**Key decisions and tradeoffs**
- *Code computes, AI reads.* Models extract promises (quoted verbatim, then string-matched to the page) and write prose that must cite a page. Code decides verdicts, ranks alerts, re-weights the portfolio and drops any point without a source. An AI verdict is used only where arithmetic can't settle a promise, and it is labelled as AI.
- *Primary sources for the analysis:* the annual report, transcripts and exchange filings, and no news or outside knowledge. Brokerage reports (only those the brokers publish openly) sit in their own section of the company report, every figure traced to its sentence and page, and never feed the verdicts. Person enrichment on the Push and Network side is kept separate.
- *One company report, saved for a week:* Ask and the company page show the same report. Code looks up a saved copy before fetching anything (no AI tokens), shows how old it is, and builds a fresh one in the background on request. Saved reports live in a Render Key Value instance, so they survive the daily redeploy.
- *A fixed pipeline over an open-ended agent:* it is cheaper, cacheable and testable. The strongest model is spent only on the judgement step.
- *Measured, not claimed:* an in-app accuracy page recomputes its checks from live data. There is a 100-filing labelled set for materiality and a 31-question retrieval eval.
- *Calm UX:* a few numbers up front with the rest folded away, every page appearing whole behind a loading bar, and tours chosen by use case.

**Architecture**
- *Data pipelines:* NSE/BSE filings and end-of-day prices go into SQLite. Annual reports and transcripts are parsed per page and cached. Multi-year tables come from screener.in's standardised copy of the accounts (labelled as such), and the latest quarter from the exchange filing itself.
- *LLMs and agents:* a provider-swappable router (Gemini free tier in the demo; Claude and Groq supported) with prompt versions, response caching, a cost log and daily budgets. Untrusted document text is fenced, and instructions inside documents are ignored (this is tested).
- *Security and privacy:* a passcode gate on the demo and per-account network isolation. A user's own LinkedIn export stays private to their browser sandbox and is deleted after 7 days. Secrets live in environment variables and never in the repo.
- *Cloud:* a FastAPI backend on Render and a Next.js frontend on Vercel. The production path (Postgres with row-level security, a queue for builds, scheduled ingestion) is in `docs/architecture.md`.

**Deliberately left out:** intraday data and push notifications (the brief is end of day by design), scraping LinkedIn (against its terms; users upload their own export), real sign-in (designed but not built), and an interactive network graph.

**Where next:** a quantitative scoring framework built into Pull (in progress), calendar-aware meeting prep, a natural-voice evening brief, intraday triggers, and management-delivery rankings across the whole watchlist.

## How I worked with the AI
- **Tool:** Claude Code (CLI), one long session plus a short setup session. Gemini (free tier) runs inside the product.
- **Transcripts:** the raw session exports are the `.jsonl` files under `~/.claude/projects/-home-tattwa-quant-enam-assignment/`. The main session can be shared as a link from claude.ai/code.
- **Decision record:** `docs/build-log.md` is the phase-by-phase record of what was built, what was measured, what went wrong and what was rejected. Examples:
  - a scorecard rebuild that ran out of model quota was blocked and recorded, never shipped half-done;
  - comparing target numbers across restatements was rejected because it invented revisions;
  - lazy-loading lower sections was overruled in favour of whole-page loading.
- **How I steered it:**
  - fixed rules (deterministic first, primary sources only, a calm UX);
  - a queue of tasks done one at a time, each shipped and verified on the live site;
  - screenshots at 390 px and browser walks of every flow;
  - feedback from friends who tried it, turned into concrete fixes (summary wording, Listen coverage, tour lag, alerts not loading).
