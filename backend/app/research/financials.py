"""Deterministic research sections (FR-PULL-03/04/06/07): no LLM touches these numbers.

Input is the screener fundamentals dict (tables keyed by row label -> {period: value}).
All amounts are Rs crore as screener reports them. Lenders get lender metrics (no EBITDA,
working-capital days or D/E, which mean little for a balance-sheet business).
"""

from __future__ import annotations

import re


def _row(table: dict, *names: str) -> dict[str, float | None]:
    for n in names:
        if n in table:
            return table[n]
    return {}


def _fy(series: dict) -> list[tuple[str, float | None]]:
    """Fiscal-year columns only (drops 'TTM'), oldest first."""
    return sorted(((k, v) for k, v in series.items() if re.match(r"\d{4}-\d{2}$", k)))


def cagr(series: dict, years: int) -> float | None:
    pts = [(k, v) for k, v in _fy(series) if v is not None]
    if len(pts) < years + 1:
        return None
    start, end = pts[-years - 1][1], pts[-1][1]
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 1)


def _num(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"-?[\d,]+(\.\d+)?", s)
    return float(m.group(0).replace(",", "")) if m else None


def _last(series: dict) -> tuple[str | None, float | None]:
    pts = [(k, v) for k, v in _fy(series) if v is not None]
    return pts[-1] if pts else (None, None)


def _ratio(a, b, pct=False, nd=2):
    if a is None or b in (None, 0):
        return None
    r = a / b * (100 if pct else 1)
    return round(r, nd)


def build_financials(f: dict) -> dict:
    t = f["tables"]
    lender = bool(f.get("is_financial"))
    q, pl, bs, cf = (
        t.get("quarters", {}),
        t.get("annual_pl", {}),
        t.get("balance_sheet", {}),
        t.get("cash_flow", {}),
    )
    ratios = t.get("ratios", {})

    rev_y = _row(pl, "Sales", "Revenue")
    op_y = _row(pl, "Operating Profit", "Financing Profit")
    margin_y = _row(pl, "OPM %", "Financing Margin %")
    pat_y = _row(pl, "Net Profit")
    rev_q = _row(q, "Sales", "Revenue")
    op_q = _row(q, "Operating Profit", "Financing Profit")
    margin_q = _row(q, "OPM %", "Financing Margin %")
    pat_q = _row(q, "Net Profit")

    equity = {
        k: (v or 0) + (_row(bs, "Reserves").get(k) or 0)
        for k, v in _row(bs, "Equity Capital").items()
    }
    debt = _row(bs, "Borrowings", "Borrowing")
    cfo = _row(cf, "Cash from Operating Activity")
    fcf = _row(cf, "Free Cash Flow")
    years = [k for k, _ in _fy(rev_y)]

    def series(*rows):
        return [{"period": y, **{name: r.get(y) for name, r in rows}} for y in years]

    quarters = sorted(k for k in rev_q)[-8:]
    top = f.get("top_ratios", {})
    fy_last, rev_last = _last(rev_y)
    snapshot = {
        "fy": fy_last,
        "revenue": rev_last,
        "revenue_ttm": rev_y.get("TTM"),
        "operating_profit": op_y.get(fy_last) if fy_last else None,
        "margin_pct": margin_y.get(fy_last) if fy_last else None,
        "margin_label": "Financing margin" if lender else "EBITDA margin (OPM)",
        "pat": pat_y.get(fy_last) if fy_last else None,
        "pat_ttm": pat_y.get("TTM"),
        "roe_pct": _num(top.get("ROE")),
        "roce_pct": None if lender else _num(top.get("ROCE")),
        "debt_to_equity": None if lender else _ratio(debt.get(fy_last), equity.get(fy_last)),
        "market_cap_cr": _num(top.get("Market Cap")),
        "pe": _num(top.get("Stock P/E")),
        "price": _num(top.get("Current Price")),
    }
    trajectory = {
        "annual": series(
            ("revenue", rev_y), ("operating_profit", op_y), ("margin_pct", margin_y), ("pat", pat_y)
        ),
        "quarterly": [
            {
                "period": p,
                "revenue": rev_q.get(p),
                "operating_profit": op_q.get(p),
                "margin_pct": margin_q.get(p),
                "pat": pat_q.get(p),
                "revenue_yoy": _yoy(rev_q, p),
                "pat_yoy": _yoy(pat_q, p),
            }
            for p in quarters
        ],
        "cagr": {
            "revenue_3y": cagr(rev_y, 3),
            "revenue_5y": cagr(rev_y, 5),
            "pat_3y": cagr(pat_y, 3),
            "pat_5y": cagr(pat_y, 5),
        },
    }
    cash = {
        "annual": [
            {
                "period": y,
                "cfo": cfo.get(y),
                "fcf": fcf.get(y),
                "pat": pat_y.get(y),
                "cfo_to_pat": _ratio(cfo.get(y), pat_y.get(y)),
            }
            for y in years
            if y in cfo
        ],
    }
    last3 = [y for y in years if y in cfo][-3:]
    cfo3, pat3 = sum(cfo.get(y) or 0 for y in last3), sum(pat_y.get(y) or 0 for y in last3)
    cash["cfo_to_pat_3y"] = _ratio(cfo3, pat3) if last3 else None
    cash["fcf_3y"] = round(sum(fcf.get(y) or 0 for y in last3), 1) if fcf else None

    balance = {
        "annual": [
            {
                "period": y,
                "borrowings": debt.get(y),
                "net_worth": equity.get(y),
                "debt_to_equity": _ratio(debt.get(y), equity.get(y)),
                "cwip": _row(bs, "CWIP").get(y),
                **(
                    {}
                    if lender
                    else {
                        "debtor_days": _row(ratios, "Debtor Days").get(y),
                        "inventory_days": _row(ratios, "Inventory Days").get(y),
                        "payable_days": _row(ratios, "Days Payable").get(y),
                        "working_capital_days": _row(ratios, "Working Capital Days").get(y),
                    }
                ),
            }
            for y in years
            if y in debt
        ],
    }
    if lender:
        npa = {"gross_npa_pct": _row(q, "Gross NPA %"), "net_npa_pct": _row(q, "Net NPA %")}
        balance["asset_quality"] = [
            {"period": p, **{k: v.get(p) for k, v in npa.items()}} for p in quarters
        ]

    out = {
        "is_lender": lender,
        "basis": f.get("basis"),
        "unit": "Rs crore",
        "source": f.get("source_url"),
        "snapshot": snapshot,
        "trajectory": trajectory,
        "cash_quality": cash,
        "balance_sheet": balance,
    }
    out["flags"] = flags(out, pl)
    return out


def _yoy(series: dict, period: str) -> float | None:
    y, m = period.split("-")
    prev = series.get(f"{int(y) - 1}-{m}")
    cur = series.get(period)
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def flags(fin: dict, pl: dict) -> list[dict]:
    """Rule-based red/green flags. Each carries the numbers that triggered it, so the
    narrative can cite them as `fin:<id>`."""
    out: list[dict] = []
    s, cash, bal = fin["snapshot"], fin["cash_quality"], fin["balance_sheet"]["annual"]
    c = fin["trajectory"]["cagr"]

    def add(fid, tone, text):
        out.append({"id": f"fin:{fid}", "tone": tone, "text": text})

    if c["revenue_3y"] is not None and c["revenue_3y"] >= 20:
        add("growth", "positive", f"Revenue compounded {c['revenue_3y']}% a year over 3 years")
    if c["revenue_3y"] is not None and c["revenue_3y"] < 5:
        add("growth", "negative", f"Revenue grew only {c['revenue_3y']}% a year over 3 years")
    if c["pat_3y"] is not None and c["pat_3y"] < 0:
        add(
            "profit_decline",
            "negative",
            f"Net profit fell {abs(c['pat_3y'])}% a year over 3 years",
        )
    elif c["pat_3y"] is None and fin["trajectory"]["annual"]:
        pats = [a["pat"] for a in fin["trajectory"]["annual"][-4:] if a["pat"] is not None]
        if len(pats) >= 2 and pats[-1] < pats[0]:
            add("profit_decline", "negative", "Net profit is lower than three years ago")
    r = cash.get("cfo_to_pat_3y")
    if r is not None and not fin["is_lender"]:
        if r < 0.5:
            add(
                "cash_conversion",
                "negative",
                f"Weak cash conversion: 3-year operating cash flow is {r:.2f}× net profit",
            )
        elif r >= 0.9:
            add("cash_conversion", "positive", f"Profits convert to cash: 3-year CFO/PAT {r:.2f}×")
    if cash.get("fcf_3y") is not None and cash["fcf_3y"] < 0 and not fin["is_lender"]:
        fcf3 = cash["fcf_3y"]
        add("fcf", "negative", f"Free cash flow was negative over 3 years (Rs {fcf3:,.0f} Cr)")
    if len(bal) >= 2 and not fin["is_lender"]:
        a, b = bal[-2], bal[-1]
        da, db = a.get("debtor_days"), b.get("debtor_days")
        if da and db and db - da >= 30:
            add(
                "receivables",
                "negative",
                f"Debtor days jumped from {da:.0f} to {db:.0f} in {b['period'][:4]}",
            )
        if b.get("debt_to_equity") is not None and b["debt_to_equity"] > 1:
            add("leverage", "negative", f"Debt/equity {b['debt_to_equity']:.2f}×")
        if b.get("debt_to_equity") is not None and b["debt_to_equity"] < 0.2:
            add("leverage", "positive", f"Lightly geared: debt/equity {b['debt_to_equity']:.2f}×")
    q = fin["trajectory"]["quarterly"]
    if len(q) >= 5 and q[-1]["margin_pct"] is not None and q[-5]["margin_pct"] is not None:
        d = q[-1]["margin_pct"] - q[-5]["margin_pct"]
        if abs(d) >= 2:
            add(
                "margin_trend",
                "positive" if d > 0 else "negative",
                f"{s['margin_label']} {'expanded' if d > 0 else 'contracted'} {abs(d):.0f} pts YoY "
                f"to {q[-1]['margin_pct']:.0f}% in {q[-1]['period']}",
            )
    oi, pbt = _row(pl, "Other Income"), _row(pl, "Profit before tax")
    fy = s["fy"]
    if fy and oi.get(fy) and pbt.get(fy) and pbt[fy] > 0 and oi[fy] / pbt[fy] >= 0.25:
        add(
            "other_income",
            "negative",
            f"Other income is {oi[fy] / pbt[fy] * 100:.0f}% of pre-tax profit in {fy[:4]}",
        )
    return out
