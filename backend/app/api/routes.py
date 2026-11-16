"""HTTP API for Push, Network and company lookup (REQUIREMENTS §6.6)."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.clock import now, window_bounds
from app.config import get_settings
from app.db import session
from app.intel import alerts as alerts_mod
from app.intel.digest import build_digest
from app.intel.taxonomy import CATEGORIES
from app.network import graph
from app.research import qa, service

router = APIRouter()


# ------------------------------------------------------------------ Push
@router.get("/digest")
def digest(
    window: str = "24h",
    start: str | None = None,
    end: str | None = None,
    include_research_set: bool = False,
) -> dict:
    try:
        return build_digest(window, start, end, include_research_set)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/alerts")
def list_alerts(window: str = "7d") -> dict:
    t0, t1 = window_bounds(window)
    return {"alerts": alerts_mod.evaluate(t0, t1), "rules": alerts_mod.get_rules()}


class AlertRules(BaseModel):
    volume_multiple: float = Field(ge=1.0, le=20.0)
    price_abs_pct: float = Field(ge=0.5, le=50.0)
    categories: list[str]
    enabled: dict[str, bool] = {"volume": True, "price": True, "category": True}


@router.get("/alert-rules")
def get_alert_rules() -> dict:
    return alerts_mod.get_rules() | {"all_categories": CATEGORIES}


@router.put("/alert-rules")
def put_alert_rules(rules: AlertRules) -> dict:
    unknown = set(rules.categories) - set(CATEGORIES)
    if unknown:
        raise HTTPException(400, f"unknown categories: {sorted(unknown)}")
    return alerts_mod.set_rules(rules.model_dump())


@router.post("/alerts/run")
def run_alerts(window: str = "24h") -> dict:
    """The scheduled EOD check, exposed for the demo (FR-ALERT-06). Idempotent."""
    t0, t1 = window_bounds(window)
    return {"evaluated": alerts_mod.run_and_store(t0, t1), "as_of": t1.isoformat()}


# ------------------------------------------------------------------ Companies
@router.get("/companies")
def companies(q: str = "", limit: int = Query(10, le=50)) -> list[dict]:
    """Autocomplete over every NSE equity; portfolio and research names rank first."""
    q = q.strip().upper()
    with session() as db:
        rows = db.execute(
            """SELECT symbol, name, in_portfolio, in_research_set FROM companies
               WHERE symbol LIKE ? OR UPPER(name) LIKE ?
               ORDER BY (symbol = ?) DESC, in_portfolio DESC, in_research_set DESC,
                        (symbol LIKE ?) DESC, LENGTH(symbol)
               LIMIT ?""",
            (f"{q}%", f"%{q}%", q, f"{q}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/companies/{symbol}/prices")
def prices(symbol: str, days: int = Query(90, le=400)) -> dict:
    with session() as db:
        rows = db.execute(
            "SELECT date, close, volume FROM prices WHERE symbol=? ORDER BY date DESC LIMIT ?",
            (symbol.upper(), days),
        ).fetchall()
    if not rows:
        raise HTTPException(404, f"no prices for {symbol}")
    return {"symbol": symbol.upper(), "series": [dict(r) for r in reversed(rows)]}


# ------------------------------------------------------------------ Network
@router.get("/people/help")
def people_help(symbol: str, limit: int = Query(5, le=20)) -> dict:
    return {"symbol": symbol.upper(), "helpers": graph.who_can_help(symbol.upper(), limit=limit)}


@router.get("/people/expertise")
def people_expertise(theme: str | None = None) -> dict:
    if not theme:
        return {"themes": graph.all_themes()}
    return {"theme": theme, "contacts": graph.expertise(theme)}


@router.get("/people/nudges")
def people_nudges(window: str = "30d") -> dict:
    t0, t1 = window_bounds(window)
    return {
        "as_of": now().isoformat(),
        "nudges": graph.reconnect_nudges(t0.isoformat(), t1.isoformat()),
    }


@router.get("/people/account")
def people_account() -> dict:
    """The current demo account and the others, for the account switch (N-7)."""
    from app.network.owner import ACCOUNTS, current_owner

    people = graph.load_people()
    me = graph.investor(people)
    return {
        "account": current_owner(),
        "investor": me.name,
        "contacts": sum(p.is_contact for p in people.values()),
        "accounts": list(ACCOUNTS),
    }


@router.post("/people/reset")
def people_reset() -> dict:
    """Restore this account's demo network (undo deletions)."""
    return {"contacts": graph.reset_network()}


@router.delete("/people/{person_id}")
def person_delete(person_id: str) -> dict:
    """N-7: remove a contact and every link derived from it, for this account only."""
    if not graph.delete_contact(person_id):
        raise HTTPException(404, "no such contact in your network")
    return {"deleted": person_id}


@router.get("/people/{person_id}")
def person(person_id: str) -> dict:
    p = graph.person_profile(person_id)
    if p is None:
        raise HTTPException(404, "person not found")
    return p


@router.get("/people/{person_id}/paths")
def person_paths(person_id: str) -> dict:
    people = graph.load_people()
    if person_id not in people:
        raise HTTPException(404, "person not found")
    return graph.paths_to(person_id, people)


@router.get("/people")
def list_people(contacts_only: bool = True) -> list[dict]:
    people = graph.load_people()
    out = [
        graph._contact_summary(p) | {"themes": p.themes}
        for p in people.values()
        if p is not graph.investor(people) and (p.is_contact or not contacts_only)
    ]
    return sorted(out, key=lambda x: -(x.get("strength") or 0))


# ------------------------------------------------------------------ Pull (FR-PULL)
@router.get("/research")
def research_list() -> list[dict]:
    """Research views ready to read instantly (precomputed or cached), newest first."""
    return service.summaries()


@router.get("/research/{symbol}")
def research(symbol: str) -> dict:
    """Cached or precomputed research view. 404 with `build_url` when not built yet; the UI
    then opens the stream, which builds it live with progress (FR-PULL-10)."""
    view = service.get_cached(symbol.upper())
    if view is None:
        raise HTTPException(
            404,
            {"status": "not_built", "build_url": f"/research/{symbol.upper()}/stream"},
        )
    return service.with_network(view)


class BuildBudget:
    """Daily cap on live builds (they spend LLM budget) and one build at a time (a free
    instance has 512 MB and each build parses PDFs). Others wait in line with a message."""

    def __init__(self) -> None:
        self.day = ""
        self.used = 0
        self.gate = threading.Lock()

    def take(self, limit: int, today: str) -> bool:
        if today != self.day:
            self.day, self.used = today, 0
        if self.used >= limit:
            return False
        self.used += 1
        return True


BUDGET = BuildBudget()


def _build_once(symbol: str, progress, force: bool) -> dict:
    if not BUDGET.gate.acquire(blocking=False):
        progress("queued", "Another analysis is running; yours starts right after it")
        BUDGET.gate.acquire()
    try:
        if not force and (view := service.get_cached(symbol.upper())) is not None:
            return view  # built by the request we waited behind
        return service.build(symbol, progress, force)
    finally:
        BUDGET.gate.release()


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=300)


QUESTIONS = BuildBudget()


@router.get("/ask/resolve")
def ask_resolve(q: str = Query(min_length=3, max_length=300)) -> dict:
    """Which company a typed question is about, so Ask can route it (FR-PULL-12)."""
    with session() as db:
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT symbol, name, in_portfolio, in_research_set FROM companies"
            ).fetchall()
        ]
    ready = {s["symbol"] for s in service.summaries()}
    sym = qa.resolve_company(q, rows, ready)
    return {"symbol": sym, "ready": sym in ready if sym else False}


@router.post("/research/{symbol}/ask")
def research_ask(symbol: str, body: Question) -> dict:
    """Ask FINN: a grounded answer from this company's documents and numbers."""
    view = service.get_cached(symbol.upper())
    if view is None:
        raise HTTPException(
            404, {"status": "not_built", "build_url": f"/research/{symbol.upper()}/stream"}
        )
    today = datetime.now(UTC).date().isoformat()
    if not QUESTIONS.take(get_settings().max_questions_per_day, today):
        raise HTTPException(429, "Today's questions are used up on this demo.")
    try:
        return qa.answer(view, body.question)
    except Exception as e:  # LLM quota or provider error: say so instead of a 500
        raise HTTPException(503, f"FINN couldn't answer right now ({type(e).__name__})") from e


@router.get("/research/{symbol}/stream")
async def research_stream(symbol: str, force: bool = False):
    """Server-sent events: `progress` {step, message} … then `result` (the view) or `error`."""
    import asyncio

    today = datetime.now(UTC).date().isoformat()
    cached = None if force else service.get_cached(symbol.upper())
    if cached is None and not BUDGET.take(get_settings().max_live_builds_per_day, today):

        async def refused():
            msg = "Today's live analyses are used up on this demo. Try one of the ready companies."
            yield {"event": "error", "data": json.dumps({"message": msg, "kind": "limit"})}

        return EventSourceResponse(refused())

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress(step: str, message: str) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, ("progress", {"step": step, "message": message})
        )

    async def run() -> None:
        try:
            view = await asyncio.to_thread(_build_once, symbol, progress, force)
            await queue.put(("result", service.with_network(view)))
        except LookupError as e:
            await queue.put(("error", {"message": str(e), "kind": "not_covered"}))
        except Exception as e:  # surfaced to the UI instead of a dropped connection
            await queue.put(("error", {"message": f"{type(e).__name__}: {e}"[:300]}))

    async def events():
        task = asyncio.create_task(run())
        try:
            while True:
                kind, data = await queue.get()
                yield {"event": kind, "data": json.dumps(data, ensure_ascii=False)}
                if kind in ("result", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()  # client went away; the build thread finishes and caches

    return EventSourceResponse(events())
