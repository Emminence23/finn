"""Judge a promise in code when it names a number that the reported financials contain.

Division of labour: the model reads the calls (finds the promise, quotes it verbatim, gives
its horizon). Deciding whether "FY26 revenue to cross Rs 4,000 crore" was met is arithmetic,
so code does it: parse the target into (measure, direction, threshold, period), look up the
reported number, compare. Code's verdict replaces the model's whenever code can measure the
promise. Everything else (segment revenue, launches, "2x market growth") keeps the model's
verdict and is labelled as judged by AI.

Deliberately narrow. A parse that is unsure returns None rather than guessing, because a
wrong code verdict looks more authoritative than a wrong AI one.
"""

from __future__ import annotations

import re

PARTLY_BAND = 0.05  # within 5% of the target counts as "partly", beyond that is a miss

# Number + unit, e.g. "INR 4,000 crores", "Rs 1.2 billion", "85 days", "16%".
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_AMOUNT = re.compile(_NUM + r"\s*(crores?|cr\b|billion|bn\b|million|mn\b)", re.I)
_PCT = re.compile(_NUM + r"\s*(?:-\s*\d[\d.]*\s*)?%")
_DAYS = re.compile(_NUM + r"\s*(?:-\s*\d+\s*)?days", re.I)
_TO_CRORE = {"crore": 1, "crores": 1, "cr": 1, "billion": 100, "bn": 100, "million": 0.1, "mn": 0.1}

# Only company-wide figures. A target that names a segment, product or business line
# ("Rail business revenue", "OSAT revenue", "smart metering revenue") is not checkable
# against consolidated numbers.
_LEAD = (
    r"^(?:(?:achieve|deliver|reach|target(?:ed)?|fy\s?\d{2,4}|h[12]\s?fy\s?\d{2,4}|full[- ]year|"
    r"total|overall|consolidated|company|annual|the|our)\s+)*"
)
_SEGMENT = re.compile(
    r"\b(segment|business|division|unit|vertical|osat|pcb|export|domestic|meter\w*|rail|"
    r"defen[cs]e|aerospace|ems|subsidiar\w*|plant|order)\b",
    re.I,
)


def _amount(text: str) -> float | None:
    m = _AMOUNT.search(text)
    if not m:
        return None
    unit = m.group(2).lower().rstrip(".")
    return float(m.group(1).replace(",", "")) * _TO_CRORE.get(unit, 1)


def parse(target: str) -> dict | None:
    """The check a target implies, or None when code can't be sure what it means."""
    t = " ".join(target.split())
    low = t.lower()
    if _SEGMENT.search(low) or "market" in low or " and " in low:
        return None  # segment-level, relative to a market, or two targets in one
    head = re.sub(_LEAD, "", low)

    if re.match(r"(net )?working capital", head) and (m := _DAYS.search(low)):
        return {
            "measure": "working_capital_days",
            "op": "<=",
            "value": float(m.group(1)),
            "label": "working-capital days",
        }
    if re.match(r"(debtor|receivable)s? days", head) and (m := _DAYS.search(low)):
        return {
            "measure": "debtor_days",
            "op": "<=",
            "value": float(m.group(1)),
            "label": "debtor days",
        }
    if re.match(r"(consolidated )?operating cash ?flows?", head) and "positive" in low:
        return {"measure": "cfo", "op": ">", "value": 0.0, "label": "operating cash flow"}
    if re.match(r"free cash ?flows?", head) and "positive" in low:
        return {"measure": "fcf", "op": ">", "value": 0.0, "label": "free cash flow"}
    if re.match(r"(ebitda|operating) margins?", head) and (m := _PCT.search(low)):
        return {
            "measure": "margin_pct",
            "op": ">=",
            "value": float(m.group(1)),
            "label": "operating margin",
        }
    if re.match(r"revenue growth", head) and (m := _PCT.search(low)):
        return {
            "measure": "revenue_growth",
            "op": ">=",
            "value": float(m.group(1)),
            "label": "revenue growth",
        }
    if (
        re.match(r"(revenues?|sales|turnover)\b", head)
        and "growth" not in low
        and (v := _amount(low)) is not None
    ):
        return {"measure": "revenue", "op": ">=", "value": v, "label": "revenue"}
    if re.match(r"(pat|net profit|profit after tax)\b", head) and (v := _amount(low)) is not None:
        return {"measure": "pat", "op": ">=", "value": v, "label": "profit after tax"}
    return None


def _annual(fin: dict, period: str) -> dict | None:
    rows = {a["period"]: dict(a) for a in fin["trajectory"]["annual"]}
    if period not in rows:
        return None
    row = rows[period]
    for part in ("cash_quality", "balance_sheet"):
        for r in fin.get(part, {}).get("annual", []):
            if r["period"] == period:
                row |= {k: v for k, v in r.items() if k != "period"}
    prev = f"{int(period[:4]) - 1}{period[4:]}"
    if prev in rows and rows[prev].get("revenue"):
        row["revenue_growth"] = (row["revenue"] / rows[prev]["revenue"] - 1) * 100
    return row


def actual(check: dict, fin: dict, deadline: str) -> tuple[float, str] | None:
    """The reported number for the check at the deadline, with the id of its source row.
    Year-end deadlines read the annual row; others read the quarter ending then (flow
    measures like revenue are not annualised from one quarter, so those return None)."""
    if deadline.endswith("-03"):
        row = _annual(fin, deadline)
        if row and row.get(check["measure"]) is not None:
            return float(row[check["measure"]]), f"FY:{deadline}"
        return None
    if check["measure"] in ("margin_pct",):
        for q in fin["trajectory"]["quarterly"]:
            if q["period"] == deadline and q.get("margin_pct") is not None:
                return float(q["margin_pct"]), f"Q:{deadline}"
    return None


def judge(target: str, deadline: str | None, latest_period: str, fin: dict | None) -> dict | None:
    """Code's verdict for a promise, or None to leave it to the model."""
    if not fin or not deadline or deadline > latest_period or fin.get("is_lender"):
        return None
    check = parse(target)
    if not check:
        return None
    got = actual(check, fin, deadline)
    if not got:
        return None
    value, source = got
    want, op = check["value"], check["op"]
    met = value > want if op == ">" else value >= want if op == ">=" else value <= want
    if met:
        verdict = "delivered"
    elif want and op != ">" and abs(value - want) / abs(want) <= PARTLY_BAND:
        verdict = "partly"
    else:
        verdict = "missed"
    unit = {
        "working_capital_days": " days",
        "debtor_days": " days",
        "margin_pct": "%",
        "revenue_growth": "%",
    }.get(check["measure"], " Cr")

    def fmt(x: float) -> str:
        if unit == " Cr":
            return f"{'-' if x < 0 else ''}₹{abs(x):,.0f} Cr"
        return f"{x:,.0f} days" if unit == " days" else f"{x:.1f}%"

    label = check["label"].capitalize()
    verb = "were" if unit == " days" else "was"
    if op == ">" and want == 0:
        said = f"{label} {verb} {fmt(value)}, against a promise to turn positive"
    else:
        rule = {">": "above", ">=": "at least", "<=": "at most"}[op]
        said = f"{label} {verb} {fmt(value)}, against {rule} {fmt(want)} promised"
    return {
        "verdict": verdict,
        "actual": said,
        "evidence": [source],
        "check": {**check, "actual": value, "source": source},
    }
