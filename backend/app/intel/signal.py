# ruff: noqa: E501  (explanations are user-facing sentences)
"""Signal-to-Network (Task C): a filing becomes a scored, explained signal with the people in
the investor's own network who may help understand it.

Announcement -> classify -> extract facts -> score attention -> match network -> explain.

Everything here is deterministic. The model's part happened earlier and is an input, not
the judge: triage gave the category and a one-line summary (labelled as AI where shown), and
management-change enrichment gave names, roles and effective dates. Code extracts amounts,
percentages and dates with the sentence they came from, computes a 0-100 attention score
from six visible components, and leaves a component unknown, never zero-by-guess, when the
filing doesn't give what it needs.

The weights are the spec's proposed starting point, not validated truths; `eval_bands`
measures them against the 100 hand-labelled filings so they can be tuned in the open.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime

from app.db import session
from app.ingest.universe import fixtures_dir

RULE_VERSION = "attention-v2"

# ------------------------------------------------------------------ the score's parts
COMPONENTS = {
    "category_base": 30,
    "financial_magnitude": 25,
    "strategic_significance": 15,
    "surprise_novelty": 15,
    "time_sensitivity": 10,
    "portfolio_relevance": 5,
}
LABELS = {
    "category_base": "Kind of event",
    "financial_magnitude": "Size of the money involved",
    "strategic_significance": "Strategic weight",
    "surprise_novelty": "Surprise",
    "time_sensitivity": "Time pressure",
    "portfolio_relevance": "Your exposure",
}
CATEGORY_BASE = {
    "M&A": 25,
    "results": 22,
    "management_change": 12,  # 20 when it is the CEO, CFO, MD or chair
    "capex": 20,
    "litigation": 18,
    "fund_raise": 16,
    "order": 15,
    "credit_rating": 14,
    "pledging": 14,
    "dividend": 12,
    "bonus_split": 12,
    "press_release": 10,
    "insider_trading": 8,
    "earnings_call": 6,
    "investor_meetings": 3,
    "agm_egm": 3,
    "postal_ballot": 3,
    "unclassified": 5,
}
CATEGORY_NAME = {
    "results": "Financial results",
    "M&A": "M&A",
    "fund_raise": "Fund raise",
    "management_change": "Management change",
    "litigation": "Litigation or regulatory",
    "insider_trading": "Insider trading disclosure",
    "earnings_call": "Earnings call",
    "investor_meetings": "Investor meeting",
    "credit_rating": "Credit rating",
    "dividend": "Dividend",
    "bonus_split": "Bonus or split",
    "capex": "Capex or project",
    "press_release": "Business update",
    "postal_ballot": "Postal ballot",
    "agm_egm": "AGM or EGM",
    "pledging": "Promoter pledge",
    "order": "Order win or loss",
    "unclassified": "Other",
}
BANDS = [(80, "critical"), (60, "high"), (35, "medium"), (15, "low"), (0, "routine")]

TOP_ROLE = re.compile(
    r"\b(c\.?e\.?o|c\.?f\.?o|chief executive|chief financial|managing director|\bmd\b|chair(man|person)?|whole[- ]time director)\b",
    re.I,
)
OTHER_KMP = re.compile(
    r"\b(company secretary|compliance officer|c\.?o\.?o|c\.?t\.?o|chief \w+ officer|director|president|head)\b",
    re.I,
)
ORDER = re.compile(r"\b(orders?(?! book)|contract|award(ed)?|letter of (award|intent))\b", re.I)
REAPPOINT = re.compile(r"\bre-?appoint\w*|\bcontinuation\b", re.I)
INDEPENDENT = re.compile(r"\bindependent director\b", re.I)
INTERNAL = re.compile(
    r"wholly[- ]owned subsidiary|step-?down subsidiary|strike off|struck off|dissol\w+|liquidat\w+"
    r"|branch\b.{0,40}\bclos\w+|preference share conversion|conversion of preference",
    re.I,
)
BUSINESS_TRANSFER = re.compile(r"slump sale|business transfer|demerg\w+", re.I)
NEW_SUBSIDIARY = re.compile(r"incorporat\w+.{0,60}subsidiary|subsidiary.{0,40}incorporat\w+", re.I)
DEPARTURE = re.compile(
    r"\b(cessation|resign\w*|step(s|ped)? down|demise|passed away|retire\w*)\b", re.I
)
RESULTS_COPY = re.compile(
    r"\b(newspaper|extracts?|auditors?'? reports?|half[- ]yearly report|limited review|outcome of board meeting.{0,20}copy)\b",
    re.I,
)
RESULTS_RELEASE = re.compile(
    r"\b(q[1-4] ?fy ?\d\d|quarterly results|financial results|shareholder letter)\b", re.I
)
REGULATOR_DECISION = re.compile(
    r"\b(rbi|reserve bank|sebi|npci|irdai|trai|cci)\b.{0,60}\b(authori[sz]\w*|approv\w*|licen[cs]\w*|defer\w*|direct\w*|mandat\w*)"
    r"|\b(authori[sz]\w*|approv\w*|licen[cs]\w*)\b.{0,40}\b(rbi|reserve bank|sebi|npci|irdai|trai|cci)\b",
    re.I,
)
ACQUIRE = re.compile(r"\b(acqui\w+|merger|amalgamat\w+|stake)\b", re.I)

STRATEGIC = [
    (
        re.compile(
            r"\b(acqui\w+|merger|amalgamat\w+|demerger|scheme of arrangement|change in control|open offer|divest\w*|stake sale)\b",
            re.I,
        ),
        15,
        "It changes what the company owns or who controls it",
    ),
    (TOP_ROLE, 15, "It concerns top leadership"),
    (REGULATOR_DECISION, 12, "A regulator decided something about the business"),
    (
        re.compile(
            r"\b(clos(ure|e) order|penalt\w+|show[- ]cause|stay|tribunal|high court|supreme court|sebi order|rbi (order|action)|ban|suspend\w*|search|raid)\b",
            re.I,
        ),
        12,
        "A regulator or court is involved",
    ),
    (
        re.compile(
            r"\b(joint venture|\bjv\b|licen[cs]\w+|partnership|technology transfer)\b", re.I
        ),
        10,
        "It adds a partner, a licence or a new line",
    ),
    (
        re.compile(
            r"\b(us ?fda|fda|drug controller|dcgi|approval for|marketing authori[sz]ation)\b", re.I
        ),
        10,
        "A regulator approved a product",
    ),
    (
        re.compile(
            r"\b(new plant|greenfield|brownfield|commission\w*|capacity|expansion|capex)\b", re.I
        ),
        10,
        "It changes capacity",
    ),
    (
        re.compile(
            r"\b(qip|rights issue|preferential|ncd|debentures?|fund rais\w+|warrants)\b", re.I
        ),
        8,
        "It changes how the company is funded",
    ),
    (OTHER_KMP, 6, "It concerns a senior manager or director"),
]
UNEXPECTED = re.compile(
    r"\b(resign\w*|immediate effect|demise|passed away|cancel\w*|terminat\w*|withdr[ae]w\w*|default\w*|downgrad\w*|fraud|closure)\b",
    re.I,
)
ROUTINE_REPEAT = {
    "results",
    "earnings_call",
    "investor_meetings",
    "agm_egm",
    "postal_ballot",
    "dividend",
    "insider_trading",
}


def band(score: int) -> str:
    return next(name for floor, name in BANDS if score >= floor)


# ------------------------------------------------------------------ facts (FR-3)
_AMOUNT = re.compile(
    r"(?:rs\.?|₹|inr)\s?([\d,]+(?:\.\d+)?)\s*(crores?|cr\b|lakhs?|million|mn\b|billion|bn\b)?", re.I
)
_TO_CR = {
    "crore": 1,
    "crores": 1,
    "cr": 1,
    "lakh": 0.01,
    "lakhs": 0.01,
    "million": 0.1,
    "mn": 0.1,
    "billion": 100,
    "bn": 100,
}
_PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s?(?:%|percent)", re.I)
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-]+({_MONTHS})[,\s\-]+(\d{{4}})\b|\b({_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b|\b(\d{{1,2}})[./-](\d{{1,2}})[./-](20\d{{2}})\b",
    re.I,
)
_EFFECTIVE = re.compile(
    r"(w\.?e\.?f\.?|with effect from|effective(?: from| date)?|from the close of|record date|book closure|cut-?off date|due on|scheduled (?:on|for))",
    re.I,
)


def _month(s: str) -> int:
    return [m[:3] for m in _MONTHS.split("|")].index(s[:3].lower()) % 12 + 1


def _parse_date(m: re.Match) -> date | None:
    try:
        if m.group(1):
            return date(int(m.group(3)), _month(m.group(2)), int(m.group(1)))
        if m.group(4):
            return date(int(m.group(6)), _month(m.group(4)), int(m.group(5)))
        return date(int(m.group(9)), int(m.group(8)), int(m.group(7)))
    except ValueError:
        return None


def _sentence(text: str, at: int) -> str:
    start = max(text.rfind(". ", 0, at) + 2, 0) if text.rfind(". ", 0, at) >= 0 else 0
    end = text.find(". ", at)
    return text[start : end + 1 if end >= 0 else len(text)].strip()


_SHARES_AT = re.compile(
    r"\b([\d,]{5,})\s+(?:equity\s+)?shares\b.{0,40}?\bat\s+(?:a\s+price\s+of\s+)?"
    r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:/-)?\s*(?:per\s+(?:equity\s+)?share|each)",
    re.I,
)


def extract_facts(subject: str, summary: str | None, enrichment: dict) -> list[dict]:
    """Facts stated in the filing's text, each with the sentence it came from and where that
    sentence is from: the exchange's own subject line, or FINN's one-line summary of the PDF
    (written by AI at triage). Nothing is inferred."""
    facts: list[dict] = []
    for source, text in (
        ("exchange subject", subject or ""),
        ("filing summary (AI)", summary or ""),
    ):
        for m in _AMOUNT.finditer(text):
            unit = (m.group(2) or "").lower()
            if not unit:
                continue  # a bare "Rs 10" is usually a face value or a per-share figure
            v = float(m.group(1).replace(",", "")) * _TO_CR.get(unit, 1)
            facts.append(
                {
                    "field": "amount",
                    "value": round(v, 2),
                    "unit": "₹ crore",
                    "source_quote": _sentence(text, m.start()),
                    "source": source,
                }
            )
        for m in _SHARES_AT.finditer(text):
            # an issue stated as shares at a price: the amount is their product, nothing more
            n, price = (float(g.replace(",", "")) for g in m.groups())
            facts.append(
                {
                    "field": "amount",
                    "value": round(n * price / 1e7, 2),
                    "unit": "₹ crore",
                    "source_quote": _sentence(text, m.start()),
                    "source": source,
                    "computed": f"{m.group(1)} shares × ₹{m.group(2)}",
                }
            )
        for m in _PCT.finditer(text):
            facts.append(
                {
                    "field": "percentage",
                    "value": float(m.group(1)),
                    "source_quote": _sentence(text, m.start()),
                    "source": source,
                }
            )
        for m in _DATE.finditer(text):
            d = _parse_date(m)
            if not d:
                continue
            before = text[max(0, m.start() - 40) : m.start()]
            field = "effective_date" if _EFFECTIVE.search(before) else "date"
            facts.append(
                {
                    "field": field,
                    "value": d.isoformat(),
                    "source_quote": _sentence(text, m.start()),
                    "source": source,
                }
            )
        if re.search(r"immediate effect", text, re.I):
            facts.append(
                {
                    "field": "effective_date",
                    "value": "immediate",
                    "source_quote": _sentence(text, text.lower().find("immediate effect")),
                    "source": source,
                }
            )
    for p in enrichment.get("people") or []:
        facts.append(
            {
                "field": f"{p.get('direction') or 'named'}_person",
                "value": p.get("name"),
                "role": p.get("role"),
                "source_quote": f"{p.get('name')}, {p.get('role')}"
                + (f", effective {p['effective_date']}" if p.get("effective_date") else ""),
                "source": "filing PDF (people extracted by AI, checked against the text)",
            }
        )
        if p.get("effective_date"):
            facts.append(
                {
                    "field": "effective_date",
                    "value": p["effective_date"],
                    "source_quote": f"{p.get('name')} ({p.get('role')}) effective {p['effective_date']}",
                    "source": "filing PDF",
                }
            )
    seen, out = set(), []
    for f in facts:
        k = (f["field"], str(f["value"]))
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


# ------------------------------------------------------------------ company scale
def company_scale(symbol: str) -> dict:
    """Revenue over the last four reported quarters and market cap, ₹ crore, from the stored
    fundamentals. Missing stays missing: no live fetch inside scoring."""
    path = fixtures_dir() / "fundamentals" / f"{symbol}.json"
    if not path.exists():
        return {}
    f = json.loads(path.read_text())
    q = [x for x in (f.get("quarterly_headline") or []) if x.get("revenue") is not None][-4:]
    out = {"revenue_ttm": sum(x["revenue"] for x in q)} if len(q) == 4 else {}
    mc = (f.get("top_ratios") or {}).get("Market Cap")
    if mc and (m := re.search(r"[\d,]+(?:\.\d+)?", mc)):
        out["market_cap"] = float(m.group(0).replace(",", ""))
    return out


def quarter_moves(symbol: str, ts: str) -> list[dict]:
    """Year-on-year revenue and profit for the latest quarter reported before a results
    filing, from the stored quarterly table, when the filing's own numbers weren't parsed."""
    path = fixtures_dir() / "fundamentals" / f"{symbol}.json"
    if not path.exists():
        return []
    rows = {r["period"]: r for r in json.loads(path.read_text()).get("quarterly_headline") or []}
    filed = ts[:7]
    done = sorted(p for p in rows if p < filed)
    if not done:
        return []
    q = done[-1]
    ago = rows.get(f"{int(q[:4]) - 1}{q[4:]}")
    out = []
    for k in ("revenue", "pat"):
        a, b = rows[q].get(k), (ago or {}).get(k)
        if a is not None and b:
            out.append(
                {"metric": k, "yoy": (a / b - 1) * 100 if b > 0 else 100.0 if a > 0 else -100.0}
            )
    return out


def _ratio_points(r: float) -> int:
    for floor, pts in ((0.10, 25), (0.05, 18), (0.02, 12), (0.005, 6)):
        if r >= floor:
            return pts
    return 2


def _move_points(pct: float) -> int:
    a = abs(pct)
    for floor, pts in ((50, 25), (30, 18), (15, 12), (5, 6)):
        if a >= floor:
            return pts
    return 2


# ------------------------------------------------------------------ attention (FR-4)
def attention(
    *,
    category: str,
    subject: str,
    summary: str | None,
    ts: str,
    facts: list[dict],
    symbol: str,
    results: dict | None = None,
    in_portfolio: bool = False,
    weight: float | None = None,
    on_watchlist: bool = False,
    linked_to_holding: bool = False,
    price_moves: list[dict] | None = None,
    prior_same_category: int | None = None,
    scale: dict | None = None,
) -> dict:
    """The 0-100 score, its six parts, a sentence for each part that scored, and the parts
    the filing gave no basis for."""
    text = f"{subject or ''} {summary or ''}"
    parts: dict[str, int | None] = {}
    why: list[str] = []
    unknown: list[str] = []
    cat = category or "unclassified"
    if cat in ("press_release", "unclassified") and RESULTS_RELEASE.search(text):
        cat = "results"  # the results told as a press release or shareholder letter
    secondary: list[str] = []
    if cat in ("press_release", "unclassified") and ORDER.search(text):
        secondary.append("order")

    # 1. kind of event
    base = CATEGORY_BASE.get(cat, 5)
    if cat == "management_change" and TOP_ROLE.search(
        text + " " + " ".join(str(f.get("role") or "") for f in facts)
    ):
        base = 20
    if "order" in secondary:
        base = max(base, CATEGORY_BASE["order"])
    if cat in ("press_release", "unclassified") and REGULATOR_DECISION.search(text):
        base = max(base, CATEGORY_BASE["litigation"])  # a regulator's decision, not a press note
    reappointed = (
        cat == "management_change" and REAPPOINT.search(text) and not DEPARTURE.search(text)
    )
    results_copy = cat == "results" and RESULTS_COPY.search(text)
    if results_copy:
        base = 6  # a newspaper extract or auditor's report repeats results already filed
    if reappointed:
        base = 6  # a routine re-appointment is a continuation, not a change
    independent_only = (
        cat == "management_change"
        and INDEPENDENT.search(text)
        and not TOP_ROLE.search(text)
        and not reappointed
    )
    if independent_only:
        base = 8  # an independent director joins or leaves the board; nobody runs the company differently
    internal = (
        cat in ("M&A", "unclassified", "press_release")
        and INTERNAL.search(text)
        and not BUSINESS_TRANSFER.search(text)
        and not REGULATOR_DECISION.search(text)
        and not (  # buying a company outright, as against topping up one already owned
            re.search(r"\bacqui\w+", text, re.I)
            and not re.search(r"\b(remaining|balance|further|additional|increased)\b", text, re.I)
        )
    )
    if internal:
        base = 6  # moving things inside the group (a subsidiary closed, merged in or re-papered)
    if cat == "M&A" and NEW_SUBSIDIARY.search(text) and not ACQUIRE.search(text):
        base = 10  # setting up a subsidiary is housekeeping unless something is bought
    parts["category_base"] = base
    why.append(
        f"{CATEGORY_NAME.get(cat, cat)}{' (order)' if 'order' in secondary else ''}: {base} of 30 for the kind of event."
    )

    # 2. size of the money, against the right yardstick
    if results_copy:
        parts["financial_magnitude"] = 0
        why.append("It repeats results filed separately, so their size is counted there.")
    elif cat == "results":
        moves = [
            r
            for r in ((results or {}).get("rows") or [])
            if r.get("metric") in ("revenue", "pat", "net_profit") and r.get("yoy") is not None
        ]
        if not moves:
            moves = quarter_moves(symbol, ts)
        if moves:
            big = max(moves, key=lambda r: abs(r["yoy"]))
            parts["financial_magnitude"] = _move_points(big["yoy"])
            why.append(
                f"{'Profit' if big['metric'] != 'revenue' else 'Revenue'} moved {big['yoy']:+.0f}% from a year ago."
            )
        else:
            parts["financial_magnitude"] = None
            unknown.append("No result numbers were read from this filing, so its size is unknown.")
    else:
        amounts = [f["value"] for f in facts if f["field"] == "amount"]
        scale = scale if scale is not None else company_scale(symbol)
        denom_key = "market_cap" if cat in ("M&A", "fund_raise", "pledging") else "revenue_ttm"
        denom = (scale or {}).get(denom_key)
        if amounts and denom:
            amt = max(amounts)
            r = amt / denom
            parts["financial_magnitude"] = _ratio_points(r)
            yard = "the company's market value" if denom_key == "market_cap" else "a year's revenue"
            why.append(f"₹{amt:,.0f} Cr is {r * 100:.1f}% of {yard} (₹{denom:,.0f} Cr).")
        else:
            parts["financial_magnitude"] = None
            unknown.append(
                "No amount was disclosed"
                if not amounts
                else "No company yardstick to size the amount against"
            )

    # 3. strategic weight: the strongest rule that fires
    hits = (
        []
        if reappointed or independent_only or internal
        else [(pts, reason) for rx, pts, reason in STRATEGIC if rx.search(text)]
    )
    if hits:
        pts, reason = max(hits)
        parts["strategic_significance"] = pts
        why.append(f"{reason}.")
    else:
        parts["strategic_significance"] = 0

    # 4. surprise: an unexpected word, the market reacting, or a first such filing
    s, notes = 0, []
    if m := UNEXPECTED.search(text):
        s += 8
        notes.append(f"it says “{m.group(0).lower()}”")
    moves = [a for a in (price_moves or []) if a.get("kind") == "price"]
    if moves:
        s += 7
        notes.append(f"the stock moved {moves[0]['value']:+.1f}% after it")
    if prior_same_category == 0 and cat not in ROUTINE_REPEAT:
        s += 5
        notes.append("it is the first filing of this kind in six months")
    if prior_same_category is None and not moves and not notes:
        parts["surprise_novelty"] = None
        unknown.append("No history to judge surprise against.")
    else:
        parts["surprise_novelty"] = min(15, s)
        if notes:
            why.append(f"Surprise: {'; '.join(notes)}.")

    # 5. time pressure: an effective date close to the filing
    filed = date.fromisoformat(ts[:10])
    eff = [f["value"] for f in facts if f["field"] == "effective_date"]
    t = 0
    when = ""
    if "immediate" in eff:
        t, when = 10, "it takes effect immediately"
    else:
        days = [
            (date.fromisoformat(v) - filed).days for v in eff if re.match(r"\d{4}-\d{2}-\d{2}$", v)
        ]
        if days:
            d = min(days, key=abs)
            if d <= 30:
                t, when = (
                    10,
                    ("it took effect on filing" if d <= 0 else f"it takes effect in {d} days"),
                )
            elif d <= 90:
                t, when = 5, f"it takes effect in {d} days"
    if not t and cat == "results" and not results_copy:
        t, when = 4, "the market reacts in the next session"
    parts["time_sensitivity"] = t
    if when:
        why.append(f"Time pressure: {when}.")

    # 6. your exposure: a small bonus, by design
    if in_portfolio:
        w = (weight or 0) * 100
        p = 5 if w >= 5 else 4 if w >= 2 else 3
        why.append(f"You hold it ({w:.1f}% of your portfolio).")
    elif on_watchlist:
        p = 2
        why.append("It's on your watchlist.")
    elif linked_to_holding:
        p = 1
        why.append("It is a competitor, supplier or customer of a holding.")
    else:
        p = 0
    parts["portfolio_relevance"] = p

    score = min(100, sum(v for v in parts.values() if v))
    return {
        "score": score,
        "priority": band(score),
        "breakdown": parts,
        "max": COMPONENTS,
        "labels": LABELS,
        "explanation": why,
        "unknown_components": unknown,
        "category": cat,
        "secondary_categories": secondary,
        "rule_version": RULE_VERSION,
    }


# ------------------------------------------------------------------ one announcement, end to end
def _row(announcement_id: str) -> dict | None:
    with session() as db:
        r = db.execute("SELECT * FROM announcements WHERE id=?", (announcement_id,)).fetchone()
    return dict(r) if r else None


def _context(symbol: str) -> dict:
    with session() as db:
        co = db.execute(
            "SELECT name, in_portfolio, weight FROM companies WHERE symbol=?", (symbol,)
        ).fetchone()
        try:
            from app.portfolio.watchlist import symbols as watch_symbols

            watched = symbol in watch_symbols()
        except Exception:
            watched = False
    return {
        "name": co["name"] if co else symbol,
        "in_portfolio": bool(co and co["in_portfolio"]),
        "weight": co["weight"] if co else None,
        "on_watchlist": watched,
    }


def _prior(symbol: str, category: str, ts: str) -> int:
    with session() as db:
        return db.execute(
            "SELECT COUNT(*) FROM announcements WHERE symbol=? AND category=? AND ts < ? AND ts >= date(?, '-180 days')",
            (symbol, category, ts, ts),
        ).fetchone()[0]


def _confidence(row: dict) -> float:
    from app.intel.taxonomy import is_unsure

    if is_unsure(row["category"], row["exch_category"] or "", row["subject"] or ""):
        return 0.4
    return {"rules": 0.95, "fixture": 0.9, "llm": 0.8}.get(row.get("category_source") or "", 0.6)


def score_row(
    row: dict, ctx: dict | None = None, price_moves: list[dict] | None = None
) -> tuple[dict, list[dict]]:
    """Facts and attention for one stored announcement."""
    enr = json.loads(row.get("enrichment_json") or "{}")
    facts = extract_facts(row.get("subject") or "", row.get("summary"), enr)
    ctx = ctx or _context(row["symbol"])
    att = attention(
        category=row.get("category") or "unclassified",
        subject=row.get("subject") or "",
        summary=row.get("summary"),
        ts=row["ts"],
        facts=facts,
        symbol=row["symbol"],
        results=enr.get("results"),
        in_portfolio=ctx["in_portfolio"],
        weight=ctx.get("weight"),
        on_watchlist=ctx.get("on_watchlist", False),
        price_moves=price_moves,
        prior_same_category=_prior(row["symbol"], row.get("category") or "unclassified", row["ts"]),
    )
    return att, facts


def analyze(announcement_id: str, owner: str) -> dict | None:
    """FR-1..9: the full signal for one announcement, for the signed-in investor. Idempotent:
    the stored analysis is returned while the rule version is unchanged. The network part is
    computed for this owner only, so two investors never share matches."""
    with session() as db:
        # the stored analysis is reused only while the rules and this investor's network are
        # unchanged; adding, importing or removing a contact moves the key
        net = db.execute(
            "SELECT (SELECT COUNT(*) FROM people WHERE owner_id=?) || '.' || (SELECT COUNT(*) FROM relationships WHERE owner_id=?) || '.' || (SELECT COALESCE(MAX(rowid), 0) FROM relationships WHERE owner_id=?)",
            (owner, owner, owner),
        ).fetchone()[0]
        version = f"{RULE_VERSION}/{net}"
        hit = db.execute(
            "SELECT json FROM signal_analysis WHERE announcement_id=? AND owner_id=? AND rule_version=?",
            (announcement_id, owner, version),
        ).fetchone()
    if hit:
        return json.loads(hit["json"])
    row = _row(announcement_id)
    if row is None:
        return None
    from datetime import timedelta

    from app.intel import alerts as alerts_mod
    from app.network import match

    filed = datetime.fromisoformat(row["ts"])
    try:
        moves = [
            a
            for a in alerts_mod.evaluate(filed, filed + timedelta(days=4))
            if a["symbol"] == row["symbol"]
        ]
    except Exception:
        moves = []  # prices unavailable: score without the market's reaction
    ctx = _context(row["symbol"])
    att, facts = score_row(row, ctx, moves)
    try:
        people_named = [f for f in facts if f["field"].endswith("_person")]
        matches = match.find(
            row["symbol"],
            att["category"],
            text=f"{row['subject']} {row.get('summary') or ''}",
            roles=[f.get("role") or "" for f in people_named],
            owner=owner,
        )
        network_note = None
    except Exception as e:  # the signal never depends on the network being available
        matches, network_note = (
            [],
            f"Network unavailable ({type(e).__name__}); the signal is shown without contacts.",
        )
    out = {
        "announcement_id": row["id"],
        "company": {"name": ctx["name"], "ticker": row["symbol"]},
        "source": {
            "exchange": "NSE",
            "title": row["subject"],
            "url": row["pdf_url"],
            "published_at": row["ts"],
            "document_type": row["exch_category"],
        },
        "event": {
            "category": att["category"],
            "category_name": CATEGORY_NAME.get(att["category"], att["category"]),
            "secondary_categories": att["secondary_categories"],
            "confidence": _confidence(row),
            "classified_by": row.get("category_source"),
            "summary": row.get("summary") or row["subject"],
        },
        "facts": facts,
        "materiality": {
            k: att[k]
            for k in (
                "score",
                "priority",
                "breakdown",
                "max",
                "labels",
                "explanation",
                "unknown_components",
            )
        },
        "network_matches": matches,
        "network_note": network_note,
        "analysis_version": "1.0",
        "rule_version": RULE_VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if network_note:
        return out  # a degraded answer is shown, never stored
    with session() as db:
        db.execute(
            "INSERT OR REPLACE INTO signal_analysis (announcement_id, owner_id, rule_version, json, created_at) VALUES (?,?,?,?,?)",
            (row["id"], owner, version, json.dumps(out, ensure_ascii=False), out["created_at"]),
        )
    return out


FEEDBACK = {"useful", "not_useful", "wrong_category", "relevant_contact", "irrelevant_contact"}


def feedback(announcement_id: str, owner: str, kind: str, person_id: str | None = None) -> dict:
    """FR-9 / spec 15: recorded per investor, never pooled, and used only to tune rules."""
    if kind not in FEEDBACK:
        raise ValueError(kind)
    with session() as db:
        db.execute(
            "INSERT INTO signal_feedback (announcement_id, owner_id, kind, person_id, created_at) VALUES (?,?,?,?,?)",
            (
                announcement_id,
                owner,
                kind,
                person_id,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        n = db.execute(
            "SELECT COUNT(*) FROM signal_feedback WHERE owner_id=?", (owner,)
        ).fetchone()[0]
    return {"recorded": kind, "total": n}


def forget_person(person_id: str, owner: str) -> None:
    """Deleting a contact invalidates the matches derived from it (spec 16)."""
    with session() as db:
        db.execute(
            "DELETE FROM signal_analysis WHERE owner_id=? AND json LIKE ?",
            (owner, f'%"{person_id}"%'),
        )


def eval_bands() -> dict:
    """The attention bands against the 100 hand-labelled filings (labelled before these
    weights existed). Material filings should land Medium or above; the rest below."""
    labels = json.loads((fixtures_dir() / "eval" / "materiality_labels.json").read_text())
    items = labels.get("labels") or labels.get("items") or []
    rows = []
    for it in items:
        r = _row(str(it["id"]))
        if not r:
            continue
        att, _ = score_row(r)
        rows.append(
            {
                "id": r["id"],
                "material": bool(it.get("material")),
                "score": att["score"],
                "priority": att["priority"],
            }
        )
    mat = [x for x in rows if x["material"]]
    non = [x for x in rows if not x["material"]]
    up = lambda xs: sum(x["score"] >= 35 for x in xs)  # noqa: E731
    return {
        "n": len(rows),
        "material_at_medium_or_above": [up(mat), len(mat)],
        "not_material_below_medium": [len(non) - up(non), len(non)],
        "bands": {b: sum(x["priority"] == b for x in rows) for _, b in BANDS},
        "rows": rows,
    }
