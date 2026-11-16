"""Compare two companies side by side (PLAN v2 "Later": cross-company comparison).

Everything is computed in code from the same tables the research view uses, so the
comparison costs nothing and every number traces to the reported financials. Each metric
says which way is better, and a few plain-language lines call out only the gaps that are
large enough to matter. Where the two businesses aren't comparable (a lender against a
manufacturer, different year ends) the comparison says so and drops the metrics that would
mislead instead of showing them.
"""

from __future__ import annotations

import re

from app.db import session
from app.network.companies import company_links, resolve_symbol
from app.research.financials import build_financials
from app.research.service import add_filed_quarter, company_name, get_cached, load_fundamentals

# key, label, unit, higher_is_better, applies_to_lenders, gap that is worth a sentence
METRICS = [
    ("revenue", "Revenue, last full year", "cr", None, True, None),
    ("revenue_3y", "Revenue growth, 3 years a year", "pct", True, True, 5.0),
    ("pat_3y", "Profit growth, 3 years a year", "pct", True, True, 5.0),
    ("revenue_yoy_q", "Revenue growth, latest quarter YoY", "pct", True, True, 10.0),
    ("margin_pct", "EBITDA margin, last full year", "pct", True, False, 3.0),
    ("cfo_to_pat_3y", "Cash conversion, 3-year CFO / profit", "x", True, False, 0.3),
    ("fcf_3y", "Free cash flow, last 3 years", "cr", True, False, None),
    ("working_capital_days", "Working capital days", "days", False, False, 20.0),
    ("debt_to_equity", "Debt / equity", "x", False, False, 0.3),
    ("roe_pct", "Return on equity", "pct", True, True, 4.0),
    ("roce_pct", "Return on capital employed", "pct", True, False, 4.0),
    ("pe", "Price / earnings", "x", None, True, None),
    ("market_cap_cr", "Market value", "cr", None, True, None),
]


def _values(fin: dict) -> dict:
    s, c = fin["snapshot"], fin["trajectory"]["cagr"]
    q = fin["trajectory"]["quarterly"]
    bal = fin["balance_sheet"]["annual"]
    last_bal = bal[-1] if bal else {}
    return {
        "revenue": s.get("revenue"),
        "revenue_3y": c.get("revenue_3y"),
        "pat_3y": c.get("pat_3y"),
        "revenue_yoy_q": q[-1].get("revenue_yoy") if q else None,
        "margin_pct": s.get("margin_pct"),
        "cfo_to_pat_3y": fin["cash_quality"].get("cfo_to_pat_3y"),
        "fcf_3y": fin["cash_quality"].get("fcf_3y"),
        "working_capital_days": last_bal.get("working_capital_days"),
        "debt_to_equity": s.get("debt_to_equity"),
        "roe_pct": s.get("roe_pct"),
        "roce_pct": s.get("roce_pct"),
        "pe": s.get("pe"),
        "market_cap_cr": s.get("market_cap_cr"),
    }


def _short(name: str) -> str:
    """Same rule as the app's shortName."""
    s = re.sub(r"\b(Limited|Ltd\.?|India|Industries|Company|Technologies|Technology)\b", "", name)
    s = s.replace("()", "")
    return re.sub(r"\s+", " ", s).strip(" (")


def _fmt(v: float, unit: str) -> str:
    if unit == "pct":
        return f"{v:.1f}%"
    if unit == "x":
        return f"{v:.2f}×"
    if unit == "days":
        return f"{v:.0f} days"
    return f"₹{v:,.0f} Cr"


_SENTENCE = {
    "revenue_3y": "{w} has grown revenue faster: {vw} a year over 3 years against {vl}.",
    "pat_3y": "{w} has grown profit faster: {vw} a year over 3 years against {vl}.",
    "revenue_yoy_q": "{w} is growing faster right now: {vw} YoY in the latest quarter, "
    "against {vl}.",
    "margin_pct": "{w} earns a wider margin: {vw} against {vl}.",
    "cfo_to_pat_3y": "{w} turns more of its profit into cash: {vw} against {vl}.",
    "working_capital_days": "{w} ties up less cash in working capital: {vw} against {vl}.",
    "debt_to_equity": "{w} carries less debt: {vw} debt to equity against {vl}.",
    "roe_pct": "{w} earns more on shareholders' money: {vw} ROE against {vl}.",
    "roce_pct": "{w} earns more on capital employed: {vw} against {vl}.",
}


_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fq(period: str) -> str:
    """'2026-09' -> 'Q2 FY27' (Indian financial year, April to March)."""
    y, m = int(period[:4]), int(period[5:7])
    fy = y + 1 if m >= 4 else y
    return f"Q{((m - 4) % 12) // 3 + 1} FY{fy % 100:02d}"


def compare(a: str, b: str) -> dict:
    a, b = a.upper(), b.upper()
    if a == b:
        raise ValueError("pick two different companies")
    fins, cos = [], []
    for sym in (a, b):
        f = load_fundamentals(sym)
        fin = build_financials(f)
        filed = add_filed_quarter(fin, sym)
        view = get_cached(sym)
        p = (view or {}).get("promises") or {}
        name = company_name(sym) or (view or {}).get("company") or sym
        fins.append(fin)
        cos.append(
            {
                "symbol": sym,
                "name": name,
                "short": _short(name),
                "fy": fin["snapshot"].get("fy"),
                "basis": fin.get("basis"),
                "is_lender": fin["is_lender"],
                "source": fin.get("source"),
                "filed": filed,
                "promises": {"score": p.get("score"), "counts": p.get("counts", {})}
                if p.get("items")
                else None,
            }
        )

    notes = []
    for c in cos:
        if c["filed"]:
            d = c["filed"]["filed"][:10]
            notes.append(
                f"{c['short']}{chr(39) if c['short'].endswith('s') else chr(39) + 's'} "
                f"{_fq(c['filed']['period'])} figures come from its results "
                f"filing of {int(d[8:])} {_MON[int(d[5:7]) - 1]}, read by AI; the rest is from "
                f"screener.in's tables."
            )
    mixed = cos[0]["is_lender"] != cos[1]["is_lender"]
    if mixed:
        lender = next(c["short"] for c in cos if c["is_lender"])
        notes.append(
            f"{lender} is a lender, so margin, cash conversion, working capital and gearing "
            f"mean different things for it. Those rows are left out."
        )
    both_lenders = cos[0]["is_lender"] and cos[1]["is_lender"]
    fy = [c["fy"] for c in cos]
    if fy[0] and fy[1] and fy[0][5:] != fy[1][5:]:
        notes.append("Their financial years end in different months, so annual figures are offset.")
    if fy[0] and fy[1] and fy[0][:4] != fy[1][:4]:
        notes.append(f"Latest full years differ ({fy[0][:7]} against {fy[1][:7]}).")

    lq = [(fin["trajectory"]["quarterly"] or [{}])[-1].get("period") for fin in fins]
    if lq[0] and lq[1] and lq[0] != lq[1]:
        notes.append(
            f"Latest quarters differ: {_fq(lq[0])} for {cos[0]['short']} against "
            f"{_fq(lq[1])} for {cos[1]['short']}, so the quarterly row compares different "
            f"periods."
        )
    va, vb = _values(fins[0]), _values(fins[1])
    metrics, lines = [], []
    for key, label, unit, higher, for_lenders, gap in METRICS:
        if (mixed or both_lenders) and not for_lenders:
            continue
        x, y = va.get(key), vb.get(key)
        better = None
        if higher is not None and x is not None and y is not None and x != y:
            better = 0 if (x > y) == higher else 1
        metrics.append(
            {"key": key, "label": label, "unit": unit, "values": [x, y], "better": better}
        )
        if better is not None and gap is not None and abs(x - y) >= gap and key in _SENTENCE:
            w, lo = (0, 1) if better == 0 else (1, 0)
            vals = (x, y)
            lines.append(
                _SENTENCE[key].format(
                    w=cos[w]["short"], vw=_fmt(vals[w], unit), vl=_fmt(vals[lo], unit)
                )
            )

    pa, pb = cos[0]["promises"], cos[1]["promises"]
    if (
        pa
        and pb
        and pa["score"] is not None
        and pb["score"] is not None
        and pa["score"] != pb["score"]
    ):
        w = 0 if pa["score"] > pb["score"] else 1
        lines.append(
            f"{cos[w]['short']}'s management has the better delivery record: "
            f"{cos[w]['promises']['score']} against {cos[1 - w]['promises']['score']} out of 100."
        )
    wins = [sum(m["better"] == i for m in metrics) for i in (0, 1)]
    return {"companies": cos, "metrics": metrics, "lines": lines[:4], "wins": wins, "notes": notes}


def peers(symbol: str) -> list[dict]:
    """Companies worth comparing with: the named competitors that FINN has numbers for."""
    from app.ingest.universe import fixtures_dir

    sym = symbol.upper()
    have = {p.stem for p in (fixtures_dir() / "fundamentals").glob("*.json")}
    links = company_links().get(sym, {})
    out: list[dict] = []

    def add(s: str | None, kind: str) -> None:
        if s and s in have and s != sym and s not in {o["symbol"] for o in out}:
            out.append({"symbol": s, "name": company_name(s) or s, "kind": kind})

    for kind in ("competitor", "customer", "supplier"):
        for name in links.get(kind, []):  # stored as company names
            add(resolve_symbol(name), kind)
    with session() as db:  # then the rest of its sector
        row = db.execute("SELECT sector FROM companies WHERE symbol=?", (sym,)).fetchone()
        if row and row["sector"]:
            for r in db.execute(
                "SELECT symbol FROM companies WHERE sector=? ORDER BY symbol", (row["sector"],)
            ):
                add(r["symbol"], "same sector")
    return out[:6]
