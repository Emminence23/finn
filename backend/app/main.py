"""FINN API. Feature routers (digest, alerts, research, people) are mounted as they're built."""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.brokerage import router as brokerage_router
from app.api.routes import router
from app.config import get_settings
from app.db import init_db, session
from app.network.owner import DEFAULT, set_owner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def require_passcode(x_finn_passcode: str | None = Header(default=None)) -> None:
    """FR-APP-04: protects the LLM budget on the public demo. Disabled when no passcode is set."""
    expected = get_settings().demo_passcode
    if expected and x_finn_passcode != expected:
        raise HTTPException(status_code=401, detail="missing or wrong passcode")


async def select_account(x_finn_user: str | None = Header(default=None)) -> None:
    """N-7: which demo account's network this request sees. Async on purpose: the owner is
    set in the request's own context, which FastAPI then copies into the worker thread that
    runs a sync route."""
    try:
        set_owner(x_finn_user or DEFAULT)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


app = FastAPI(title="FINN API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().allowed_origins),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# an NSE symbol: letters, digits, & and - (M&M, BAJAJ-AUTO). Checked before any route uses
# one in a file path (fixtures, page cache) or an outside URL (screener, NSE).
_SYMBOL = re.compile(r"^[A-Za-z0-9&-]{1,20}$")


async def valid_symbols(request: Request) -> None:
    for name in ("symbol", "a", "b"):
        v = request.path_params.get(name) or request.query_params.get(name)
        if v is not None and not _SYMBOL.match(v):
            raise HTTPException(400, f"'{v[:30]}' isn't an NSE symbol")


app.include_router(
    router,
    dependencies=[Depends(require_passcode), Depends(select_account), Depends(valid_symbols)],
)
app.include_router(
    brokerage_router,
    dependencies=[Depends(require_passcode), Depends(select_account), Depends(valid_symbols)],
)


@app.get("/health")
def health() -> dict:
    """Liveness + warm-up target (Render cold starts)."""
    with session() as db:
        counts = {
            t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("companies", "announcements", "prices", "people")
        }
    from app import store

    return {"status": "ok", "counts": counts, "saved_reports": store.backend()}


@app.get("/admin/costs", dependencies=[Depends(require_passcode)])
def costs() -> dict:
    """NFR-12: LLM usage and cost summary per task/model."""
    with session() as db:
        rows = db.execute(
            """SELECT task, provider, model,
                      COUNT(*) AS calls, SUM(cache_hit) AS cache_hits,
                      SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
                      ROUND(SUM(cost_usd), 4) AS cost_usd,
                      SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors
               FROM llm_calls GROUP BY task, provider, model ORDER BY cost_usd DESC"""
        ).fetchall()
    by_task = [dict(r) for r in rows]
    return {"total_usd": round(sum(r["cost_usd"] or 0 for r in by_task), 4), "by_task": by_task}
