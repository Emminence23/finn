# ruff: noqa: E501  (user-facing sentences read better unbroken)
"""Reports for the Ask pipeline, written by code from `analyse` output. Each report is a list
of the blocks the Ask screen already draws (stats, table, points, text, note), so a report
costs no model tokens. Every figure comes from a tool result; every grade states its rule.

    uv run python -m app.agent.reports verdict TRENT
    uv run python -m app.agent.reports compare TCS INFY
"""

from __future__ import annotations

import json
import sys

from app.agent import analyse as an
from app.agent import tools

KINDS = {
    "snapshot": "Snapshot",
    "results": "Latest results",
    "bull_bear": "Bull vs bear",
    "verdict": "Weighing it up",
    "valuation": "Valuation",
    "momentum": "Price and momentum",
    "filings": "Recent filings",
    "guidance": "What management said",
    "full": "Full report",
    "compare": "Comparison",
    "portfolio": "Your portfolio",
    "brokers": "What brokers say",
}
MENU = [
    "verdict",
    "results",
    "bull_bear",
    "valuation",
    "momentum",
    "filings",
    "guidance",
    "brokers",
    "full",
]


# ------------------------------------------------------------------ formatting
def cr(x: float | None) -> str:
    if x is None:
        return "–"
    return f"{'−' if x < 0 else ''}₹{abs(x):,.0f} Cr"


def rs(x: float | None) -> str:
    return "–" if x is None else f"₹{x:,.2f}" if x < 100 else f"₹{x:,.0f}"


def pc(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "–"
    return f"{x:+.1f}%" if signed else f"{x:.1f}%"


def short(name: str) -> str:
    """'Tata Consultancy Services Ltd' -> 'Tata Consultancy'; 'Infosys Ltd' -> 'Infosys'."""
    words = [
        w for w in name.replace("Limited", "").replace("Ltd", "").replace(".", "").split() if w
    ]
    return " ".join(words[:2]) if len(" ".join(words)) > 16 else " ".join(words)


def _pt(text: str) -> dict:
    return {"text": text, "cites": []}


def _grade_word(g: str, check: str) -> str:
    if check == "Valuation":
        return {"strong": "Attractive", "fair": "Fair", "weak": "Stretched"}[g]
    return {"strong": "Strong", "fair": "Fair", "weak": "Weak"}[g]


def _source(a: dict, extra: str = "") -> dict:
    return {
        "type": "note",
        "text": f"Computed by FINN from reported financials ({a['basis']}, screener.in's copy of the filings), NSE prices and filings{extra}. Grades follow fixed rules shown with each check. Not investment advice.",
    }


# ------------------------------------------------------------------ sections
def results_block(a: dict) -> list[dict]:
    r = a.get("results")
    if not r:
        return [{"type": "text", "text": "No quarterly results available."}]

    def chg(v: float | None, note: str | None) -> str:
        return pc(v) if v is not None else (note or "–")

    rows = [
        [x["label"], cr(x["value"]), chg(x["qoq"], x["qoq_note"]), chg(x["yoy"], x["yoy_note"])]
        for x in r["rows"]
    ]
    blocks = [
        {
            "type": "table",
            "title": f"{r['quarter']} results vs {r['prev_quarter']} (QoQ) and {r['year_ago_quarter'] or 'a year ago'} (YoY)",
            "columns": ["", r["quarter"], "QoQ", "YoY"],
            "rows": rows,
        }
    ]
    m, aq = r["margin"], r.get("asset_quality")
    if m["now"] is not None:
        blocks.append(
            _txt(
                f"Operating margin {m['now']:.0f}%, against {m['prev']:.0f}% last quarter and {m['year_ago']:.0f}% a year ago."
                if m["year_ago"] is not None and m["prev"] is not None
                else f"Operating margin {m['now']:.0f}%."
            )
        )
    if aq and aq["gnpa"] is not None:
        blocks.append(
            _txt(
                f"Gross NPA {aq['gnpa']:.2f}%, net NPA {aq['nnpa']:.2f}%."
                if aq["nnpa"] is not None
                else f"Gross NPA {aq['gnpa']:.2f}%."
            )
        )
    return blocks


def _txt(t: str) -> dict:
    return {"type": "text", "text": t}


def stats_block(a: dict) -> dict:
    v, q, m = a["valuation"], a["quality"], a.get("momentum") or {}
    items = [
        {
            "label": "Price",
            "value": rs(m.get("close")),
            "sub": f"{m.get('last_date', '')} · 1y {pc(m.get('year'))}" if m else "",
        },
        {"label": "Market cap", "value": cr(v.get("market_cap_cr")), "sub": ""},
        {
            "label": "P/E",
            "value": f"{v['pe']:.1f}" if v.get("pe") else "–",
            "sub": f"PEG {v['peg']}" if v.get("peg") else "",
        },
        {
            "label": "ROE",
            "value": pc(q.get("roe"), signed=False),
            "sub": "" if q["lender"] else f"ROCE {pc(q.get('roce'), signed=False)}",
        },
    ]
    if not q["lender"]:
        items.append(
            {
                "label": "Debt to equity",
                "value": f"{q['debt_to_equity']}×" if q.get("debt_to_equity") is not None else "–",
                "sub": q.get("balance_date") or "",
            }
        )
    return {"type": "stats", "items": items}


def scorecard_block(a: dict) -> dict:
    tone = {"strong": "positive", "weak": "negative", "fair": None}
    return {
        "type": "points",
        "title": "What the numbers say",
        "items": [
            {
                "text": f"{s['check']}: {_grade_word(s['grade'], s['check'])}. {s['detail'][0].upper() + s['detail'][1:]} ({s['rule']}).",
                "cites": [],
                "tone": tone[s["grade"]],
            }
            for s in a["scorecard"]
        ],
    }


def bull_bear_blocks(a: dict) -> list[dict]:
    """One bull case and one bear case: the rules on the numbers first, then what FINN read
    in the earnings calls where it has read them."""
    bb = a["bull_bear"]
    rsch = a.get("research") or {}
    bull = [_pt(x) for x in bb["bull"]] + [
        _pt(f"From the calls: {x}") for x in rsch.get("bull", [])[:2]
    ]
    bear = [_pt(x) for x in bb["bear"]] + [
        _pt(f"From the calls: {x}") for x in rsch.get("bear", [])[:2]
    ]
    out = []
    if bull:
        out.append({"type": "points", "title": "Bull case", "tone": "positive", "items": bull})
    if bear:
        out.append({"type": "points", "title": "Bear case", "tone": "negative", "items": bear})
    if not out:
        out.append(_txt("No rule fired strongly either way on these numbers."))
    return out


def brokers_block(a: dict) -> list[dict]:
    b = a.get("brokers")
    if not b or not b.get("reports"):
        return []
    lines = [
        _pt(
            f"{b['reports']} reports from {b['brokerages']} brokerages; ratings: "
            + ", ".join(f"{n} {k}" for k, n in b["ratings"].items() if n and k != "not mapped")
            + "."
        )
    ]
    for t in b["targets"]:
        span = f"₹{t['min']:,.0f} to ₹{t['max']:,.0f}" if t["n"] > 1 else f"₹{t['median']:,.0f}"
        hz = (
            "No stated horizon"
            if t["horizon"] == "not stated"
            else f"{t['horizon'].replace(' months', '-month')} targets"
        )
        lines.append(_pt(f"{hz}: {span}, median {pc(t['vs_close_pct'])} from the last close."))
    return [{"type": "points", "title": "Brokerage views FINN holds", "items": lines}]


def press_block(ticker: str, wait_s: float = 0) -> list[dict]:
    """Banks' and brokers' calls as the press reported them (app/brokerage/news.py). With
    `wait_s`, a company not searched in the last 12 hours is searched now, up to that long."""
    import time

    from app.brokerage import news

    got = news.get(ticker, start=True)
    t_end = time.monotonic() + wait_s
    while (
        got["job"].get("status") == "running" and not got.get("latest") and time.monotonic() < t_end
    ):
        time.sleep(2)
        got = news.get(ticker, start=False)
    rows = got.get("latest") or []
    if not rows:
        if got["job"].get("status") == "running":
            return [
                _txt(
                    "Still searching the financial press for bank and broker calls; ask again in a minute."
                )
            ]
        return (
            [_txt("No bank or broker calls on it in the press in the last six months.")]
            if wait_s
            else []
        )
    tgts = [c["target"] for c in rows if c["target"] is not None]
    head = f"{len(rows)} houses in the press"
    if len(tgts) > 1:
        med = (
            sorted(tgts)[len(tgts) // 2]
            if len(tgts) % 2
            else sum(sorted(tgts)[len(tgts) // 2 - 1 : len(tgts) // 2 + 1]) / 2
        )
        head += f": targets {rs(min(tgts))} to {rs(max(tgts))}, median {rs(med)}"
    table = [
        [
            c["house"],
            (c["rating"] or "–").capitalize(),
            rs(c["target"])
            + (f" (from {rs(c['previous_target'])})" if c["previous_target"] else ""),
            c["date"] or "",
            c["source"],
        ]
        for c in rows
    ]
    summ = got.get("summary") or {}
    lead = (
        [{"type": "text", "text": summ["text"], "by": summ.get("by")}] if summ.get("text") else []
    )
    return [
        *lead,
        {
            "type": "table",
            "title": head,
            "columns": ["House", "Call", "Target", "Date", "Reported by"],
            "rows": table,
        },
        {
            "type": "note",
            "text": "As reported in the press, not read from the reports: AI listed each call and code kept it only if the house and the target are in the article's own sentence."
            + (
                " AI wrote the summary from code's figures; code checked every number and house in it."
                if summ.get("by") == "ai"
                else ""
            )
            + " The company page links every article.",
        },
    ]


def brokers_report(a: dict, ticker: str) -> list[dict]:
    """The report-read views FINN holds, then the press. When FINN holds no reports, it
    starts looking for public ones (ICICI Securities, PL Capital) for next time."""
    out = brokers_block(a)
    after = []
    b = a.get("brokers") or {}
    if not b.get("reports"):
        from datetime import UTC, datetime

        from app.api.routes import BUDGET
        from app.brokerage import discover
        from app.config import get_settings

        if discover.status(ticker).get("status") != "running" and BUDGET.take(
            get_settings().max_live_builds_per_day, datetime.now(UTC).date().isoformat()
        ):
            discover.search(ticker)
        after.append(
            _txt(
                "FINN holds no brokerage reports on it yet, so it is checking ICICI Securities' and PL Capital's public servers now; they will show on the company page."
            )
        )
    return out + press_block(ticker, wait_s=90) + after


def holding_block(a: dict) -> list[dict]:
    h = a.get("holding")
    if not h:
        return []
    return [
        _txt(
            f"You hold {h['qty']:,.0f} shares at an average {rs(h['avg_cost'])}: {h['weight']:.1f}% of the portfolio, {pc(h['gain_pct'])} overall."
        )
    ]


def valuation_blocks(a: dict) -> list[dict]:
    v, g = a["valuation"], a["growth"]
    rows = [
        ["P/E", f"{v['pe']:.1f}" if v.get("pe") else "–"],
        ["Price to book", f"{v['pb']}×" if v.get("pb") else "–"],
        ["Earnings yield", pc(v.get("earnings_yield"), signed=False)],
        ["3-year profit CAGR", pc(v.get("pat_cagr_3y"), signed=False)],
        ["PEG (P/E ÷ profit CAGR)", str(v["peg"]) if v.get("peg") else "–"],
        ["Dividend yield", pc(v.get("dividend_yield"), signed=False)],
        ["Market cap", cr(v.get("market_cap_cr"))],
    ]
    read = {
        "strong": "On FINN's rule this reads attractive (PEG at or below 1.2, or P/E at or below 15).",
        "fair": "On FINN's rule this reads fair (neither cheap for its growth nor stretched).",
        "weak": "On FINN's rule this reads stretched (P/E above 25 with PEG above 2).",
        None: "There's no positive P/E to judge it on.",
    }[an.value_grade(v)]
    ttm = g.get("ttm") or {}
    return [
        {"type": "table", "title": "Valuation", "columns": ["Measure", "Value"], "rows": rows},
        _txt(
            read
            + (f" Trailing twelve-month profit {cr(ttm.get('pat'))}." if ttm.get("pat") else "")
        ),
    ]


def momentum_blocks(a: dict) -> list[dict]:
    m = a.get("momentum")
    if not m:
        return [_txt("Price data isn't available right now.")]
    rows = [
        [k, pc(m[f])]
        for k, f in (
            ("1 day", "day"),
            ("1 week", "week"),
            ("1 month", "month"),
            ("3 months", "quarter"),
            ("6 months", "half"),
            ("1 year", "year"),
        )
    ]
    trend = []
    if m["sma200"]:
        trend.append(
            f"{'above' if m['above_sma200'] else 'below'} its 200-day average ({rs(m['sma200'])})"
        )
    if m["sma50"]:
        trend.append(
            f"{'above' if m['above_sma50'] else 'below'} its 50-day average ({rs(m['sma50'])})"
        )
    return [
        {
            "type": "stats",
            "items": [
                {"label": "Close", "value": rs(m["close"]), "sub": m["last_date"]},
                {
                    "label": "52-week range",
                    "value": f"{rs(m['low'])}–{rs(m['high'])}",
                    "sub": f"{pc(m['from_high'])} from the high",
                },
                {
                    "label": "Volatility",
                    "value": pc(m["volatility"], signed=False),
                    "sub": "annualised, 6 months",
                },
            ],
        },
        {"type": "table", "title": "Returns", "columns": ["Period", "Change"], "rows": rows},
        _txt(
            f"The stock is {' and '.join(trend)}."
            + (
                f" Last session's volume was {m['volume_vs_avg']}× its 20-day average."
                if m.get("volume_vs_avg")
                else ""
            )
        ),
    ]


def filings_blocks(ticker: str) -> list[dict]:
    d = an.filings_digest(tools.run("filings", ticker=ticker), n=10)
    if not d["items"]:
        return [_txt("No exchange filings in the last 60 days.")]
    return [
        {
            "type": "table",
            "title": f"Filings that matter, last 60 days ({len(d['items'])} of {d['count']}; routine ones left out)",
            "columns": ["Date", "Filing"],
            "rows": [
                [x["date"], (x["summary"] or x["subject"] or x["type"])[:200]] for x in d["items"]
            ],
        },
    ]


def guidance_blocks(ticker: str) -> list[dict]:
    c = tools.run("call", ticker=ticker)
    if not c or "error" in c:
        return [_txt("No earnings-call transcript is available for this company.")]
    if not c["sentences"]:
        return [_txt(f"FINN found no forward-looking statements in the {c['label']}.")]
    return [
        {
            "type": "points",
            "title": f"Forward-looking lines from the {c['label']}",
            "items": [_pt(f"“{s['text']}” (p{s['page']})") for s in c["sentences"]],
        },
        {
            "type": "note",
            "text": "Quoted word for word, picked by keyword (targets, guidance, timelines, numbers) in code. Read the call for the full context.",
        },
    ]


# ------------------------------------------------------------------ reports
def build(kind: str, tickers: list[str]) -> dict:
    """One report. Returns the title, blocks, the analysis digest and the links it used."""
    if kind == "portfolio":
        return portfolio_report()
    if kind == "compare" or len(tickers) > 1:
        return compare(tickers)
    t = tickers[0]
    a = an.analyse(t, deep=kind in ("full", "filings"))
    if "error" in a:
        return {
            "title": KINDS.get(kind, "Report"),
            "blocks": [_txt(f"FINN couldn't fetch {t}'s data right now ({a['error']}).")],
            "digest": "",
            "name": t,
        }
    blocks: list[dict]
    if kind == "results":
        blocks = results_block(a)
    elif kind == "bull_bear":
        blocks = bull_bear_blocks(a)
    elif kind == "valuation":
        blocks = valuation_blocks(a)
    elif kind == "momentum":
        blocks = momentum_blocks(a)
    elif kind == "filings":
        blocks = filings_blocks(t)
    elif kind == "guidance":
        blocks = guidance_blocks(t)
    elif kind == "brokers":
        blocks = brokers_report(a, t)
    elif kind == "verdict":
        grades = [s["grade"] for s in a["scorecard"]]
        lead = f"FINN doesn't tell you to buy or sell. On the numbers, {a['name']} reads strong on {grades.count('strong')} of {len(grades)} checks and weak on {grades.count('weak')}."
        weak = [s["check"].lower() for s in a["scorecard"] if s["grade"] == "weak"]
        if weak:
            lead += f" The weak spots: {', '.join(weak)}."
        blocks = [
            _txt(lead),
            stats_block(a),
            scorecard_block(a),
            *bull_bear_blocks(a),
            *brokers_block(a),
            *holding_block(a),
        ]
    elif kind == "full":
        blocks = [
            stats_block(a),
            _txt(a["about"] or ""),
            *results_block(a),
            scorecard_block(a),
            *bull_bear_blocks(a),
            *valuation_blocks(a)[:1],
            *brokers_block(a),
            *press_block(t),
            *filings_blocks(t)[:1],
            *holding_block(a),
        ]
    else:  # snapshot
        blocks = [
            stats_block(a),
            _txt(a["about"] or ""),
            *results_block(a)[:1],
            *bull_bear_blocks(a)[:2],
            *holding_block(a),
        ]
    blocks = [b for b in blocks if b.get("text", True)]
    if kind != "brokers":  # the brokers report carries its own source note
        blocks.append(_source(a, ", and the latest earnings call" if kind == "guidance" else ""))
    return {
        "title": KINDS[kind],
        "blocks": blocks,
        "digest": an.digest(a),
        "name": a["name"],
        "source_url": a["source_url"],
    }


def compare(tickers: list[str]) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(an.analyse, tickers))
    ok = [a for a in res if "error" not in a]
    if not ok:
        return {
            "title": KINDS["compare"],
            "blocks": [_txt("FINN couldn't fetch these companies' data right now.")],
            "digest": "",
            "name": " vs ".join(tickers),
        }

    def row(label, f):
        return [label, *[f(a) for a in ok]]

    def yo(a, metric):
        r = a.get("results")
        x = next((x for x in r["rows"] if x["metric"] == metric), None) if r else None
        return (
            pc(x["yoy"])
            if x and x["yoy"] is not None
            else (x["yoy_note"] if x and x["yoy_note"] else "–")
        )

    rows = [
        row("Market cap", lambda a: cr(a["valuation"]["market_cap_cr"])),
        row("P/E", lambda a: f"{a['valuation']['pe']:.1f}" if a["valuation"]["pe"] else "–"),
        row("PEG", lambda a: str(a["valuation"]["peg"]) if a["valuation"]["peg"] else "–"),
        row("ROE", lambda a: pc(a["quality"]["roe"], signed=False)),
        row("ROCE", lambda a: "–" if a["lender"] else pc(a["quality"]["roce"], signed=False)),
        row(
            "Debt to equity",
            lambda a: (
                "–"
                if a["lender"]
                else (
                    f"{a['quality']['debt_to_equity']}×"
                    if a["quality"]["debt_to_equity"] is not None
                    else "–"
                )
            ),
        ),
        row("Revenue CAGR, 3 years", lambda a: pc(a["growth"]["revenue"]["cagr_3y"], signed=False)),
        row("Profit CAGR, 3 years", lambda a: pc(a["growth"]["pat"]["cagr_3y"], signed=False)),
        row("Latest quarter revenue YoY", lambda a: yo(a, "revenue")),
        row("Latest quarter profit YoY", lambda a: yo(a, "pat")),
        row("1-year return", lambda a: pc((a.get("momentum") or {}).get("year"))),
        row("From 52-week high", lambda a: pc((a.get("momentum") or {}).get("from_high"))),
    ]
    names = [short(a["name"]) for a in ok]
    lines = []
    for label, key, better in (
        ("Cheaper on P/E", ("valuation", "pe"), min),
        ("Higher ROE", ("quality", "roe"), max),
        ("Faster profit growth (3 years)", ("growth", "pat"), max),
    ):
        vals = [
            (a[key[0]][key[1]]["cagr_3y"] if key[0] == "growth" else a[key[0]][key[1]], n)
            for a, n in zip(ok, names, strict=True)
        ]
        vals = [(v, n) for v, n in vals if v is not None]
        if len(vals) > 1:
            lines.append(_pt(f"{label}: {better(vals)[1]}."))
    blocks = [{"type": "table", "columns": ["", *names], "rows": rows}]
    if lines:
        blocks.append({"type": "points", "title": "Side by side", "items": lines})
    blocks.append(
        {
            "type": "note",
            "text": "Computed by FINN from each company's reported financials (screener.in's copy of the filings) and NSE prices. Lenders have no ROCE or debt-to-equity reading here. Not investment advice.",
        }
    )
    return {
        "title": KINDS["compare"],
        "blocks": blocks,
        "digest": "\n\n".join(an.digest(a) for a in ok),
        "name": " vs ".join(names),
    }


def portfolio_report() -> dict:
    p = tools.run("portfolio")
    hs = p["holdings"]
    rows = [
        [
            h["name"].replace(" Limited", ""),
            f"{h['weight']:.1f}%",
            pc(h["day_pct"]),
            pc(h["return_1m"]),
            pc(h["gain_pct"]),
            f"{h['pe']:.0f}" if h.get("pe") else "–",
        ]
        for h in hs
    ]
    best = max(hs, key=lambda h: h["return_1m"] or -999)
    worst = min(hs, key=lambda h: h["return_1m"] or 999)
    top3 = sum(h["weight"] for h in hs[:3])
    pts = [
        _pt(
            f"Best over the month: {best['name']} ({pc(best['return_1m'])}); worst: {worst['name']} ({pc(worst['return_1m'])})."
        ),
        _pt(f"The three largest positions are {top3:.0f}% of the portfolio."),
    ]
    themes: dict[str, float] = {}
    for h in hs:
        themes[h["theme"] or "other"] = themes.get(h["theme"] or "other", 0) + h["weight"]
    big = max(themes.items(), key=lambda x: x[1])
    pts.append(_pt(f"Largest theme: {big[0]} at {big[1]:.0f}%."))
    return {
        "title": KINDS["portfolio"],
        "blocks": [
            {"type": "points", "title": "At a glance", "items": pts},
            {
                "type": "table",
                "title": f"Holdings as of {p['as_of']}",
                "columns": ["Stock", "Weight", "Day", "1 month", "Overall", "P/E"],
                "rows": rows,
            },
            {"type": "note", "text": "Computed by FINN from your holdings and NSE prices."},
        ],
        "digest": "\n".join(
            f"{h['symbol']}: weight {h['weight']:.1f}%, 1m {pc(h['return_1m'])}, overall {pc(h['gain_pct'])}"
            for h in hs
        ),
        "name": "Portfolio",
    }


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING)
    kind, *ticks = sys.argv[1:]
    out = build(kind, [t.upper() for t in ticks])
    print(json.dumps(out, indent=1, ensure_ascii=False)[:12000])
