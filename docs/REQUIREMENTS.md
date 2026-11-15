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
| FR-PUSH-01 | Show every announcement across the portfolio for a user-selected window (24h default; 3d, 7d, custom) | M | Changing the window re-queries; count matches the source rows for that range |
| FR-PUSH-02 | Classify each announcement into the reference categories (17, incl. `unclassified`) | M | ≥90% agreement with a hand-labelled set of 40 filings |
| FR-PUSH-03 | Rank items by priority = f(category weight, materiality, network relevance) | M | Results, M&A and management change always rank above routine items |
| FR-PUSH-04 | Collapse routine categories (unclassified, postal ballot, AGM, investor meetings, newspaper ads) into a "Routine (n)" group | M | Collapsed by default; expandable |
| FR-PUSH-05 | Show a one-line, plain-English summary per non-routine item | S | ≤ 20 words; contains no facts absent from the filing |
| FR-PUSH-06 | Link each item to the original exchange PDF | M | Opens the NSE attachment |

### 3.2 Push: hero cards (`FR-CARD`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-CARD-01 | **Results card:** Revenue, EBITDA, PBT, PAT for the current quarter, with QoQ and YoY % | M | Numbers match the results filing or the screener table within 1%; % changes computed in code |
| FR-CARD-02 | Results card shows its data source and a cross-check badge (filing vs screener) | S | Badge = ✓ when both agree within 1% |
| FR-CARD-03 | **Management change card:** role, direction (in/out), short bio of the incoming person | M | Bio comes from the profile store; no invented facts |
| FR-CARD-04 | Management change card shows network overlap: worked with, studied with, or 2nd-degree path | M | Path is rendered with link strength |
| FR-CARD-05 | **Material event card** (M&A, capex, litigation, fund raise): best-placed contact plus a one-line "why" | M | "Why" cites a concrete overlap (company, role, years) |
| FR-CARD-06 | Other categories get a summary or no summary, based on materiality | S | Documented rule in code |

### 3.3 Push: alerts (`FR-ALERT`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-ALERT-01 | Volume alert when EOD volume ≥ *k* × its 20-day average (default *k* = 2.0) | M | Unit-tested on synthetic series |
| FR-ALERT-02 | Price alert when \|daily % change\| ≥ *x* (default 5%) | M | Unit-tested |
| FR-ALERT-03 | Category alert for user-selected material categories | M | Toggling a category updates alerts |
| FR-ALERT-04 | Thresholds are **user-configurable** in the UI and persisted | M | Survives reload |
| FR-ALERT-05 | Each alert shows *why it fired* (e.g. "Vol 2.7× 20d avg") | M | Visible on the card |
| FR-ALERT-06 | Alerts are evaluated after each EOD ingest (scheduled); the demo has a "Run EOD check" action | S | Endpoint is idempotent |
| FR-ALERT-07 | Web push notifications | C | — |

### 3.4 Pull: research (`FR-PULL`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-PULL-01 | Research view for **any NSE ticker** with screener coverage | M | A ticker outside the demo set completes end-to-end |
| FR-PULL-02 | **Primary sources only:** annual reports, concall transcripts, exchange filings, standardised financials | M | Every LLM claim carries a document and page reference; prompts forbid outside knowledge |
| FR-PULL-03 | **Financial snapshot:** revenue, EBITDA margin, PAT, ROE/ROCE, D/E (deterministic) | M | Computed from tables, not by an LLM |
| FR-PULL-04 | **Trajectory:** multi-year growth and margin trend | M | Sparkline plus 3/5-year CAGR |
| FR-PULL-05 | **Promised vs delivered** over the last 4 quarters: each promise → actual → verdict (Delivered / Partly / Missed / Too early) | M | Every verdict shows the verbatim quote, its source, and the actual number |
| FR-PULL-06 | **Cash quality:** CFO/PAT and FCF trend | S | Deterministic |
| FR-PULL-07 | **Balance sheet:** debt, D/E, working-capital days | S | Deterministic |
| FR-PULL-08 | **Business snapshot:** what they do, segments, revenue mix | S | Grounded in the AR |
| FR-PULL-09 | **Bull vs bear:** 3 points each, each cited | C | — |
| FR-PULL-10 | Progress streaming for live (uncached) research | S | UI shows step-by-step progress via SSE |
| FR-PULL-11 | Results cached per (ticker, document set, prompt version) | M | A repeat request for the same company returns in <1s |
| FR-PULL-12 | Natural-language question over one company's documents ("did they deliver on margin guidance?") | C | Answer is cited |

### 3.5 Network (`FR-NET`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-NET-01 | Onboarding inputs: past employers, alma maters, contacts (name, company, relationship, last contact), people met | M | Loaded from a JSON seed; the schema is documented |
| FR-NET-02 | Graph of people, companies and schools with derived **overlap edges** (same employer with overlapping tenure; same school with overlapping years) | M | Unit-tested overlap logic |
| FR-NET-03 | **Who can help with company X:** ranked contacts (worked there > competitor/supplier/customer > theme) with reasons | M | Shown inside Pull and on material-event cards |
| FR-NET-04 | **Paths to person P:** 1st and 2nd degree, with link strength | M | Shown on management-change cards |
| FR-NET-05 | **Entity resolution:** match a name in a filing to a profile (name + company + role), with a confidence score | M | Below the threshold → "possible match" label, never asserted |
| FR-NET-06 | **Expertise map:** contacts by theme | S | Query by theme returns a ranked list |
| FR-NET-07 | **Reconnect nudges:** contact not spoken to in >90 days whose current or former employer had a material event in the window | S | Nudge cites the event |
| FR-NET-08 | **Person page:** career timeline, overlaps with the investor, paths | S | — |
| FR-NET-09 | Diligence questions worth asking before meeting a person | C | — |
| FR-NET-10 | Interactive network map visualisation | C | — |

### 3.6 Application shell (`FR-APP`)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-APP-01 | Three-tab mobile navigation: **Today** (Push), **Ask** (Pull), **People** (Network) | M | Usable one-handed at 375px width |
| FR-APP-02 | Command bar in Ask accepting a ticker or a company name | M | Autocomplete from the NSE symbol list |
| FR-APP-03 | Installable PWA (manifest, icons) | S | "Add to Home Screen" works |
| FR-APP-04 | Demo passcode gate (protects LLM budget) | S | API rejects requests without the passcode |
| FR-APP-05 | Loading skeletons and empty and error states everywhere | M | No blank screens; no raw stack traces |

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
| NFR-07 | Security | Secrets only in env vars; `.env` is gitignored; CORS locked to the frontend origin; passcode on the API. |
| NFR-08 | Usability | Mobile-first (375–430px), dark-first theme, tabular numerals, ≥44px tap targets, WCAG AA contrast. |
| NFR-09 | Portability | The LLM provider can be swapped through config with no code change (§6.2). |
| NFR-10 | Maintainability | Typed Python (Pydantic models), ruff-clean, typed TS. Modules map to requirement areas. |
| NFR-11 | Politeness | Rate-limit scrapers (≤1 req/s per host), identify with a standard UA, cache aggressively, respect robots and terms. |
| NFR-12 | Observability | Structured logs. Per-LLM-call log of model, tokens, latency, cache hit; a cost summary endpoint. |

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
| M5 Deploy | 5 | NFR-01, NFR-07, FR-APP-04 | Public URLs work on a real phone |
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
