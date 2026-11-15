"""HTTP API for Push, Network and company lookup (REQUIREMENTS §6.6)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.clock import now, window_bounds
from app.db import session
from app.intel import alerts as alerts_mod
from app.intel.digest import build_digest
from app.intel.taxonomy import CATEGORIES
from app.network import graph

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
               ORDER BY in_portfolio DESC, in_research_set DESC,
                        (symbol = ?) DESC, (symbol LIKE ?) DESC, LENGTH(symbol)
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
        if p.id != graph.ME and (p.is_contact or not contacts_only)
    ]
    return sorted(out, key=lambda x: -(x.get("strength") or 0))
