# FINN: Financial Investment Agent

A mobile-first investor companion with three layers:
- **Push:** what changed across your portfolio today, and why you should care.
- **Pull:** research on any NSE company built only from primary sources, led by "did management deliver what they promised?"
- **Network:** who in your own network can help you understand it, and how you know them.

**Demo:** _link added after deploy_ (passcode in the covering email). The free API host sleeps when idle, so the first load can take up to a minute.

> Spec: [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) · Architecture: [`docs/architecture.md`](docs/architecture.md) · Build history: [`docs/build-log.md`](docs/build-log.md) · Deploy: [`docs/DEPLOY.md`](docs/DEPLOY.md)

## 60-second tour
1. **Today.** The brief for the last 24 hours, 7 days or 30 days. Results cards lead with what the numbers say ("Profit down 36% YoY even as revenue grew 12%"), show QoQ and YoY, and are cross-checked against screener.in. A management change shows the incoming person's background and your path to them. Each card names the person to call and why. Routine filings are folded away.
2. **Alert settings** (top right). Change the volume or price threshold and the feed re-ranks.
3. **Ask → Kaynes.** The promise scorecard: FY26 revenue ₹3,626 Cr against ₹4,000 Cr+ guided, working capital 133 days against ≤85, each with the verbatim quote, call and page beside the reported number.
4. **Ask FINN** on the same page: "Why did receivables go up?" The answer cites call pages, and uncited points are removed by code.
5. **Ask → any other ticker** (e.g. TATAELXSI). FINN reads its annual report and last four calls live, with progress, in under a minute.
6. **People.** The expertise map by theme, reconnect nudges, and profiles with "ask them about" and "can introduce you to".

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
- **A custom date range in Today.** Fixed 24h, 7-day and 30-day windows cover most of the demo, but an older event such as the Pidilite CFO change (9 October) falls outside them.
- **"Questions worth asking" before a meeting, and an interactive network map.** Both were "could haves" and were cut for time.
- **Multi-user accounts.** One demo user. The production design (row-level security, encrypted per-user data) is in the architecture doc.

## Where I'd take it next
- A two-minute **voice brief** of Today for the commute.
- **Calendar-aware prep:** "you're meeting X tomorrow: here's what changed at their company and what to ask".
- **Intraday triggers** for price and volume, plus filings polled through market hours.
- **Watchlist-wide scorecards:** rank every holding by how reliably its management delivers.
- **Real network import** from LinkedIn's official APIs or a user's export, with consent built into onboarding.
