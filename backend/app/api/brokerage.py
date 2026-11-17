"""Brokerage intelligence API (brief §7). Paths follow the brief, without the /api prefix
the rest of this API doesn't use. Every response is computed in code from stored reports;
the one AI step (why they disagree) is stored and checked."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.brokerage import discover, explain, jobs, news, service
from app.network.owner import current_owner, is_sandbox

router = APIRouter()


def _owner() -> str:
    return current_owner()


@router.get("/companies/{symbol}/brokerage/overview")
def overview(
    symbol: str,
    start: str | None = Query(None, alias="from"),
    end: str | None = Query(None, alias="to"),
    horizon: str | None = None,
) -> dict:
    out = service.overview(symbol, _owner(), start, end, horizon)
    out["covered"] = out["reports"] > 0 or bool(out["stale"])
    return out


@router.get("/companies/{symbol}/brokerage/reports")
def reports(
    symbol: str,
    brokerage_id: str | None = None,
    rating: str | None = None,
    start: str | None = Query(None, alias="from"),
    end: str | None = Query(None, alias="to"),
    horizon: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict:
    rows = service.reports(symbol, _owner(), brokerage_id, rating, start, end, horizon)
    return {
        "total": len(rows),
        "page": page,
        "items": rows[(page - 1) * per_page : page * per_page],
    }


@router.get("/companies/{symbol}/brokerage/revisions")
def revisions(
    symbol: str,
    lookback_days: int | None = Query(None, ge=1, le=3650),
    metric: str | None = None,
    brokerage_id: str | None = None,
) -> dict:
    return service.revisions(symbol, _owner(), lookback_days, metric, brokerage_id)


@router.get("/companies/{symbol}/brokerage/divergence")
def divergence(symbol: str) -> dict:
    return service.divergence(symbol, _owner()) | {"explanation": explain.get(symbol)}


@router.post("/companies/{symbol}/brokerage/divergence/explain")
def explain_now(symbol: str) -> dict:
    """Runs the AI explanation once for the current evidence (stored after)."""
    try:
        return explain.get(symbol, run=True)
    except Exception as e:
        raise HTTPException(503, "The AI is busy; try again in a minute.") from e


@router.get("/companies/{symbol}/brokerage/track-record")
def company_track_record(symbol: str) -> dict:
    return service.track_record(symbol=symbol, owner=_owner())


@router.get("/brokerages/{brokerage_id}/track-record")
def brokerage_track_record(brokerage_id: str, symbol: str | None = None) -> dict:
    return service.track_record(symbol=symbol, brokerage_id=brokerage_id, owner=_owner())


class Upload(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z0-9&-]{1,20}$")
    brokerage: str = Field(min_length=2, max_length=80)
    pdf_base64: str
    source_url: str | None = Field(None, max_length=500)
    permitted: bool = Field(description="the investor confirms they may use this report")


@router.post("/brokerage/reports/ingest")
def ingest(body: Upload) -> dict:
    owner = _owner()
    if not is_sandbox(owner):
        raise HTTPException(
            403,
            "Reports you add stay private to you: switch to your own space "
            "(Network → Yours) first.",
        )
    if not body.permitted:
        raise HTTPException(
            400, "Confirm you may use this report (your subscription or a public copy)."
        )
    from datetime import UTC, datetime

    from app.api.routes import BUDGET
    from app.config import get_settings

    if not BUDGET.take(
        get_settings().max_live_builds_per_day, datetime.now(UTC).date().isoformat()
    ):
        raise HTTPException(429, "Today's AI reads are used up; try tomorrow.")
    try:
        job = jobs.start(
            owner, body.symbol.upper(), body.brokerage, body.pdf_base64, body.source_url
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"job_id": job, "status": "running"}


@router.get("/brokerage/ingest/{job_id}")
def ingest_status(job_id: str) -> dict:
    out = jobs.status(job_id, _owner())
    if out is None:
        raise HTTPException(404, "no such job")
    return out


def _take_read() -> None:
    from datetime import UTC, datetime

    from app.api.routes import BUDGET
    from app.config import get_settings

    if not BUDGET.take(
        get_settings().max_live_builds_per_day, datetime.now(UTC).date().isoformat()
    ):
        raise HTTPException(429, "Today's AI reads are used up; try tomorrow.")


@router.post("/companies/{symbol}/brokerage/find")
def find_reports(symbol: str) -> dict:
    """Look for this company's public brokerage reports (ICICI Securities, PL Capital) and
    read the newest few in the background. Poll GET .../find for progress."""
    if discover.status(symbol.upper()).get("status") != "running":
        _take_read()
    return discover.search(symbol)


@router.get("/companies/{symbol}/brokerage/find")
def find_status(symbol: str) -> dict:
    return discover.status(symbol.upper())


class Link(BaseModel):
    url: str = Field(min_length=12, max_length=500)
    brokerage: str | None = Field(None, max_length=80)
    permitted: bool = Field(description="the link is a public copy the investor may use")


@router.post("/companies/{symbol}/brokerage/link")
def add_link(symbol: str, body: Link) -> dict:
    """Read one publicly posted brokerage PDF from its link."""
    if not body.permitted:
        raise HTTPException(400, "Confirm the link is a public copy you may use.")
    _take_read()
    try:
        return discover.add_link(symbol, body.url.strip(), body.brokerage)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/companies/{symbol}/brokerage/news")
def broker_news(symbol: str) -> dict:
    """Banks' and brokers' calls on this company as reported in the financial press, each
    checked against its article sentence. The first request starts the search (about a
    minute); poll until job.status is done. Saved for 12 hours."""
    return news.get(symbol)


@router.post("/companies/{symbol}/brokerage/news/refresh")
def broker_news_refresh(symbol: str) -> dict:
    return news.refresh(symbol)
