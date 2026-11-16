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
   - `FINN_DEMO_PASSCODE`: the passcode reviewers type once;
   - `ALLOWED_ORIGINS`: the Vercel URL from step 2 (comma-separated if more than one).
3. Check `https://<service>.onrender.com/health` returns `{"status":"ok", …}`.
4. Saved reports: create a free Key Value instance in the same region (**New → Key Value**, maxmemory policy `volatile-ttl`) and set `REDIS_URL` on the API to its internal URL (`redis://<id>:6379`). `/health` then shows `"saved_reports":"key-value"`. Without it, reports are saved in the local SQLite and lost on each deploy; if the instance can't be reached, the API falls back to local for 5 minutes.

## 2. Web app on Vercel
```bash
cd frontend
npx vercel link                     # new project, root = frontend
npx vercel env add NEXT_PUBLIC_API_URL production   # https://<service>.onrender.com
npx vercel --prod
```
Then put the production URL into `ALLOWED_ORIGINS` on Render (step 1.2). Render restarts the service when an env var changes.

## Behaviour on free hosting
- **Cold starts.** Render's free instance sleeps after 15 minutes idle and takes up to a minute to wake. The app pings `/health` on load and shows "Waking the server…" if it is slow. `.github/workflows/keep-warm.yml` pings `/health` every 13 minutes on weekdays, 09:30–18:30 IST, so it stays awake during market hours (about 1,000 of the 2,000 free Actions minutes a month on a private repo). Outside those hours it sleeps as before.
- **Ephemeral disk.** The web service's SQLite is rebuilt on every deploy (the daily refresh redeploys each morning); the precomputed research ships in the image. Reports and deep reads built live are kept for a week in the Key Value instance instead. Its free plan has no persistence, so a restart of that instance (rare) clears them.
- **LLM budget.** Every API route needs the passcode. Live builds are capped at `FINN_MAX_LIVE_BUILDS_PER_DAY` (default 20) and Ask FINN questions at `FINN_MAX_QUESTIONS_PER_DAY` (default 60). Builds run one at a time, since the instance has 512 MB and each build parses PDFs. Spend per task is at `/admin/costs`.
