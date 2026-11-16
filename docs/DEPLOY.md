# Deploying FINN

| Part | Host | Plan | Config |
|---|---|---|---|
| API (FastAPI + SQLite) | Render | Free web service, Docker | `render.yaml` (blueprint) |
| Web app (Next.js) | Vercel | Hobby | root directory `frontend/` |

The API image seeds SQLite from the committed fixtures at build time, so the demo never depends on live scraping (NFR-02). Live research for a new ticker still fetches screener.in and the company's PDFs at request time.

## Live
| Part | Address | Service |
|---|---|---|
| Web app | https://finn-iota-murex.vercel.app | Vercel project `finn` |
| API | https://finn-api-9hft.onrender.com | Render `finn-api-9hft`, Singapore, from Blueprint `finn` |

Both deploy from `main`: Render rebuilds on every push (Blueprint auto-sync); the web app redeploys with `cd frontend && npx vercel deploy --prod`. `frontend/.vercelignore` keeps local `.env*` files out of the upload.

## 1. API on Render
1. Render dashboard → **New → Blueprint** → pick this repo. Render reads `render.yaml`.
2. Fill the secret values it asks for:
   - `GEMINI_API_KEY` and/or `ANTHROPIC_API_KEY` (set `LLM_PROVIDER=anthropic` to run everything on Claude);
   - `FINN_DEMO_PASSCODE`: the passcode reviewers type once;
   - `ALLOWED_ORIGINS`: the Vercel URL from step 2 (comma-separated if more than one).
3. Check `https://<service>.onrender.com/health` returns `{"status":"ok", …}`.

## 2. Web app on Vercel
```bash
cd frontend
npx vercel link                     # new project, root = frontend
npx vercel env add NEXT_PUBLIC_API_URL production   # https://<service>.onrender.com
npx vercel --prod
```
Then put the production URL into `ALLOWED_ORIGINS` on Render (step 1.2). Render restarts the service when an env var changes.

## Behaviour on free hosting
- **Cold starts.** Render's free instance sleeps after 15 minutes idle and takes up to a minute to wake. The app pings `/health` on load and shows "Waking the server…" if it is slow.
- **Ephemeral disk.** Research built live is cached on the instance and lost on restart; the precomputed set ships in the image.
- **LLM budget.** Every API route needs the passcode. Live builds are capped at `FINN_MAX_LIVE_BUILDS_PER_DAY` (default 20) and Ask FINN questions at `FINN_MAX_QUESTIONS_PER_DAY` (default 60). Builds run one at a time, since the instance has 512 MB and each build parses PDFs. Spend per task is at `/admin/costs`.
