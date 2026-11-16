"""HTTP API for Push, Network and company lookup (REQUIREMENTS §6.6)."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from typing import Literal

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
from app.network.owner import current_owner
from app.research import pull, qa, service

router = APIRouter()


# ------------------------------------------------------------------ Portfolio
@router.get("/portfolio")
def portfolio_overview() -> dict:
    from app.portfolio import analytics

    return analytics.overview()


@router.get("/portfolio/suggested")
def portfolio_suggested() -> dict:
    """Code's suggested weights, plus the AI review if one is stored for these inputs."""
    from app.portfolio import analytics, review

    return {**analytics.suggest(), "review": review.get_review(run=False)}


@router.post("/portfolio/suggested/review")
def portfolio_review() -> dict:
    """Ask the model to review the suggestion (uses quota; stored by input hash)."""
    from app.llm.base import LLMError
    from app.portfolio import review

    try:
        return review.get_review(run=True)
    except LLMError as e:
        raise HTTPException(503, f"AI review unavailable: {e}") from e


@router.get("/portfolio/settings")
def portfolio_settings_get() -> dict:
    from app.portfolio import settings

    return {
        "settings": settings.get_settings(),
        "defaults": settings.DEFAULTS,
        "ranges": settings.RANGE,
        "nullable": sorted(settings.NULLABLE),
    }


@router.put("/portfolio/settings")
def portfolio_settings_put(body: dict) -> dict:
    """Change any of the portfolio rules; null switches a limit off."""
    from app.portfolio import settings

    try:
        return {"settings": settings.set_settings(body)}
    except KeyError as e:
        raise HTTPException(400, str(e).strip("'")) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/portfolio/settings/reset")
def portfolio_settings_reset() -> dict:
    from app.portfolio import settings

    return {"settings": settings.reset_settings()}


@router.get("/portfolio/holdings")
def holdings_get() -> dict:
    from app.portfolio import holdings

    return {
        **holdings.get_positions(),
        "holdings": holdings.get_holdings(),
        "custom": holdings.is_custom(),
        "candidates": holdings.candidates(),
    }


def _holdings_call(fn, *args):
    try:
        return {"holdings": fn(*args)}
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'")) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.put("/portfolio/holdings")
def holdings_put(body: dict) -> dict:
    """Replace positions. Body: {"qty": {"TCS": 40, ...}} (shares), or {"weights": {...}}
    (any scale) to re-weight at today's prices keeping the total value."""
    from app.portfolio import holdings

    if "qty" in body:
        return _holdings_call(holdings.set_positions, body.get("qty") or {})
    return _holdings_call(holdings.set_holdings, body.get("weights") or {})


@router.post("/portfolio/holdings")
def holdings_add(body: dict) -> dict:
    from app.portfolio import holdings

    return _holdings_call(holdings.add_holding, str(body.get("symbol", "")))


@router.delete("/portfolio/holdings/{symbol}")
def holdings_remove(symbol: str) -> dict:
    from app.portfolio import holdings

    return _holdings_call(holdings.remove_holding, symbol)


@router.post("/portfolio/holdings/reset")
def holdings_reset() -> dict:
    """Back to the demo. Returns the positions it replaced, so the app can offer Undo."""
    from app.portfolio import holdings

    before = {s: [q, c] for s, (q, c) in holdings._raw().items()} if holdings.is_custom() else None
    return {**_holdings_call(holdings.reset_holdings), "undo": before}


@router.post("/portfolio/holdings/restore")
def holdings_restore(body: dict) -> dict:
    """Undo a reset. Body: {"positions": {"TCS": [shares, average cost], ...}}."""
    from app.portfolio import holdings

    return _holdings_call(holdings.restore_positions, body.get("positions") or {})


# ------------------------------------------------------------------ Watchlist
@router.get("/watchlist")
def watchlist_get() -> dict:
    from app.portfolio import watchlist

    return watchlist.items()


def _watch_call(fn, *args) -> dict:
    from app.portfolio import watchlist

    try:
        fn(*args)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'")) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return watchlist.items()


@router.post("/watchlist")
def watchlist_add(body: dict) -> dict:
    from app.portfolio import watchlist

    return _watch_call(watchlist.add, str(body.get("symbol", "")))


@router.delete("/watchlist/{symbol}")
def watchlist_remove(symbol: str) -> dict:
    from app.portfolio import watchlist

    return _watch_call(watchlist.remove, symbol)


@router.post("/watchlist/reset")
def watchlist_reset() -> dict:
    from app.portfolio import watchlist

    return _watch_call(watchlist.reset)


@router.get("/movers")
def movers(limit: int = Query(3, ge=1, le=10)) -> dict:
    from app.portfolio import watchlist

    return watchlist.movers(limit)


# ------------------------------------------------------------------ Accuracy
@router.get("/eval")
def eval_report() -> dict:
    """How accurate is FINN: live checks recomputed from current data, plus build-time ones."""
    from app import evals

    return evals.report()


@router.get("/eval/labels")
def eval_labels() -> dict:
    """The hand-labelled filings next to where FINN puts each one today."""
    from app import evals

    return evals.labelled_filings()


# ------------------------------------------------------------------ Compare
@router.get("/compare/peers")
def compare_peers(symbol: str) -> dict:
    from app.research.compare import peers

    return {"symbol": symbol.upper(), "peers": peers(symbol)}


@router.get("/compare")
def compare_two(a: str, b: str) -> dict:
    """Two companies side by side, computed in code from reported financials (no LLM)."""
    from app.research.compare import compare

    try:
        return compare(a, b)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # unknown ticker or numbers unavailable
        raise HTTPException(404, f"couldn't load numbers for {a.upper()} or {b.upper()}") from e


# ------------------------------------------------------------------ Push
@router.get("/digest/brief")
def digest_brief(window: str = "24h", start: str | None = None, end: str | None = None) -> dict:
    """FR-PUSH-11: Today as a short spoken script, read by the phone's own voice."""
    from app.intel.brief import build_brief

    try:
        return build_brief(window, start, end)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


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
    """Every field optional: what isn't sent keeps its current value. Bounds are only
    what makes arithmetic sense (a multiple above zero, a percentage under 100)."""

    volume_multiple: float | None = Field(None, gt=0, le=100)
    volume_low_multiple: float | None = Field(None, gt=0, le=100)
    volume_mode: Literal["high", "low", "either"] | None = None
    volume_window: int | None = Field(None, ge=2, le=250)
    price_abs_pct: float | None = Field(None, ge=0, le=100)
    price_direction: Literal["up", "down", "either"] | None = None
    combine: Literal["any", "all"] | None = None
    min_materiality: int | None = Field(None, ge=0, le=100)
    categories: list[str] | None = None
    enabled: dict[str, bool] | None = None


@router.get("/alert-rules")
def get_alert_rules() -> dict:
    return alerts_mod.get_rules() | {"all_categories": CATEGORIES}


@router.put("/alert-rules")
def put_alert_rules(rules: AlertRules) -> dict:
    unknown = set(rules.categories or []) - set(CATEGORIES)
    if unknown:
        raise HTTPException(400, f"unknown categories: {sorted(unknown)}")
    try:
        return alerts_mod.set_rules(rules.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


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


@router.get("/people/meetings")
def meetings_list() -> dict:
    from app.network import meetings

    return {"today": meetings.today().isoformat(), "meetings": meetings.list_meetings()}


@router.get("/people/meetings/prep")
def meetings_prep() -> dict:
    """Prep cards for meetings in the next two days, for the top of Today."""
    from app.network import meetings

    return {"prep": meetings.prep()}


@router.post("/people/meetings")
def meetings_add(body: dict) -> dict:
    from app.network import meetings

    try:
        return meetings.add_meeting(body.get("person", ""), body.get("day", ""), body.get("note"))
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/people/meetings/{meeting_id}")
def meetings_delete(meeting_id: int) -> dict:
    from app.network import meetings

    if not meetings.delete_meeting(meeting_id):
        raise HTTPException(404, "no such meeting")
    return {"deleted": meeting_id}


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


# ------------------------------------------------------------------ bring your own network
def _mine(fn, *args):
    try:
        return fn(*args)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/people/mine")
def mine_create() -> dict:
    """A private sandbox for this browser; send its id as X-Finn-User from then on."""
    from app.network import mine

    return {"account": mine.create_sandbox(), "expires_in_days": mine.SANDBOX_DAYS}


@router.put("/people/mine/career")
def mine_career(body: dict) -> dict:
    from app.network import mine

    return _mine(
        mine.set_career, body.get("roles", []), body.get("education", []), body.get("name")
    )


@router.post("/people/mine/contacts")
def mine_contact(body: dict) -> dict:
    from app.network import mine

    return _mine(mine.add_contact, body)


@router.post("/people/mine/linkedin")
def mine_linkedin(body: dict) -> dict:
    from app.network import mine

    return _mine(mine.import_linkedin, body.get("csv", ""))


@router.delete("/people/mine")
def mine_delete() -> dict:
    from app.network import mine

    _mine(mine.delete_sandbox)
    return {"deleted": True}


@router.post("/people/reset")
def people_reset() -> dict:
    """Restore this account's demo network (undo deletions)."""
    return {"contacts": graph.reset_network()}


@router.get("/notes")
def notes_list(symbol: str) -> dict:
    from app.network import notes

    return {"symbol": symbol.upper(), "notes": notes.list_notes(symbol)}


@router.post("/notes")
def notes_add(body: dict) -> dict:
    from app.network import notes

    try:
        return notes.add_note(body.get("symbol", ""), body.get("text", ""), body.get("contact"))
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/notes/{note_id}")
def notes_delete(note_id: int) -> dict:
    from app.network import notes

    if not notes.delete_note(note_id):
        raise HTTPException(404, "no such note")
    return {"deleted": note_id}


@router.put("/people/{person_id}/identity")
def person_identity(person_id: str, body: dict) -> dict:
    """FR-NET-05: the investor says whether a filing person is one of their contacts."""
    try:
        return graph.answer_identity(person_id, body.get("contact", ""), body.get("verdict", ""))
    except KeyError as e:
        raise HTTPException(404, "person not found") from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


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


@router.get("/people/{person_id}/questions")
def person_questions(person_id: str) -> dict:
    """Questions worth asking before a meeting, from FINN's research (no LLM)."""
    from app.network.diligence import meeting_questions

    out = meeting_questions(person_id)
    if out is None:
        raise HTTPException(404, "person not found")
    return out


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
        # the page asks before building (a build spends the day's AI budget), so it needs
        # to know whether the ticker exists and how many reads are left
        raise HTTPException(
            404,
            {
                "status": "not_built",
                "build_url": f"/research/{symbol.upper()}/stream",
                "covered": _listed(symbol),
                "builds_left": BUDGET.left(get_settings().max_live_builds_per_day),
            },
        )
    return service.with_network(view)


def _listed(symbol: str) -> dict | None:
    with session() as db:
        r = db.execute(
            "SELECT symbol, name FROM companies WHERE symbol=?", (symbol.upper(),)
        ).fetchone()
    return dict(r) if r else None


class BuildBudget:
    """Daily cap on live builds (they spend LLM budget) and one build at a time (a free
    instance has 512 MB and each build parses PDFs). Others wait in line with a message."""

    def __init__(self) -> None:
        self.day = ""
        self.used = 0
        self.gate = threading.Lock()  # one build at a time
        self._count = threading.Lock()  # the counter itself: two requests can't both take
        # the last unit. In-process, so it resets on restart and isn't shared across
        # workers; fine for one free instance, a database counter in production.

    def left(self, limit: int, today: str | None = None) -> int:
        today = today or datetime.now(UTC).date().isoformat()
        with self._count:
            return limit if today != self.day else max(0, limit - self.used)

    def take(self, limit: int, today: str) -> bool:
        with self._count:
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


# ------------------------------------------------------------------ Signal-to-Network (Task C)
class AnalyzeBody(BaseModel):
    announcement_id: str = Field(min_length=1, max_length=40)


@router.post("/announcements/analyze")
def announcements_analyze(body: AnalyzeBody) -> dict:
    """One filing as a signal: category, facts with evidence, a 0-100 attention score with
    its parts, and ranked contacts from the signed-in investor's own network. The investor
    comes from the session, never from the payload."""
    from app.intel import signal

    out = signal.analyze(body.announcement_id, current_owner())
    if out is None:
        raise HTTPException(404, "No such announcement")
    return out


class NetworkSearch(BaseModel):
    company_ticker: str = Field(min_length=1, max_length=20)
    theme: str | None = Field(default=None, max_length=60)
    max_degree: int = Field(default=2, ge=1, le=2)
    limit: int = Field(default=5, ge=1, le=10)


@router.post("/network/search")
def network_search(body: NetworkSearch) -> dict:
    from app.network import match

    return match.search(
        body.company_ticker.upper(), body.theme, body.max_degree, body.limit, current_owner()
    )


class SignalFeedback(BaseModel):
    kind: str = Field(max_length=30)
    person_id: str | None = Field(default=None, max_length=80)


@router.post("/signals/{announcement_id}/feedback")
def signal_feedback(announcement_id: str, body: SignalFeedback) -> dict:
    from app.intel import signal

    try:
        return signal.feedback(announcement_id, current_owner(), body.kind, body.person_id)
    except ValueError as e:
        raise HTTPException(400, f"Unknown feedback kind: {e}") from e


class PullMessage(BaseModel):
    message: str = Field(min_length=1, max_length=300)
    symbol: str | None = Field(default=None, max_length=20)
    intent: str | None = Field(default=None, max_length=20)


@router.post("/pull/chat")
def pull_chat(body: PullMessage) -> dict:
    """Ask (FR-PULL-13, FR-PULL-18). A message is planned in code: which report, about which
    of the ~2,600 listed companies. Data tools fetch fresh financials, prices and filings;
    analysis and the report are code, so most answers cost no model tokens. FINN's deeper
    research (promised vs delivered and the rest) answers its own questions where it has read
    the company, and open "why" questions on those go to grounded Q&A."""
    from app.agent import reports as agent_reports
    from app.agent import run as agent
    from app.agent.plan import plan

    owner = current_owner()
    if body.intent in agent_reports.KINDS:  # a tap on a report in the menu
        return agent.ask(body.message, body.symbol, body.intent, owner)

    intent = body.intent if body.intent in pull.TITLES else pull.route(body.message)
    p = plan(body.message, body.symbol, use_model=False)
    symbol = p.tickers[0] if len(p.tickers) == 1 or (intent == "network" and p.tickers) else None
    view = service.get_cached(symbol) if symbol else None
    if symbol and intent == "network":  # needs the investor's network
        listed = _listed(symbol)
        if listed or view:
            name = view["company"] if view else listed["name"]
            docs = view["documents"] if view else []
            return {"kind": "reply", **pull.network(symbol, name, body.message, owner, docs)}
    if symbol and intent == "brokers":  # read from brokerage reports
        listed = _listed(symbol)
        if listed or view:
            return {
                "kind": "reply",
                **pull.brokers(symbol, (view or {}).get("company") or listed["name"], owner),
            }
    if view and intent == "qa" and pull._WHY.search(body.message.strip().lower()):
        return _grounded_answer(view, body.message)  # an open "why" on a company FINN has read
    if view and (intent in RESEARCH_INTENTS or body.intent in pull.TITLES) and intent != "qa":
        return {"kind": "reply", **pull.reply(view, intent, owner)}
    out = (
        agent.reply(p, owner)
        if p.tickers or p.report == "portfolio"
        else agent.ask(body.message, body.symbol, None, owner)
    )
    if out["kind"] == "pick":
        return {
            "kind": "pick",
            "ready": [
                {"symbol": s["symbol"], "company": s["company"]} for s in service.summaries()
            ],
        }
    return out


# What FINN's built research answers better than a computed report: the call-by-call promise
# check, narrative vs numbers, the guidance read from calls, and open "why" questions.
RESEARCH_INTENTS = {
    "ledger",
    "narrative",
    "guidance",
    "balance",
    "cash",
    "trajectory",
    "business",
    "bull_bear",
}


def _grounded_answer(view: dict, message: str) -> dict:
    today = datetime.now(UTC).date().isoformat()
    if not QUESTIONS.take(get_settings().max_questions_per_day, today):
        return {
            "kind": "reply",
            **pull.reply(view, "overview"),
            "notice": "Today's open questions are used up on this demo, so here is the overview.",
        }
    try:
        answer = qa.answer(view, message)
    except Exception as e:  # LLM quota or provider error: the code-built outputs still work
        return {
            "kind": "reply",
            **pull.reply(view, "overview"),
            "notice": f"FINN couldn't answer that right now ({type(e).__name__}). "
            "The outputs below are built in code and still work.",
        }
    out = pull.reply(view, "overview")
    out.update(intent="qa", title="Answer", blocks=[{"type": "answer", **answer}])
    out["menu"] = [{"intent": k, "label": v} for k, v in pull.MENU]
    return {"kind": "reply", **out}


@router.get("/research/{symbol}/stream")
async def research_stream(symbol: str, force: bool = False):
    """Server-sent events: `progress` {step, message} … then `result` (the view) or `error`."""
    import asyncio

    today = datetime.now(UTC).date().isoformat()
    cached = None if force else service.get_cached(symbol.upper())
    if cached is None and not _listed(symbol):
        # checked before the budget: a mistyped ticker never spends a live read

        async def unknown():
            msg = f"{symbol.upper()} isn't an NSE-listed company FINN knows."
            yield {"event": "error", "data": json.dumps({"message": msg, "kind": "not_covered"})}

        return EventSourceResponse(unknown())
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
