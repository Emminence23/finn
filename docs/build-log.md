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

## Phase 4b: Ask FINN and AI labels (added after a review of the build)
- **Why:** walking through the app, the LLM was invisible. It runs ahead of time and only leaves structured output, nothing says which text an AI wrote, and "Ask" was a search box. The plan had questions in Ask ("did Dixon deliver on margin guidance?") but Phase 4 shipped search only. AI labels were not in the plan.
- **Ask FINN** (`app/research/qa.py`, FR-PULL-12):
  - retrieval is deterministic: BM25 over every page of the company's 4 calls and annual report, top 8 pages, plus the computed numbers, flags and promise scorecard;
  - the model may cite only those pages and ids (`FY:2026-03`, `fin:receivables`, `P2`); code removes uncited points and reports how many were removed;
  - "the documents don't answer this" is a valid answer;
  - suggested questions are built in code from the misses and red flags, so they cost nothing;
  - the Ask tab detects a question, finds which company it is about, and opens that company with the question asked.
- **Bug caught by a test:** the company resolver matched the lowercase word "margin" to a ticker called MARGIN. Lowercase tickers and names now match only companies FINN follows.
- **AI labels** (FR-APP-06): the router records which model answered every call, cache hits included, and research views store it per section. Scorecard, bull/bear, business, answers, AI-read results tables and AI-extracted bios carry "AI · read from … · model". Computed numbers don't, and the flags say "Computed from reported financials, not by AI."
- **Page texts ship with the image** (`data/fixtures/pages/`, 6 MB), so Q&A works on the deployed API without the 600 MB PDF cache.
- **Fixtures rebuilt from the LLM cache** at no cost to add model records. Manappuram's scorecard was redone on Gemini 3.5 Flash: 15 items, mostly "can't tell" because segment numbers aren't reported. Kaynes keeps its earlier scorecard until the strong model is available.
- **Budget:** questions are capped at `FINN_MAX_QUESTIONS_PER_DAY` (default 60); a repeated question is answered from the cache.

## Phase 4c: requirements gaps closed (plan v2)
- **Why:** three plans were compared side by side: a broad product-vision draft, a requirements review of it, and the plan we followed. `PLAN_v2.md` combines them. The review's acceptance tests found gaps in what we built, and each fix below has a test.
- **Unsure filings stay visible** (FR-PUSH-07). `unclassified` was in the routine set, so anything the rules couldn't place was folded away. Checking the data showed what that hid on the 30-day window: the Jio Platforms IPO price (Reliance +11.6% that day), Persistent reaching 94% of Nagarro, a CDO resignation. Now an unsure filing is folded only if the triage model read it and scored it as paperwork.
- **No % off a loss** (FR-CARD-07). `pct_change` divided by the absolute prior value, so a loss turning into a profit printed as a large positive %. Now it shows words ("turned profitable"). Stored cards are recomputed on read, and the cross-check keeps its own relative-difference helper.
- **Split and bonus guard** (FR-ALERT-08). A move is treated as mechanical only if it matches a standard split or bonus ratio *and* the company filed a split or bonus recently, so a real 50% crash still alerts. No real alert changed: the window holds no splits.
- **Statement types and "Revised"** (FR-PULL-13), computed in code and applied when a view is read, so the stored scorecards needed no new AI calls.
  - **First attempt over-fired**, as checking it against the four stored scorecards showed. "Not measurable" swallowed Kaynes' positive-cash-flow promise. Comparing target numbers across merged restatements invented revisions, because the model had merged Manappuram's ROA and ROE targets into one promise.
  - **Final rule:** "Revised" needs a cited management update that revises, delays or withdraws a target for the same metric. "Not measurable" is kept for statements with no number, no direction and no date.
  - **Result:** one real revision, Aarti's Zone IV commissioning "delayed by 3 to 4 months". "Too early" is renamed "Not yet due".
- **Declared vs inferred links, insider mark** (FR-NET-02/03). Overlaps were shown as "confirmed", which read as if FINN knew two people had worked together. They now say "inferred, years overlap" or "inferred, years unknown", and only links the investor recorded say "declared". A contact who works at the company now carries "Works there now: keep it to public information".
- **Untrusted documents** (NFR-13). Every document-reading prompt now carries a rule that document text is data, not instructions. The test uses a fake model that obeys an injected instruction and checks that the citation validator removes its output. Changing the prompts means LLM cache misses on the next rebuild. Stored research views stay valid because their key is the prompt version.
- **Freshness and custom dates** (NFR-14, FR-PUSH-01). Today shows how current filings and prices are, with a warning when a session is missing. Two windows were added: 3 days, and custom dates using the phone's own date picker. The custom range reaches the 9 October Pidilite CFO change, which the README had listed as left out.

## Phase 4d: priority levels, calibrated (plan v2, item 1)
- **Labels first.** Before any level rule existed, 100 portfolio filings were drawn with a fixed seed and labelled material or not from their category, subject and summary alone. The labeller was the coding model, working to a written definition; FINN's scores were not shown. A human pass is the obvious next step. 25 of the 100 are material.
- **Baseline: 21 of 25 outside Routine (84%, target 95%).** The four misses were two event-grouping bugs, not judgement:
  - three results decks filed as a bare "Investor Presentation" were classed as investor meetings;
  - Asian Paints filed its results under "Dividend".
  - Fixes: a deck within 3 days of the company's results joins the results card, and a "Dividend" filing whose subject is results is results. The one stored fixture row was corrected by the same rule, with no AI call. After the fixes: 25 of 25.
- **First Important rule failed the rarity target:** 27% of filings and 42% of 30-day cards, because results season made almost every results card Important.
  - **Tightened:** results are judged on their numbers (PAT or revenue up or down 15%+ YoY, or a swing off a loss) instead of the triage score. HDFC Bank and Infosys (PAT +6%) are now Notable.
  - **Result:** Important is 10.7% of digest items on 7 days and 18.6% on 30 days. The 24-hour window (3 cards) is too small to hold to a share.
  - "Items" means cards plus folded filings, one per item, which is how the digest presents them.
- **Reasons name the rule, not the numbers.** The first reason line repeated the headline and the move chips. Results now say "PAT or revenue moved 15% or more YoY"; other cards give the category and materiality, or the stock move that decided it.

## Phase 4e: three voices on the company page (plan v2, item 2)
- **Why:** a scorecard row mixed three kinds of sentence with nothing to tell them apart: management's quote, the model's "Actual" line and the model's note. The model's line contains numbers, so it read as if it were a reported figure.
- **One visual rule per voice:**
  - reported figures stay plain tabular numbers (tiles, tables);
  - management's words are italic quotes on a grey rule with call and page;
  - FINN's read (outcome and note, the credibility paragraph, business, bull/bear and Ask FINN answers) sits on an accent rule, labelled "FINN's read" where it shares space with a quote.
  - A three-item legend under the company header says so once.
- **Outcome lines now link to the figures they rest on.** The verdict's evidence ids (`FY:2026-03`, `Q:2026-06`) render as "FY26 reported" chips that jump to the numbers section. A fixture test checks that every judged row cites only ids that exist.

## Phase 4f: deleting a contact, and a second account (plan v2, item 3)
- **Why:** the privacy rule "network data is the investor's own" was only claimed. There was one network and no way to remove anyone from it.
- **Owner on every row.**
  - The `owner_id` column already existed but everything read `demo`.
  - A request now names its account in `X-Finn-User`, checked against a fixed list and held in a context variable that every network query reads.
  - People named in public filings are stored once under `public`, because they are public facts. Contacts and relationships never are.
- **Bug avoided:** a sync FastAPI dependency runs in its own worker thread, so a context variable it sets is lost before the route runs. The dependency is async so the value lands in the request's context, which FastAPI then copies into the route's thread. The isolation tests would have failed without this.
- **Deletion is simple because nothing derived is stored.** Paths, overlaps, who-can-help, nudges and "knows" links are all computed on read. Deleting the person (roles and schools cascade) and every relationship row naming them removes them everywhere. The test checks each surface rather than trusting that argument.
- **Second demo account:** a different investor with three contacts (HDFC Bank, Trent, Manappuram). People has a two-way switch, plus "Restore the demo network" to undo removals.
- **Not done:** real sign-in and row-level security. The header is a demo switch and the docs say so.
