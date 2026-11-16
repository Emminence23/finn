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

## Blocked: Kaynes scorecard rebuild (plan v2, item 4)
- **What:** re-run `python -m app.research.service --fixtures --force KAYNES` so the scorecard is rebuilt with the v2 prompts (safety rule, statement types).
- **Tried 16 Nov 2026, 07:53 IST.** Extraction ran and found 32 statements and 28 promises due for checking. Then the scorecard step hit HTTP 429 on both models allowed for it (`gemini-4-hydrogen`, then `gemini-3.5-flash`), and the guidance step's fallbacks were also exhausted.
- **The build guard worked as designed.** The view was marked incomplete (`missing: promises`) and the fixture was **not** written, so the committed Kaynes view (4 missed, 1 can't tell, 4 not yet due) is still what the demo serves.
- **To finish:** after the free daily quota resets, run `make research` with `--force KAYNES`, check that the four misses are still found, re-run `make check` and commit the fixture. No paid model was used; Claude stays off unless the owner allows it.

## Phase 4g: same name, different person (FR-NET-05)
- **Gap found while checking PLAN_v2:** the spec listed entity resolution as a Must, but nothing linked a filing name to a contact. So the same-name trap could not happen, and it also could not be handled.
- **Rule:**
  - a contact who shares a filing person's normalised name is shown as a *question*;
  - it is "possible" when nothing else agrees and "likely" when an employer or school also agrees;
  - it becomes a direct "your contact" link only after the investor taps **Same person**, and **Not them** hides it.
  - Answers are stored per account, keyed by company and name so they survive a re-extraction, and are deleted with the contact or a reset.
  - Namesakes are kept out of the "via" paths, so nobody is shown as a route to themselves.
- **Planted cases:**
  - *Amit Agarwal*, a Jaipur chartered accountant in the main demo network, sits next to Pidilite's incoming CFO of the same name. He is "possible", with nothing else in the two records agreeing.
  - *Rajat Shah* in the second account shares Ingersoll Rand and IIT Guwahati with CG Power's new VP Services, so he is "likely".

## Phase 4h: a next action on every card (plan v2, principle 5)
- **Before:** every card ended in the same "Research →" link. The step that mattered (the new CFO, the scorecard, the contact who knows) was sometimes on the card and sometimes not.
- **Now:** `next_action()` in the digest picks one target per card, in code and in order of usefulness for that card's kind: person, contact, scorecard, filing, research. The card footer shows it.
- **Fix:** `#promises` links landed at the top of the page, because the browser jumps to the anchor before the view has loaded. The view now scrolls to the anchor itself once it renders.
- **Checked at 390px:** "Check their promises →" on a results card, "Call Karthik →" on the Kaynes M&A card. Footer items no longer wrap.

## Phase 4i: what contacts told you, kept apart (plan v2, Pull "Should")
- **Why:** an investor's best information about a company often comes from a call with a contact. FINN had nowhere to put it. Mixing it into the research would break the rule that every claim traces to a primary source.
- **Separation is structural, not a prompt rule:**
  - notes live in the network module, owner-scoped like contacts;
  - the research and Ask FINN code never import that module, so there is no code path from a note to a prompt;
  - a spy-model test confirms it.
- **Shown in their own place:** a dashed "off the record" panel under "Who you know", with "Karthik told you · date" attribution.
- **Privacy:** deleting a contact deletes the notes attributed to them and keeps the investor's own notes. Restoring the demo network clears all notes.

## Phase 4j: questions to ask before a meeting (FR-NET-09)
- **Built in code, not by the model.** The questions come from what the research already established: missed or revised promises, one negative flag, the next promise falling due. So the network never goes near an LLM, the feature costs nothing, and each question can show its source (call and page plus outcome, or "computed from reported financials").
- **Wording follows the relation:**
  - former employee: "From your time at Kaynes, was that ever realistic?";
  - current employee: public figures only, with the insider caution;
  - industry peer: "Was that specific to Aarti, or industry-wide?"
- **First version was repetitive:** three near-identical "they guided X and missed" lines. Now there are at most two misses, worded differently, plus one flag.
- **Coverage:** 11 of the 44 people visible to the main demo account get questions. That is everyone linked to a company with a research view; the rest get none rather than generic filler.

## Phase 4k: writeup brought up to date (plan v2, phase 6)
- README tour now covers priority levels, next actions, the three voices, off-the-record notes, meeting questions, the same-name check and the second account.
- Added **Measured, not assumed**: calibration, rule coverage, extraction accuracy, the model comparison and cost. Every figure is copied from this log or the architecture doc, not re-estimated.
- Added **Open questions for ENAM**: pooled vs private networks, current insiders, and whether screener.in counts as primary data. Each says what FINN does today.
- "Left out" no longer lists meeting questions or multi-user isolation, which are built. It says plainly that the account switch is not sign-in.

## Phase 4l: what's new since you last looked (FR-PUSH-10)
- **Why:** a brief you open every morning should say what's new and stay quiet about what you've already handled.
- **By card, not by time.** The demo clock is pinned to the latest filing, so "since 18:40 yesterday" would never change between visits. Read state is a list of card ids this browser has shown (the snapshot from earlier visits is taken once per page load) plus the ids the investor acted on.
- **Opened means acted on, not scrolled past.** Following a card's next action or its filing dims it on the next visit, like a read email. Cards merely scrolled past keep full weight.
- **Storage:** per-viewer browser storage, wrapped so a private window or blocked storage simply shows no marks. Bounded to the latest 500 ids.
- **Checked with a browser script:** first visit shows 0 marks; a return visit with two unseen cards shows "2 new" and two marks; after acting on the top card it shows "Opened" and is dimmed.

## Phase 4m: listen to the brief (FR-PUSH-11)
- **Script in code, voice on the phone.** `/digest/brief` turns the digest's top five cards into short spoken lines. The phone's speech engine reads them, so there is no LLM, no audio hosting and no cost, and the brief can only say what the cards say.
- **Written for the ear:** "rupees 40 crore", "66 percent year on year", "F Y 27"; "Also at Kaynes" instead of repeating the name; the contact to call once per company.
- **Bug found while checking:** a test browser couldn't replace `window.speechSynthesis` by plain assignment, so the first check silently used the real (silent) engine and saw no lines. The check now installs a fake engine with `defineProperty`, which also confirmed the app reads lines in order and resets the button.

## Phase 4n: bring your own network (FR-NET-12)
- **Why:** with a synthetic network, a reviewer has to take "who can help" on trust. With their own, they can check it against people they actually know.
- **Sandbox per browser.** The server creates the id (`u_` plus 16 hex characters), so a made-up id is refused. Sandboxes expire after 7 days and are purged with all their rows when the next one is created; the visitor can delete theirs at any time. The demo accounts stay read-only through these routes.
- **LinkedIn's own export, not scraping.** `Connections.csv` has a preamble before the header, so the parser finds the header line. It keeps name, company, position and the connection date. E-mail and URL are dropped before anything is stored, and a test searches the whole database for them.
- **Honest strength.** A LinkedIn connection is a weak link (0.3) with no tenure. Overlaps through it say "years unknown", the same as for filing people, so a hand-entered close colleague always outranks a bulk import.
- **Bugs found in the browser run:**
  - the year boxes inherited `w-full` from the shared input style and pushed the page to 1,478px wide at phone size. They now use their own fixed-width style;
  - accounts without stored alert rules got empty category alerts (the second demo account had been affected silently since 4f). Accounts with no rules now fall back to the defaults.
- **Checked end to end at 390px:** a single Hindustan Unilever stint produces "You and Amit both worked at Hindustan Unilever", and an imported Pfizer connection becomes the route to him.

## Phase 4o: compare two companies (FR-PULL-16)
- **Built from what was already computed.** `build_financials` gives every company the same snapshot, growth, cash and balance-sheet tables, so a comparison is a pairing plus rules: which direction is better for each row, and which gaps are big enough to say out loud. No LLM, no cost; works for all 21 companies with stored numbers and, live, any NSE ticker.
- **Refuses to compare what isn't comparable.** A bank's "margin", cash flow and gearing mean something else, so a lender against a non-lender drops those rows with a note rather than declaring a winner. Different financial year ends are flagged.
- **Bugs found:**
  - competitor links are stored as company names, so the first peer list for Kaynes was empty. Names are now resolved to tickers, with the same sector as a fallback;
  - the app's short-name rule turned "Dixon Technologies (India) Limited" into "Dixon ()". Fixed in both the frontend and the backend copies.
- **Checked at 390px**, light and dark: Kaynes vs Dixon (Dixon better on 8 of 10; Kaynes on margin and gearing) and HDFC Bank vs ICICI Bank (lender rows only).

## Phase 4p: meeting prep from a date (FR-NET-13)
- **Calendar-aware prep without calendar access.** The investor notes a meeting on a person's page. From two days before, Today leads with a prep card: what changed at the companies that person knows, and what to ask. A real calendar integration would only change where the date comes from.
- **Assembled in code** from the 30-day digest and the meeting questions, so nothing about who you're meeting goes to an LLM. Meetings are owner-scoped and deleted with the contact or a reset.
- **First version was too narrow:** for ex-Kaynes Karthik all three "what changed" lines were Kaynes filings, one of them boilerplate ("Approved un-audited ... results"). Now there are at most two per company, ordered with the companies they worked at first, and results say what the numbers did ("Profit down 66% year on year even as revenue grew 4%").
- **Tooling note:** `pkill -f "uvicorn app.main"` matched the shell running it and killed the command. Restarts go through the restart script.

## Phase 4q: how accurate is FINN, in the app (NFR-15)
- **Why:** the calibration numbers lived in the README and a test file. A reviewer using the app on a phone would never see them, and a README number can go stale.
- **Live where possible.** `/eval` recomputes priority calibration, the Important share and the screener cross-check from the current data on each request. It reuses the digest, so it measures exactly what the feed shows. Build-time measurements (rule coverage, people extraction, the model comparison) need a model run or hand check, so they are labelled with how and when.
- **Misses shown, not hidden.** The labelled set is listed filing by filing with FINN's current level. It shows that 25 filings labelled not material still appear as Notable or Important, which is the intended error direction (recall first), and says so.

## Phase 4r: the AI reads, code judges (FR-PULL-05a)
- **What prompted it:** the Kaynes rebuild after the quota reset (482 s) came back worse: 1 miss instead of 4, and 21 of 24 promises "too early". Two causes. Extraction varies between runs (this time the "FY26 revenue Rs 4,000 crore" promise wasn't extracted at all). And verdicts were the model's opinion even when they were plain arithmetic. The old fixture was kept. The rebuild had also been written to `research_cache`, which outranks the fixture, so that row was deleted too.
- **Change:** `research/measure.py` parses a promise's target into a check (measure, direction, threshold) and compares it with the reported figure at the deadline. It is narrow on purpose: segment names, "and", "market", flows judged on one quarter, lenders and anything not yet due return None, because a wrong code verdict looks more authoritative than a wrong AI one.
- **Result on stored builds:** every score unchanged (code and model agreed wherever both could judge). Kaynes' revenue, working-capital and cash-flow misses are now arithmetic with the reported row cited; the receivables miss stays with the model.
- **Next along the same line:** keep promises found by earlier builds when their quotes still match the transcript, so a rebuild can't forget a promise that was once extracted and verified.

## Phase 4s: portfolio page, suggested weights, editable holdings (FR-PORT-01..04)
- **Principle, from the user:** not everything needs the free AI key; deterministic algorithms first, AI to fine-tune. The page is code end to end. The model's one job is reading filings the optimiser can't, and its output is a bounded, cited nudge.
- **Optimiser choices:** equal risk contribution rather than mean-variance, because mean-variance needs return forecasts that six months of prices can't support and swings to corners. The covariance is shrunk halfway to constant correlation (18 names, 126 returns). The quality tilt is exp(0.3 × composite) so it leans rather than dominates. There's a 3-point step limit, so the suggestion is a move from today's portfolio, not a different portfolio.
- **Reasons were wrong at first:** "9% of the risk on 9% of the money (more risk than its weight)" compared risk with weight, while risk parity targets an equal share (1/18 = 5.6%). "Slow growth" was given as a reason for an increase. The reason is now built stage by stage (risk balance, tilt, limits), and an opposing factor reads "held back by" or "cut less thanks to".
- **AI review on the free tier:** one call, 40 filings. It made four trims of 0.3–0.9 points (CG Power plant closure order, Kaynes delivery and cash, HDFC Bank CEO change, Trent chairman retiring). Nothing was dropped. Stored by input hash and shipped as `fixtures/portfolio_review.json`.
- **Bug found in review:** the AI marker showed on most rows, because renormalising after four nudges moves every weight slightly. Now only the adjusted holdings are marked, with the AI's reason under the code's.
- **Holdings per account:** a `holdings` table; no rows means the demo weights. `digest._companies` and the alert queries read it, so Today follows an edit.

## Phase 4t: share, and offline (FR-APP-07, FR-APP-08)
- **Share** builds plain text in code from the card. It survives WhatsApp and mail and needs no image renderer. The first version repeated the title on the clipboard, and its "Copied" label pushed the next-action link into truncation. Now cards show a tick and announce "Copied" to screen readers only.
- **Offline split in two.** The worker caches only same-origin pages and static files. API data is saved by the app's fetch wrapper per account, because a worker can't see which account a cached API answer belonged to without parsing headers. The paths are whitelisted and small (the 7-day digest is 30 KB), so localStorage is enough.
- **Bug found offline:** "Waking the server…" appeared under the offline banner, because the health ping fails offline too. It now stays quiet when the browser reports offline.

## Phase 4u: first-visit tour (FR-APP-09)
- **Why:** FINN has grown to about 15 features, most a tap below the surface. A reviewer on a phone in a hurry will miss the scorecard, the portfolio suggestion and the accuracy page unless something points at them.
- **Targets are existing labels** (`#promises`, the View and Demo-account radio groups, the accuracy link) plus two `data-tour` attributes, so the tour doesn't need its own markup.
- **Bugs found walking it:** the first card and the accuracy link sat under the coach card. The accuracy link is at the bottom of Today and can't scroll higher, so the card moves to the top when the target stays low. The first card got pushed down by the meeting prep, which loads after the scroll, so placement runs again once the layout settles.

## Phase 4v: portfolio as positions, one-year chart, a calmer page; Today's toolbar
- **Asked for:** Tour and Accuracy moved up beside the alerts button, a light/dark toggle there, 14- and 21-day windows; a portfolio page that leads with invested, 6-month return and P/E, the rest in a table and folded sections; shares and prices instead of typing percentages; a one-year returns chart that looks good.
- **Positions, not weights.** `holdings` now stores shares and average cost; the demo is seeded under `__demo__` at the 13 Nov 2025 close (₹50 L). Weights are market value / total, so they drift with prices. Editing is − / + per lot (about 0.5% of the portfolio, rounded to 1, 2, 5, 10…) with weights recomputed in the browser; the server repeats the same arithmetic on save. Buys blend into the average cost; sells keep it.
- **A year of prices** (real, yfinance, stitched onto the existing six months with no adjustment drift) and the Nifty 50 for comparison. Risk still uses the last 126 sessions.
- **The >20% target wasn't reachable honestly.** Over this year the Nifty fell 2.8%; only two of FINN's 21 stocks rose more than 20%. Adding winners from outside would be visible hindsight, so the demo was re-weighted towards the stronger well-known names it already held (Titan, ICICI Bank, Bajaj Finance, Sun Pharma): +7.4%, 10 points ahead of the Nifty. With every holding at 1% or more, about +9% is the ceiling. The chart caption says the demo was bought on its first day.
- **Bug found:** a holding already above the 9% cap (Titan at 14% after its run) had its step band inverted, so the suggestion jumped it 5 points. Such holdings now move one full 3-point step towards the band. The AI review's limits now come from the same per-holding bands, stretched by its ±2 points, and the UI says when the limits left a nudge no room ("asked +1.0 pts, no room within the limits").
- **Theme reason wording:** a holding that rose but less than the tilt wanted read "trimmed to keep its theme within the cap"; now "held back".
- The suggestion changed, so the stored review no longer matched; one more free Gemini call regenerated it.

## Phase 4w: nothing hard-wired (portfolio rules and alert rules)
- **Asked for:** "Don't hard-wire limits." The 9% maximum, 20% theme cap, 3-point step, ±2-point AI nudge, 1.5× volume floor, OR-only alerts and the materiality-50 bar were all constants.
- **Portfolio:** `portfolio/settings.py` holds per-account rules with defaults; analytics reads them through `limits()`, which relaxes any rule that can't hold (and returns a note the page shows). Limits can be switched off (null). The AI review's nudge and count are settings too, written into its prompt; with the defaults the prompt is unchanged in meaning.
- **Alerts:** heavy, quiet or either volume, a chosen averaging window, up/down/either price, OR vs AND, and the filings' materiality bar. The API takes partial updates and only refuses what's arithmetically meaningless (a zero multiple, a percentage over 100).
- **Review key:** the stored demo review depends on its inputs, and Today's price-move levels depend on the account's alert rules, so a locally tuned account had a different key from a fresh seed. The fixture now holds the review under both keys; the output is the same model answer, with the same cited filings.
- **Follow-up:** the − / + lot and the size of a newly added company are settings too, set in the Edit sheet. Two bugs found in the browser check: both sizes shared one debounced save, so changing the second dropped the first (now batched), and "comes in at 5.5%" landed at 5.2% because buying grows the total (it now buys w / (1 − w) of the current value, in the browser and on the server).

## Phase 4x: deployed
- **API on Render** (free, Singapore, the closest region to India) from the `render.yaml` Blueprint; the private repo is shared with Render's GitHub app only. The image was built and run locally first: it seeds itself in about 6 s, idles at about 180 MB of the 512 MB, refuses requests without the passcode, and serves the stored AI review with no model call.
- **Web app on Vercel** (Hobby), with the API address set as a production env var.
- **Vercel refused the first deploy** because Next.js 15.5.4 has a known vulnerability. Upgraded to 15.5.29 and React 19.1.10 (`npm audit fix` for sharp too); `make check` passes. What `npm audit` still lists is PostCSS inside Next, which only processes FINN's own stylesheets at build time; the fix is Next 16, a major upgrade left for later.
- **Secrets** (the Gemini key) are entered in Render's dashboard, never in the repo or the chat.

## Phase 4y: a fresh reviewer's pass
- **How:** a new agent with no context used the live app on a 390px phone as a fund manager would and reported bugs, trust problems and ranked improvements. Everything below came from that report.
- **Numbers that disagreed, fixed:**
  - *Kaynes growth three ways.* The research view's tables stopped at Q1 FY27 (+40.6%), while Today had the Q2 FY27 results filed on 14 Nov (+4.4%). Compare had also been setting Kaynes' Q1 against Dixon's Q2 without saying so. A newer results filing is now added as the latest quarter, in code and on the same basis, for the research page and Compare; the page names the filing, and Compare flags different latest quarters.
  - *Unusual moves mixed days.* "+11.6% · Volume 2.27×" for Reliance took the price from 2 Nov and the volume from 3 Nov. Tiles and card chips now take one session and show its date. A card only shows moves from the sessions after its filing, and the Important reason dates the move.
  - *Card age.* A grouped card showed the newest filing's age next to an older headline; it now shows the headline filing's time.
  - *Theme labels.* CG Power was "semiconductors" (it has an assembly venture) and Kaynes wasn't with Dixon; Pidilite and Asian Paints were split across chemicals and staples. Now capital goods (CG Power, Polycab), electronics manufacturing (Kaynes, Dixon) and home improvement (Pidilite, Asian Paints); the three contacts who track paints and adhesives carry the new tag.
  - *Suggestion reasons.* "Held back to keep its theme within the cap" appeared for IT at 6% against a 20% cap. It now appears only when the theme is at the cap; otherwise the reason names the step limit slowing the larger cuts.
  - *Ask FINN* gave a receivables answer that contradicted itself. Code now marks any figure it can't find on the cited page, and the prompt asks for the date and basis when figures differ.
- **Improvements:** Today weighs position size (a 0.5% holding no longer ranks like a 12% one) and each card says its share of the portfolio; As it stands names holdings outside your own min and max; materiality, delivery and contact scores explain themselves where they appear; Ask FINN's wait shows stages; Compare lights the Ask tab; contact gaps use the same months on Today and People.
- **The stored AI review was regenerated** (one free Gemini call; the main model was at quota, so its free fallback answered): the same three nudges, CG Power −1.3, Kaynes −0.4 and Sun Pharma asked +1.0 with no room.
- **Follow-up, the rest of the list:**
  - *Today header:* "Filings to 15 Nov · …" instead of a bare date under "Today", and "Reading…" while a new window loads instead of the old window's summary. The window chips stay: 14d and 21d were asked for.
  - *Undo on Reset to demo:* reset returns the positions it replaced and a restore endpoint puts back the exact shares and buy prices (re-saving the shares would have re-bought them at today's price and wiped the gain).
  - *Day-first dates:* the range picker shows "1 Nov 2026" over the native picker, which otherwise follows the browser's locale.
  - *Number formats:* −₹3,167 Cr (true minus, before the rupee sign), 66.4× and 0.19×, ROE and ROCE to one decimal, and the gap to the Nifty computed from the rounded figures shown.
  - *Warm-up:* a scheduled GitHub Action keeps the API awake in market hours.
  - *Caught in the browser check:* Compare's footer said "No AI", but a filed quarter is read from the filing by AI. Compare now says which figures came from a filing, and the footer points to that note.

## Phase 4z: a second reviewer, on the backend
- **How:** an independent static review of the backend code. Each claim was checked against the code before acting; the ones that held are fixed below. Incremental ingestion, background jobs, schema migrations and hybrid retrieval were judged right for production and too large for now; they stay in the open list.
- **Financial safeguards:** growth over N years needs the year exactly N back (a missing year gave a wrong "3-year" figure); three-year cash conversion and free cash flow need all three years (missing years had counted as zero) and say how many they had; cash conversion isn't divided by a loss; negative net worth is flagged instead of reading as low gearing. No figure changed on the 21 committed companies, and synthetic tables test each case.
- **Research freshness:** the cache key covers every value in the financial tables as well as the documents, prompt versions and latest quarter, so a restated number triggers a rebuild. A stored view whose inputs have changed is still shown, marked out of date with a Rebuild button, instead of passing as current. The check reads committed fundamentals only, never a live fetch.
- **One card per event:** filings were grouped by company and category, so Kaynes' Vishay term sheet and its Toyokawa joint venture sat on one M&A card, and five HDFC Bank appointments on one. Filings now join the event whose summary is closest, if close enough and within a month; the threshold came from real pairs (same event 64 to 99, different 38 to 52). Today's Important share moved to 13.3% on 7 days and 17.1% on 30 (measured on a fresh seed with the default alert rules), both inside the 20% target.
- **Robustness:** the daily build budget's counter is locked, so two requests can't both take the last build; a model that fails with a server error or timeout now falls back like one out of quota, while a bad key stops at once; triage re-asks once for filings a batch left out and logs any still missing; ticker parameters are validated before use; contacts' roles and schools are filtered by owner in SQL, with indexes for the per-owner reads.
- **Honest sourcing:** the README and FR-PULL-02 called screener.in's standardised tables a primary source. They are a secondary copy of the reported accounts; the docs now say so and say which figures come from a filing.
- **The stored AI review was regenerated** (new cards): four nudges now, adding HDFC Bank −0.8 for its Deputy MD leaving during the CEO change.

- **Queued, by decision:** (1) a retrieval test for Ask FINN, 15–20 questions with their answering page, to measure BM25's hit rate before changing retrieval (then a finance synonym list if it misses, meaning-based search last); (2) a "path to production" section with each deferred item and its trigger: fetching only new filings when Today must update itself, versioned schema changes when user data must survive a deploy, a job queue when builds outgrow a request.

## Phase 5a: a UI/UX review, and Today rewritten as a note
- **How:** a fresh Fable 5.2 agent used the live app as a fund manager would (8:45 before the open, a commute, meeting prep) at 390 px and 360 px, light and dark. It was also told that a general-purpose model, given the same assignment, produced the same three tabs as FINN's first draft, and asked where FINN still looked like a template. Its verdict: honest and well made per component, but "a feed, plus a report, plus a contacts list"; on the 24-hour view three Kaynes cards about a 0.5% position led, while CG Power's closure order at 11% sat deep in Portfolio.
- **Today is a note now** (`intel/note.py`, code only). A lead paragraph, then Needs you / Worth knowing / Set aside, each with its rule in a sentence. Each item leads with a sentence that names the company and its numbers ("Kaynes' profit fell 66% from a year ago, on revenue up 4%"), then its size ("0.5% of your portfolio (₹27,440), so read it rather than act on it") and why it made the cut; evidence is folded. On a quiet day, big events from the 14 days before stay in view with their latest update (the closure order, then the court's stay). Moves are called unexplained only if the company filed nothing in the four days before: the first version said CG Power "rose 3.5% with no filing to explain it" two days after its court stay.
- **The person block acts.** Two questions written from the card, Email with them pre-filled, Call and WhatsApp when a number is known; "Call Deepak" no longer opens a profile. Demo contacts carry example.com addresses. A first attempt also kept e-mails from LinkedIn imports; a privacy test caught it and it was reverted.
- **Navigation:** Today and Portfolio, with an Ask FINN bar between them on every screen. People left the tab bar (the brief says the network "is not a separate app") and opens from Ask and from every name; its page leads with search, then who's worth a call, then everyone, described by how you know them. A question naming no company answers with today's note instead of "Name the company".
- **Bugs fixed:** opening an unread company started a live read without asking (and a mistyped ticker spent one); the gate showed a raw 401 and the tour behind it; Suggested showed "−4.1" next to "limited to your 3-point step" (the code's −3.0 and the AI's −1.1 are now two numbers); "Rs 18,987 million" beside "₹953 Cr"; "delivered 1, partly ½" read as a count; skeletons with no end; ambiguous dates; the tour hanging over the wrong page; page titles.
- **Suggested opens with a sentence** ("Trim 8 and add to 10…"), lists the changes of a point or more, folds the rest and "How this is built".
- **Default alert rules** lowered to 1.5× volume and 3% price: at 2× and 5% the live 7-day view had no moves. Important stays within target: 13.3% on 7 days, 18.8% on 30.
- **Legibility:** secondary text darkened to 4.9:1, section titles in sentence case, controls at least 32 px high and card actions 36 px.
- **The stored AI review was regenerated** (cards changed): three nudges, CG Power −1.1, Kaynes −0.4, HDFC Bank −0.8.
- **Not done from the review:** builds off the request worker and a cached digest (the job-queue item already queued), research for more holdings (AI cost), portfolio-level Ask, the call loop, promise due-dates on Today, a server-side "since you last looked", and a real 8:45 notification.

## Phase 5b: the two queued items
- **Ask FINN retrieval test** (`app/research/retrieval_eval.py`, no AI). 20 investor questions on Kaynes, Aarti, Persistent and Manappuram, each with a pattern for the answer's own wording, checked by hand against the pages. Plain BM25 found an answer page in the top 8 for 16 of 20: every question that used the documents' words (9 of 9), but only 7 of 11 that didn't ("How long do customers take to pay?" never reached "receivable days"; "How busy are the engineers?" never reached "utilization").
- **A synonym list fixed those:** 15 phrases that map an investor's words to a filing's, added at 0.6 weight so the question's own words still lead. Tuning set 20 of 20, first-ranked 15 of 20 (was 7).
- **Then 11 held-out questions,** written after the list and not used to change it: 9 of 11 with or without the list. The misses ("How much does Persistent return to shareholders?", "What does Manappuram pay to borrow money?") are exactly the gap a hand list leaves, so the list is recorded as fixing the questions it was written for, not as generalising. Embeddings stay the next step, with this test as the bar (architecture doc, "Path to production").
- **Path to production** is now a section of the architecture doc: incremental ingestion, migrations and a job queue, each with the moment it becomes necessary.

## Phase 5c: a tab bar again, and three ideas from a broker app
- **Why:** after Phase 5a, contacts were only reachable through Ask or a name, and in use they weren't found ("I don't see contacts"). The user also asked for features from Groww, the investing app they use.
- **Tab bar:** Today · Portfolio · Ask · Watchlist · Network, five tabs on every screen, Ask in the middle. FR-APP-01 records the reversal and why.
- **Holdings card:** Portfolio opens with current value, invested, total returns and 1D returns, then the holdings list open by default (shares, average, LTP with its day move, value, gain; sort by value, returns or 1D). 1D is the last close against the one before, computed per position in `portfolio/holdings.py`; the positions' day changes sum to the portfolio's.
- **Watchlist** (`portfolio/watchlist.py`, per account, no AI): Watch on company pages, Add from the companies the price snapshot covers. A company without prices is refused with the reason rather than shown blank. Each row carries the latest filing Today wouldn't set aside, using the same routine rule.
- **Top movers** across holdings and watchlist: on Portfolio and Watchlist, and at the foot of Today, not above the note, so the note still leads.
- **Not taken from Groww:** order placement, F&O, mutual funds, intraday charts. FINN doesn't trade, and the prices are end of day.

## Phase 5e: friends' feedback
- **"Summary is too brief and weirdly phrased."** The lead is now three short paragraphs: the last close (down 0.8%, ₹41,719, with Pidilite and Polycab), what came in with the items themselves and the holding's size, and what is still open. Phrases like "read it rather than act on it" and "Nothing new needs a decision" are gone; a second item about the same company says "Its board…" instead of repeating the name. A note about a past window leaves out the last close.
- **"Listen is on very few screens."** It was on Today only, and only when there were cards. It is now also on company pages, Portfolio, Watchlist and profiles, and on quiet days. One component, each screen's script written in code from what it shows.
- **"Progress circle."** A progress ring for every wait: it fills over the minute a sleeping server can take, spins with the elapsed seconds elsewhere, shows on Saving, and while Listen plays it tracks how far through the script it is.
- **"Tour is laggy."** At 4× CPU slowdown the card vanished for over a second on the way to Kaynes and could jump top-to-bottom 0.7 s into a step. Pages are now prefetched, the card stays up with "Opening Kaynes…", targets are found per frame rather than every 150 ms, and the card's side is fixed per step. Every card now shows within 0.2 s.
- **"Alerts not loading."** The settings sheet showed a grey block until the rules arrived and had no error state, so a failed or slow request (a sleeping server) left it grey forever. It now shows a ring, then an error with Try again; a failed save says so.

