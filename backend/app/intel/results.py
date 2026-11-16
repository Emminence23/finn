"""Results card (FR-CARD-01/02): headline numbers from the results filing, computed in code.

The LLM only *transcribes* line items from the results statement (current quarter, previous
quarter, year-ago quarter). Unit conversion, EBITDA, QoQ/YoY and the cross-check against
screener are deterministic (NFR-04).
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.db import session
from app.intel.pdftext import filing_pdf
from app.llm import Doc, get_llm
from app.llm.safety import UNTRUSTED_INPUT

log = logging.getLogger(__name__)
PROMPT_VERSION = "results-v2"

UNIT_TO_CRORE = {
    "crore": 1.0,
    "lakh": 0.01,
    "million": 0.1,
    "thousand": 0.0001,
    "rupees": 1e-7,
    "billion": 100.0,
}


class PeriodFigures(BaseModel):
    label: str = Field(description="Column heading, e.g. 'Quarter ended 30.09.2026'")
    period_end: str = Field(description="Quarter end as YYYY-MM, e.g. 2026-09")
    revenue_from_operations: float | None
    other_income: float | None
    finance_costs: float | None
    depreciation: float | None
    profit_before_tax: float | None
    profit_after_tax: float | None
    interest_earned: float | None = Field(
        default=None, description="Banks only: 'Interest earned' total line; null otherwise"
    )


class ResultsExtraction(BaseModel):
    found: bool = Field(description="False if this document has no quarterly results table")
    basis: Literal["consolidated", "standalone"]
    unit: Literal["crore", "lakh", "million", "thousand", "rupees", "billion"]
    is_lender: bool = Field(description="True for banks/NBFCs (interest income statements)")
    current: PeriodFigures | None
    previous_quarter: PeriodFigures | None
    year_ago_quarter: PeriodFigures | None


SYSTEM = """You transcribe numbers from an Indian listed company's quarterly results filing. \
Find the statement of financial results. Prefer the CONSOLIDATED statement if present, else \
standalone. Copy figures exactly as printed for three quarter columns: the current quarter, \
the immediately preceding quarter, and the same quarter of the previous year. Do not use \
half-year or full-year columns. Do not compute anything. Use null when a line is absent. For \
banks, revenue_from_operations is total income from operations (interest earned plus other \
operating income, excluding other income) and ALSO copy the 'Interest earned' total into \
interest_earned. profit_after_tax is the total net profit for the period (before \
non-controlling interests / minority share). Report the unit the statement states (e.g. \
'Rs in crore' → crore, 'Rs in lakhs' → lakh, '₹ million' → million)."""
SYSTEM += "\n" + UNTRUSTED_INPUT


def extract_results(pdf_url: str) -> ResultsExtraction | None:
    path = filing_pdf(pdf_url)
    if path is None:
        return None
    return get_llm().run(
        "extract_results",
        system=SYSTEM,
        prompt="Extract the quarterly figures.",
        docs=[Doc(title="Results filing", pdf_path=path)],
        schema=ResultsExtraction,
        prompt_version=PROMPT_VERSION,
        max_tokens=2000,
    )


# ---------------------------------------------------------------- deterministic part
def _cr(x: float | None, k: float) -> float | None:
    return None if x is None else round(x * k, 2)


def _ebitda(p: PeriodFigures, k: float) -> float | None:
    """Operating EBITDA = PBT + finance costs + depreciation − other income."""
    if None in (p.profit_before_tax, p.finance_costs, p.depreciation):
        return None
    return round(
        (p.profit_before_tax + p.finance_costs + p.depreciation - (p.other_income or 0)) * k, 2
    )


def is_bank(symbol: str) -> bool:
    """Banks (deposit-takers) vs NBFCs: decided from the balance sheet, not by the LLM."""
    # Any period with a balance sheet: ordering by period is unsafe ('TTM' sorts after dates
    # and carries no balance sheet), which once silently turned every bank into an NBFC.
    with session() as db:
        rows = db.execute(
            "SELECT data_json FROM financials_annual WHERE symbol=?", (symbol,)
        ).fetchall()
    return any("Deposits" in json.loads(r["data_json"]).get("balance_sheet", {}) for r in rows)


def _figures(p: PeriodFigures | None, k: float, lender: bool, bank: bool = False) -> dict | None:
    if p is None:
        return None
    # Banks: 'Interest earned' is the comparable top line. NBFCs: revenue from operations.
    top = p.interest_earned if bank and p.interest_earned is not None else p.revenue_from_operations
    return {
        "period": p.period_end,
        "revenue": _cr(top, k),
        "ebitda": None if lender else _ebitda(p, k),
        "pbt": _cr(p.profit_before_tax, k),
        "pat": _cr(p.profit_after_tax, k),
    }


def pct_change(new: float | None, old: float | None) -> float | None:
    """% change on a positive base only (PU-8). Off a loss or zero a percentage misleads
    (a loss of 10 turning into a profit of 5 would print +150%), so the card shows both
    values and a `change_note` instead."""
    if new is None or old is None or old <= 0:
        return None
    return round((new - old) / old * 100, 1)


def change_note(new: float | None, old: float | None) -> str | None:
    """Words for a move that has no meaningful percentage (base zero or negative)."""
    if new is None or old is None or old > 0:
        return None
    if old == 0:
        return None if new == 0 else ("up from nil" if new > 0 else "loss from nil")
    if new > 0:
        return "turned profitable"
    if new == 0:
        return "back to break-even"
    return "loss narrowed" if new > old else "loss widened"


def refresh_changes(card: dict | None) -> dict | None:
    """Recompute % changes and notes from a stored card's values, so cards saved before a
    rule change follow the current rule (the fixtures keep only what the filing said)."""
    if not card:
        return card
    for r in card["rows"]:
        v, p, y = r["value"], r.get("prev"), r.get("year_ago")
        r.update(
            qoq=pct_change(v, p),
            yoy=pct_change(v, y),
            qoq_note=change_note(v, p),
            yoy_note=change_note(v, y),
        )
    return card


def _rel_diff(a: float | None, b: float | None) -> float | None:
    """Relative gap between two readings of the same figure, for cross-checks."""
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / abs(b) * 100, 1)


METRICS = ("revenue", "ebitda", "pbt", "pat")


def build_results_card(symbol: str, ex: ResultsExtraction) -> dict | None:
    if not ex.found or ex.current is None:
        return None
    k = UNIT_TO_CRORE[ex.unit]
    bank = ex.is_lender and is_bank(symbol)
    cur = _figures(ex.current, k, ex.is_lender, bank)
    prev = _figures(ex.previous_quarter, k, ex.is_lender, bank)
    yago = _figures(ex.year_ago_quarter, k, ex.is_lender, bank)
    rows = [
        {
            "metric": m,
            "value": cur[m],
            "prev": prev[m] if prev else None,
            "year_ago": yago[m] if yago else None,
            "qoq": pct_change(cur[m], prev[m] if prev else None),
            "yoy": pct_change(cur[m], yago[m] if yago else None),
            "qoq_note": change_note(cur[m], prev[m] if prev else None),
            "yoy_note": change_note(cur[m], yago[m] if yago else None),
        }
        for m in METRICS
    ]
    margin = (
        round(cur["ebitda"] / cur["revenue"] * 100, 1)
        if cur["ebitda"] is not None and cur["revenue"]
        else None
    )
    return {
        "period": cur["period"],
        "basis": ex.basis,
        "unit": "Rs crore",
        "is_lender": ex.is_lender,
        "revenue_label": "Interest earned" if bank else "Revenue",
        "ebitda_margin": margin,
        "rows": rows,
        "cross_check": cross_check(symbol, cur),
        "source": "results filing",
    }


def cross_check(symbol: str, cur: dict, tolerance_pct: float = 1.0) -> dict:
    """Compare against screener's standardised quarterly table (FR-CARD-02)."""
    with session() as db:
        row = db.execute(
            "SELECT revenue, ebitda, pbt, pat FROM financials_quarterly "
            "WHERE symbol=? AND period=? AND source='screener'",
            (symbol, cur["period"]),
        ).fetchone()
    if row is None:
        return {"status": "unavailable", "diffs": {}}
    diffs = {}
    for m in ("revenue", "pbt", "pat"):  # screener's 'Operating Profit' is defined differently
        d = _rel_diff(cur[m], row[m])
        if d is not None:
            diffs[m] = d
    if not diffs:
        return {"status": "unavailable", "diffs": {}}
    off = [m for m, d in diffs.items() if abs(d) > tolerance_pct]
    if not off:
        return {"status": "match", "diffs": diffs}
    if off == ["pat"]:
        # Top line and PBT agree, so the gap is below PBT: almost always the filing's
        # owners' share vs screener's total profit (minority interest). Say so, don't hide it.
        return {"status": "pat_basis", "diffs": diffs}
    return {"status": "differs", "diffs": diffs}


def screener_results_card(symbol: str) -> dict | None:
    """Fallback when the filing can't be parsed: screener's table, labelled as such."""
    with session() as db:
        rows = db.execute(
            "SELECT period, revenue, ebitda, pbt, pat FROM financials_quarterly "
            "WHERE symbol=? AND source='screener' ORDER BY period DESC LIMIT 5",
            (symbol,),
        ).fetchall()
    if not rows:
        return None
    cur = dict(rows[0])
    prev = dict(rows[1]) if len(rows) > 1 else None
    yago = dict(rows[4]) if len(rows) > 4 else None
    return {
        "period": cur["period"],
        "basis": "consolidated",
        "unit": "Rs crore",
        "is_lender": cur["ebitda"] is None,
        "revenue_label": "Revenue",
        "ebitda_margin": (
            round(cur["ebitda"] / cur["revenue"] * 100, 1)
            if cur["ebitda"] is not None and cur["revenue"]
            else None
        ),
        "rows": [
            {
                "metric": m,
                "value": cur[m],
                "prev": prev and prev[m],
                "year_ago": yago and yago[m],
                "qoq": pct_change(cur[m], prev and prev[m]),
                "yoy": pct_change(cur[m], yago and yago[m]),
                "qoq_note": change_note(cur[m], prev and prev[m]),
                "yoy_note": change_note(cur[m], yago and yago[m]),
            }
            for m in METRICS
        ],
        "cross_check": {"status": "unavailable", "diffs": {}},
        "source": "screener.in (filing not parsed)",
    }
