# ruff: noqa: E501  (user-facing sentences read better unbroken)
"""Pull as a conversation (FR-PULL-13 to FR-PULL-16).

A message about a company is routed in code to one of the brief's research outputs, each
built in code from the stored view (the company's annual report, last four earnings calls
and reported numbers). Only open questions ("why did receivables go up?") go to the model,
through `qa.answer`, which cites pages and drops uncited points. Nothing here reads news,
broker notes or the model's own knowledge of the company.

The centrepiece is `ledger`: the last four quarters, what management promised on each call
on headline numbers and growth, and what was delivered, with each verdict measured in code
where the reported numbers settle it (see `measure`) and the scorecard's verdict otherwise.
"""

from __future__ import annotations

import re

from app.research import measure
from app.research.promises import _CUT, horizon_end

# Headline numbers and growth commentary, as the guidance extractor tags them.
HEADLINE = {
    "revenue_growth": "growth",
    "aum_growth": "growth",
    "ebitda_margin": "margins",
    "pat": "margins",
    "working_capital": "cash",
    "debt": "funding",
    "capex": "funding",
}
# Dated projects (a plant, a capacity, an order) are kept beside the headline numbers: they
# are where the revenue growth is meant to come from.
PROJECTS = {"capacity", "order_book"}
GROUPS = {
    "growth": "Growth",
    "margins": "Margins and profit",
    "cash": "Cash and working capital",
    "funding": "Capex and debt",
    "projects": "Projects and capacity",
}
SHORT = {
    "growth": "growth",
    "margins": "margins",
    "cash": "cash",
    "funding": "funding",
    "projects": "projects",
}
JUDGED = ("delivered", "partly", "missed")

# The menu, in the order the brief lists it. `ledger` is its worked example.
MENU = [
    ("ledger", "Promised vs delivered"),
    ("business", "Business snapshot"),
    ("financial", "Financial snapshot"),
    ("trajectory", "Trajectory"),
    ("balance", "Balance sheet"),
    ("cash", "Cash quality"),
    ("narrative", "Narrative vs numbers"),
    ("guidance", "Guidance"),
    ("bull_bear", "Bull vs bear"),
]
TITLES = dict(MENU) | {
    "overview": "Overview",
    "qa": "Answer",
    "network": "Who can help",
    "brokers": "What brokers expect",
}

# Routing is code, so the same words always open the same analysis. First match wins.
_INTENTS = [
    (
        "network",
        r"who (can|could|should|would|in my network|do i know|knows)|whom|who to (call|ask)|"
        r"anyone (who|i know)|introduc|my network|my contacts",
    ),
    (
        "brokers",
        r"broker|analysts?\b|street|consensus|target price|price target|\btps?\b|"
        r"ratings?\b|upgrade|downgrade|sell[- ]side|research reports?",
    ),
    (
        "ledger",
        r"promis|deliver|last (four|4) quarters|(four|4) quarters|track record|kept (its|their) "
        r"word|credib|say[- ]do|walk(ed)? the talk",
    ),
    ("narrative", r"narrative|story|diverg|versus (the )?numbers|vs\.? (the )?numbers|spin"),
    ("bull_bear", r"\bbull|\bbear|case for|case against|upside|downside|thesis|risks?\b"),
    ("guidance", r"guid|outlook|forecast|target|expect|plans?\b|next year"),
    ("cash", r"\bcash|conversion|\bcfo\b|\bfcf\b"),
    (
        "balance",
        r"balance sheet|\bdebt|leverag|borrow|working capital|receivable|debtor|inventor|"
        r"funding|gearing|payable",
    ),
    (
        "trajectory",
        r"trajector|trend|multi[- ]?year|over the years|cagr|history|historical|growing|"
        r"compress|direction",
    ),
    (
        "financial",
        r"financial snapshot|headline numbers|key (numbers|ratios|metrics)|ratios?\b|valuation|"
        r"\bp/?e\b|\broe\b|\broce\b|at a glance|margins?\b|profit|revenue|numbers",
    ),
    (
        "business",
        r"what (does|do) .{0,40}\bdo\b|business|segment|revenue mix|products?|customers?|"
        r"what is it|who are they",
    ),
]
_WHY = re.compile(
    r"^\s*(why|how come|how did|how does|how is|how will|explain|what caused|what drove)", re.I
)


def route(message: str) -> str:
    """The output a message asks for. Open 'why' questions go to grounded Q&A; a message that
    names nothing but the company gets the overview."""
    m = message.strip().lower()
    if _WHY.search(m):
        return "qa"
    for intent, pattern in _INTENTS:
        if re.search(pattern, m):
            return intent
    return "overview" if len(m.split()) <= 3 else "qa"


# ------------------------------------------------------------------ formatting
def fq(period: str) -> str:
    """'2026-06' -> 'Q1 FY27' (Indian fiscal year, April to March)."""
    y, m = int(period[:4]), int(period[5:7])
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m)
    fy = y if m <= 3 else y + 1
    return f"Q{q} FY{fy % 100:02d}" if q else period


def fy(period: str) -> str:
    return f"FY{int(period[:4]) % 100:02d}"


def cr(x: float | None) -> str:
    if x is None:
        return "–"
    return f"{'−' if x < 0 else ''}₹{abs(x):,.0f} Cr"


def pc(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "–"
    s = f"{x:+.0f}%" if signed else f"{x:.0f}%"
    return s.replace("-", "−")


def _join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _lower(label: str) -> str:
    """'Financing margin' -> 'financing margin', but 'EBITDA margin' stays."""
    return label if label[1:2].isupper() else label[:1].lower() + label[1:]


def _short(label: str) -> str:
    """'Q1 FY27 call (Aug 2026)' -> 'Aug 2026 call'."""
    m = re.match(r"(.*?) call \((.*)\)", label or "")
    return f"{m.group(2)} call" if m else label


# ------------------------------------------------------------------ the ledger
def _status(s: dict, scored: dict, latest: str, fin: dict) -> dict:
    """Where one statement stands: the scorecard's verdict if it judged it, else code's
    measure, else whether it is still to fall due."""
    if s["kind"] == "update":
        return {"verdict": "update", "revision": bool(_CUT.search(f"{s['target']} {s['quote']}"))}
    it = scored.get(s["id"])
    due = horizon_end(s.get("horizon"))
    if it:
        return {
            "due": due,
            "verdict": it["verdict"],
            "actual": it.get("actual"),
            "evidence": it.get("evidence", []),
            "judged_by": it.get("judged_by", "ai"),
            "revised": it.get("revised"),
            "key": "+".join(it["promise_ids"]),
        }
    deadline = horizon_end(s.get("horizon"))
    if code := measure.judge(s["target"], deadline, latest, fin):
        return {
            "verdict": code["verdict"],
            "actual": code["actual"],
            "evidence": code["evidence"],
            "judged_by": "code",
        }
    if deadline and deadline > latest:
        return {"verdict": "too_early", "due": deadline}
    if not deadline:
        return {"verdict": "open"}  # no date given, so nothing falls due
    return {"verdict": "unclear"}  # due, and nothing reported settles it


def _quarter_row(q: dict | None) -> dict | None:
    if not q:
        return None
    return {
        k: q.get(k) for k in ("period", "revenue", "revenue_yoy", "margin_pct", "pat", "pat_yoy")
    }


def ledger(view: dict) -> dict:
    """Last four quarters: what each call promised on headline numbers, what was delivered."""
    fin, latest = view["financials"], view["latest_quarter"]
    calls = sorted(
        (d for d in view["documents"] if d["kind"] == "transcript"),
        key=lambda d: d.get("quarter") or d["period"],
    )[-4:]
    scored = {pid: it for it in view["promises"]["items"] for pid in it["promise_ids"]}
    quarters = {q["period"]: q for q in fin["trajectory"]["quarterly"]}
    rows, seen, tally = [], set(), []
    for d in calls:
        said, updates = [], []
        for s in view["guidance"]:
            if s["doc_id"] != d["id"]:
                continue
            group = HEADLINE.get(s.get("metric") or "")
            if (
                not group
                and s.get("metric") in PROJECTS
                and (s.get("horizon") or s["kind"] == "update")
            ):
                group = "projects"
            if not group:
                continue
            st = _status(s, scored, latest, fin)
            item = {
                "id": s["id"],
                "group": group,
                "target": s["target"],
                "quote": s["quote"],
                "page": s["page"],
                "doc_id": s["doc_id"],
                "horizon": s.get("horizon"),
                "segment": bool(measure._SEGMENT.search(s["target"].lower())),
                "materiality": s.get("materiality", 0),
                **st,
            }
            if s["kind"] == "update":
                updates.append(item)
                continue
            said.append(item)
            key = st.get("key") or s["id"]  # a promise repeated on later calls counts once
            if key not in seen:
                seen.add(key)
                tally.append(item)
        said.sort(
            key=lambda i: (i["group"] == "projects", i["segment"], -i["materiality"], i["id"])
        )
        updates.sort(key=lambda i: (not i["revision"], -i["materiality"]))
        rows.append(
            {
                "doc_id": d["id"],
                "call": d["label"],
                "quarter": d.get("quarter"),
                "quarter_label": fq(d["quarter"]) if d.get("quarter") else None,
                "delivered": _quarter_row(quarters.get(d.get("quarter"))),
                "promised": said,
                "updates": updates,
            }
        )
    counts = {
        v: sum(i["verdict"] == v for i in tally)
        for v in (*JUDGED, "revised", "unclear", "too_early", "open", "not_measurable")
    }
    return {
        "calls": rows,
        "counts": counts,
        "summary": _ledger_summary(rows, tally, counts, fin),
        "credibility": view["promises"].get("credibility"),
        "margin_label": fin["snapshot"].get("margin_label") or "Operating margin",
    }


def _ledger_summary(rows: list[dict], tally: list[dict], counts: dict, fin: dict) -> list[str]:
    if not rows:
        return ["FINN has no earnings calls for this company, so there is nothing to check."]
    out = []
    first, last = _short(rows[0]["call"]), _short(rows[-1]["call"])
    groups = _join([SHORT[g] for g in GROUPS if any(i["group"] == g for i in tally)])
    out.append(
        f"Across {len(rows)} calls, from the {first} to the {last}, management gave "
        f"{len(tally)} distinct targets on {groups or 'headline numbers'}."
    )
    due = sum(counts[v] for v in (*JUDGED, "unclear"))
    parts = [
        f"{counts['delivered']} delivered" if counts["delivered"] else "",
        f"{counts['partly']} partly" if counts["partly"] else "",
        f"{counts['missed']} missed" if counts["missed"] else "",
        f"{counts['unclear']} can't be settled from the reported numbers"
        if counts["unclear"]
        else "",
    ]
    later = counts["too_early"] + counts["revised"]
    tail = []
    if counts["revised"]:
        tail.append(f"{counts['revised']} were revised before falling due")
    if counts["too_early"]:
        tail.append(f"{counts['too_early']} fall due later")
    if counts["open"]:
        tail.append(f"{counts['open']} gave no date")
    if due:
        out.append(f"Of the {due} now due, {_join(parts)}" + (f"; {_join(tail)}." if tail else "."))
    elif later:
        out.append(f"None has fallen due yet: {_join(tail)}.")

    delivered = [r["delivered"] for r in rows if r["delivered"]]
    if delivered:
        yoy = [pc(q["revenue_yoy"], True) for q in delivered if q.get("revenue_yoy") is not None]
        margins = [q["margin_pct"] for q in delivered if q.get("margin_pct") is not None]
        label = (fin["snapshot"].get("margin_label") or "operating margin").split(" (")[0]
        line = f"Delivered, {fq(delivered[0]['period'])} to {fq(delivered[-1]['period'])}: revenue"
        line += f" {_join(yoy)} from a year earlier" if yoy else ""
        if margins:
            lo, hi = min(margins), max(margins)
            band = f"{lo:.0f}%" if lo == hi else f"between {lo:.0f}% and {hi:.0f}%"
            line += f"; {_lower(label)} {band}"
        out.append(line + ".")

    judged = sorted(
        (i for i in tally if i["verdict"] in JUDGED and i.get("actual")),
        key=lambda i: (i["segment"], -i["materiality"]),
    )
    if miss := next((i for i in judged if i["verdict"] == "missed"), None):
        out.append(f"Largest miss: {miss['target']}. {miss['actual']}.")
    if hit := next((i for i in judged if i["verdict"] == "delivered"), None):
        out.append(f"Delivered: {hit['target']}. {hit['actual']}.")
    cuts = [(r["call"], u) for r in rows for u in r["updates"] if u["revision"]]
    cuts.sort(key=lambda cu: -cu[1]["materiality"])
    if cuts:
        said = "; ".join(f"{u['target'].rstrip('.')} ({_short(call)})" for call, u in cuts[:2])
        out.append(f"Revised along the way: {said}.")
    upcoming = sorted(
        (i for i in tally if i["verdict"] == "too_early" and i.get("due")),
        key=lambda i: (i["due"], i["segment"], -i["materiality"]),
    )
    if upcoming:
        n = upcoming[0]
        out.append(f"Next to fall due: {n['target']} ({n['horizon']}).")
    return [re.sub(r"\.\.$", ".", s) for s in out]


# ------------------------------------------------------------------ the other outputs
def _qrows(fin: dict, n: int = 4) -> list[dict]:
    return fin["trajectory"]["quarterly"][-n:]


def _annual(fin: dict, part: str, n: int = 3) -> list[dict]:
    rows = fin[part]["annual"] if part != "trajectory" else fin["trajectory"]["annual"]
    return rows[-n:]


def business(view: dict) -> list[dict]:
    b = view.get("business") or {}
    blocks: list[dict] = []
    if w := b.get("what_they_do"):
        blocks.append({"type": "text", "text": w["text"], "cites": w.get("cites", [])})
    if segs := b.get("segments"):
        blocks.append(
            {
                "type": "points",
                "title": "Segments and revenue mix",
                "items": [
                    {
                        "text": f"{s['name']}" + (f": {s['share']}" if s.get("share") else ""),
                        "cites": s.get("cites", []),
                    }
                    for s in segs
                ],
            }
        )
    for key, title in (
        ("customers_and_markets", "Customers and markets"),
        ("recent_developments", "Recent developments"),
    ):
        if b.get(key):
            blocks.append({"type": "points", "title": title, "items": b[key][:4]})
    if not blocks:
        return [
            {
                "type": "text",
                "text": "FINN couldn't write a business snapshot from the annual report it has.",
            }
        ]
    blocks.append(
        {
            "type": "note",
            "text": "Written by AI from the annual report and calls; every line cites its page.",
        }
    )
    return blocks


def financial(view: dict) -> list[dict]:
    f = view["financials"]
    s = f["snapshot"]
    label = (s.get("margin_label") or "Operating margin").split(" (")[0]
    tiles = [
        (
            "Revenue",
            cr(s.get("revenue")),
            f"{fy(s['fy'])} · last 12 months {cr(s.get('revenue_ttm'))}",
        ),
        (
            label,
            pc(s.get("margin_pct")),
            f"{fy(s['fy'])} · operating profit {cr(s.get('operating_profit'))}",
        ),
        ("Net profit", cr(s.get("pat")), f"{fy(s['fy'])} · last 12 months {cr(s.get('pat_ttm'))}"),
        (
            "Return on equity",
            pc(s.get("roe_pct")),
            f"ROCE {pc(s.get('roce_pct'))}" if s.get("roce_pct") is not None else "",
        ),
        (
            "Debt to equity",
            f"{s['debt_to_equity']:.2f}×" if s.get("debt_to_equity") is not None else "–",
            "",
        ),
        (
            "P/E",
            f"{s['pe']:.0f}" if s.get("pe") else "–",
            f"market cap {cr(s.get('market_cap_cr'))}",
        ),
    ]
    blocks: list[dict] = [
        {"type": "stats", "items": [{"label": a, "value": b, "sub": c} for a, b, c in tiles]}
    ]
    if f.get("flags"):
        blocks.append(
            {
                "type": "points",
                "title": "What stands out",
                "items": [
                    {
                        "text": x["text"],
                        "tone": x["tone"],
                        "cites": [{"doc": x["id"], "page": None}],
                    }
                    for x in f["flags"]
                ],
            }
        )
    blocks.append(
        {
            "type": "note",
            "text": f"Reported figures, {f['basis']}, ₹ crore. Flags are computed in code.",
        }
    )
    return blocks


def trajectory(view: dict) -> list[dict]:
    f = view["financials"]
    annual = _annual(f, "trajectory", 5)
    rows = []
    for i, a in enumerate(annual):
        prev = annual[i - 1] if i else None
        yoy = (a["revenue"] / prev["revenue"] - 1) * 100 if prev and prev.get("revenue") else None
        rows.append(
            [
                fy(a["period"]),
                cr(a["revenue"]),
                pc(yoy, True) if yoy is not None else "–",
                pc(a.get("margin_pct")),
                cr(a.get("pat")),
            ]
        )
    c = f["trajectory"].get("cagr") or {}
    first, last = annual[0], annual[-1]
    reads = []
    if c.get("revenue_3y") is not None:
        r3, r5 = c["revenue_3y"], c.get("revenue_5y")
        pace = ""
        if r5 is not None:
            pace = (
                " — slower than"
                if r3 < r5 - 3
                else " — faster than"
                if r3 > r5 + 3
                else " — about the same as"
            )
            pace += f" the five-year {pc(r5)}"
        reads.append(f"Revenue compounded {pc(r3)} a year over three years{pace}.")
    if c.get("pat_3y") is not None and c.get("revenue_3y") is not None:
        gap = c["pat_3y"] - c["revenue_3y"]
        word = "faster than" if gap > 3 else "slower than" if gap < -3 else "in line with"
        reads.append(f"Profit grew {pc(c['pat_3y'])} a year, {word} revenue.")
    if first.get("margin_pct") is not None and last.get("margin_pct") is not None:
        d = last["margin_pct"] - first["margin_pct"]
        word = "widened" if d >= 1 else "compressed" if d <= -1 else "held"
        reads.append(
            f"Margin {word}: {pc(first['margin_pct'])} in {fy(first['period'])} to {pc(last['margin_pct'])} in {fy(last['period'])}."
        )
    q = _qrows(f)
    qrows = [
        [
            fq(x["period"]),
            cr(x["revenue"]),
            pc(x.get("revenue_yoy"), True),
            pc(x.get("margin_pct")),
            pc(x.get("pat_yoy"), True),
        ]
        for x in q
    ]
    return [
        {
            "type": "points",
            "title": "What's growing, what's compressing",
            "items": [{"text": t, "cites": []} for t in reads],
        },
        {
            "type": "table",
            "title": "Year by year",
            "columns": ["Year", "Revenue", "Growth", "Margin", "Profit"],
            "rows": rows,
        },
        {
            "type": "table",
            "title": "Last four quarters",
            "columns": ["Quarter", "Revenue", "YoY", "Margin", "Profit YoY"],
            "rows": qrows,
        },
        {
            "type": "note",
            "text": "Computed in code from reported figures. YoY compares with the same quarter a year earlier.",
        },
    ]


def _transpose(rows: list[dict], fields: list[tuple[str, str, str]]) -> dict:
    cols = ["", *[fy(r["period"]) for r in rows]]
    out = []
    for key, label, kind in fields:
        vals = [r.get(key) for r in rows]
        if all(v is None for v in vals):
            continue
        fmt = {
            "cr": cr,
            "x": lambda v: f"{v:.2f}×" if v is not None else "–",
            "d": lambda v: f"{v:.0f}" if v is not None else "–",
        }[kind]
        out.append([label, *[fmt(v) for v in vals]])
    return {"type": "table", "columns": cols, "rows": out}


def balance(view: dict) -> list[dict]:
    f = view["financials"]
    rows = _annual(f, "balance_sheet", 3)
    table = _transpose(
        rows,
        [
            ("borrowings", "Borrowings", "cr"),
            ("net_worth", "Net worth", "cr"),
            ("debt_to_equity", "Debt / equity", "x"),
            ("debtor_days", "Debtor days", "d"),
            ("inventory_days", "Inventory days", "d"),
            ("payable_days", "Payable days", "d"),
            ("working_capital_days", "Working-capital days", "d"),
            ("cwip", "Capital work in progress", "cr"),
        ],
    )
    reads = []
    a, b = rows[0], rows[-1]
    if a.get("borrowings") is not None and b.get("borrowings") is not None:
        word = (
            "rose"
            if b["borrowings"] > a["borrowings"] * 1.05
            else "fell"
            if b["borrowings"] < a["borrowings"] * 0.95
            else "held"
        )
        reads.append(
            f"Borrowings {word} from {cr(a['borrowings'])} to {cr(b['borrowings'])} over {len(rows) - 1} years."
        )
    if a.get("working_capital_days") is not None and b.get("working_capital_days") is not None:
        reads.append(
            f"The working-capital cycle went from {a['working_capital_days']:.0f} to {b['working_capital_days']:.0f} days"
            + (
                f"; debtor days {a['debtor_days']:.0f} to {b['debtor_days']:.0f}."
                if a.get("debtor_days") is not None
                else "."
            )
        )
    if (
        a.get("net_worth") is not None
        and b.get("net_worth")
        and b["net_worth"] > a["net_worth"] * 1.5
        and (b.get("borrowings") or 0) < b["net_worth"]
    ):
        reads.append(
            f"Net worth grew from {cr(a['net_worth'])} to {cr(b['net_worth'])}, so growth has been funded mostly with equity."
        )
    flags = [x for x in f.get("flags", []) if x["id"] in ("fin:leverage", "fin:receivables")]
    items = [{"text": t, "cites": []} for t in reads] + [
        {"text": x["text"], "tone": x["tone"], "cites": [{"doc": x["id"], "page": None}]}
        for x in flags
    ]
    return [
        {"type": "points", "title": "Debt, leverage and the working-capital cycle", "items": items},
        {**table, "title": "Year end"},
        {"type": "note", "text": f"Reported figures, {f['basis']}, ₹ crore. Computed in code."},
    ]


def cash(view: dict) -> list[dict]:
    f = view["financials"]
    cq = f["cash_quality"]
    rows = _annual(f, "cash_quality", 3)
    table = _transpose(
        rows,
        [
            ("cfo", "Operating cash flow", "cr"),
            ("fcf", "Free cash flow", "cr"),
            ("pat", "Net profit", "cr"),
            ("cfo_to_pat", "Cash / profit", "x"),
        ],
    )
    reads = []
    if cq.get("cfo_to_pat_3y") is not None:
        r = cq["cfo_to_pat_3y"]
        verdict = (
            "Profits are turning into cash."
            if r >= 0.8
            else "Only part of the profit is turning into cash."
            if r >= 0.4
            else "Profits are not turning into cash."
        )
        reads.append(f"Over three years, operating cash flow was {r:.2f}× net profit. {verdict}")
    if cq.get("fcf_3y") is not None:
        reads.append(f"Free cash flow over three years: {cr(cq['fcf_3y'])}.")
    if f.get("is_lender"):
        reads.append(
            "For a lender, operating cash flow mostly reflects loan growth, so it is negative when the book grows."
        )
    flags = [
        x
        for x in f.get("flags", [])
        if x["id"] in ("fin:cash_conversion", "fin:fcf", "fin:other_income")
    ]
    items = [{"text": t, "cites": []} for t in reads] + [
        {"text": x["text"], "tone": x["tone"], "cites": [{"doc": x["id"], "page": None}]}
        for x in flags
    ]
    return [
        {"type": "points", "title": "Do profits turn into cash?", "items": items},
        {**table, "title": "Cash flow"},
        {"type": "note", "text": "Reported figures, ₹ crore. Computed in code."},
    ]


def _trend(group: str, fin: dict) -> str:
    q = _qrows(fin)
    s = fin["snapshot"]
    if group == "growth":
        yoy = [pc(x.get("revenue_yoy"), True) for x in q if x.get("revenue_yoy") is not None]
        c = (fin["trajectory"].get("cagr") or {}).get("revenue_3y")
        return f"Revenue {_join(yoy)} from a year earlier in the last {len(yoy)} quarters" + (
            f"; {pc(c)} a year over three years." if c is not None else "."
        )
    if group == "margins":
        m = [pc(x.get("margin_pct")) for x in q if x.get("margin_pct") is not None]
        p = [pc(x.get("pat_yoy"), True) for x in q if x.get("pat_yoy") is not None]
        return f"Margin {_join(m)} in the last {len(m)} quarters; profit {_join(p)} from a year earlier."
    rows = fin["cash_quality"]["annual"][-3:]
    bs = fin["balance_sheet"]["annual"][-3:]
    if group == "projects":
        cw = [(b["period"], b["cwip"]) for b in bs if b.get("cwip") is not None]
        if len(cw) >= 2:
            return f"Capital work in progress {cr(cw[0][1])} ({fy(cw[0][0])}) to {cr(cw[-1][1])} ({fy(cw[-1][0])}): projects not yet earning."
        return "Projects show up in the numbers only once commissioned."
    if group == "cash":
        cfo = _join(
            [f"{cr(r['cfo'])} ({fy(r['period'])})" for r in rows if r.get("cfo") is not None]
        )
        wc = [b["working_capital_days"] for b in bs if b.get("working_capital_days") is not None]
        tail = f"; working-capital days {wc[0]:.0f} to {wc[-1]:.0f}" if len(wc) >= 2 else ""
        return f"Operating cash flow {cfo}{tail}."
    borrow = [b["borrowings"] for b in bs if b.get("borrowings") is not None]
    fcf = fin["cash_quality"].get("fcf_3y")
    parts = []
    if len(borrow) >= 2:
        parts.append(f"borrowings {cr(borrow[0])} to {cr(borrow[-1])}")
    if s.get("debt_to_equity") is not None:
        parts.append(f"debt/equity {s['debt_to_equity']:.2f}×")
    if fcf is not None:
        parts.append(f"free cash flow {cr(fcf)} over three years")
    return (_join(parts) or "No balance-sheet figures").capitalize() + "."


def narrative(view: dict) -> list[dict]:
    """Where management's story and the reported numbers agree or part ways, by theme. The
    story is management's latest words; the numbers are the trend; the read is the tally of
    verdicts on that theme's promises that have fallen due, so it is code, not opinion."""
    led = ledger(view)
    fin = view["financials"]
    stmts = [i for c in led["calls"] for i in c["promised"]]
    flags = {x["id"]: x for x in fin.get("flags", [])}
    by_group = {
        "growth": ["fin:growth"],
        "margins": ["fin:other_income"],
        "cash": ["fin:cash_conversion", "fin:receivables"],
        "funding": ["fin:leverage", "fin:fcf"],
        "projects": [],
    }
    themes = []
    for g, title in GROUPS.items():
        items = [i for i in stmts if i["group"] == g]
        if not items:
            continue
        seen, uniq = set(), []
        for i in items:
            k = i.get("key") or i["id"]
            if k not in seen:
                seen.add(k)
                uniq.append(i)
        due = [i for i in uniq if i["verdict"] in JUDGED]
        missed = sum(i["verdict"] == "missed" for i in due)
        partly = sum(i["verdict"] == "partly" for i in due)
        if not due:
            read, tone = "Not tested yet: none of these targets has fallen due.", "neutral"
        elif missed:
            read, tone = (
                f"The numbers fall short of the story: {missed} of {len(due)} targets now due were missed.",
                "negative",
            )
        elif partly:
            read, tone = (
                f"Partly backed: {partly} of {len(due)} targets now due were met only in part.",
                "neutral",
            )
        else:
            read, tone = (
                f"The numbers back the story: all {len(due)} targets now due were delivered.",
                "positive",
            )
        latest = sorted(
            (i for i in uniq if not i["segment"]), key=lambda i: (i["doc_id"], -i["materiality"])
        )
        said = (latest or uniq)[0]
        themes.append(
            {
                "title": title,
                "said": {
                    "quote": said["quote"],
                    "target": said["target"],
                    "doc_id": said["doc_id"],
                    "page": said["page"],
                },
                "numbers": _trend(g, fin),
                "flags": [
                    flags[k]["text"]
                    for k in by_group[g]
                    if k in flags and flags[k]["tone"] == "negative"
                ],
                "read": read,
                "tone": tone,
                "evidence": [
                    {"target": i["target"], "verdict": i["verdict"], "actual": i.get("actual")}
                    for i in due
                ],
            }
        )
    return [
        {"type": "themes", "items": themes},
        {
            "type": "note",
            "text": "Management's words are quoted from the calls. The numbers and the read are computed in code from reported figures and the verdicts in Promised vs delivered.",
        },
    ]


def guidance(view: dict) -> list[dict]:
    led = ledger(view)
    calls = led["calls"]
    if not calls:
        return [{"type": "text", "text": "FINN has no earnings calls for this company."}]
    latest = calls[-1]
    allg = [
        g for g in view["guidance"] if g["doc_id"] == latest["doc_id"] and g["kind"] == "guidance"
    ]
    allg.sort(
        key=lambda g: (
            g.get("metric") not in HEADLINE,
            measure._SEGMENT.search(g["target"].lower()) is not None,
            -g.get("materiality", 0),
        )
    )
    items = [
        {
            "target": g["target"],
            "horizon": g.get("horizon"),
            "quote": g["quote"],
            "doc_id": g["doc_id"],
            "page": g["page"],
            "headline": g.get("metric") in HEADLINE,
        }
        for g in allg[:10]
    ]
    blocks: list[dict] = [
        {"type": "guidance", "title": f"Guided on the {_short(latest['call'])}", "items": items}
    ]
    changes = [u for c in calls for u in c["updates"] if u["revision"]]
    if changes:
        blocks.append(
            {
                "type": "guidance",
                "title": "Changed along the way",
                "items": [
                    {
                        "target": u["target"],
                        "horizon": u.get("horizon"),
                        "quote": u["quote"],
                        "doc_id": u["doc_id"],
                        "page": u["page"],
                        "headline": True,
                    }
                    for u in changes
                ],
            }
        )
    blocks.append(
        {
            "type": "note",
            "text": "Quoted verbatim from the calls; each quote was string-matched to its page. Headline numbers first.",
        }
    )
    return blocks


def bull_bear(view: dict) -> list[dict]:
    bb = view.get("bull_bear") or {}
    if not bb:
        return [
            {
                "type": "text",
                "text": "FINN couldn't build a bull and bear case from the sources it has.",
            }
        ]
    blocks = [
        {"type": "points", "title": "Bull case", "tone": "positive", "items": bb.get("bull", [])},
        {"type": "points", "title": "Bear case", "tone": "negative", "items": bb.get("bear", [])},
    ]
    if bb.get("watch"):
        blocks.append(
            {"type": "points", "title": "What would change the view", "items": bb["watch"]}
        )
    blocks.append(
        {
            "type": "note",
            "text": "Written by AI from the calls, annual report and computed flags; uncited points were removed in code.",
        }
    )
    return blocks


def overview(view: dict) -> list[dict]:
    led = ledger(view)
    s = view["financials"]["snapshot"]
    label = (s.get("margin_label") or "Operating margin").split(" (")[0]
    return [
        {
            "type": "stats",
            "items": [
                {"label": "Revenue", "value": cr(s.get("revenue")), "sub": fy(s["fy"])},
                {"label": label, "value": pc(s.get("margin_pct")), "sub": fy(s["fy"])},
                {"label": "Net profit", "value": cr(s.get("pat")), "sub": fy(s["fy"])},
            ],
        },
        {
            "type": "points",
            "title": "Promised vs delivered, last four quarters",
            "items": [{"text": t, "cites": []} for t in led["summary"][:3]],
        },
        {
            "type": "note",
            "text": "Pick what to dig into below. Everything comes from the annual report, the last four calls and the reported numbers.",
        },
    ]


SECTIONS = {
    "business": business,
    "financial": financial,
    "trajectory": trajectory,
    "balance": balance,
    "cash": cash,
    "narrative": narrative,
    "guidance": guidance,
    "bull_bear": bull_bear,
    "overview": overview,
}


def reply(view: dict, intent: str) -> dict:
    """The blocks for one output. `ledger` returns its own structure in one block."""
    blocks = [{"type": "ledger", **ledger(view)}] if intent == "ledger" else SECTIONS[intent](view)
    return {
        "symbol": view["symbol"],
        "company": view["company"],
        "intent": intent,
        "title": TITLES[intent],
        "blocks": blocks,
        "menu": [{"intent": k, "label": v} for k, v in MENU if k != intent],
        "documents": view["documents"],
        "as_of": view["latest_quarter"],
    }


# ------------------------------------------------------------------ what brokers expect
def brokers(symbol: str, company: str | None, owner: str) -> dict:
    """The brokerage block for the chat: computed in code from stored reports, plus the
    stored, checked explanation of where they differ."""
    from app.brokerage import explain
    from app.brokerage import service as bs

    ov = bs.overview(symbol, owner)
    block = {"type": "brokers", "symbol": symbol, "overview": ov}
    if ov["reports"]:
        block["revisions"] = bs.revisions(symbol, owner)
        block["divergence"] = bs.divergence(symbol, owner) | {"explanation": explain.get(symbol)}
        block["track"] = bs.track_record(symbol=symbol, owner=owner)
    return {
        "symbol": symbol,
        "company": company or symbol,
        "intent": "brokers",
        "title": TITLES["brokers"],
        "blocks": [block],
        "menu": [{"intent": k, "label": v} for k, v in MENU],
        "documents": [],
    }


# ------------------------------------------------------------------ who can help (Task C)
_EVENT_WORDS = [
    ("capex", r"capex|plant|capacity|project|expansion"),
    ("management_change", r"\bcfo\b|\bceo\b|\bmd\b|management|leadership|appoint|resign"),
    ("M&A", r"acqui|merger|deal|stake|\bjv\b|joint venture"),
    ("litigation", r"court|legal|regulat|litigation|penalt|closure"),
    ("fund_raise", r"\bqip\b|fund ?rais|debt|borrow|rights issue"),
    ("order", r"\border|customer|contract"),
    ("results", r"results|numbers|margin|profit|revenue|quarter"),
]


def network(
    symbol: str, company: str, message: str, owner: str, documents: list | None = None
) -> dict:
    """Who in the investor's own network may help with this company, for the event the
    message names (a CFO change asks for finance people first, capex for operations)."""
    from app.network import match

    m = message.lower()
    category = next((c for c, rx in _EVENT_WORDS if re.search(rx, m)), None)
    found = match.find(symbol, category, text=message, owner=owner)
    topic = match.TOPIC.get(category or "", "the company and its business")
    return {
        "symbol": symbol,
        "company": company,
        "intent": "network",
        "title": TITLES["network"],
        "blocks": [
            {"type": "contacts", "items": found, "topic": topic, "event": category},
            {
                "type": "note",
                "text": "From your own network only, ranked in code by company overlap, role, sector, recency and how well you know them. Employment is not inside knowledge: each line says what they may give context on and what is unknown.",
            },
        ],
        "menu": [{"intent": k, "label": v} for k, v in MENU],
        "documents": documents or [],
        "as_of": None,
    }
