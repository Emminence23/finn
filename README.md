# FINN: Financial Investment Agent

A mobile-first investor companion with three layers:
- **Push:** what changed across your portfolio today, and why you should care.
- **Pull:** research on any NSE company from its own disclosures (annual report, earnings-call transcripts, exchange filings), led by "did management deliver what they promised?" The multi-year financial tables are screener.in's standardised copy of the reported accounts, labelled as such; the latest quarter comes from the exchange filing itself.
- **Network:** who in your own network can help you understand it, and how you know them.

**Demo:** https://finn-iota-murex.vercel.app (passcode in the covering email). The free API host sleeps when idle, so the first load can take up to a minute.

> Spec: [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) · Architecture: [`docs/architecture.md`](docs/architecture.md) · Build history: [`docs/build-log.md`](docs/build-log.md) · Deploy: [`docs/DEPLOY.md`](docs/DEPLOY.md)

## 60-second tour
1. **Today** reads as a note, written in code from your filings, prices and positions. It opens with three short paragraphs: the last close ("Your portfolio ended 13 Nov, the last close, down 0.5% (₹26,908) at ₹51.0 lakh; Tata Motors fell 3.3% and Vodafone Idea 3.1%."), what came in and whether any of it needs a decision ("Bajaj Finance closed QIP raising funds… Bajaj Finance is 6% of your portfolio, ₹3.3 lakh."), and what is still open from earlier ("Titan's management change (7% of your portfolio) and BHEL's expansion (6%)"). The note sits folded under the greeting, which follows the time in India (good morning from 4 am, afternoon from noon, evening from 4 pm, "Up late?" after 10 pm), then three bands, each with its rule in a sentence: **Needs you** (Important, at a position of real size, one card per stock with its other news beneath), **Worth knowing** (one line each, opened in place) and **Set aside** (routine paperwork and low-rated items, counted and named). On a quiet day, big events from the two weeks before stay in view under **Still open**, with their latest update (BHEL's Adani Power orders, then the Power Grid order). Pick any window, 24 hours to 30 days, or any dates (try 1–15 November for Dabur's CEO change).
   Each item leads with a sentence, its size in your portfolio and why it made the cut; the evidence (the results table cross-checked against screener.in, the incoming person's background) is folded beneath. The contact who can explain it comes with two questions written from the item and an **Email** button with them already in it (Call and WhatsApp appear when FINN has a number). **Listen** reads the brief aloud in the phone's own voice; company pages, Portfolio, Watchlist and profiles have their own Listen too. On a return visit, new items are marked.
2. **Why, and who can help** (under any card). The signal behind the card: a 0–100 attention score built from six visible parts (kind of event, size of the money against a yardstick, strategic weight, surprise, time pressure, your exposure), each part with its sentence or marked unknown; the facts with the sentence they came from; and who in your own network may help, ranked by company overlap, role fit for this kind of event, sector, recency and how well you know them, first and second degree, each saying what they may give context on and what is unknown. Mark it useful, not useful or wrong category; feedback stays with your account. Ask "Who in my network can help me understand Dabur's CEO change?" for the same ranking in the chat.
3. **Alert settings** (top right). Change the volume or price threshold and the feed re-ranks.
4. **Ask** is a chat. Type "L&T: promised vs delivered over the last four quarters": FINN replies in the thread with the four calls, oldest first, each with what was reported that quarter and the headline targets given on it, every target marked delivered, missed, can't tell or not yet due (measured in code against the reported number wherever the numbers settle it), the revisions along the way, and a summary written in code ("Of the 7 now due, 1 missed and 6 can't be settled from the reported numbers; 12 fall due later… Largest miss: FY26 revenue growth 11.8% vs 15% guided"). Chips under each reply open the rest of the menu: business, financial snapshot, trajectory, balance sheet, cash quality, narrative vs numbers, guidance, bull vs bear. Follow-ups ("and the balance sheet?") stay on the same company; open "why" questions go to the cited Q&A. Every answer comes from the annual report, the last four calls and the reported numbers only.
5. **Ask → L&T → Full page** (the middle of the tab bar: Today · Portfolio · Ask · Watchlist · Network). The promise scorecard: FY26 revenue growth 11.8% against 15% guided, the Hyderabad Metro handover signed but late, each with the verbatim quote, call and page beside the reported number. Reported figures, management's words and FINN's own reading look different everywhere on the page. Below "Who you know", an off-the-record panel keeps what contacts told you apart from the evidence: it is never sent to the AI or cited.
   Under "The numbers", **Compare with BHEL** puts the two side by side: growth, margin, cash conversion, working capital, returns and each management's delivery score, with the better side of each row marked.
   **What brokers expect** (same page, L&T): 12 reports from ICICI Securities, PL Capital, Motilal Oswal and Sharekhan, read from the brokers' own public servers. Ratings, the 12-month target range (₹4,400 to ₹4,710 against a last close of ₹4,144) with PL's target, which states no horizon, kept apart rather than pooled; each house's latest view with a **Source** drawer showing the sentence and page every figure came from; revisions (ICICI ₹5,000 → ₹4,710; Motilal keeps BUY while trimming EPS); where estimates differ most; and why, an AI explanation whose every figure code checks against the reports it cites. The track record says "Track record unavailable — insufficient comparable observations." because no 12-month target has run its course yet; FY26 forecasts made in January are shown against what L&T then reported, without a ranking. Ask "What do brokers expect for L&T?" for the same in the chat. In your own space, **Add a report** reads a PDF you may use and keeps it private to you.
6. **Ask FINN** on the same page: "How big is the order book?" The answer cites call pages, and uncited points are removed by code.
7. **Ask → any listed company, in your own words.** "Should I buy Trent?", "compare tcs and infosys", "How was HDFC Bank's latest quarter?", "Is it expensive?", "How is my portfolio doing?". Code plans the answer (which report, which tickers), data tools fetch today's accounts, prices and filings, and the analysis and report are code: a scorecard where every grade states its rule, results vs last quarter and a year ago, bull and bear points that each name the rule that fired, valuation, momentum, filings, management's forward-looking lines quoted with their page, or a side-by-side table. Answers take 1 to 4 seconds and use no AI tokens; a small AI call with no data plans only a question the rules can't place. Each step runs alone from the command line (`uv run python -m app.agent.run "Should I buy Trent?"`, `app.agent.tools financials TRENT`, `app.agent.analyse TRENT`, `app.agent.reports compare TCS INFY`).
8. **Network** (its own tab, or any name in the app). Search first, then who's worth a call, then everyone, each described by how you know them. The expertise map by theme, reconnect nudges, and profiles with "ask them about", "can introduce you to" and "Before you meet", which lists questions built from FINN's research, each showing its source. Open Dabur's CFO: one of your contacts is also called Ankush Jain, and FINN shows a "possible match" to confirm or dismiss instead of assuming they're the same person.
   On any profile, **Meeting soon?** takes a date: from two days before, Today opens with a prep card (what changed at the companies they know, and what to ask).
9. **Portfolio**. *As it stands* opens like a broker app: current value, invested, total returns and the day's returns, then the day's top movers and every holding with its shares, average price, last price and gain (sort by value, returns or 1D). Below that, a one-year chart against the Nifty 50 (+2.0% against −3.3% for the demo); warnings ("Lenders together are 21%"); everything else in one table, with themes and correlated pairs folded away. *Suggested* opens with one sentence ("Trim 11 and add to 9. 15.1% of the portfolio changes hands…"), then the larger changes, each explained, with the smaller ones folded. The same 20 holdings are re-weighted by code (balance risk, lean towards quality, stay within limits), then an **AI review** that read 40 recent filings nudges four, citing each one (BHEL's Adani Power orders, Dabur's CEO resigning, HDFC Bank's CEO change, L&T's delivery record); a row shows the code's change and the AI's separately. *As it stands* also names holdings outside your own limits. **Edit** changes shares with − / + and recomputes the weights as you go, and **Reset to demo** can be undone; Today follows.
   **Watchlist** follows companies you don't hold (Persistent, Manappuram and Aarti in the demo): price, the day's move, a month's line and the latest filing that isn't paperwork. Tap **Watch** on any company page to add one.
   Every card and company page has **Share** (plain text with the filing link, for WhatsApp or mail). Add FINN to the home screen: once opened, the last brief still loads offline.
   On a first visit FINN asks what you'd like to do and runs a tour for it (check my morning, research a company, review my portfolio, use my network, or a quick look at everything); the Tour button at the top of Today asks again. Every page appears whole, behind a loading bar, once all its parts are in.
10. **Network → Yours.** Try it on your own network: type where you worked and studied, upload the `Connections.csv` LinkedIn lets you export, and every path, "who can help" and meeting question rebuilds around you. It's private to your browser, keeps no e-mails or profile links, and is deleted after 7 days. Switch to "Second investor" and every list changes, because each account sees only its own contacts. "Remove from my network" on a profile takes every link through that person with it, and "Restore the demo network" undoes it.

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
- **Brokerage reports behind a login, and PDFs in the repo.** FINN uses only reports the brokers publish on their own open servers (Trendlyne's copies need a sign-in, so they weren't used). The PDFs stay in a local cache; the repo keeps only the figures read from them, short excerpts and the link. A target-accuracy ranking needs at least 10 targets whose horizon has passed; there are none yet, so FINN says so instead of ranking.
- **Real sign-in.** Two demo accounts show that networks are kept apart, but the switch is a header, not authentication. The production design (row-level security, encrypted per-user data) is in the architecture doc.

## Measured, not assumed
The same table lives in the app at **How accurate is FINN?** (Today's footer), where the first three rows are recomputed from the current data and each of the 100 labelled filings can be checked against where FINN puts it.

| What | Result | How |
|---|---|---|
| Material filings kept out of Routine | 25 of 25 | 100 of the 20-stock portfolio's filings, picked at random and labelled before the levels were tuned (`backend/data/fixtures/eval/materiality_labels.json`) |
| Attention score bands (0–100) | 18 of 25 material filings at Medium or above; 73 of 75 not-material below Medium | The same 100 labelled filings, scored by the spec's six-part rule; rules fixed after reading the misses, bands unchanged (build log, Phases 5h and 5j). The misses are mostly investor decks and sales updates with no amount |
| Share of items marked Important | 11.9% on 7 days, 15.0% on 30 days (target ≤ 20%) | Same digest, cards plus folded filings, one card per event |
| Filings decided by rules, with no LLM call | 380 of 455 | Ingested portfolio filings, 18 Sep to 17 Nov 2026 |
| Ask FINN finds the page that answers the question | 13 of 13 tuning questions; 21 of 23 held-out ones, written after the synonym list | 36 investor questions on 4 companies, answer pages marked by a pattern and checked by hand; the same ranking the app uses, no AI (`backend/data/fixtures/eval/retrieval_questions.json`) |
| People extracted from management-change filings | 7/7 people, 6/7 roles, 10/14 prior employers, 8/11 schools | Hand-checked golden set, each against the filing PDF |
| Brokerage report fields read correctly | 60 of 60 cover fields; 285 of 285 estimates found on their page | 12 L&T reports from 4 brokerages, cover values hand-read (`backend/data/fixtures/eval/brokerage_gold.json`); every estimate checked in code against its page |
| Promises found in one company's four calls, small vs mid model | 5 vs 10, including all 3 misses | Same calls, two tiers; the reason the scorecard uses the larger model |
| Cost on Claude | About $0.32 per new company analysis and $0.02 per question; filings about $0.03 a day for a 20-stock portfolio, shared | Per-call token log (`/admin/costs`); the demo itself ran on Gemini's free tier |

## Where I'd take it next
- **A better voice brief:** a natural voice instead of the phone's built-in one, delivered as a podcast-style feed the evening before.
- **Calendar-aware prep:** read meetings from the investor's calendar (with consent) instead of asking them to note each one, and send the prep card the evening before.
- **Intraday triggers** for price and volume, plus filings polled through market hours.
- **Watchlist-wide scorecards:** rank every holding by how reliably its management delivers.
- **Richer network import:** past positions and schools from LinkedIn's full export (the connections file has only current roles), and contacts from a phone's address book with explicit consent.
