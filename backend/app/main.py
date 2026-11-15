"""FINN API. Feature routers (digest, alerts, research, people) are mounted as they're built."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db, session

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


app = FastAPI(title="FINN API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().allowed_origins),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness + warm-up target (Render cold starts)."""
    with session() as db:
        counts = {
            t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("companies", "announcements", "prices", "people")
        }
    return {"status": "ok", "counts": counts}


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
