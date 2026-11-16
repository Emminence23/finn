# FINN: Financial Investment Agent

A mobile-first investor companion with three layers:
- **Push:** what changed across your portfolio today, and why you should care.
- **Pull:** research on any NSE company from its own disclosures (annual report, earnings-call transcripts, exchange filings), led by "did management deliver what they promised?" The multi-year financial tables are screener.in's standardised copy of the reported accounts, labelled as such; the latest quarter comes from the exchange filing itself.
- **Network:** who in your own network can help you understand it, and how you know them.

**Demo:** https://finn-iota-murex.vercel.app (passcode in the covering email). The free API host sleeps when idle, so the first load can take up to a minute.

> Spec: [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) · Architecture: [`docs/architecture.md`](docs/architecture.md) · Build history: [`docs/build-log.md`](docs/build-log.md) · Deploy: [`docs/DEPLOY.md`](docs/DEPLOY.md)

## 60-second tour
1. **Today** reads as a note, written in code from your filings, prices and positions. It opens with three short paragraphs: the last close ("Your portfolio ended 13 Nov, the last close, down 0.8% (₹41,719) at ₹53.7 lakh; Pidilite fell 3.4% and Polycab 2.2%."), what came in and whether any of it needs a decision ("Kaynes' profit fell 66% from a year ago, on revenue up 4%… Kaynes is a small holding (0.5% of your portfolio, ₹27,440), so there's nothing to act on."), and what is still open from earlier ("Bajaj Finance's fund raise and CG Power's legal case"), then three bands, each with its rule in a sentence: **Needs you** (Important, at a position of real size), **Worth knowing** (one line each, opened in place) and **Set aside** (routine paperwork and low-rated items, counted and named). On a quiet day, big events from the two weeks before stay in view under **Still open**, with their latest update (CG Power's closure order, then the court's stay). Pick any window, 24 hours to 30 days, or any dates (try 1–15 October for the Pidilite CFO change).
   Each item leads with a sentence, its size in your portfolio and why it made the cut; the evidence (the results table cross-checked against screener.in, the incoming person's background) is folded beneath. The contact who can explain it comes with two questions written from the item and an **Email** button with them already in it (Call and WhatsApp appear when FINN has a number). **Listen** reads the brief aloud in the phone's own voice; company pages, Portfolio, Watchlist and profiles have their own Listen too. On a return visit, new items are marked.
2. **Alert settings** (top right). Change the volume or price threshold and the feed re-ranks.
3. **Ask** is a chat. Type "Kaynes: promised vs delivered over the last four quarters": FINN replies in the thread with the four calls, oldest first, each with what was reported that quarter and the headline targets given on it, every target marked delivered, missed, can't tell or not yet due (measured in code against the reported number wherever the numbers settle it), the revisions along the way, and a summary written in code ("Of the 6 now due, 4 missed… Largest miss: FY26 revenue ₹3,626 Cr against ₹4,000 Cr guided"). Chips under each reply open the rest of the menu: business, financial snapshot, trajectory, balance sheet, cash quality, narrative vs numbers, guidance, bull vs bear. Follow-ups ("and the balance sheet?") stay on the same company; open "why" questions go to the cited Q&A. Every answer comes from the annual report, the last four calls and the reported numbers only.
4. **Ask → Kaynes → Full page** (the middle of the tab bar: Today · Portfolio · Ask · Watchlist · Network). The promise scorecard: FY26 revenue ₹3,626 Cr against ₹4,000 Cr+ guided, working capital 133 days against ≤85, each with the verbatim quote, call and page beside the reported number. Reported figures, management's words and FINN's own reading look different everywhere on the page. Below "Who you know", an off-the-record panel keeps what contacts told you apart from the evidence: it is never sent to the AI or cited.
   Under "The numbers", **Compare with DIXON** puts the two side by side: growth, margin, cash conversion, working capital, returns and each management's delivery score, with the better side of each row marked.
5. **Ask FINN** on the same page: "Why did receivables go up?" The answer cites call pages, and uncited points are removed by code.
6. **Ask → any other ticker** (e.g. TATAELXSI). FINN asks first, since a live read spends the day's shared AI budget, then reads its annual report and last four calls, with progress, in about a minute. A ticker that doesn't exist never spends a read.
7. **Network** (its own tab, or any name in the app). Search first, then who's worth a call, then everyone, each described by how you know them. The expertise map by theme, reconnect nudges, and profiles with "ask them about", "can introduce you to" and "Before you meet", which lists questions built from FINN's research, each showing its source. Open the Pidilite CFO: one of your contacts is also called Amit Agarwal, and FINN shows a "possible match" to confirm or dismiss instead of assuming they're the same person.
   On any profile, **Meeting soon?** takes a date: from two days before, Today opens with a prep card (what changed at the companies they know, and what to ask).
8. **Portfolio**. *As it stands* opens like a broker app: current value, invested, total returns and the day's returns, then the day's top movers and every holding with its shares, average price, last price and gain (sort by value, returns or 1D). Below that, a one-year chart against the Nifty 50 (+7.4% against −2.8% for the demo); warnings ("Lenders together are 38%"); everything else in one table, with themes and correlated pairs folded away. *Suggested* opens with one sentence ("Trim 8 and add to 10. 22.2% of the portfolio changes hands…"), then the larger changes, each explained, with the smaller ones folded. The same 18 holdings are re-weighted by code (balance risk, lean towards quality, stay within limits), then an **AI review** that read 40 recent filings nudges three, citing each one (CG Power's plant closure order, Kaynes' delivery record, HDFC Bank's Deputy MD leaving during its CEO change); a row shows the code's change and the AI's separately. *As it stands* also names holdings outside your own limits. **Edit** changes shares with − / + and recomputes the weights as you go, and **Reset to demo** can be undone; Today follows.
   **Watchlist** follows companies you don't hold (Persistent, Manappuram and Aarti in the demo): price, the day's move, a month's line and the latest filing that isn't paperwork. Tap **Watch** on any company page to add one.
   Every card and company page has **Share** (plain text with the filing link, for WhatsApp or mail). Add FINN to the home screen: once opened, the last brief still loads offline.
   On a first visit FINN asks what you'd like to do and runs a tour for it (check my morning, research a company, review my portfolio, use my network, or a quick look at everything); the Tour button at the top of Today asks again. Every page appears whole, behind a loading bar, once all its parts are in.
9. **Network → Yours.** Try it on your own network: type where you worked and studied, upload the `Connections.csv` LinkedIn lets you export, and every path, "who can help" and meeting question rebuilds around you. It's private to your browser, keeps no e-mails or profile links, and is deleted after 7 days. Switch to "Second investor" and every list changes, because each account sees only its own contacts. "Remove from my network" on a profile takes every link through that person with it, and "Restore the demo network" undoes it.

Anything an AI wrote carries an "AI · read from … · model" label. Numbers computed in code don't.

## Run locally
```bash
make setup                             # uv sync + npm install
cp backend/.env.example backend/.env   # add at least one LLM key (Gemini free tier works)
make seed                              # SQLite from committed fixtures, ~2.5s
make api                               # http://localhost:8000/health
make web                               # http://localhost:3000
make check                             # lint + tests + frontend build
```

## LLM providers are swappable
Every LLM call goes through one router (`backend/app/llm/`) and is named by **task**, not by model. `backend/config/models.yaml` maps each task to a tier (fast, mid or strong), and each provider to a model per tier.

| Want to… | Do this |
|---|---|
| Switch everything to Claude | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` |
| Use Claude only for the promise scorecard | `LLM_PROVIDER_PROMISE_VS_DELIVERY=anthropic` |
| Run locally on Ollama | `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=…` |
| Try a different model | `LLM_MODEL_GEMINI_FAST=<id>` |

Check the setup with `uv run python -m app.llm.cli routes | models <provider> | ping`. All outputs are cached in SQLite, so re-runs are free, and `/admin/costs` reports spend per task.

## Repo layout
```
backend/    FastAPI + SQLite: ingest, intel (Push), network, research (Pull), LLM router
frontend/   Next.js mobile-first PWA
docs/       Requirements, architecture, build log, deploy guide
```

## What I left out, and why
- **Live intraday data and push notifications.** The brief is end of day by design; NSE EOD files are free and reliable, while intraday feeds are paid.
- **Scraping LinkedIn.** It breaks LinkedIn's terms. The demo network is synthetic; your own network comes from the export LinkedIn gives every member, which you upload yourself.
- **An open-ended research agent.** A fixed pipeline with code-enforced citations is cheaper, cacheable and testable. The judgement step gets the strongest model instead.
- **An interactive network map.** A "could have", cut for time; paths are shown as hop-by-hop lines instead.
- **Real sign-in.** Two demo accounts show that networks are kept apart, but the switch is a header, not authentication. The production design (row-level security, encrypted per-user data) is in the architecture doc.

## Measured, not assumed
The same table lives in the app at **How accurate is FINN?** (Today's footer), where the first three rows are recomputed from the current data and each of the 100 labelled filings can be checked against where FINN puts it.

| What | Result | How |
|---|---|---|
| Material filings kept out of Routine | 25 of 25 | 100 portfolio filings, picked at random and labelled before the levels were tuned (`backend/data/fixtures/eval/materiality_labels.json`) |
| Share of items marked Important | 13.3% on 7 days, 18.8% on 30 days (target ≤ 20%) | Same digest, cards plus folded filings, one card per event |
| Filings decided by rules, with no LLM call | 454 of 517 | Ingested portfolio filings |
| Ask FINN finds the page that answers the question | 20 of 20 tuning questions; 9 of 11 held-out ones, written after the synonym list | 31 investor questions on 4 companies, answer pages marked by a pattern and checked by hand; the same ranking the app uses, no AI (`backend/data/fixtures/eval/retrieval_questions.json`) |
| People extracted from management-change filings | 7/7 people and roles, 17/18 prior employers, 8/10 schools | Hand-checked golden set |
| Promises found in Kaynes' calls, small vs mid model | 5 vs 10, including all 3 misses | Same calls, two tiers; the reason the scorecard uses the larger model |
| Cost on Claude | About $0.32 per new company analysis and $0.02 per question; filings about $0.03 a day for a 20-stock portfolio, shared | Per-call token log (`/admin/costs`); the demo itself ran on Gemini's free tier |

## Open questions for ENAM
- **Is a network private to one investor, or pooled across the team?** FINN keeps each investor's network separate and stores public filing people once. Pooling would be a sharing setting on top of that, not a rebuild, but who sees whose contacts is a policy call.
- **How should FINN treat a contact who works at the company now?** Today it marks them ("keep it to public information") and keeps meeting questions to public figures. A compliance team may want them hidden on restricted names, or every contact logged.
- **Are screener.in's standardised tables acceptable for history?** Every claim the AI makes cites the company's own documents, and the latest quarter is read from the exchange filing, but the multi-year tables behind growth, margins, cash conversion and gearing are screener.in's standardisation of the reported accounts. If that isn't acceptable, the history would be read from the annual reports and quarterly filings themselves: more parsing, and each number would carry its page.

## Where I'd take it next
- **A better voice brief:** a natural voice instead of the phone's built-in one, delivered as a podcast-style feed the evening before.
- **Calendar-aware prep:** read meetings from the investor's calendar (with consent) instead of asking them to note each one, and send the prep card the evening before.
- **Intraday triggers** for price and volume, plus filings polled through market hours.
- **Watchlist-wide scorecards:** rank every holding by how reliably its management delivers.
- **Richer network import:** past positions and schools from LinkedIn's full export (the connections file has only current roles), and contacts from a phone's address book with explicit consent.
