# Deploying FINN

| Part | Host | Plan | Config |
|---|---|---|---|
| API (FastAPI + SQLite) | Render | Free web service, Docker | `render.yaml` (blueprint) |
| Web app (Next.js) | Vercel | Hobby | root directory `frontend/` |
| Saved reports (a week) | Render Key Value `finn-cache` | Free, Singapore | `REDIS_URL` on the API |

The API image seeds SQLite from the committed fixtures at build time, so the demo never depends on live scraping (NFR-02). Live research for a new ticker still fetches screener.in and the company's PDFs at request time.

## Live
| Part | Address | Service |
|---|---|---|
| Web app | https://finn-iota-murex.vercel.app | Vercel project `finn` |
| API | https://finn-api-9hft.onrender.com | Render `finn-api-9hft`, Singapore, from Blueprint `finn` |

Both deploy from `main` on every push: Render through Blueprint auto-sync, Vercel through its Git integration (the project's Root Directory must be `frontend`, or the build finds no `app/` directory). Commits by the daily-refresh bot are blocked by Vercel because their author isn't a team member; they only change fixtures, so the web app doesn't need them. `frontend/.vercelignore` keeps local `.env*` files out of the upload.

## 1. API on Render
1. Render dashboard → **New → Blueprint** → pick this repo. Render reads `render.yaml`.
2. Fill the secret values it asks for:
   - `GEMINI_API_KEY` and/or `ANTHROPIC_API_KEY` (set `LLM_PROVIDER=anthropic` to run everything on Claude);
   - optional `GEMINI_API_KEY_FALLBACK`: a key from a **second Google project** (free quota is counted per project, so a second key in the same project adds nothing). When the first key's daily quota for a model is spent, FINN uses this key for that model before falling back to another model. Add `GEMINI_API_KEY_FALLBACK_2` (up to `_5`), each from yet another project, to extend the chain; keys are tried in order. When every key and model is spent, the API answers `503` with code `ai_quota` and the reset time, and the app says so;
   - `FINN_DEMO_PASSCODE`: the passcode reviewers type once;
   - `ALLOWED_ORIGINS`: the Vercel URL from step 2 (comma-separated if more than one).
3. Check `https://<service>.onrender.com/health` returns `{"status":"ok", …}`.
4. Saved reports: create a free Key Value instance in the same region (**New → Key Value**, maxmemory policy `volatile-ttl`) and set `REDIS_URL` on the API to its internal URL (`redis://<id>:6379`). `/health` then shows `"saved_reports":"key-value"`. Without it, reports are saved in the local SQLite and lost on each deploy; if the instance can't be reached, the API falls back to local for 5 minutes.

## 2. Web app on Vercel
1. Vercel dashboard → **Add New → Project** → import this repo, **Root Directory** `frontend` (framework is detected as Next.js).
2. Add `NEXT_PUBLIC_API_URL` = `https://<service>.onrender.com` for Production, then deploy. Every push to `main` redeploys from then on.
Then put the production URL into `ALLOWED_ORIGINS` on Render (step 1.2). Render restarts the service when an env var changes.

## Behaviour on free hosting
- **Cold starts.** Render's free instance sleeps after 15 minutes idle and takes up to a minute to wake. The app pings `/health` on load and shows "Waking the server…" if it is slow. `.github/workflows/keep-warm.yml` pings `/health` every 13 minutes on weekdays, 09:30–18:30 IST, so it stays awake during market hours (about 1,000 of the 2,000 free Actions minutes a month on a private repo). Outside those hours it sleeps as before.
- **Errors.** Every failure has one shape, `{"error": {code, message, detail, request_id}}` (`backend/app/errors.py`): `ai_quota`, `ai_error`, `source_unavailable` (NSE, screener.in, Yahoo, a news site), `daily_budget`, `bad_request`, `unauthorized`, `internal`. The `request_id` is also the `X-Request-Id` header and appears in the server log line, so a reported error can be found. The app (`frontend/src/lib/errors.ts`) also names failures that never reach FINN: offline, connection dropped, timeout, and the host's 502/503 while the server restarts.
- **Live data.** The API checks NSE filings and prices itself: at startup, then every 30 minutes (every 15 while the market is open; any page load or the keep-warm ping starts a check that is due). New filings get the same enrichment as the morning job (rules, then one batched free-model triage). Today's price row is the latest trade while NSE is open, with hourly bars at `GET /companies/{symbol}/intraday`; `GET /live` shows the last check. What a check adds is saved in Key Value (`finn:live:snapshot`) and restored after a redeploy, so the model is never paid twice for a filing. Set `FINN_LIVE_REFRESH=0` to turn it off. The morning GitHub job still commits fixtures, but freshness no longer depends on it (GitHub's scheduled runs can be late or skipped).
- **Ephemeral disk.** The web service's SQLite is rebuilt on every deploy (the daily refresh redeploys each morning); the precomputed research ships in the image. Reports and deep reads built live are kept for a week in the Key Value instance instead. Its free plan has no persistence, so a restart of that instance (rare) clears them.
- **LLM budget.** Every API route needs the passcode. Live builds are capped at `FINN_MAX_LIVE_BUILDS_PER_DAY` (default 20) and Ask FINN questions at `FINN_MAX_QUESTIONS_PER_DAY` (default 60). Builds run one at a time, since the instance has 512 MB and each build parses PDFs. Spend per task is at `/admin/costs`.
