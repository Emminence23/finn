"""AI fine-tuning of the code's suggested weights, inside limits code enforces.

The optimiser in analytics.py sees prices and reported financials. It can't read a filing,
so it can't know that a CFO resigned last week or that a large order was cancelled. This
step gives the model exactly that context (material filings from the last 30 days, the
promise record, cash-flow warnings), each with an id, and asks for at most MAX_ADJUST
adjustments of at most ±MAX_NUDGE points, each citing those ids.

Code then:
  - drops adjustments to companies not held, or citing nothing it was given;
  - clips each to ±MAX_NUDGE points and keeps the MAX_ADJUST largest;
  - re-applies the name bounds and theme caps and renormalises;
  - returns both the code weights and the reviewed weights, so the change is visible.

The review runs only when asked (it uses the free-tier quota). Results are stored by a hash
of the inputs, so the same portfolio and news never call the model twice, and a stored
review in fixtures/portfolio_review.json serves the demo without any call.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

from app.db import session
from app.ingest.universe import fixtures_dir
from app.portfolio import analytics

PROMPT_VERSION = "portfolio-review-v1"
MAX_NUDGE = 2.0  # percentage points
MAX_ADJUST = 5

SYSTEM = """You are reviewing a suggested re-weighting of an Indian equity portfolio for a
fund manager. The weights were set by code from price risk and reported financials. Code
cannot read filings. Your only job is to adjust the weights where the EVENTS or RECORDS you
are given contain something the numbers would miss: a governance problem, a management
exit, a large order won or lost, guidance cut, a regulatory action.

Rules:
- At most 5 adjustments, each between -2 and +2 percentage points. Zero adjustments is a
  valid and common answer. Do not adjust for anything already reflected in the numbers
  (growth, margins, valuation, volatility).
- Every adjustment must cite at least one id from EVENTS or RECORDS. No outside knowledge.
- "reason": one plain sentence a fund manager would accept, naming the event.
- "summary": two sentences at most on what, if anything, the filings change about the
  suggestion. Say plainly if they change nothing."""


class Adjustment(BaseModel):
    symbol: str
    delta_pp: float = Field(description="percentage points, between -2 and +2")
    reason: str
    cites: list[str]


class Review(BaseModel):
    adjustments: list[Adjustment]
    summary: str


def _context(sug: dict) -> tuple[list[dict], list[dict]]:
    """Material filings (last 30 days) and records per holding, each with an id."""
    from app.intel.digest import build_digest

    held = {h["symbol"] for h in sug["holdings"]}
    events = [
        {
            "id": f"A:{c['id']}",
            "symbol": c["symbol"],
            "date": c["ts"][:10],
            "level": c["level"],
            "what": c["title"],
        }
        for c in build_digest("30d")["cards"]
        if c["symbol"] in held and c["level"] in ("important", "notable")
    ][:40]
    records = []
    for s in sorted(held):
        f = analytics._fundamentals(s) or {}
        if f.get("delivery") is not None:
            records.append(
                {
                    "id": f"P:{s}",
                    "symbol": s,
                    "what": f"management delivery score {f['delivery']}/100 on "
                    f"promises from the last four calls",
                }
            )
        if (
            not f.get("is_lender")
            and f.get("cfo_to_pat_3y") is not None
            and f["cfo_to_pat_3y"] < 0.5
        ):
            records.append(
                {
                    "id": f"F:{s}",
                    "symbol": s,
                    "what": f"3-year operating cash flow is {f['cfo_to_pat_3y']:.2f}x "
                    f"reported profit",
                }
            )
    return events, records


def _prompt(sug: dict, events: list[dict], records: list[dict]) -> str:
    table = [
        {
            "symbol": h["symbol"],
            "theme": h["theme"],
            "current": round(h["current"], 1),
            "suggested": round(h["suggested"], 1),
            "why": h["reason"],
        }
        for h in sug["holdings"]
    ]
    return (
        f"SUGGESTION (percent of portfolio)\n{json.dumps(table, ensure_ascii=False)}\n\n"
        f"EVENTS (filings, last 30 days)\n{json.dumps(events, ensure_ascii=False)}\n\n"
        f"RECORDS\n{json.dumps(records, ensure_ascii=False)}"
    )


def _key(prompt: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}\n{SYSTEM}\n{prompt}".encode()).hexdigest()[:20]


def _fixture() -> dict:
    path = fixtures_dir() / "portfolio_review.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _stored(key: str) -> dict | None:
    with session() as db:
        r = db.execute("SELECT output_json FROM portfolio_reviews WHERE key=?", (key,)).fetchone()
    if r:
        return json.loads(r["output_json"])
    return _fixture().get(key)


def apply(sug: dict, review: Review, events: list[dict], records: list[dict]) -> dict:
    """Enforce the limits and produce the reviewed weights. Pure code."""
    ids = {e["id"] for e in events} | {r["id"] for r in records}
    rows = {h["symbol"]: h for h in sug["holdings"]}
    kept, dropped = [], []
    for a in review.adjustments:
        sym = a.symbol.upper().strip()
        cites = [c for c in a.cites if c in ids]
        if sym not in rows:
            dropped.append({"symbol": sym, "why": "not held"})
            continue
        if not cites:
            dropped.append({"symbol": sym, "why": "cited nothing it was given"})
            continue
        delta = max(-MAX_NUDGE, min(MAX_NUDGE, a.delta_pp))
        if abs(delta) < 0.1:
            continue
        kept.append(
            {"symbol": sym, "delta": delta, "asked": a.delta_pp, "reason": a.reason, "cites": cites}
        )
    kept.sort(key=lambda k: -abs(k["delta"]))
    for k in kept[MAX_ADJUST:]:
        dropped.append({"symbol": k["symbol"], "why": f"more than {MAX_ADJUST} adjustments"})
    kept = kept[:MAX_ADJUST]

    want = {s: h["suggested"] / 100 for s, h in rows.items()}
    for k in kept:
        want[k["symbol"]] += k["delta"] / 100
    theme = {s: h["theme"] for s, h in rows.items()}
    lo = {s: analytics.MIN_W for s in rows}
    hi = {s: analytics.MAX_W for s in rows}
    final = analytics._project({s: max(v, 1e-6) for s, v in want.items()}, theme, lo, hi)
    for k in kept:
        k["applied"] = (final[k["symbol"]] - want[k["symbol"]] + k["delta"] / 100) * 100
    return {
        "summary": review.summary,
        "adjustments": kept,
        "dropped": dropped,
        "weights": {s: v * 100 for s, v in final.items()},
    }


def get_review(run: bool = False) -> dict:
    """The stored review for the current suggestion, or a new one when `run` is set."""
    from app.llm import get_llm

    sug = analytics.suggest()
    events, records = _context(sug)
    prompt = _prompt(sug, events, records)
    key = _key(prompt)
    out = _stored(key)
    if out is None and not run:
        return {"status": "not_run", "key": key, "events": len(events)}
    if out is None:
        res = get_llm().run(
            "portfolio_review",
            system=SYSTEM,
            prompt=prompt,
            schema=Review,
            prompt_version=PROMPT_VERSION,
            max_tokens=4000,
        )
        out = res.model_dump()
        with session() as db:
            db.execute(
                "INSERT OR REPLACE INTO portfolio_reviews (key, output_json) VALUES (?,?)",
                (key, json.dumps(out)),
            )
    applied = apply(sug, Review.model_validate(out), events, records)
    by_id = {e["id"]: e for e in events} | {r["id"]: r for r in records}
    for k in applied["adjustments"]:
        k["sources"] = [by_id[c] for c in k["cites"]]
    return {"status": "done", "key": key, "events": len(events), **applied}
