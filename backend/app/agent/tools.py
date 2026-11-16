# ruff: noqa: E501  (rule text and table field lists read better unbroken)
"""Data tools for the Ask pipeline (FR-PULL-18). Each fetches one kind of fresh data from a
public source and returns it as plain, structured Python (no prose). The model never sees raw
pages or tables: at most it picks which tools to run and with which arguments (a ticker, a
period); `analyse` turns the results into figures and `reports` into the answer.

    uv run python -m app.agent.tools                       # list the tools and their args
    uv run python -m app.agent.tools financials TRENT      # run one, print JSON

Results are kept in memory for a few hours, so a follow-up question costs no refetch."""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from app.clock import now
from app.db import session

log = logging.getLogger(__name__)
TTL_S = 4 * 3600


@dataclass(frozen=True)
class Tool:
    name: str
    fn: Callable
    args: dict[str, str]  # arg -> one-line description, for the planner and the CLI
    about: str


TOOLS: dict[str, Tool] = {}
_cache: dict[tuple, tuple[float, object]] = {}
_lock = threading.Lock()


def tool(name: str, about: str, **args: str):
    def wrap(fn):
        TOOLS[name] = Tool(name, fn, args, about)
        return fn

    return wrap


def run(name: str, **kw):
    """Run a tool, from the cache when fresh. A failing source returns {"error": ...} so a
    report can still be built from the others."""
    key = (name, tuple(sorted(kw.items())))
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    try:
        out = TOOLS[name].fn(**kw)
    except Exception as e:  # noqa: BLE001 - one source down shouldn't sink the answer
        log.warning("tool %s%s failed: %s", name, kw, e)
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def forget(ticker: str) -> None:
    """Drop a company's cached tool results, so a fresh report fetches everything again."""
    with _lock:
        for k in [k for k in _cache if ("ticker", ticker) in k[1]]:
            del _cache[k]


def company_name(ticker: str) -> str | None:
    with session() as db:
        r = db.execute("SELECT name FROM companies WHERE symbol=?", (ticker.upper(),)).fetchone()
    return r["name"] if r else None


def _rows(table: dict[str, dict], fields: dict[str, str], periods: list[str]) -> list[dict]:
    from app.agent.analyse import norm

    return [
        {"period": norm(p)} | {k: table.get(src, {}).get(p) for k, src in fields.items()}
        for p in periods
    ]


def _periods(table: dict[str, dict]) -> list[str]:
    """Column labels in date order, whether written '2026-09' or 'Sep 2026'."""
    from app.agent.analyse import norm

    return sorted((k for k in next(iter(table.values()), {}) if k != "TTM"), key=norm)


def _num(text: str | None) -> float | None:
    """'₹ 1,68,779 Cr.' -> 168779.0; '88.1' -> 88.1; '3,400 / 2,184' -> 3400.0."""
    if not text:
        return None
    t = str(text).replace(",", "").replace("₹", "").split("/")[0]
    digits = "".join(c for c in t if c.isdigit() or c in ".-")
    try:
        return float(digits) if digits not in ("", "-", ".") else None
    except ValueError:
        return None


# ------------------------------------------------------------------ the tools
@tool(
    "financials",
    "Reported accounts (screener.in's copy of the filings): quarters, years, balance sheet, cash flow, ratios",
    ticker="NSE symbol",
)
def financials(ticker: str) -> dict:
    from app.ingest.fundamentals import fetch_fundamentals
    from app.research.service import load_fundamentals

    t = ticker.upper()
    try:
        f = fetch_fundamentals(t)
        live = True
    except Exception as e:  # noqa: BLE001 - the committed copy is better than nothing
        log.warning("live fundamentals for %s failed (%s); using the stored copy", t, e)
        f, live = load_fundamentals(t), False
    tb = f["tables"]
    q, a = tb.get("quarters", {}), tb.get("annual_pl", {})
    qp, ap = _periods(q), _periods(a)
    qf = {
        "revenue": "Sales",
        "op_profit": "Operating Profit",
        "opm": "OPM %",
        "other_income": "Other Income",
        "interest": "Interest",
        "depreciation": "Depreciation",
        "pbt": "Profit before tax",
        "pat": "Net Profit",
        "eps": "EPS in Rs",
    }
    if f.get("is_financial"):  # lenders: screener labels revenue and profit differently
        qf |= {
            "revenue": "Revenue" if "Revenue" in q else "Sales",
            "op_profit": "Financing Profit",
            "opm": "Financing Margin %",
            "gnpa": "Gross NPA %",
            "nnpa": "Net NPA %",
        }
    b, c, r = tb.get("balance_sheet", {}), tb.get("cash_flow", {}), tb.get("ratios", {})
    bp, cp, rp = _periods(b), _periods(c), _periods(r)
    ratios = f.get("top_ratios") or {}
    return {
        "ticker": t,
        "name": f.get("name") or company_name(t) or t,
        "about": re.sub(r"\s*\[\d+\]", "", f.get("about") or "").strip() or None,
        "basis": f.get("basis", "consolidated"),
        "is_financial": bool(f.get("is_financial")),
        "source_url": f.get("source_url"),
        "live": live,
        "ratios": {
            "market_cap_cr": _num(ratios.get("Market Cap")),
            "price": _num(ratios.get("Current Price")),
            "high_52w": _num(ratios.get("High / Low")),
            "low_52w": _num((ratios.get("High / Low") or "/").split("/")[-1]),
            "pe": _num(ratios.get("Stock P/E")),
            "book_value": _num(ratios.get("Book Value")),
            "dividend_yield": _num(ratios.get("Dividend Yield")),
            "roce": _num(ratios.get("ROCE")),
            "roe": _num(ratios.get("ROE")),
        },
        "quarters": _rows(q, qf, qp[-9:]),
        "annual": _rows(a, qf | {"payout": "Dividend Payout %"}, ap[-6:])
        + (_rows(a, qf, ["TTM"]) if "TTM" in next(iter(a.values()), {}) else []),
        "balance": _rows(
            b,
            {
                "equity_capital": "Equity Capital",
                "reserves": "Reserves",
                "borrowings": "Borrowings",
                "total_assets": "Total Assets",
                "cwip": "CWIP",
                "investments": "Investments",
            },
            bp[-4:],
        ),
        "cashflow": _rows(
            c,
            {
                "cfo": "Cash from Operating Activity",
                "cfi": "Cash from Investing Activity",
                "fcf": "Free Cash Flow",
                "cfo_ebitda": "CFO/EBITDA",
            },
            cp[-4:],
        ),
        "efficiency": _rows(
            r,
            {
                "debtor_days": "Debtor Days",
                "inventory_days": "Inventory Days",
                "ccc": "Cash Conversion Cycle",
                "wc_days": "Working Capital Days",
                "roce": "ROCE %",
            },
            rp[-4:],
        ),
        "documents": f.get("documents", []),
    }


@tool(
    "prices",
    "Daily closing prices and volumes (Yahoo Finance)",
    ticker="NSE symbol",
    period="1y, 6mo, 3mo or 5y",
)
def prices(ticker: str, period: str = "1y") -> dict:
    from app.ingest.prices import fetch_prices

    df = fetch_prices([ticker.upper()], period).sort_values("date")
    return {
        "ticker": ticker.upper(),
        "period": period,
        "dates": df["date"].tolist(),
        "close": [float(x) for x in df["close"]],
        "volume": [int(x) for x in df["volume"]],
    }


@tool(
    "filings",
    "Exchange announcements (NSE) for a recent window",
    ticker="NSE symbol",
    days="look-back in days, default 60",
)
def filings(ticker: str, days: int = 60) -> list[dict]:
    from app.ingest.announcements import fetch_announcements

    today = now().date()
    rows = fetch_announcements(ticker.upper(), today - timedelta(days=int(days)), today)
    # FINN's own triage (category, materiality) where it has read the filing
    with session() as db:
        known = {
            r["id"]: dict(r)
            for r in db.execute(
                "SELECT id, category, materiality, summary FROM announcements WHERE symbol=?",
                (ticker.upper(),),
            ).fetchall()
        }
    out = []
    for r in sorted(rows, key=lambda r: r["ts"], reverse=True):
        k = known.get(r["id"], {})
        out.append(
            {
                "date": r["ts"][:10],
                "type": r["exch_category"],
                "subject": r["subject"][:300],
                "url": r["pdf_url"],
                "category": k.get("category"),
                "materiality": k.get("materiality"),
                "summary": k.get("summary"),
            }
        )
    return out


@tool(
    "brokers",
    "Brokerage reports FINN holds: ratings, targets by horizon, revisions",
    ticker="NSE symbol",
)
def brokers(ticker: str, owner: str = "demo") -> dict:
    from app.brokerage import service as bs

    ov = bs.overview(ticker.upper(), owner)
    return {
        "reports": ov["reports"],
        "brokerages": ov["brokerages"],
        "ratings": ov["ratings"],
        "targets": [
            {
                "horizon": g["horizon"],
                "n": g["brokerages"],
                "min": g["targets"]["min"],
                "max": g["targets"]["max"],
                "median": g["targets"]["median"],
                "vs_close_pct": g.get("median_vs_last_close_pct"),
                "who": g["who"],
            }
            for g in ov["targets"]
        ],
        "stale": len(ov["stale"]),
        "last_close": ov.get("last_close"),
    }


@tool("holding", "The investor's own position in this stock, if any", ticker="NSE symbol")
def holding(ticker: str) -> dict | None:
    from app.portfolio import analytics

    h = next((x for x in analytics.overview()["holdings"] if x["symbol"] == ticker.upper()), None)
    if not h:
        return None
    return {
        k: h[k]
        for k in (
            "qty",
            "avg_cost",
            "price",
            "weight",
            "gain_pct",
            "value",
            "return_1m",
            "return_6m",
        )
    }


@tool("portfolio", "The investor's holdings with weights, returns, P/E and ROE")
def portfolio() -> dict:
    from app.portfolio import analytics

    o = analytics.overview()
    return {
        "as_of": o["as_of"],
        "summary": o["summary"],
        "holdings": [
            {
                k: h.get(k)
                for k in (
                    "symbol",
                    "name",
                    "theme",
                    "weight",
                    "price",
                    "gain_pct",
                    "day_pct",
                    "return_1m",
                    "return_6m",
                    "pe",
                    "roe",
                    "volatility",
                    "is_lender",
                )
            }
            for h in o["holdings"]
        ],
    }


@tool(
    "research",
    "FINN's built research on the company, if any: the promise check and bull/bear points",
    ticker="NSE symbol",
)
def research(ticker: str) -> dict | None:
    from app.research import pull
    from app.research import service as rs

    view = rs.get_cached(ticker.upper())
    if not view:
        return None
    led = pull.ledger(view)
    bb = view.get("bull_bear") or {}
    return {
        "promise_summary": led["summary"][:3],
        "bull": [x["text"] for x in (bb.get("bull") or [])[:3]],
        "bear": [x["text"] for x in (bb.get("bear") or [])[:3]],
    }


@tool(
    "call",
    "The latest earnings call: management's forward-looking sentences, found by keyword",
    ticker="NSE symbol",
)
def call(ticker: str) -> dict | None:
    from app.agent.analyse import guidance_sentences
    from app.research.docs import load_pages, select_docs

    docs = run("financials", ticker=ticker).get("documents", [])
    refs = [r for r in select_docs(docs, n_transcripts=1) if r.kind == "transcript"]
    if not refs:
        return None
    pages = load_pages(ticker.upper(), refs[0])
    return {
        "label": refs[0].label,
        "url": refs[0].url,
        "pages": len(pages),
        "sentences": guidance_sentences(pages),
    }


def manifest() -> str:
    """The tool list as the planner sees it: names and arguments only, no data."""
    return "\n".join(f"- {t.name}({', '.join(t.args)}): {t.about}" for t in TOOLS.values())


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    if len(sys.argv) < 2:
        print(manifest())
        sys.exit()
    name, *rest = sys.argv[1:]
    names = list(TOOLS[name].args)
    print(
        json.dumps(
            run(name, **dict(zip(names, rest, strict=False))),
            indent=1,
            ensure_ascii=False,
            default=str,
        )[:20000]
    )
