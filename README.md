# FINN: Financial Investment Agent

A mobile-first investor companion with three layers:
- **Push:** what changed across your portfolio, and why you should care.
- **Pull:** grounded research on any NSE company.
- **Network:** who in your own network can help you understand it.

> Status: in development. See [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) for the spec.

## Repo layout
```
backend/    FastAPI + SQLite. Ingest, intelligence, network graph, research, LLM layer
frontend/   Next.js mobile-first PWA
docs/       Requirements, architecture, build log (AI build history)
```

## Quick start
```bash
make setup                       # uv sync + npm install
cp backend/.env.example backend/.env   # add at least one LLM key (Gemini free tier works)
make api                         # http://localhost:8000/health
make web                         # http://localhost:3000
make check                       # lint + tests + frontend build (same as CI)
```

## LLM providers are swappable
Every LLM call goes through one router (`backend/app/llm/`) and is named by **task**, not by model.
`backend/config/models.yaml` maps each task to a tier (fast, mid or strong), and each provider to a model per tier.

| Want to… | Do this |
|---|---|
| Switch everything to Claude | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` |
| Use Claude only for the hero analysis | `LLM_PROVIDER_PROMISE_VS_DELIVERY=anthropic` |
| Run locally on Ollama | `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=…` |
| Try a different model | `LLM_MODEL_GEMINI_FAST=<id>` |

Check the setup with `uv run python -m app.llm.cli routes | models <provider> | ping`.
All outputs are cached in SQLite, so re-runs are free. `/admin/costs` reports spend per task.
