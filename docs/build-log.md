# Build log

Key prompts, course-corrections, and accept-vs-rewrite decisions made while building FINN with Claude Code.

## Phase 0: setup
- Chose FastAPI + Next.js, with Anthropic models routed by task (Haiku 5.5 for bulk, Opus 5.5 for reasoning).
- Pinned Python 3.12 via uv instead of the system 3.14, to avoid missing wheels.
- Probed data sources live before designing ingest: NSE announcements API works (cookie-primed session, date ranges, PDFs); BSE API returns 403, so it was dropped; screener.in gives quarterly tables plus AR and transcript links for any ticker.
- No Anthropic API key available (claude.ai subscription ≠ API access), so the LLM layer became provider-agnostic with task-based routing (config/models.yaml), defaulting to free tiers.

## Infrastructure
- Built a provider-agnostic LLM router: callers name a *task*; YAML and env pick the provider and model. Adapters: Gemini, Anthropic, and OpenAI-compatible (Groq, OpenRouter, Ollama). Includes a SQLite response cache, one retry on invalid structured output, and per-call usage and cost logging.
- Considered renting a GPU box for Ollama. Rejected: the deployed demo needs an LLM whenever reviewers open it, so a GPU box would have to stay on (cost) or would break the demo when stopped. Free hosted tiers plus a ≤$10 Anthropic top-up for the hero analysis is cheaper and more reliable. Ollama remains a supported provider.
- Model IDs are left as `TBD` and fail loudly, rather than being guessed. They're filled in from each provider's live model list (`app.llm.cli models`).
- Tests use a fake provider and never hit a real API (12 passing). The Docker image builds and serves /health.

## Phase 1: data
- Snapshot pipeline (`make snapshot`) freezes live data into committed fixtures, and `make seed` loads them into SQLite in about 2.5s. The demo never scrapes live (NFR-02).
- Data snapshot: 2,601 NSE symbols; 6 months of prices for 21 tickers; 517 NSE announcements (60 days); screener fundamentals for all 21 tickers (~12 quarters plus annual P&L, balance sheet, cash flow and ratios; 1,874 document links); 4 transcripts plus the latest annual report for each research company, cached locally rather than committed.
- **Course-correction (ethics):** the plan said to generate synthetic profiles with an LLM, including people named in filings. Inventing careers for real, named executives would mean fabricating facts about real people. Instead, filing people are built **only from the "brief profile" annexure that SEBI requires in appointment filings** (a primary source, cited by announcement ID). The investor's contacts are fictional, and they connect to real executives only through employers and schools stated in those filings. Unknown tenure years are left null so overlaps are labelled "possible" rather than asserted.
- Found the brief's exact hero case in real data: Pidilite appointed a **CFO-Designate** (Oct 9). Other management changes with rich profiles: HDFC Bank CCO (ex-ICICI Bank, which is also in the portfolio), CG Power SMPs, SRF CHRO, Trent director.
- Screener parser handles lenders (Revenue/Financing Profit, no EBITDA → stored as null rather than faked) and falls back from consolidated to standalone figures.
- BSE stays dropped (403). NSE `attchmntText` gives a free, usable subject line per filing.
- Gemini key added. Probed every listed model with a one-line request instead of trusting the model list: several returned 404 (not available to new users), 429 (no free quota) or 503/504 (overloaded). Chose fast=`gemini-3.5-flash-lite`, mid=`gemini-3.5-flash`, strong=`gemini-4-hydrogen`.
- **Bug found:** the first probe hung indefinitely because the Gemini client had no timeout. Fixed with a 120s timeout plus exponential-backoff retries on 429/5xx in the Gemini adapter.

## Phase 2: Push + Network
- **Rules first, LLM second:** a keyword/category rule table decides 454 of 517 filings with no LLM call. Only ambiguous filings, plus categories whose materiality depends on content, go to batched triage (10 per call), which covered 229 items.
- **The LLM transcribes and code calculates:** for results filings the model only copies line items from the PDF. Code computes EBITDA (PBT + finance costs + D&A − other income), QoQ and YoY, then cross-checks revenue, PBT and PAT against screener.in at 1% tolerance. Result: 18 cards; most match, and two banks differ only on PAT (consolidated vs standalone basis, with the differences shown on the card rather than hidden).
- **Bug found by the cross-check:** bank revenue never matched screener. Banks report "interest earned" as the top line, NBFCs don't. Added `interest_earned` to the schema and decide bank-vs-NBFC in code from the balance sheet (a "Deposits" row). The first fix wrongly turned Bajaj Finance and Chola into banks and was corrected.
- **Graceful degradation:** the Infosys extraction kept hitting Gemini 503s (overload), so the card falls back to screener's numbers and is labelled that way.
- **The AI corrected the golden set:** the hand-built fixture had Anup Bagchi in the wrong role. The extractor said he is HDFC Bank's new MD & CEO, and the PDF confirmed it, so the fixture was fixed rather than the model "corrected".
- **People-extraction eval (`python -m app.intel.eval_people`):**
  - v1 scored roles 5/7, prior employers 7/18, schools 3/11. The CG Power filing is a long board outcome, and its two SMP profiles sit after the results statement, past the first 8 pages.
  - v2 sends page 1 plus the pages that mention appointments or profiles. It also normalises role strings in the scorer (CEO and "Chief Executive Officer" are the same role).
  - v2 scores people 7/7, roles 7/7, prior employers 17/18, schools 8/10.
- **The network graph is pure code:** paths, overlaps, who-can-help and reconnect nudges never send contact data to an LLM (privacy, §6.4).

## Phase 3: Pull research engine
- **Pipeline:**
  - screener tables, then the deterministic sections (snapshot, trajectory, cash quality, balance sheet, rule-based flags);
  - the latest annual report plus the last 4 concall transcripts, downloaded and split into pages;
  - guidance extraction, one call per transcript;
  - promised-vs-delivered;
  - business snapshot plus bull/bear;
  - "who can help" attached at read time.
- **Anti-hallucination, in code:**
  - (a) every guidance quote is fuzzy-matched against the page text and re-located if the cited page is wrong; unmatched quotes are dropped;
  - (b) verdicts may cite only evidence ids that code supplied (`Q:2026-06`, `FY:2026-03`, update ids);
  - (c) "missed" before the deadline is downgraded to "too early" unless a management update admits a miss;
  - (d) narrative citations must point at pages that were actually in the prompt.
- **Model choice was measured:** on the same Kaynes call, flash-lite found 5 promises and flash found 10, including the three that turned out to be missed. Guidance moved to the mid tier.
- **The Kaynes scorecard is the demo story:**
  - FY26 revenue was ₹3,626 Cr against ₹4,000 Cr+ guided, after an earlier cut from ₹4,500 Cr;
  - working capital was 133 days against ≤85 guided;
  - operating cash flow was −₹600 Cr against "positive";
  - debtor days went from 77 to 154.
  - Each one shows the verbatim quote, call and page next to the reported number.
- **Bug: the thinking model ran out of tokens.** The strong model spent its 8k output budget reasoning, then returned truncated JSON. Budgets were raised to 16–20k, staying under the Anthropic non-streaming limit so a switch to Claude still works.
- **Bug: free-tier daily quota.** Gemini Flash allows 20 requests per day per model, and one research build uses about 6. Added a quota-aware fallback chain per tier (`fallbacks` in models.yaml): exhausted models are skipped for an hour and every response records the model that served it. Builds with a failed section are flagged `incomplete` and are never cached or saved as fixtures (the first run had silently cached a partial Manappuram view).
- **Rejected Gemma 4 as a fallback:** it returns HTTP 500 when given a response schema, and wraps JSON in code fences.
- **Verdict honesty:** "partly" was being used for "the data isn't reported". Added an `unclear` verdict, excluded from the credibility score.
- **An unseen ticker (Tata Elxsi) found two ingest bugs:**
  - its consolidated screener page stops in 2015, so the fetcher now picks whichever basis has the newest quarter;
  - screener listed the same call twice, so the two transcripts collided on one filename; transcripts are now deduplicated by month.

## Phase 4: frontend
- **Three tabs, one job each:**
  - Today (Push): ranked brief for 24h / 7d / 30d, unusual moves, people worth reconnecting with, routine filings folded away;
  - Ask (Pull): one search box for tickers, themes and people, plus a list of management track records;
  - People (Network): expertise map by theme, contact profiles with "ask them about", "can introduce you to" and paths.
- **Company page leads with promised-vs-delivered.** An unbuilt ticker builds live over SSE with step-by-step progress; incomplete builds show a banner instead of passing as complete.
- **A brief, not a dashboard.** The 30-day window had 60 cards. The feed shows the top 8 and folds the rest behind "N more, lower priority"; each company's "who to ask" appears once, on its most important card. Results cards lead with what the numbers say ("Profit down 36% YoY even as revenue grew 12%") instead of the filing's subject line.
- **Charts follow the dataviz rules:** single-series sparklines with hover and arrow-key access, a thin segmented verdict bar with a counted legend, status colours always paired with an icon and label, tabular figures, and selected dark-mode tokens.
- **Bug: every bank was treated as an NBFC.** `is_bank` read the latest annual row, which sorted to 'TTM' and has no balance sheet. Bank revenue was therefore compared on the wrong line and screener showed 36–57% gaps. With the fix, revenue and PBT match screener to 0.0%.
- **Honest cross-check labels.** The remaining HDFC Bank and ICICI Bank gap is PAT only (−3.9%, −6.1%): the filing's owners' share against screener's total profit. These now show as "revenue and PBT match; PAT −x% (owners' share vs total)" instead of a bare "differs".
- **Bug: blank revenue label** on screener-fallback cards (Trent): fixed.
- **PWA basics:** icon, manifest and theme colour, so it can be added to a phone's home screen.
