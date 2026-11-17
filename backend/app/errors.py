"""Errors that say what went wrong. Every failure the API returns has the same shape:

    {"error": {"code": "ai_quota", "message": "...", "detail": "...", "request_id": "..."},
     "detail": "<message>"}          # `detail` kept for clients that read FastAPI's default

Codes:
  ai_quota            every AI model this answer may use is out of free-tier quota today
  ai_error            the AI model failed (not quota): bad output, overloaded, timed out
  source_unavailable  an outside data source (NSE, screener.in, Yahoo, a news site) failed
  daily_budget        FINN's own daily cap on AI builds or questions is used up
  bad_request         the request itself is wrong (unknown symbol, bad input)
  unauthorized        missing or wrong passcode
  internal            a bug in FINN; the request_id finds it in the server log

The request_id is also sent as the X-Request-Id header on every response.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.llm.base import AllModelsExhausted, LLMError, QuotaExhausted

log = logging.getLogger("errors")
request_id: ContextVar[str] = ContextVar("request_id", default="-")

SOURCES = {
    "nseindia": "NSE",
    "screener.in": "screener.in",
    "yahoo": "Yahoo Finance",
    "icicidirect": "ICICI Securities",
    "plindia": "PL Capital",
    "bing.com": "Bing News",
    "news.google": "Google News",
}


def _quota_reset() -> str:
    """Gemini's free tier resets at midnight US Pacific time; say when that is in India."""
    now = datetime.now(UTC)
    pacific = now - timedelta(hours=8)  # PST; a DST hour off at most
    reset = (pacific + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    ist = reset + timedelta(hours=8, minutes=330)
    mins = int((reset - pacific).total_seconds() // 60)
    left = f"{mins // 60} h {mins % 60} min" if mins >= 60 else f"{mins} min"
    return f"about {ist:%H:%M} IST, in {left}"


def _source(url: str) -> str:
    host = urlparse(url).netloc
    return next((name for k, name in SOURCES.items() if k in host), host or "a data source")


def describe(e: Exception) -> str:
    """One sentence for a failure that a page handles itself (and still shows what it can)."""
    if isinstance(e, AllModelsExhausted | QuotaExhausted):
        return f"The free AI quota is used up for today; it resets {_quota_reset()}."
    if isinstance(e, LLMError):
        return f"The AI model failed on this ({str(e)[:120]})."
    if isinstance(e, httpx.HTTPError):
        url = str(e.request.url) if getattr(e, "request", None) else ""
        return f"{_source(url)} didn't answer."
    return f"Something broke inside FINN ({type(e).__name__}, reference {request_id.get()})."


def body(
    status: int, code: str, message: str, detail: str | None = None, raw: object = None
) -> JSONResponse:
    """`raw` keeps a route's own structured detail (e.g. {"status": "not_listed"}) as is."""
    rid = request_id.get()
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "detail": detail, "request_id": rid},
            "detail": message if raw is None else raw,
        },
        headers={"X-Request-Id": rid},
    )


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_id(req: Request, call_next):
        rid = uuid.uuid4().hex[:10]
        request_id.set(rid)
        resp = await call_next(req)
        resp.headers["X-Request-Id"] = rid
        resp.headers["Access-Control-Expose-Headers"] = "X-Request-Id"
        return resp

    @app.exception_handler(AllModelsExhausted)
    async def _all_quota(req: Request, e: AllModelsExhausted):
        log.warning("[%s] %s %s: %s", request_id.get(), req.method, req.url.path, e)
        return body(
            503,
            "ai_quota",
            "The free AI quota is used up for today, so FINN can't write this answer now.",
            f"Gemini's free tier refused {' and '.join(e.models)} on every key FINN has. "
            f"It resets {_quota_reset()}.",
        )

    @app.exception_handler(QuotaExhausted)
    async def _quota(req: Request, e: QuotaExhausted):
        log.warning("[%s] %s %s: %s", request_id.get(), req.method, req.url.path, e)
        return body(
            503,
            "ai_quota",
            "The free AI quota is used up for today.",
            f"{e}. It resets {_quota_reset()}.",
        )

    @app.exception_handler(LLMError)
    async def _llm(req: Request, e: LLMError):
        log.warning("[%s] %s %s: %s", request_id.get(), req.method, req.url.path, e)
        auth = "API key" in str(e) or "PERMISSION" in str(e) or "401" in str(e)
        return body(
            502,
            "ai_error",
            "The AI service rejected FINN's key."
            if auth
            else "The AI model failed on this request.",
            str(e)[:300],
        )

    @app.exception_handler(httpx.HTTPError)
    async def _upstream(req: Request, e: httpx.HTTPError):
        url = str(e.request.url) if getattr(e, "request", None) else ""
        status = getattr(getattr(e, "response", None), "status_code", None)
        src = _source(url)
        log.warning("[%s] %s %s: %s %s", request_id.get(), req.method, req.url.path, src, e)
        what = (
            f"{src} refused FINN's request ({status})"
            if status
            else f"{src} didn't answer ({type(e).__name__})"
        )
        return body(
            502, "source_unavailable", f"{what}, so this answer can't be built now.", url[:200]
        )

    @app.exception_handler(HTTPException)
    async def _http(req: Request, e: HTTPException):
        code = {401: "unauthorized", 429: "daily_budget", 404: "not_found"}.get(
            e.status_code, "bad_request" if e.status_code < 500 else "internal"
        )
        if isinstance(e.detail, dict):
            msg = str(e.detail.get("message") or e.detail.get("status") or "Not found.")
            return body(e.status_code, code, msg, raw=e.detail)
        return body(e.status_code, code, str(e.detail))

    @app.exception_handler(RequestValidationError)
    async def _invalid(req: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return body(
            422, "bad_request", f"The request isn't valid: {where} {first.get('msg', '')}".strip()
        )

    @app.exception_handler(Exception)
    async def _bug(req: Request, e: Exception):
        tb = traceback.extract_tb(e.__traceback__)
        where = next(
            (
                f"{f.filename.split('/app/')[-1]}:{f.lineno}"
                for f in reversed(tb)
                if "/app/" in f.filename
            ),
            "?",
        )
        log.exception("[%s] %s %s failed at %s", request_id.get(), req.method, req.url.path, where)
        return body(
            500,
            "internal",
            "Something broke inside FINN while building this. It's a bug, not your input.",
            f"{type(e).__name__} at {where}: {str(e)[:200]}",
        )
