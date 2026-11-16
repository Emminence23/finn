# FINN: Financial Investment Agent

A mobile-first investor companion with three layers:
- **Push:** what changed across your portfolio today, and why you should care.
- **Pull:** research on any NSE company built only from primary sources, led by "did management deliver what they promised?"
- **Network:** who in your own network can help you understand it, and how you know them.

**Demo:** _link added after deploy_ (passcode in the covering email). The free API host sleeps when idle, so the first load can take up to a minute.

> Spec: [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) · Architecture: [`docs/architecture.md`](docs/architecture.md) · Build history: [`docs/build-log.md`](docs/build-log.md) · Deploy: [`docs/DEPLOY.md`](docs/DEPLOY.md)

## 60-second tour
1. **Today.** The brief for the last 24 hours, 3, 7 or 30 days, or any dates you pick (try 1–15 October for the Pidilite CFO change). Results cards lead with what the numbers say ("Profit down 36% YoY even as revenue grew 12%"), show QoQ and YoY, and are cross-checked against screener.in. A management change shows the incoming person's background and your path to them. Each card is marked Important or Notable with a one-line reason, names the person to call and why, and ends in one next step (the incoming person, the promise scorecard, the contact to call). Routine filings are folded away; filings FINN can't place stay visible, marked "Unclassified".
   Tap **Listen to the brief** for the same items read aloud, about a minute, in the phone's own voice. On a return visit, new cards are marked and the ones you acted on are dimmed.
2. **Alert settings** (top right). Change the volume or price threshold and the feed re-ranks.
3. **Ask → Kaynes.** The promise scorecard: FY26 revenue ₹3,626 Cr against ₹4,000 Cr+ guided, working capital 133 days against ≤85, each with the verbatim quote, call and page beside the reported number. Reported figures, management's words and FINN's own reading look different everywhere on the page. Below "Who you know", an off-the-record panel keeps what contacts told you apart from the evidence: it is never sent to the AI or cited.
4. **Ask FINN** on the same page: "Why did receivables go up?" The answer cites call pages, and uncited points are removed by code.
5. **Ask → any other ticker** (e.g. TATAELXSI). FINN reads its annual report and last four calls live, with progress, in under a minute.
6. **People.** The expertise map by theme, reconnect nudges, and profiles with "ask them about", "can introduce you to" and "Before you meet", which lists questions built from FINN's research, each showing its source. Open the Pidilite CFO: one of your contacts is also called Amit Agarwal, and FINN shows a "possible match" to confirm or dismiss instead of assuming it's him. Switch to "Second investor" and every list changes, because each account sees only its own contacts. "Remove from my network" on a profile takes every link through that person with it, and "Restore the demo network" undoes it.

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
- **Real LinkedIn data.** Scraping it breaks its terms. The network is synthetic, and production would use official APIs or the user's own data export.
- **An open-ended research agent.** A fixed pipeline with code-enforced citations is cheaper, cacheable and testable. The judgement step gets the strongest model instead.
- **An interactive network map.** A "could have", cut for time; paths are shown as hop-by-hop lines instead.
- **Real sign-in.** Two demo accounts show that networks are kept apart, but the switch is a header, not authentication. The production design (row-level security, encrypted per-user data) is in the architecture doc.

## Measured, not assumed
| What | Result | How |
|---|---|---|
| Material filings kept out of Routine | 25 of 25 | 100 portfolio filings, picked at random and labelled before the levels were tuned (`backend/data/fixtures/eval/materiality_labels.json`) |
| Share of items marked Important | 10.7% on 7 days, 18.6% on 30 days (target ≤ 20%) | Same digest, cards plus folded filings |
| Filings decided by rules, with no LLM call | 454 of 517 | Ingested portfolio filings |
| People extracted from management-change filings | 7/7 people and roles, 17/18 prior employers, 8/10 schools | Hand-checked golden set |
| Promises found in Kaynes' calls, small vs mid model | 5 vs 10, including all 3 misses | Same calls, two tiers; the reason the scorecard uses the larger model |
| Cost on Claude | About $0.32 per new company analysis and $0.02 per question; filings about $0.03 a day for a 20-stock portfolio, shared | Per-call token log (`/admin/costs`); the demo itself ran on Gemini's free tier |

## Open questions for ENAM
- **Is a network private to one investor, or pooled across the team?** FINN keeps each investor's network separate and stores public filing people once. Pooling would be a sharing setting on top of that, not a rebuild, but who sees whose contacts is a policy call.
- **How should FINN treat a contact who works at the company now?** Today it marks them ("keep it to public information") and keeps meeting questions to public figures. A compliance team may want them hidden on restricted names, or every contact logged.
- **Are screener.in's standardised tables acceptable as primary data?** FINN reads the exchange filings and uses screener only to cross-check and fill history. If it isn't acceptable, history would come from the filings themselves, at more parsing cost.

## Where I'd take it next
- **A better voice brief:** a natural voice instead of the phone's built-in one, delivered as a podcast-style feed the evening before.
- **Calendar-aware prep:** the evening before a meeting on your calendar, a note with what changed at their company and the "Before you meet" questions.
- **Intraday triggers** for price and volume, plus filings polled through market hours.
- **Watchlist-wide scorecards:** rank every holding by how reliably its management delivers.
- **Real network import** from LinkedIn's official APIs or a user's export, with consent built into onboarding.
