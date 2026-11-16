# ruff: noqa: E501  (rule text and table field lists read better unbroken)
"""Analysis for the Ask pipeline: pure functions from tool results to figures and findings.
Everything a report states is computed here, with the rule that produced it, so the same
data always gives the same answer and no model does arithmetic.

    uv run python -m app.agent.analyse TRENT     # every analysis for one ticker, as JSON
"""

from __future__ import annotations

import json
import re
import statistics
import sys

# ------------------------------------------------------------------ helpers


def pct(a: float | None, b: float | None) -> float | None:
    """Growth of a over b in %, None when it isn't meaningful (missing, or a loss base)."""
    if a is None or b is None or b <= 0:
        return None
    return round((a / b - 1) * 100, 1)


def cagr(first: float | None, last: float | None, years: int) -> float | None:
    if not first or not last or first <= 0 or last <= 0 or years <= 0:
        return None
    return round(((last / first) ** (1 / years) - 1) * 100, 1)


def change_note(a: float | None, b: float | None) -> str | None:
    """Words for a change a % can't describe: swings across zero and losses."""
    if a is None or b is None:
        return None
    if b < 0 and a < 0:
        return "loss narrowed" if a > b else "loss widened"
    if b < 0 <= a:
        return "turned profitable"
    if b >= 0 > a:
        return "turned to a loss"
    return None


_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


def norm(period: str) -> str:
    """'2026-09' stays; 'Sep 2026' -> '2026-09'; anything else is returned unchanged."""
    p = period.strip()
    m = re.fullmatch(r"([A-Za-z]{3})\w*\s+(\d{4})", p)
    if m and m.group(1).lower() in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}"
    return p


def _year_ago(period: str, periods: list[str]) -> str | None:
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        return None
    want = f"{int(period[:4]) - 1}{period[4:]}"
    return want if want in periods else None


def fq(period: str) -> str:
    """'2026-09' -> 'Q2 FY27' (Indian fiscal year, April to March)."""
    period = norm(period)
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        return period
    y, m = int(period[:4]), int(period[5:7])
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m)
    return f"Q{q} FY{(y if m <= 3 else y + 1) % 100:02d}" if q else period


def fy(period: str) -> str:
    p = norm(period)
    return p if not re.match(r"\d{4}", p) else f"FY{int(p[:4]) % 100:02d}"


# ------------------------------------------------------------------ results
METRICS = [("revenue", "Revenue"), ("op_profit", "EBITDA"), ("pbt", "PBT"), ("pat", "PAT")]
# Lenders: EBITDA means nothing; net interest income (interest earned less interest paid) is
# the operating line, and screener's "financing profit" is after provisions, often negative.
LENDER_METRICS = [
    ("revenue", "Interest earned"),
    ("nii", "Net interest income"),
    ("pbt", "PBT"),
    ("pat", "PAT"),
]


def _with_nii(q: dict) -> dict:
    rev, intr = q.get("revenue"), q.get("interest")
    return q | {"nii": round(rev - intr, 2) if rev is not None and intr is not None else None}


def results(fin: dict) -> dict | None:
    """Latest quarter vs the previous one (QoQ) and the same quarter a year ago (YoY)."""
    qs = fin.get("quarters") or []
    if len(qs) < 2:
        return None
    lender = fin.get("is_financial")
    if lender:
        qs = [_with_nii(q) for q in qs]
    metrics = LENDER_METRICS if lender else METRICS
    periods = [q["period"] for q in qs]
    cur, prev = qs[-1], qs[-2]
    ya_p = _year_ago(cur["period"], periods)
    ya = next((q for q in qs if q["period"] == ya_p), None)
    label = dict(metrics)
    rows = []
    for k, _ in metrics:
        v, p, y = cur.get(k), prev.get(k), ya.get(k) if ya else None
        rows.append(
            {
                "metric": k,
                "label": label[k],
                "value": v,
                "prev": p,
                "year_ago": y,
                "qoq": pct(v, p),
                "yoy": pct(v, y),
                "qoq_note": change_note(v, p),
                "yoy_note": change_note(v, y),
            }
        )
    margin = (
        {"now": None, "prev": None, "year_ago": None}
        if lender
        else {
            "now": cur.get("opm"),
            "prev": prev.get("opm"),
            "year_ago": ya.get("opm") if ya else None,
        }
    )
    return {
        "period": cur["period"],
        "quarter": fq(cur["period"]),
        "prev_quarter": fq(prev["period"]),
        "year_ago_quarter": fq(ya_p) if ya_p else None,
        "rows": rows,
        "margin": margin,
        "eps": cur.get("eps"),
        "asset_quality": {
            "gnpa": cur.get("gnpa"),
            "nnpa": cur.get("nnpa"),
            "gnpa_prev": prev.get("gnpa"),
        }
        if fin.get("is_financial")
        else None,
    }


# ------------------------------------------------------------------ growth and quality
def growth(fin: dict) -> dict:
    years = [a for a in fin.get("annual") or [] if a["period"] != "TTM"]
    out: dict = {"years": [fy(a["period"]) for a in years]}
    for k in ("revenue", "pat", "op_profit"):
        series = [a.get(k) for a in years]
        out[k] = {
            "values": series,
            "yoy_last": pct(series[-1], series[-2]) if len(series) >= 2 else None,
            "cagr_3y": cagr(series[-4], series[-1], 3) if len(series) >= 4 else None,
            "cagr_5y": cagr(series[-6], series[-1], 5) if len(series) >= 6 else None,
        }
    margins = (
        [] if fin.get("is_financial") else [a.get("opm") for a in years if a.get("opm") is not None]
    )
    out["margin"] = {
        "values": margins,
        "change_3y": round(margins[-1] - margins[-4], 1) if len(margins) >= 4 else None,
    }
    ttm = next((a for a in fin.get("annual") or [] if a["period"] == "TTM"), None)
    out["ttm"] = {k: ttm.get(k) for k in ("revenue", "pat", "opm", "eps")} if ttm else None
    return out


def quality(fin: dict) -> dict:
    r = fin.get("ratios") or {}
    bal = (fin.get("balance") or [{}])[-1]
    eq = (bal.get("equity_capital") or 0) + (bal.get("reserves") or 0)
    debt = bal.get("borrowings")
    cf = fin.get("cashflow") or []
    cfo_ebitda = [c.get("cfo_ebitda") for c in cf if c.get("cfo_ebitda") is not None]
    fcf = [c.get("fcf") for c in cf]
    eff = fin.get("efficiency") or []
    wc = [e.get("wc_days") for e in eff if e.get("wc_days") is not None]
    debtor = [e.get("debtor_days") for e in eff if e.get("debtor_days") is not None]
    return {
        "roe": r.get("roe"),
        "roce": r.get("roce"),
        "debt_to_equity": round(debt / eq, 2) if debt is not None and eq > 0 else None,
        "borrowings": debt,
        "balance_date": bal.get("period"),
        "cfo_to_ebitda_avg": round(statistics.mean(cfo_ebitda), 0) if cfo_ebitda else None,
        "fcf": fcf,
        "fcf_years": [fy(c["period"]) for c in cf],
        "fcf_positive_years": sum(1 for x in fcf if x is not None and x > 0),
        "wc_days": wc,
        "wc_days_change": round(wc[-1] - wc[0], 0) if len(wc) >= 2 else None,
        "debtor_days": debtor,
        "lender": bool(fin.get("is_financial")),
    }


def valuation(fin: dict, g: dict) -> dict:
    r = fin.get("ratios") or {}
    pe, price, bv = r.get("pe"), r.get("price"), r.get("book_value")
    growth3 = (g.get("pat") or {}).get("cagr_3y")
    return {
        "pe": pe,
        "pb": round(price / bv, 1) if price and bv else None,
        "earnings_yield": round(100 / pe, 1) if pe and pe > 0 else None,
        "peg": round(pe / growth3, 1) if pe and growth3 and growth3 > 0 else None,
        "pat_cagr_3y": growth3,
        "dividend_yield": r.get("dividend_yield"),
        "market_cap_cr": r.get("market_cap_cr"),
    }


# ------------------------------------------------------------------ price action
def momentum(px: dict) -> dict | None:
    c, v = px.get("close") or [], px.get("volume") or []
    if len(c) < 30:
        return None

    def ret(n: int) -> float | None:
        return pct(c[-1], c[-1 - n]) if len(c) > n else None

    def sma(n: int) -> float | None:
        return round(statistics.mean(c[-n:]), 2) if len(c) >= n else None

    daily = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
    vol20 = statistics.mean(v[-21:-1]) if len(v) > 21 else None
    hi, lo = max(c), min(c)
    return {
        "last_date": px["dates"][-1],
        "close": c[-1],
        "day": ret(1),
        "week": ret(5),
        "month": ret(21),
        "quarter": ret(63),
        "half": ret(126),
        "year": pct(c[-1], c[0]),
        "high": hi,
        "low": lo,
        "from_high": pct(c[-1], hi),
        "from_low": pct(c[-1], lo),
        "sma50": sma(50),
        "sma200": sma(200),
        "above_sma50": c[-1] > sma(50) if sma(50) else None,
        "above_sma200": c[-1] > sma(200) if sma(200) else None,
        "volatility": round(statistics.pstdev(daily[-126:]) * (252**0.5) * 100, 1)
        if len(daily) > 20
        else None,
        "volume_vs_avg": round(v[-1] / vol20, 2) if vol20 else None,
        "period": px.get("period"),
    }


# ------------------------------------------------------------------ filings
def filings_digest(rows: list[dict] | dict, n: int = 8) -> dict:
    if not isinstance(rows, list):
        return {"count": 0, "items": [], "material": 0}
    routine = re.compile(
        r"trading window|loss of share|duplicate|newspaper|book closure|investor meet|analyst.*meet|copy of",
        re.I,
    )
    ranked = sorted(
        rows,
        key=lambda r: (
            -(r.get("materiality") or (0 if routine.search(r["type"] + r["subject"]) else 30)),
            r["date"],
        ),
    )
    keep = [r for r in ranked if not routine.search(r["type"] + " " + r["subject"])][:n]
    return {
        "count": len(rows),
        "material": sum(1 for r in rows if (r.get("materiality") or 0) >= 50),
        "items": sorted(keep, key=lambda r: r["date"], reverse=True),
    }


# ------------------------------------------------------------------ the call
_FORWARD = re.compile(
    r"\b(guid|expect|target|outlook|aim|plan to|going forward|next (year|quarter|few)|FY\s?2?\d|"
    r"by (march|december|the end)|capex|commission|margin of|growth of|double|we will)\w*",
    re.I,
)
_NUMBERED = re.compile(r"\d")


def guidance_sentences(pages: list[str], n: int = 8) -> list[dict]:
    """Management's forward-looking sentences, by keyword: ones naming a number first, then
    earlier pages (prepared remarks come before analyst questions). Code only, so it never
    paraphrases; each sentence is quoted with its page."""
    found = []
    for i, page in enumerate(pages, 1):
        for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", page)):
            s = s.strip()
            if 60 <= len(s) <= 320 and _FORWARD.search(s) and not s.endswith("?"):
                found.append(
                    {
                        "page": i,
                        "text": s,
                        "score": (2 if _NUMBERED.search(s) else 0)
                        + (1 if i <= len(pages) / 3 else 0),
                    }
                )
    found.sort(key=lambda x: (-x["score"], x["page"]))
    seen, out = set(), []
    for f in found:
        k = f["text"][:60]
        if k not in seen:
            seen.add(k)
            out.append({"page": f["page"], "text": f["text"]})
        if len(out) == n:
            break
    return sorted(out, key=lambda x: x["page"])


# ------------------------------------------------------------------ the scorecard
def _grade(value: float | None, good: float, ok: float, higher_better: bool = True) -> str | None:
    if value is None:
        return None
    v = value if higher_better else -value
    g, o = (good, ok) if higher_better else (-good, -ok)
    return "strong" if v >= g else "fair" if v >= o else "weak"


def scorecard(
    fin: dict, g: dict, qa: dict, val: dict, mom: dict | None, res: dict | None, brk: dict | None
) -> list[dict]:
    """Six checks, each graded strong / fair / weak by a stated rule. This is a reading of the
    numbers, not a recommendation."""
    out = []
    gr = (g.get("revenue") or {}).get("cagr_3y")
    gp = (g.get("pat") or {}).get("cagr_3y")
    out.append(
        {
            "check": "Growth",
            "grade": _grade(
                min(x for x in (gr, gp) if x is not None)
                if (gr is not None or gp is not None)
                else None,
                15,
                8,
            ),
            "detail": f"3-year CAGR: revenue {_p(gr)}, profit {_p(gp)}",
            "rule": "strong if both ≥15% a year, fair if ≥8%",
        }
    )
    if qa["lender"]:
        out.append(
            {
                "check": "Returns",
                "grade": _grade(qa["roe"], 15, 11),
                "detail": f"ROE {_p(qa['roe'])}",
                "rule": "strong if ROE ≥15%, fair if ≥11%",
            }
        )
    else:
        out.append(
            {
                "check": "Returns",
                "grade": _grade(qa["roce"], 20, 12),
                "detail": f"ROCE {_p(qa['roce'])}, ROE {_p(qa['roe'])}",
                "rule": "strong if ROCE ≥20%, fair if ≥12%",
            }
        )
        de = qa["debt_to_equity"]
        out.append(
            {
                "check": "Balance sheet",
                "grade": _grade(de, 0.3, 1.0, higher_better=False),
                "detail": f"debt to equity {de if de is not None else 'n/a'}×",
                "rule": "strong if ≤0.3×, fair if ≤1.0×",
            }
        )
        ce = qa["cfo_to_ebitda_avg"]
        out.append(
            {
                "check": "Cash conversion",
                "grade": _grade(ce, 80, 55),
                "detail": f"operating cash flow {ce if ce is not None else 'n/a'}% of EBITDA on average",
                "rule": "strong if ≥80%, fair if ≥55%",
            }
        )
    if res:
        yoy = next((r["yoy"] for r in res["rows"] if r["metric"] == "pat"), None)
        out.append(
            {
                "check": "Latest quarter",
                "grade": _grade(yoy, 15, 0),
                "detail": f"{res['quarter']} profit {_p(yoy, signed=True)} YoY"
                if yoy is not None
                else f"{res['quarter']}: profit not comparable",
                "rule": "strong if profit grew ≥15% YoY, fair if it grew at all",
            }
        )
    out.append(
        {
            "check": "Valuation",
            "grade": value_grade(val),
            "detail": f"P/E {val['pe'] if val['pe'] is not None else 'n/a'}, PEG {val['peg'] if val['peg'] is not None else 'n/a'} (P/E ÷ 3-year profit CAGR)",
            "rule": "attractive if PEG ≤1.2 or P/E ≤15; stretched if PEG >2 and P/E >25; fair otherwise",
        }
    )
    if mom:
        trend = (
            "above"
            if mom["above_sma200"]
            else "below"
            if mom["above_sma200"] is False
            else "n/a vs"
        )
        out.append(
            {
                "check": "Price trend",
                "grade": "strong"
                if mom["above_sma200"] and (mom["quarter"] or 0) > 0
                else "weak"
                if mom["above_sma200"] is False and (mom["quarter"] or 0) < 0
                else "fair",
                "detail": f"{trend} its 200-day average; 3 months {_p(mom['quarter'], signed=True)}, 1 year {_p(mom['year'], signed=True)}",
                "rule": "strong if above the 200-day average and up over 3 months; weak if below and down",
            }
        )
    if brk and brk.get("reports"):
        tgt = next((t for t in brk["targets"] if t["horizon"] != "not stated"), None) or (
            brk["targets"][0] if brk["targets"] else None
        )
        if tgt and tgt.get("vs_close_pct") is not None:
            out.append(
                {
                    "check": "Broker targets",
                    "grade": _grade(tgt["vs_close_pct"], 15, 0),
                    "detail": f"median target {_p(tgt['vs_close_pct'], signed=True)} from the last close ({tgt['n']} {'house' if tgt['n'] == 1 else 'houses'})",
                    "rule": "strong if ≥15% upside, fair if any",
                }
            )
    return [x for x in out if x["grade"]]


def value_grade(val: dict) -> str | None:
    """P/E and PEG together: a low multiple isn't stretched just because growth was slow."""
    pe, peg = val.get("pe"), val.get("peg")
    if pe is None or pe <= 0:
        return None
    if (peg is not None and peg <= 1.2) or pe <= 15:
        return "strong"
    if pe > 25 and (peg is None or peg > 2):
        return "weak"
    return "fair"


def _p(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.1f}%" if signed else f"{x:.1f}%"


# ------------------------------------------------------------------ bull and bear, by rule
def bull_bear(
    fin: dict, g: dict, qa: dict, val: dict, mom: dict | None, res: dict | None, brk: dict | None
) -> dict:
    """Each point is a rule that fired on the numbers, stated with its figure."""
    bull, bear = [], []
    rv, pt = g.get("revenue") or {}, g.get("pat") or {}
    if (rv.get("cagr_3y") or 0) >= 15:
        bull.append(f"Revenue has compounded {rv['cagr_3y']:.1f}% a year over three years.")
    elif rv.get("cagr_3y") is not None and rv["cagr_3y"] < 5:
        bear.append(f"Revenue growth is slow: {rv['cagr_3y']:.1f}% a year over three years.")
    if (pt.get("cagr_3y") or 0) >= 15:
        bull.append(f"Profit has compounded {pt['cagr_3y']:.1f}% a year over three years.")
    elif pt.get("cagr_3y") is not None and pt["cagr_3y"] < 0:
        bear.append(f"Profit has shrunk {abs(pt['cagr_3y']):.1f}% a year over three years.")
    m = g.get("margin") or {}
    if m.get("change_3y") is not None:
        if m["change_3y"] >= 2:
            bull.append(
                f"Operating margin is up {m['change_3y']:.1f} points over three years, to {m['values'][-1]:.0f}%."
            )
        elif m["change_3y"] <= -2:
            bear.append(
                f"Operating margin is down {abs(m['change_3y']):.1f} points over three years, to {m['values'][-1]:.0f}%."
            )
    if res:
        pat = next(r for r in res["rows"] if r["metric"] == "pat")
        rev = next(r for r in res["rows"] if r["metric"] == "revenue")
        if pat["yoy"] is not None and pat["yoy"] >= 15:
            bull.append(
                f"{res['quarter']} profit grew {pat['yoy']:.1f}% YoY, on revenue {_p(rev['yoy'], signed=True)}."
            )
        elif pat["yoy"] is not None and pat["yoy"] < 0:
            bear.append(
                f"{res['quarter']} profit fell {abs(pat['yoy']):.1f}% YoY (revenue {_p(rev['yoy'], signed=True)})."
            )
        elif pat["yoy_note"]:
            (bull if pat["yoy_note"] in ("loss narrowed", "turned profitable") else bear).append(
                f"{res['quarter']}: {pat['yoy_note']} from a year ago."
            )
        mg = res["margin"]
        if (
            mg["now"] is not None
            and mg["year_ago"] is not None
            and abs(mg["now"] - mg["year_ago"]) >= 1.5
        ):
            (bull if mg["now"] > mg["year_ago"] else bear).append(
                f"{res['quarter']} margin {mg['now']:.0f}% vs {mg['year_ago']:.0f}% a year ago."
            )
        aq = res.get("asset_quality")
        if (
            aq
            and aq["gnpa"] is not None
            and aq["gnpa_prev"] is not None
            and abs(aq["gnpa"] - aq["gnpa_prev"]) >= 0.1
        ):
            (bull if aq["gnpa"] < aq["gnpa_prev"] else bear).append(
                f"Gross NPA {aq['gnpa']:.2f}% vs {aq['gnpa_prev']:.2f}% last quarter."
            )
    if not qa["lender"]:
        if (qa["roce"] or 0) >= 20:
            bull.append(f"High returns on capital: ROCE {qa['roce']:.1f}%.")
        elif qa["roce"] is not None and qa["roce"] < 10:
            bear.append(f"Low returns on capital: ROCE {qa['roce']:.1f}%.")
        de = qa["debt_to_equity"]
        if de is not None and de <= 0.2:
            bull.append(f"Little debt: debt to equity {de}×.")
        elif de is not None and de >= 1.0:
            bear.append(f"Leveraged balance sheet: debt to equity {de}×.")
        if qa["cfo_to_ebitda_avg"] is not None and qa["cfo_to_ebitda_avg"] < 55:
            bear.append(
                f"Weak cash conversion: operating cash flow averages {qa['cfo_to_ebitda_avg']:.0f}% of EBITDA."
            )
        if qa["wc_days_change"] is not None and qa["wc_days_change"] >= 15:
            bear.append(
                f"Working capital days rose by {qa['wc_days_change']:.0f} over {len(qa['wc_days'])} years."
            )
    elif (qa["roe"] or 0) >= 15:
        bull.append(f"ROE of {qa['roe']:.1f}%.")
    vg = value_grade(val)
    growth_txt = (
        f" against {val['pat_cagr_3y']:.1f}% profit growth (PEG {val['peg']})"
        if val.get("peg")
        else ""
    )
    if vg == "strong":
        bull.append(f"Valuation looks undemanding: P/E {val['pe']}{growth_txt}.")
    elif vg == "weak":
        bear.append(
            f"Valuation is rich: P/E {val['pe']}{growth_txt or ', with no profit growth to set against it'}."
        )
    if mom:
        if mom["from_high"] is not None and mom["from_high"] <= -25:
            bear.append(f"The stock is {abs(mom['from_high']):.0f}% below its 52-week high.")
        if mom["above_sma200"] and (mom["quarter"] or 0) > 10:
            bull.append(
                f"Strong price trend: up {mom['quarter']:.1f}% in three months and above its 200-day average."
            )
    if brk and brk.get("reports"):
        r = brk["ratings"]
        if r.get("positive", 0) and not r.get("negative", 0):
            bull.append(
                f"Every rated brokerage FINN holds is positive ({r['positive']} of {sum(r.values())})."
            )
        if r.get("negative", 0):
            bear.append(f"{r['negative']} of the brokerages FINN holds rate it negative.")
    return {"bull": bull[:5], "bear": bear[:5]}


# ------------------------------------------------------------------ everything for a ticker
def analyse(ticker: str, deep: bool = False) -> dict:
    from app.agent import tools

    fin = tools.run("financials", ticker=ticker)
    if "error" in fin:
        return {"ticker": ticker, "error": fin["error"]}
    px = tools.run("prices", ticker=ticker, period="1y")
    brk = tools.run("brokers", ticker=ticker)
    brk = brk if isinstance(brk, dict) and "error" not in brk else None
    g, qa = growth(fin), quality(fin)
    val, res = valuation(fin, g), results(fin)
    mom = momentum(px) if "error" not in px else None
    out = {
        "ticker": ticker.upper(),
        "name": fin["name"],
        "about": fin["about"],
        "basis": fin["basis"],
        "source_url": fin["source_url"],
        "lender": fin["is_financial"],
        "results": res,
        "growth": g,
        "quality": qa,
        "valuation": val,
        "momentum": mom,
        "brokers": brk,
        "scorecard": scorecard(fin, g, qa, val, mom, res, brk),
        "bull_bear": bull_bear(fin, g, qa, val, mom, res, brk),
        "holding": tools.run("holding", ticker=ticker),
        "research": tools.run("research", ticker=ticker),
    }
    if deep:
        out["filings"] = filings_digest(tools.run("filings", ticker=ticker))
    return out


def digest(a: dict) -> str:
    """The analysis as a few hundred tokens of plain facts: what a model gets, if one is used
    at all, instead of raw tables and transcripts."""
    if "error" in a:
        return f"{a['ticker']}: data unavailable ({a['error']})"
    lines = [f"{a['name']} ({a['ticker']}), {a['basis']}."]
    if a["results"]:
        r = a["results"]
        lines.append(
            f"{r['quarter']}: "
            + "; ".join(
                f"{x['label']} {x['value']:,.0f} Cr (QoQ {_p(x['qoq'], True) if x['qoq'] is not None else x['qoq_note'] or 'n/a'}, YoY {_p(x['yoy'], True) if x['yoy'] is not None else x['yoy_note'] or 'n/a'})"
                for x in r["rows"]
                if x["value"] is not None
            )
        )
    for s in a["scorecard"]:
        lines.append(f"{s['check']}: {s['grade']} ({s['detail']}).")
    lines += [f"Bull: {b}" for b in a["bull_bear"]["bull"]] + [
        f"Bear: {b}" for b in a["bull_bear"]["bear"]
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING)
    a = analyse(sys.argv[1].upper(), deep=True)
    print(json.dumps(a, indent=1, ensure_ascii=False, default=str)[:15000])
    print("\nDIGEST\n" + digest(a))
