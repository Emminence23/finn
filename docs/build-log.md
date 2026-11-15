# Build log

Key prompts, course-corrections, and accept-vs-rewrite decisions made while building FINN with Claude Code.

## Phase 0: setup
- Chose FastAPI + Next.js, with Anthropic models routed by task (Haiku 5.5 for bulk, Opus 5.5 for reasoning).
- Pinned Python 3.12 via uv instead of the system 3.14, to avoid missing wheels.
- Probed data sources live before designing ingest: NSE announcements API works (cookie-primed session, date ranges, PDFs); BSE API returns 403, so it was dropped; screener.in gives quarterly tables plus AR and transcript links for any ticker.
- No Anthropic API key available (claude.ai subscription ≠ API access), so the LLM layer became provider-agnostic with task-based routing (config/models.yaml), defaulting to free tiers.

## Infrastructure
- Built a provider-agnostic LLM router: callers name a *task*; YAML and env pick the provider and model. Adapters: Gemini, Anthropic, and OpenAI-compatible (Groq, OpenRouter, Ollama). Includes a SQLite response cache, one retry on invalid structured output, and per-call usage and cost logging.
- Considered renting a GPU box for Ollama. Rejected: the deployed demo needs an LLM whenever reviewers open it, so a GPU box would have to stay on (cost) or would break the demo when stopped. Free hosted tiers plus a ≤$10 Anthropic top-up for the hero analysis is cheaper and more reliable. Ollama remains a supported provider.
- Model IDs are left as `TBD` and fail loudly, rather than being guessed. They're filled in from each provider's live model list (`app.llm.cli models`).
- Tests use a fake provider and never hit a real API (12 passing). The Docker image builds and serves /health.

## Phase 1: data
- Snapshot pipeline (`make snapshot`) freezes live data into committed fixtures, and `make seed` loads them into SQLite in about 2.5s. The demo never scrapes live (NFR-02).
- Data snapshot: 2,601 NSE symbols; 6 months of prices for 21 tickers; 517 NSE announcements (60 days); screener fundamentals for all 21 tickers (~12 quarters plus annual P&L, balance sheet, cash flow and ratios; 1,874 document links); 4 transcripts plus the latest annual report for each research company, cached locally rather than committed.
- **Course-correction (ethics):** the plan said to generate synthetic profiles with an LLM, including people named in filings. Inventing careers for real, named executives would mean fabricating facts about real people. Instead, filing people are built **only from the "brief profile" annexure that SEBI requires in appointment filings** (a primary source, cited by announcement ID). The investor's contacts are fictional, and they connect to real executives only through employers and schools stated in those filings. Unknown tenure years are left null so overlaps are labelled "possible" rather than asserted.
- Found the brief's exact hero case in real data: Pidilite appointed a **CFO-Designate** (Oct 9). Other management changes with rich profiles: HDFC Bank CCO (ex-ICICI Bank, which is also in the portfolio), CG Power SMPs, SRF CHRO, Trent director.
- Screener parser handles lenders (Revenue/Financing Profit, no EBITDA → stored as null rather than faked) and falls back from consolidated to standalone figures.
- BSE stays dropped (403). NSE `attchmntText` gives a free, usable subject line per filing.
