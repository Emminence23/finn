# FINN: Requirements Specification

| | |
|---|---|
| **Product** | FINN, a Financial Investment Agent |
| **Version** | 1.0 (prototype) |
| **Status** | Approved for build |
| **Source brief** | `../../ASSIGNMENT.md` (ENAM Founding AI Engineer Build Challenge) |
| **Build plan** | `../../PLAN.md` |

This document defines **what** FINN must do and **how we'll know it works**. Requirement IDs (e.g. `FR-PUSH-03`) are referenced in code comments, tests and commit messages for traceability.

Priority uses **MoSCoW**: **M**ust (the demo fails without it) · **S**hould (expected; cut only under time pressure) · **C**ould (nice-to-have) · **W**on't (explicitly out of scope for v1).

---

## 1. Purpose and scope

### 1.1 Problem
1. Investors drown in filings, prices and announcements; the scarce skill is **filtering** to what matters.
2. Investors underuse their **personal network** because they can't see who knows whom or who worked where.

### 1.2 Product vision
FINN is a mobile-first daily companion that (a) **pushes** only what matters across a portfolio, (b) **pulls** grounded research on any NSE company on demand, and (c) weaves the investor's **network** into both, so every insight comes with "who can help me understand this".

### 1.3 Interaction point of view
> FINN is a **morning brief, not a dashboard**. Open it, see the 3–5 things that matter today, each with who to call. Everything routine is folded away. Research is one tap or one question away.

### 1.4 Primary user
A single **public-markets investor** (fund manager or analyst) at a lean firm, using a phone through the day. They are a power user with little patience, who wants density over decoration.

### 1.5 In scope (v1 prototype)
- A mock portfolio of 18 NSE companies and a research set of 4 companies
- Engine that generalises to **any NSE ticker** with public data
- Synthetic investor network (~50 contacts plus ~10 people named in filings)
- Responsive web app (PWA) deployed at a public URL

### 1.6 Out of scope (Won't, v1)
- Real-time intraday prices, order execution, portfolio P&L accounting
- Real LinkedIn integration or scraping (synthetic profiles only; see §6.4)
- Multi-user accounts, SSO, billing
- Native iOS/Android builds
- News, broker notes or any secondary research in Pull

---

## 2. Glossary
Financial terms follow the companion reference (`ASSIGNMENT.md` §9–10). Project-specific terms:

| Term | Meaning |
|---|---|
| **Card** | One prioritised item in the Push feed (filing, alert or nudge) |
| **Materiality** | 0–100 score of how likely an item is to matter to the investor |
| **Contact** | A person in the investor's network (first degree) |
| **Filing person** | A person named in a filing (e.g. an incoming CFO), not necessarily a contact |
| **Path** | A chain of relationships from the investor to a person (1st or 2nd degree) |
| **Promise** | A forward-looking, measurable statement by management in a concall or AR |
| **Window** | The time range of the Push digest (default 24h) |

---

## 3. Functional requirements

### 3.1 Push: digest (`FR-PUSH`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-PUSH-01 | Show every announcement across the portfolio for a user-selected window (24h default; 3d, 7d, 14d, 21d, 30d, custom) | M | Changing the window re-queries; count matches the source rows for that range |
| FR-PUSH-02 | Classify each announcement into the reference categories (17, incl. `unclassified`) | M | ≥90% agreement with a hand-labelled set of 40 filings |
| FR-PUSH-03 | Rank items by priority = f(category weight, materiality, network relevance, position size). A holding at an equal share counts 1×, a 0.5% position about ½×, a 12% one about 1.5×; each card says how much of the portfolio it is. A price or volume move is shown against a filing only if it came in the sessions after it (filed before the 15:30 close: that day; up to 4 days on), and a card's time is its headline filing's | M | Results, M&A and management change always rank above routine items; `test_review_fixes.py`: a 0.5% holding ranks below an equal-weight one on the same filing; a move from before the filing isn't attached |
| FR-PUSH-04 | Collapse routine categories (unclassified, postal ballot, AGM, investor meetings, newspaper ads) into a "Routine (n)" group | M | Collapsed by default; expandable. One card per event, not per category: results and earnings-call filings of a period stay together; other filings join an event only when their summaries are close (token-sort ≥ 60) within 30 days, so two deals are two cards and an order with its court stay is one |
| FR-PUSH-12 | **Today as a note** (added after the UI review; `intel/note.py`, code only): a lead paragraph assembled from computed fields, then **Needs you** (Important at a position of at least half an equal share), **Worth knowing** (the rest, one line each) and **Set aside** (routine plus Notable items rated under 30 with no price reaction, counted by kind). Each item's sentence names the company, the numbers and its size in rupees; on a quiet day, Important events at real positions from the 14 days before stay in view with their latest update; price moves are called unexplained only when no filing from the company in the four days before exists. AI summaries are rewritten to one unit (₹ Cr, true minus, ×) by code; quotes never are | M | Each band's rule tested on the 30-day digest; the quiet-day lead and the CG Power carry tested |
| FR-PUSH-08 | **Priority levels** (added in v2): each card is Important or Notable with a one-line reason naming what decided it; Routine is the folded group. Results are Important when PAT or revenue moves 15%+ YoY (or swings off a loss); management changes and material events at materiality ≥ 70; anything else at ≥ 85; any filing the stock moved on. Important cards sort first. An untitled investor presentation within 3 days of results joins the results card | M | Against 100 filings hand-labelled before tuning (`fixtures/eval/materiality_labels.json`): 25/25 material filings outside Routine (target ≥ 95%). Important is 10.7% of digest items on 7 days and 18.6% on 30 days (target ≤ 20%). `tests/test_priority.py` |
| FR-PUSH-09 | **Next action on every card** (added in v2, principle 5): code picks the one step a card leads to and the footer shows it. A management change goes to the incoming person ("See how you reach Amit"). A material event with a strong helper goes to that contact ("Call Karthik"). Results go to the promise scorecard when a research view exists ("Check their promises"), otherwise to a live build. An unplaced filing goes to the filing itself. Anything else goes to the research view. Section links scroll to the section once the view loads | M | `test_every_card_opens_a_next_action`: every 7d and 30d card has a label, a reason and a valid target; the Pidilite CFO card leads to the CFO's page |
| FR-PUSH-10 | **What's new since you last looked:** cards this browser hasn't shown before carry a "New" mark, with a count above the feed; cards whose next action or filing the investor opened are dimmed and marked "Opened". Tracked by card, not time, so it works on the pinned demo clock. Stored per viewer in the browser (a convenience, not shared state); with storage unavailable nothing is marked | S | Browser scenario: first visit marks nothing; a return visit with two unseen cards shows "2 new" and two marks; acting on a card dims it on the next visit |
| FR-PUSH-11 | **Listen to the brief:** Today read aloud by the phone's own speech engine. The script is written in code from the same digest (`GET /digest/brief`): the same top five items in the same order, numbers spelled for the ear (rupees, crore, percent, year on year), who to call, the price moves. No LLM and no cost. Hidden where the browser has no speech engine | S | `test_brief.py`: brief items match the digest's top five in order on 24h, 7d and 30d; no "%", "₹", "Rs", "YoY", "Cr" or "INR" left in the text; under two minutes; an empty window says so. Browser check with a fake speech engine: all lines are spoken in order and the button returns |
| FR-PUSH-07 | **Unsure is not routine** (added in v2): a filing the rules could not place stays visible, marked "Unclassified", unless the triage model read it and scored it as paperwork (materiality < 10). Unrelated unsure filings are never merged into one card | M | A deliberately odd filing stays visible (`test_unsure_filings_are_not_folded`). On the 30-day window this surfaced 9 filings that had been folded, including the Jio Platforms IPO price |
| FR-PUSH-05 | Show a one-line, plain-English summary per non-routine item | S | ≤ 20 words; contains no facts absent from the filing |
| FR-PUSH-06 | Link each item to the original exchange PDF | M | Opens the NSE attachment |

### 3.2 Push: hero cards (`FR-CARD`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-CARD-01 | **Results card:** Revenue, EBITDA, PBT, PAT for the current quarter, with QoQ and YoY % | M | Numbers match the results filing or the screener table within 1%; % changes computed in code |
| FR-CARD-07 | **No % off a loss or zero base** (added in v2): the card shows both values and words ("turned profitable", "loss narrowed") instead | M | A loss of 10 turning into a profit of 5 shows "turned profitable", not +150%; stored cards are recomputed on read |
| FR-CARD-02 | Results card shows its data source and a cross-check badge (filing vs screener) | S | Badge = ✓ when both agree within 1% |
| FR-CARD-03 | **Management change card:** role, direction (in/out), short bio of the incoming person | M | Bio comes from the profile store; no invented facts |
| FR-CARD-04 | Management change card shows network overlap: worked with, studied with, or 2nd-degree path | M | Path is rendered with link strength |
| FR-CARD-05 | **Material event card** (M&A, capex, litigation, fund raise): best-placed contact plus a one-line "why" | M | "Why" cites a concrete overlap (company, role, years) |
| FR-CARD-06 | Other categories get a summary or no summary, based on materiality | S | Documented rule in code |

### 3.3 Push: alerts (`FR-ALERT`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-ALERT-01 | Volume alert when EOD volume ≥ *k* × its 20-day average (default *k* = 1.5, lowered from 2.0 after review: at 2.0 a week of demo data showed no moves) | M | Unit-tested on synthetic series |
| FR-ALERT-02 | Price alert when \|daily % change\| ≥ *x* (default 3%, lowered from 5%: a large-cap moving 3% in a session is unusual) | M | Unit-tested |
| FR-ALERT-08 | **Corporate-action guard** (added in v2): no price or volume alert on a day whose move matches a split or bonus ratio, when the company filed a split or bonus in the prior 75 days | M | A 1:2 split day raises no alert; the same drop with no such filing still alerts |
| FR-ALERT-03 | Category alert for user-selected material categories | M | Toggling a category updates alerts |
| FR-ALERT-04 | Thresholds are **user-configurable** in the UI and persisted | M | Survives reload |
| FR-ALERT-05 | Each alert shows *why it fired* (e.g. "Vol 2.7× 20d avg") | M | Visible on the card |
| FR-ALERT-06 | Alerts are evaluated after each EOD ingest (scheduled); the demo has a "Run EOD check" action | S | Endpoint is idempotent |
| FR-ALERT-07 | Web push notifications | C | — |

### 3.4 Pull: research (`FR-PULL`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-PULL-01 | Research view for **any NSE ticker** with screener coverage | M | A ticker outside the demo set completes end-to-end |
| FR-PULL-02 | **The company's own disclosures:** annual reports, concall transcripts, exchange filings. Multi-year financial tables are screener.in's standardised copy of the reported accounts (secondary, labelled on every screen that uses them); a newer quarter is read from the exchange filing | M | Every LLM claim carries a document and page reference; prompts forbid outside knowledge; Compare and the research page say which figures come from screener and which from a filing. Open: reading the history from the filings themselves (see README, open questions) |
| FR-PULL-03 | **Financial snapshot:** revenue, EBITDA margin, PAT, ROE/ROCE, D/E (deterministic) | M | Computed from tables, not by an LLM |
| FR-PULL-04 | **Trajectory:** multi-year growth and margin trend | M | Sparkline plus 3/5-year CAGR |
| FR-PULL-05 | **Promised vs delivered** over the last 4 quarters: each promise → actual → verdict (Delivered / Partly / Missed / Revised / Can't tell / Not yet due / Not checkable) | M | Every verdict shows the verbatim quote, its source, and the actual number |
| FR-PULL-05a | **Code judges what it can measure.** The AI reads the calls (finds each promise, quotes it, gives its horizon). Whether a company-wide numeric target was met (revenue, revenue growth, margin, PAT, working-capital or debtor days, operating or free cash flow turning positive) is arithmetic, so code parses the target, reads the reported figure for the deadline and decides: met → Delivered, within 5% → Partly, otherwise Missed. Code's verdict replaces the model's; segment figures, launches and targets relative to a market keep the model's verdict. Each verdict says which judged it, and the scorecard says how many were judged by arithmetic. Runs on every read, so stored builds follow it without a model call | M | `test_research.py`: seven targets judged correctly (including "Rs 35 billion", a 2% shortfall → Partly, a range taking its lower bound); six left to the model (segments, two targets in one, relative to market, not yet due, one quarter of a flow); a code verdict that contradicts the model wins, says so, survives re-reading, and falls back to the model's without financials. Kaynes: 3 of its 4 misses are now arithmetic |
| FR-PULL-14 | **Three voices** (added in v2): reported figures, management's words and FINN's interpretation look different everywhere on the company page. Figures are plain tabular numbers; management's words are italic quotes on a grey rule with call and page; FINN's read (scorecard outcomes and notes, the credibility paragraph, business, bull/bear, Ask FINN answers) sits on an accent rule. A legend under the header says so once. Scorecard outcomes link to the reported figures they rest on | M | A reader can tell which voice a sentence is without tapping (checked at 390px, light and dark). Every judged scorecard row carries a quote and cites only ids that exist (`test_verdicts_rest_on_reported_figures_or_quotes_that_exist`) |
| FR-PULL-15 | **What contacts told you, kept apart from evidence** (added in v2): private notes per company, optionally attributed to a contact, in their own dashed "off the record" panel on the company page. They are never mixed into the research view, never sent to an LLM, never citable by Ask FINN, private to the account, and deleted with the contact they are attributed to | S | `test_notes.py`: notes are invisible to the other account; a contact's notes go when the contact is deleted while the investor's own stay; a spy model sees no note text in any Ask FINN prompt; the research view never contains a note |
| FR-PULL-16 | **Compare two companies** (PLAN v2 "Later"): `/compare?a=&b=` puts two companies side by side, computed in code from the same tables as the research view. Rows cover size, 3-year and latest-quarter growth, margin, cash conversion, free cash flow, working-capital days, gearing, ROE, ROCE, valuation and the management delivery score. Each row marks the better side (direction-aware; size and valuation pick none), and up to four sentences call out only large gaps. A lender against a non-lender drops the rows that mean something else for a bank and says so; different year ends are flagged. A results filing newer than the reported tables is added as the latest quarter (same basis only), here and on the research page, so Compare, research and Today show the same quarter; different latest quarters are flagged. Peers to compare with are the named competitors, then the same sector. No LLM | S | `test_compare.py`: Kaynes vs Dixon marks the higher margin and the fewer working-capital days, picks no side on size or P/E, and its sentence quotes the winning value; HDFC Bank vs Titan drops the five non-lender rows with a note; same ticker twice is refused; Kaynes' first peer is Dixon (resolved from the competitor name) |
| FR-PORT-01 | **Portfolio page** (new tab): the whole portfolio as it stands, computed in code from end-of-day prices and reported financials. Return over the price history and the last month, annualised volatility, worst fall, effective number of holdings, top-5 weight, weighted P/E, ROE and 3-year sales growth; weight and share of risk by theme and by holding; the most correlated pairs (linking to Compare); warnings for holdings above your maximum or below your minimum (named, largest first), a theme over your cap, lenders over it, a holding whose risk share is well above its weight, and pairs that move together. No AI | M | `test_portfolio.py`: weights, theme weights and risk shares each sum to 100; the demo shows the 38% lender warning and INFY/TCS as the most correlated pair |
| FR-PORT-02 | **Suggested portfolio, same holdings.** Code: equal risk contribution on a covariance shrunk halfway to constant correlation, tilted by a quality composite (returns on capital, growth, cash conversion, debt, earnings yield, delivery score; z-scored, capped ±2), then 2–9% per holding, 20% per theme, at most 3 points of change at a time. Each change gets a sentence naming its drivers stage by stage, and only the limit that actually binds ("held back to keep its theme within the cap" only when the theme is at the cap). Before/after volatility, largest theme, P/E, ROE and turnover. No return forecast | M | Weights sum to 100 and respect every bound; the same inputs give the same output; volatility falls; ERC equals inverse volatility when correlations are zero; TITAN (14% after a strong year, above the 9% cap) comes down the full 3 points; a holding outside 2–9% moves one full step towards it |
| FR-PORT-03 | **AI review of the suggestion, within code's limits.** Run only when asked. The model gets the suggestion, 30 days of material filings and records (delivery score, weak cash conversion), each with an id, and may propose at most 5 adjustments of ±2 points, each citing ids. Code drops unheld or uncited items, clips, re-applies the bounds and shows code-only and reviewed weights side by side with each adjustment's source. Stored by a hash of the inputs, so it never runs twice for the same portfolio and news; the demo's review ships as a fixture | M | A −5 request is clipped to −2; an adjustment citing an unknown id and one for an unheld company are dropped; the result sums to 100 within bounds; the review isn't run on read, runs once when asked and is served from storage after |
| FR-PORT-04 | **Edit your portfolio:** positions are shares and average buy price (dummy data for the demo); − / + buttons change shares by a lot worth about 0.5% of the portfolio, or type a number, and code recomputes value and weight per row as you go, with the buy and sell totals. Buying blends into the average cost at today's price; selling keeps it. Remove holdings, add any company FINN covers, adopt the suggested weights, or reset to the demo, which offers Undo for 20 seconds (the exact shares and buy prices come back; nothing is re-bought at today's price). Per account, like the network. Today's feed, ranking and alerts follow the account's holdings | M | Adding PERSISTENT and removing KAYNES in one account leaves the other untouched; Today stops treating KAYNES as held for that account only; unknown tickers 404; an empty portfolio is refused; reset restores the demo; `test_review_fixes.py`: undo after a reset returns the same shares and average costs. Browser check: edit, save, page follows, reset, undo |
| FR-PULL-13 | **Statement types and revisions** (added in v2): each promise is typed number, direction, dated milestone or not measurable; not-measurable statements get no verdict. A cited management update that revises, delays or withdraws a target makes the promise "Revised" before its deadline; after the deadline it is judged on the outcome with the revision shown beside it | M | Worked cases pass in CI (`test_worked_verdict_cases`): annual guidance mid-year, a cut before the deadline, a delayed milestone, a cut then missed, "lower costs" is not a cut, an update on another metric, a not-measurable statement |
| FR-PULL-06 | **Cash quality:** CFO/PAT and FCF trend | S | Deterministic |
| FR-PULL-07 | **Balance sheet:** debt, D/E, working-capital days | S | Deterministic |
| FR-PULL-08 | **Business snapshot:** what they do, segments, revenue mix | S | Grounded in the AR |
| FR-PULL-09 | **Bull vs bear:** 3 points each, each cited | C | — |
| FR-PULL-10 | Progress streaming for live (uncached) research | S | UI shows step-by-step progress via SSE |
| FR-PULL-17 | **Ask before a live read** (added after the UI review): an unread company shows what reading it involves and how many of the day's live reads are left; the read starts on a tap. A ticker that isn't NSE-listed is refused before the budget is touched | M | Tested: an unknown ticker leaves the budget unchanged |
| FR-PULL-11 | Results cached per (ticker, prompt versions, documents read, latest quarter, every value in the financial tables) | M | A repeat request for the same company returns in <1s. A view whose inputs changed since it was built is still shown, marked out of date, with a rebuild button; the check uses committed fundamentals only, so a read never triggers a live fetch |
| FR-PULL-12 | Ask FINN (was a "could"; promoted after review): a free-text question about a company, answered only from its documents and numbers. Ask routes a typed question to the right company | S | Every point cites a page, number or promise that was in the prompt; uncited points are removed in code; unanswerable questions say so. A figure in a point that code can't find on the pages it cites is shown under the point ("Not found on the cited page: 1,158"); the wait shows its stage and seconds |

### 3.5 Network (`FR-NET`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-NET-01 | Onboarding inputs: past employers, alma maters, contacts (name, company, relationship, last contact), people met | M | Loaded from a JSON seed; the schema is documented |
| FR-NET-02 | Graph of people, companies and schools with derived **overlap edges** (same employer with overlapping tenure; same school with overlapping years). Each link is **declared** (the investor recorded it) or **inferred** (two career records overlap); inferred links are worded as overlap, never "worked with" or "knows" | M | Unit-tested overlap logic and wording |
| FR-NET-03 | **Who can help with company X:** ranked contacts (worked there > competitor/supplier/customer > theme) with reasons. A contact who works at the company now is marked: they may hold unpublished price-sensitive information | M | Shown inside Pull and on material-event cards; the insider mark is unit-tested |
| FR-NET-14 | **Reach, not just a profile** (added after the UI review): the contact on a card comes with two questions written in code from the card's facts (a results swing, the incoming person) and Email with them pre-filled, Call and WhatsApp when a number is known. The demo contacts carry example.com addresses only; LinkedIn imports still keep no e-mails | M | No card action is labelled Call unless it can call |
| FR-NET-04 | **Paths to person P:** 1st and 2nd degree, with link strength | M | Shown on management-change cards |
| FR-NET-05 | **Entity resolution:** a filing person who shares a contact's name is shown as a match to check, never as the contact. "Possible match" when only the name agrees, "likely" when an employer or school also agrees; it becomes "your contact" only after the investor taps **Same person**, and **Not them** hides it. Answers persist per account, are cleared with the contact or a reset, and namesakes never appear as a path to themselves | M | `test_identity.py` on planted cases: a Jaipur accountant named Amit Agarwal next to Pidilite's incoming CFO is "possible" on the profile and the card, never a direct link; a second-account Rajat Shah sharing Ingersoll Rand and IIT Guwahati is "likely"; answers persist and cannot cross accounts |
| FR-NET-06 | **Expertise map:** contacts by theme | S | Query by theme returns a ranked list |
| FR-NET-07 | **Reconnect nudges:** contact not spoken to in >90 days whose current or former employer had a material event in the window | S | Nudge cites the event |
| FR-NET-08 | **Person page:** career timeline, overlaps with the investor, paths | S | — |
| FR-NET-09 | **Before you meet:** up to six questions on a person's page, built in code (no LLM, so nothing about the person leaves the server) from FINN's research on companies they know. Each question shows the call and page or computed flag it rests on and is worded by relation. Former employees are asked whether a target was realistic; people who work there now get questions on public figures only, with the insider caution; industry peers are asked whether an issue is company-specific | S ✅ | `test_diligence.py`: Karthik (ex-Kaynes) gets "former" questions on Kaynes misses with call, page and outcome; every question has a promise or flag basis; no model is called; current roles are marked as insiders |
| FR-NET-10 | Interactive network map visualisation | C | — |
| FR-NET-11 | **Owner's control and isolation** (added in v2, N-7): every network row carries its owner; a request sees only its own contacts and relationships, plus people named in public filings (stored once, shared). The investor can remove a contact; their paths, overlaps, who-can-help entries, nudges and "knows" links go with them, because all of those are computed on read. A second demo account (`X-Finn-User: demo2`, switch on People) shows the split. This is a demo switch, not sign-in; production takes the owner from auth and enforces it with row-level security | M | `test_network_privacy.py` on the seeded fixtures: the second account sees none of the first's contacts, gets 404 on their profiles and paths, and is never offered them as helpers in its digest; deleting a contact removes it from paths, helpers, nudges and other profiles and leaves the other account untouched; reset restores the demo |
| FR-NET-12 | **Bring your own network:** a visitor gets a private sandbox (created by the server, 7-day expiry, deletable at any time), enters their own employers and schools, and adds contacts by hand or by uploading LinkedIn's own Connections.csv export. Only names, employers, titles, years and how they know someone are kept: export e-mails and profile URLs are dropped on import. Paths, overlaps, who can help, nudges and meeting questions then run on their network. Imported connections are weak links (0.3) with years unknown, so they rank below anything declared by hand | S | `test_mine.py`: import keeps two of three rows (one has no company) and stores no e-mail or URL anywhere in the database; a Kaynes connection becomes the top helper and is marked an insider; saving a Hindustan Unilever stint creates a direct inferred path to Pidilite's CFO-designate; demo accounts refuse edits (403); a made-up sandbox id is refused; expired sandboxes are purged with all their rows. Browser run at 390px: switch to "Yours", save a career, upload a CSV, see the network and the CFO path; no horizontal scroll |
| FR-NET-13 | **Meeting prep from a date:** on a person's page the investor notes an upcoming meeting (date, optional topic). From two days before until the day, Today opens with a prep card: up to three material changes in the last 30 days at the companies that person knows (where they worked first, at most two per company, results stated as what the numbers did) and the first two "Before you meet" questions. Built in code from the digest and research; meetings are private to the account and deleted with the contact | S | `test_meetings.py`: a meeting tomorrow shows, one in nine days doesn't; the card lists Kaynes for ex-Kaynes Karthik with questions about Kaynes; another account sees nothing and can't delete it; deleting the contact removes the meeting; past dates and other accounts' contacts are refused |

### 3.6 Application shell (`FR-APP`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-APP-01 | Navigation (revised after the UI review): two places and a question. **Today** and **Portfolio** are tabs; the middle of the bar is an **Ask FINN** bar on every screen, for a company, a person, what someone knows, or a question. The network has no tab of its own: it opens from Ask and from every name ("the Network is not a separate app") | M | Usable one-handed at 360px width |
| FR-APP-02 | Command bar in Ask accepting a ticker or a company name | M | Autocomplete from the NSE symbol list |
| FR-APP-03 | Installable PWA (manifest, icons) | S | "Add to Home Screen" works; offline and PNG icons in FR-APP-07 |
| FR-APP-04 | Demo passcode gate (protects LLM budget). Locked, the screen shows only the passcode form, never the errors or tour behind it | S | API rejects requests without the passcode |
| FR-APP-05 | Loading skeletons and empty and error states everywhere. After 8 s a loading screen says why (waking, or busy with a live analysis) and offers a retry | M | No blank screens; no raw stack traces; no endless grey blocks |
| FR-APP-06 | AI labels: every LLM-written section says it is AI, what it was read from, and which model wrote it | S | Computed numbers never carry the label; a fallback model shows under its own name |
| FR-PORT-07 | **The investor's rules, not ours.** Largest and smallest holding, theme cap, most change at a time, quality tilt, risk window, the AI review's nudge size and count, the Edit sheet's − / + lot (default 0.5% of the portfolio) and a new holding's size (default 3% of the total after buying) are per-account settings (Your rules sheet; typed to two decimals or slider). Holding, theme and step limits can be switched off. Rules that can't hold for the portfolio (a 10% minimum across 18 stocks) are relaxed just enough and the page says so. The theme cap is also the concentration-warning line. The AI's limits go into its prompt and code enforces them; 0 switches the review off | M | `test_limits_are_the_investors_and_can_be_switched_off`, `test_ai_limits_follow_settings`; browser check: 14.5% max and no step saved and reflected, Defaults restores |
| FR-PORT-05 | **Lead with three numbers, fold the rest.** Invested (and value now), 6-month return and weighted P/E as tiles; a one-year chart; warnings; every other statistic in one table; By theme, Holdings (shares × price, buy price, gain) and Move-together pairs as folded sections | M | Browser check at 390px, light and dark: three tiles, chart, table, three sections closed until tapped |
| FR-PORT-06 | **One-year chart against the Nifty 50.** Value of the positions over a year of real end-of-day prices, beside the Nifty 50 scaled to the same start (one rupee axis); dotted line at the amount invested; touch or hover for a day's values. Risk statistics still use the last 126 sessions. The demo portfolio was weighted with hindsight towards this year's stronger stocks among the same 18 (no new companies): +7.4% against the Nifty's −2.8%. Keeping all 18 at 1% or more caps it near +9% | M | The curve starts at the amount invested and ends at today's value; 1-year return equals gain since bought; more than 240 days shown and 127 used for risk |
| FR-APP-07 | **Works offline once opened.** A service worker caches the app shell (pages and hashed static files, never API calls). The app saves the last good answer for Today's endpoints (digest, brief, meeting prep, portfolio) per account and serves it when the network fails, under a banner saying when it was saved. The "waking the server" note stays quiet offline. PNG and maskable icons for install | S | Browser check: load Today, go offline, reload: the same 4 cards and the meeting prep render under "Offline. Showing what FINN saved on 16 Nov, 02:05 pm"; the worker controls the page; the manifest lists 192, 512 and maskable icons |
| FR-APP-08 | **Share.** A share button on every card and on each company page. It builds plain text in code (what happened, why it matters, the key figures, the filing link; for a company, the delivery record and the missed promises with their numbers) and uses the phone's share sheet, or copies when there is none. Feedback on cards is a tick, so the footer never reflows | S | Browser check: the copied text for the Kaynes results card and the Kaynes page reads as above with the NSE filing URL |
| FR-APP-09 | **First-visit tour:** six steps over what a reviewer would otherwise miss (what makes a card, Listen, the promise scorecard, the portfolio and its suggestion, your own network, the accuracy page). Each opens its page and outlines its target, placed clear of the coach card. Shown once, only on a first visit to Today (a shared deep link opens straight on its page); the Tour button at the top of Today replays it; Skip or Done remembers | S | Browser check: all six steps land on the right page with their target outlined, in light and dark; after Done it doesn't return on reload; the replay link restarts it; a first visit to /c/KAYNES shows no tour |
| FR-ALERT-07 | **Flexible alert rules.** Volume: heavy (at least N× average, from 1.0×), quiet (at most N×), or either; average over 2–250 sessions. Price: up, down or either, by at least N% (0–100). Volume and price combine as OR (either alerts) or AND (only a day meeting both); the sheet states the rule in a sentence. Filing materiality threshold 0–100. Every number typed to two decimals or set with a slider; partial updates keep the rest | M | `test_alert_rules_low_volume_direction_and_and_or`, `test_alert_rules_api_takes_partial_updates_and_two_decimals`; browser check: Either + 1.25× + AND saved and described |
| FR-APP-10 | **Light/dark toggle** at the top of Today, next to Tour, Accuracy and alert settings (all moved up from the page footer). Starts from the phone's setting; a tap pins the other, remembered, applied before first paint | S | Browser check: toggling flips every token; reload keeps it with no flash |

---

## 4. Non-functional requirements (`NFR`)

| ID | Category | Requirement |
|---|---|---|
| NFR-01 | Performance | The Today feed loads in <2s on 4G (data is precomputed). Cached research loads in <1s. Live research finishes in <90s with visible progress. |
| NFR-02 | Reliability | **The demo never depends on live scraping.** Fixtures snapshot the demo universe; live fetch is an enhancement with graceful fallback. |
| NFR-03 | Cost | The entire build and demo run on free tiers. LLM calls are cached; every LLM step is behind a rules-first or deterministic path where possible. |
| NFR-04 | Accuracy | Numbers are computed in code, not generated by an LLM. LLM output that states a number must match a source value or be discarded. |
| NFR-05 | Grounding | Pull output carries citations. Unknown means "not disclosed", never a guess. |
| NFR-06 | Privacy | See §6.4. Network data never leaves the backend except as needed for display, and is **never sent to an LLM provider that trains on inputs**. |
| NFR-07 | Security | Secrets only in env vars; `.env` is gitignored; CORS locked to the frontend origin; passcode on the API. Ticker parameters must look like an NSE symbol before any route uses them in a path or URL; network rows are filtered by owner in SQL |
| NFR-08 | Usability | Mobile-first (375–430px), dark-first theme, tabular numerals, ≥44px tap targets, WCAG AA contrast. |
| NFR-09 | Portability | The LLM provider can be swapped through config with no code change (§6.2). A model that fails (quota, server error or timeout after its own retries, or invalid output twice) hands over to the next configured fallback; a bad key or permission error stops at once. Batched triage checks every filing came back once and re-asks for any missing |
| NFR-10 | Maintainability | Typed Python (Pydantic models), ruff-clean, typed TS. Modules map to requirement areas. |
| NFR-11 | Politeness | Rate-limit scrapers (≤1 req/s per host), identify with a standard UA, cache aggressively, respect robots and terms. |
| NFR-12 | Observability | Structured logs. Per-LLM-call log of model, tokens, latency, cache hit; a cost summary endpoint. |
| NFR-13 | Untrusted documents | Text inside a filing or transcript cannot steer FINN. Prompts mark document text as data; code validators drop any citation, evidence id or quote the model returns that code did not send. Tested with an "obedient" fake model (`test_instructions_inside_a_document_are_not_obeyed`). |
| NFR-14 | Freshness | Today shows how old filings and prices are; EOD prices are flagged once a finished trading session is missing (weekends skipped; exchange holidays not modelled). |
| NFR-15 | Visible accuracy | `/accuracy` in the app (linked from Today's footer) shows FINN's measurements. Live checks (priority calibration on the 100 labelled filings, Important share on 7 and 30 days, results figures against screener.in) are recomputed from current data on every request, so the page can't drift from the product. Build-time measurements say how and when they were taken. Every labelled filing is listed with its label, FINN's current level and a link to the filing, misses included. `test_evals.py` checks the page reports what the calibration tests assert. |

---

## 5. Data sources (verified 2026-11-16)

| Source | Use | Access | Status |
|---|---|---|---|
| **Yahoo Finance via `yfinance`** | EOD OHLCV, 6-month history | Python library, `SYMBOL.NS` | ✅ All 21 demo tickers return data |
| **NSE corporate announcements API** `nseindia.com/api/corporate-announcements` | Push feed: filings with `desc` (exchange category), `attchmntText` (subject), `attchmntFile` (PDF), `sm_isin`, `smIndustry` | JSON. Needs a cookie-primed session (GET homepage first). Supports `symbol`, `from_date`, `to_date` (DD-MM-YYYY), or all equities | ✅ Per-symbol and market-wide queries work; PDFs download from `nsearchives.nseindia.in` |
| **BSE announcements API** | Backup feed | JSON | ❌ 403 Access Denied (bot protection). **Not used**; NSE is the single filings source |
| **screener.in company page** `/company/{SYM}/consolidated/` | Quarterly table (Sales, Operating Profit ≈ EBITDA, PBT, Net Profit; ~12 quarters), annual P&L, balance sheet, cash flow, ratios, plus links to **annual reports**, **concall transcripts**, PPTs and quarterly result PDFs | HTML scrape (BeautifulSoup) | ✅ Verified on SRF: 13 quarterly rows, 46 concall entries, 15 ARs, transcript PDFs hosted on company IR sites |
| **Company IR sites / NSE archives** | Transcript and AR PDFs (linked from screener) | Direct PDF download | ✅ |
| **NSE equity symbol list** (`EQUITY_L.csv` from NSE archives) | Ticker autocomplete and validation | CSV | To verify in Phase 1 |
| **Network profiles** | Contacts and filing people | **Synthetic JSON** (LLM-generated from a schema, hand-edited for demo overlaps) | Decision: §6.4 |

**Compliance note:** NSE and screener.in data are used for a non-commercial prototype at low request volume with caching. A production system would license exchange data (an NSE data feed or a vendor) and fundamentals (a vendor API). This goes in the writeup.

---

## 6. Architecture and design constraints

### 6.1 System overview
```
          ┌──────────────── Ingest (scheduled jobs) ─────────────────┐
yfinance ─┤ prices.py        → prices                                 │
NSE API  ─┤ announcements.py → announcements (+ PDFs in cache/)       │
screener ─┤ fundamentals.py  → financials, documents (+ PDFs)         │
seed JSON─┤ network.py       → people, roles, education, relations    │
          └──────────────────────────┬──────────────────────────────┘
                                     ▼
                 ┌────────── Intelligence layer ──────────┐
                 │ classify → prioritise → enrich cards   │
                 │ alerts engine (rules)                  │
                 │ entity resolution  ↔  network graph    │
                 │ research pipeline (extract → analyse)  │
                 └──────────┬─────────────────────────────┘
                            ▼
          SQLite (+ LLM cache) ──► FastAPI (REST + SSE) ──► Next.js PWA
```

### 6.2 LLM provider abstraction
- One interface: `llm.complete(task, messages, schema=None, docs=None) -> Result`.
- **Routing is by task, not hard-coded model:** `config/models.yaml` maps each task to a provider and model:

| Task | Tier | Volume | Notes |
|---|---|---|---|
| `classify_filing` | small/fast | high | Only for filings the rules can't classify |
| `summarise_filing` | small/fast | high | One-liners |
| `extract_results` | small/fast + PDF/text | medium | Numbers validated in code |
| `extract_person` | small/fast | low | Name, role, direction from management-change filings |
| `extract_guidance` | small/fast, long context | medium | Per transcript; cached per document |
| `promise_vs_delivery` | **strong reasoning** | low | The hero analysis |
| `business_snapshot`, `bull_bear` | mid | low | Cited |
| `synth_profiles` | any | one-off | Build-time only |

- The provider is chosen in config (see §6.3). Adapters: Anthropic, Google Gemini, OpenAI-compatible (covers Groq, OpenRouter, Ollama).
- **Cache:** key = sha256(task, model, prompt_version, input); stored in SQLite. **Every result is reproducible offline.**
- Structured outputs are validated with Pydantic; a failed validation triggers one retry and is then rejected.

### 6.3 LLM provider decision (pending the user's key)
| Option | Cost | Fit | Privacy |
|---|---|---|---|
| **Google Gemini API free tier** (AI Studio key) | Free, rate-limited | Flash/Flash-Lite for bulk, long context, native PDF input | Free-tier inputs may be used to improve Google products → **no network PII sent** |
| **Groq free tier** (OpenAI-compatible) | Free, ~30 RPM / ~1k RPD per model | Very fast; good for classification and summaries | Check terms |
| **OpenRouter `:free` models** | Free, ~50 RPD | Fallback only | Varies by upstream |
| **Ollama local** | Free | Small models on CPU; slow | Best: nothing leaves the machine. Candidate for entity resolution |
| **Anthropic API** | Paid (separate from claude.ai subscription; some plans include monthly API credits) | Best-fit routing (Haiku 5.5 bulk / Opus 5.5 reasoning) | Not trained on API data by default |

**Default plan:** Gemini (bulk + reasoning) as primary, Groq as fast fallback, all through the abstraction. Swapping in Anthropic later is a config change. PII-touching steps (entity resolution) are deterministic first (rapidfuzz), and any LLM help receives only the filing text, never the investor's contact list.

### 6.4 Privacy and security design
- **Synthetic profiles** for the demo. Production: user-supplied contacts (consent rests with the user), official LinkedIn APIs or user data exports, no scraping.
- **Data minimisation:** store professional fields only (roles, employers, education, tenure, themes). No personal contact info.
- **Isolation:** the network is scoped to one investor (`owner_id` on every network row). Production: row-level security plus encryption at rest.
- **Retention:** filing-person bios expire after 90 days; a contact is hard-deleted when removed.
- **LLM boundary:** network data is never sent to free-tier providers. Graph reasoning is code (networkx); the LLM only phrases "why" from facts the code selected.

### 6.5 Data model (core tables)
`companies(symbol, name, isin, sector, industry, in_portfolio, weight)` ·
`prices(symbol, date, open, high, low, close, volume)` ·
`announcements(id, symbol, ts, exch_category, subject, pdf_url, category, materiality, summary, enrichment_json)` ·
`financials_quarterly(symbol, period, revenue, ebitda, pbt, pat, source)` ·
`financials_annual(...)` · `documents(id, symbol, kind, period, url, local_path, sha256)` ·
`people(id, name, headline, is_contact, themes)` · `roles(person_id, company, title, from, to)` ·
`education(person_id, school, program, from, to)` · `relationships(owner_id, person_id, type, strength, last_contact)` ·
`company_links(symbol, other, kind: competitor|supplier|customer)` ·
`alert_rules(owner_id, kind, params_json, enabled)` · `alerts(id, rule_id, symbol, ts, reason, payload)` ·
`llm_cache(key, task, model, prompt_version, output_json, tokens_in, tokens_out, created_at)`

### 6.6 API contract (v1)
| Method | Path | Purpose | Req |
|---|---|---|---|
| GET | `/health` | Liveness and warm-up | — |
| GET | `/digest?window=24h` | Ranked cards plus routine group | FR-PUSH, FR-CARD |
| GET | `/alerts` · PUT `/alert-rules` · POST `/alerts/run` | Alerts | FR-ALERT |
| GET | `/companies?q=` | Autocomplete | FR-APP-02 |
| GET | `/research/{symbol}` · GET `/research/{symbol}/stream` (SSE) | Pull | FR-PULL |
| GET | `/people/help?symbol=` · `/people/{id}` · `/people/{id}/paths` · `/people/expertise?theme=` · `/people/nudges` | Network | FR-NET |
| GET · POST · DELETE | `/people/account` · `/people/reset` · `/people/{id}` (header `X-Finn-User`) | Account switch, restore demo network, remove a contact | FR-NET-11 |
| GET | `/admin/costs` | LLM usage summary | NFR-12 |

---

## 7. Engineering practices

| Area | Standard |
|---|---|
| **Repo** | Monorepo: `backend/`, `frontend/`, `docs/`. Conventional Commits (`feat(push): results card [FR-CARD-01]`). |
| **Branching** | Trunk-based on `main` with short-lived feature branches per phase; squash merges. |
| **Python** | 3.12, `uv`, Pydantic models at every boundary, `ruff` (lint + format), type hints throughout. |
| **TypeScript** | Strict mode, ESLint, Tailwind tokens; API types defined once in `src/lib/api.ts`. |
| **Testing** | `pytest` unit tests for deterministic logic (alerts, QoQ/YoY math, overlap edges, path finding, entity resolution, classifier rules). A golden set of ~40 labelled filings for the classifier. **LLM calls are mocked in tests** (replayed from cache). One API smoke test per endpoint. |
| **CI** | GitHub Actions on push: ruff, pytest, `next lint`, `next build`. |
| **Config** | 12-factor: env vars for secrets and URLs; `models.yaml` for routing; `.env.example` committed. |
| **Docs** | `REQUIREMENTS.md` (this), `architecture.md` (+ diagram), `build-log.md` (AI build history), ADR-style decisions in §9 below. |
| **Definition of done** | Linked to a requirement ID, tests pass, works at 375px, no console errors, logged in the build log if an AI course-correction happened. |

---

## 8. Milestones and traceability

| Milestone | Phase (PLAN.md) | Requirements delivered | Exit check |
|---|---|---|---|
| M0 Setup | 0 | NFR-07, NFR-10 | ✅ Envs build; tickers verified |
| M1 Data | 1 | §5 sources, FR-NET-01, NFR-02, NFR-11 | ✅ `make seed` fills SQLite from fixtures in ~2.5s |
| M2 Push + Network | 2 | FR-PUSH-01..06, FR-CARD-01..05, FR-ALERT-01..05, FR-NET-02..05, 07 | ✅ `/digest` returns ranked, enriched cards; people eval 7/7 roles, 17/18 employers |
| M3 Pull | 3 | FR-PULL-01..05, 10, 11, FR-NET-03 inside Pull | 🟡 Research set precomputed (4/4). An unseen ticker (TATAELXSI) builds live in 19s via SSE. Its scorecard is pending a quota reset or the Claude budget |
| M4 Frontend | 4 | FR-APP-01..05, all UI surfaces | ✅ Today, Ask, company research, People and profile screens checked at 390px in light and dark: no horizontal scroll, no console errors |
| M5 Deploy | 5 | NFR-01, NFR-07, FR-APP-04 | 🟡 Live: web on Vercel, API on Render (Singapore). Passcode gate, Today, Portfolio, People and a company page checked at 390px against the live URLs, no horizontal scroll. Real-phone check pending |
| M6 Submission | 6 | Writeup items from the brief | README, architecture doc, build log, email draft |

---

## 9. Decision log (lightweight ADRs)

| # | Decision | Alternatives | Rationale |
|---|---|---|---|
| D1 | FastAPI + Next.js PWA | All-Python HTMX; Expo | Python suits data and LLM work; a PWA is the easiest for reviewers to open on a phone |
| D2 | SQLite plus a committed fixture snapshot | Postgres/Supabase | Zero ops; demo reliability; swappable |
| D3 | NSE as the single filings source | BSE | BSE API returns 403; NSE verified working |
| D4 | screener.in for fundamentals and document links | Company IR sites directly | One consistent structure for any ticker → generalises |
| D5 | Synthetic network profiles | Scraping LinkedIn; public datasets | Respects platform terms; lets us plant demo overlaps; documented as synthetic |
| D6 | Provider-agnostic LLM layer with task-based routing | Hard-code one vendor | Free-tier constraints today; a cost/quality swap later is config-only |
| D7 | Numbers computed in code; LLM only extracts and explains | LLM computes deltas | Accuracy (NFR-04) and auditability |
| D8 | Network reasoning in code (networkx), LLM only phrases it | LLM over the whole contact list | Privacy (NFR-06), determinism, cost |
| D9 | Hosted free-tier LLMs (Gemini primary), optional ≤$10 Anthropic for `promise_vs_delivery`; no rented GPU | Cloud GPU running Ollama | The demo must answer whenever reviewers open it; an always-on GPU costs more than the API budget. Ollama stays a supported provider via config |
| D10 | Quota-aware fallback chain per tier (`fallbacks` in models.yaml); an incomplete research view is flagged and never cached | One model per tier; cache whatever came back | Free tiers allow as few as 20 requests per day per model. One research build uses about 6 mid-tier calls. Partial results must not stick |
| D11 | Promise verdicts limited to evidence ids supplied by code; a verdict of "missed" before the deadline needs a management update | Let the model judge freely | Stops plausible but unfounded verdicts. Every verdict is traceable to a quote and a number |

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| NSE starts blocking mid-build | Med | High | Snapshot fixtures early (Phase 1, first hour) |
| screener.in rate-limits | Med | Med | Cache HTML and PDFs; ≤1 req/s |
| Free-tier LLM rate limits during the backfill | High | Med | Rules-first classifier; cache; spread across providers |
| Scanned or odd results PDFs | Med | Med | Fall back to the screener quarterly table and label the source |
| LLM invents facts in Pull | Med | High | Citations required; numbers from tables; validation rejects mismatches |
| Render cold start during review | High | Med | Warm-up ping and splash |
| Time overrun | High | High | Cut lines per phase (PLAN.md); MoSCoW priorities above |
