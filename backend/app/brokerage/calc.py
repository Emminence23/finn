"""Brokerage calculations (brief §6). Pure functions, no model, no I/O.

Conventions, stated once and shown in the UI:
- implied return = (target / reference - 1) x 100, reference = the price the report printed;
- revision = (new / old - 1) x 100, only for the same metric, fiscal period, unit, definition;
- target error = (target - realised) / realised x 100 (positive: the target was above);
- percentiles by linear interpolation between closest ranks;
- amounts are compared only after code converts them to INR crore (bn x 100, mn / 10);
- one latest report per brokerage in any snapshot, so one house never counts twice."""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from statistics import mean, median

MIN_SAMPLE = 10  # brief §6.5: no ranking below this many eligible observations
SMALL_SAMPLE = 20  # above the minimum but still flagged as small
OUTLIER_PCT = 15.0  # a target this far from the others' median is called out
NEAR_ZERO_RETURN = 1.0  # a realised move inside ±1% counts as flat, not a direction
METHOD = "finn-brokerage-v1"


def implied_return(target: float | None, reference: float | None) -> float | None:
    if not target or not reference or target <= 0 or reference <= 0:
        return None
    return (target / reference - 1) * 100


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    if (old < 0) != (new < 0):
        return None  # a change of sign has no meaningful percentage
    return (new / old - 1) * 100


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def stats(xs: list[float]) -> dict | None:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    m = median(xs)
    return {
        "n": len(xs),
        "median": m,
        "mean": mean(xs),
        "min": min(xs),
        "max": max(xs),
        "p25": percentile(xs, 0.25),
        "p75": percentile(xs, 0.75),
        "iqr": percentile(xs, 0.75) - percentile(xs, 0.25),
        "mad": median([abs(x - m) for x in xs]),
    }


def horizon_bucket(value: float | None, unit: str | None) -> str:
    """Comparable horizons share a bucket; a missing horizon is its own bucket."""
    if value is None or not unit:
        return "not stated"
    u = unit.lower().rstrip("s")
    months = {"month": value, "year": value * 12, "week": value * 12 / 52}.get(u)
    if months is None:
        return f"{value:g} {unit}"
    return f"{round(months):d} months"


def horizon_days(value: float | None, unit: str | None) -> int | None:
    b = horizon_bucket(value, unit)
    m = re.fullmatch(r"(\d+) months", b)
    return round(int(m.group(1)) * 365 / 12) if m else None


def to_crore(value: float, unit: str) -> float | None:
    """Aggregate rupee amounts in INR crore (bn x 100, mn / 10). Per-share figures,
    percentages and unknown units return None, so they are never mixed with amounts."""
    u = unit.lower()
    if "share" in u or "%" in u or u.strip() == "x":
        return None
    if not re.search(r"inr|rs|₹|`|rupee", u):
        return None
    if re.search(r"\bcr(ore)?s?\b", u):
        return value
    if re.search(r"\b(b|bn|billion)\b", u):
        return value * 100
    if re.search(r"\b(mn|million)\b", u):
        return value / 10
    return None


BASIS_TOLERANCE_PCT = 3.0


def basis_check(estimates: list[dict], reported: dict[str, dict]) -> dict[str, dict]:
    """Per metric, does this report's table describe the reported consolidated company?
    Its own reported-year rows are compared with the company's reported figures; a gap
    beyond BASIS_TOLERANCE_PCT means another basis (standalone, ex-subsidiaries)."""
    out: dict[str, dict] = {}
    for e in estimates:
        # revenue only: EPS and profit differ by definition (adjusted vs reported), not basis
        if not e.get("is_actual") or not e.get("fiscal_period") or e["metric"] != "revenue":
            continue
        rep = (reported.get(e["fiscal_period"]) or {}).get(e["metric"])
        mine = e["value"] if e["metric"] == "EPS" else e.get("value_cr")
        if rep is None or mine is None or e["metric"] in out:
            continue
        gap = pct_change(mine, rep)
        out[e["metric"]] = {
            "fiscal_period": e["fiscal_period"],
            "table": mine,
            "reported": rep,
            "gap_pct": gap,
            "same_basis": gap is not None and abs(gap) <= BASIS_TOLERANCE_PCT,
        }
    return out


def comparable_key(e: dict, across_brokerages: bool = True) -> tuple | None:
    """Estimates compare only within the same metric, fiscal period, unit family and
    definition. Aggregate amounts are compared in INR crore; others in their printed unit."""
    if not e.get("fiscal_period") or e.get("is_actual"):
        return None
    if across_brokerages and e.get("other_basis"):
        return None  # fine against the same house's own earlier table, not against others
    unit = (e.get("unit") or "").strip()
    if e.get("value_cr") is not None:
        family = "INR crore"
    elif e["metric"] == "EPS" and re.search(r"inr|rs|₹|`", unit.lower()):
        family = "INR/share"  # EPS is per share whether printed 'INR' or 'INR/share'
    else:
        family = unit
    return (
        e["metric"],
        e["fiscal_period"],
        family,
        (e.get("definition") or "").lower(),
        (e.get("scenario") or "").lower(),
        bool(e.get("other_basis")),
    )


def comparable_value(e: dict) -> float:
    return e["value_cr"] if e.get("value_cr") is not None else e["value"]


def latest_per_brokerage(
    obs: list[dict], start: str | None = None, end: str | None = None
) -> list[dict]:
    """The latest report from each brokerage inside the window."""
    best: dict[str, dict] = {}
    for o in obs:
        d = o.get("published_at")
        if not d or (start and d < start) or (end and d > end):
            continue
        cur = best.get(o["brokerage_id"])
        if cur is None or d > cur["published_at"]:
            best[o["brokerage_id"]] = o
    return sorted(best.values(), key=lambda o: o["published_at"], reverse=True)


def revision_pairs(obs: list[dict], end: str | None = None) -> list[tuple[dict, dict]]:
    """(previous, latest) for each brokerage with at least two dated reports up to `end`."""
    by: dict[str, list[dict]] = {}
    for o in obs:
        if o.get("published_at") and (not end or o["published_at"] <= end):
            by.setdefault(o["brokerage_id"], []).append(o)
    out = []
    for xs in by.values():
        xs.sort(key=lambda o: o["published_at"])
        out += list(zip(xs, xs[1:], strict=False))
    return out


_ORDER = {"negative": 0, "neutral": 1, "positive": 2}


def rating_move(old: str | None, new: str | None) -> str | None:
    if old not in _ORDER or new not in _ORDER:
        return None
    d = _ORDER[new] - _ORDER[old]
    return "upgrade" if d > 0 else "downgrade" if d < 0 else "unchanged"


def revision(prev: dict, cur: dict) -> dict:
    """What one brokerage changed between two of its reports."""
    est_prev = {
        comparable_key(e, False): e for e in prev.get("estimates", []) if comparable_key(e, False)
    }
    est = []
    for e in cur.get("estimates", []):
        k = comparable_key(e, False)
        if k and k in est_prev:
            old, new = comparable_value(est_prev[k]), comparable_value(e)
            ch = pct_change(new, old)
            if ch is not None:
                est.append(
                    {
                        "metric": k[0],
                        "fiscal_period": k[1],
                        "unit": k[2],
                        "old": old,
                        "new": new,
                        "change_pct": ch,
                    }
                )
    return {
        "brokerage_id": cur["brokerage_id"],
        "from": prev["published_at"],
        "to": cur["published_at"],
        "from_report": prev["report_id"],
        "to_report": cur["report_id"],
        "rating_from": prev.get("rating_raw"),
        "rating_to": cur.get("rating_raw"),
        "rating_move": rating_move(prev.get("rating"), cur.get("rating")),
        "target_from": prev.get("target_price"),
        "target_to": cur.get("target_price"),
        "target_change_pct": pct_change(cur.get("target_price"), prev.get("target_price")),
        "estimates": est,
    }


def momentum(revs: list[dict], as_of: str, days: int) -> dict:
    """Brief §3.5 over revisions whose later report falls in the lookback window. Counts are
    per brokerage: one house revising twice counts once, by its latest move."""
    start = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
    latest: dict[str, dict] = {}
    n_reports = 0
    for r in revs:
        if start < r["to"] <= as_of:
            n_reports += 1
            if r["brokerage_id"] not in latest or r["to"] > latest[r["brokerage_id"]]["to"]:
                latest[r["brokerage_id"]] = r
    rs = list(latest.values())
    moves = [r["rating_move"] for r in rs]
    tps = [r["target_change_pct"] for r in rs if r["target_change_pct"] is not None]
    eps: dict[str, list[float]] = {}
    for r in rs:
        for e in r["estimates"]:
            if e["metric"] == "EPS":
                eps.setdefault(e["fiscal_period"], []).append(e["change_pct"])
    ups, downs = sum(t > 0 for t in tps), sum(t < 0 for t in tps)
    return {
        "days": days,
        "from": start,
        "to": as_of,
        "brokerages": len(rs),
        "revisions": n_reports,
        "upgrades": moves.count("upgrade"),
        "downgrades": moves.count("downgrade"),
        "unchanged": moves.count("unchanged"),
        "target_up": ups,
        "target_down": downs,
        "target_same": sum(t == 0 for t in tps),
        "median_target_change_pct": median(tps) if tps else None,
        "median_eps_change_pct": {fy: median(v) for fy, v in sorted(eps.items())},
        "net_breadth": (ups - downs) / len(rs) if rs else None,
    }


def outliers(points: list[tuple[str, float]]) -> list[dict]:
    """A brokerage whose value sits more than OUTLIER_PCT from the median of the others."""
    out = []
    if len(points) < 3:
        return out
    for i, (who, v) in enumerate(points):
        rest = [x for j, (_, x) in enumerate(points) if j != i]
        m = median(rest)
        gap = pct_change(v, m)
        if gap is not None and abs(gap) > OUTLIER_PCT:
            out.append({"brokerage_id": who, "value": v, "others_median": m, "gap_pct": gap})
    return out


def price_on_or_before(prices: list[tuple[str, float]], day: str) -> tuple[str, float] | None:
    """The last close on or before `day` (prices sorted by date). Never a later price."""
    best = None
    for d, c in prices:
        if d <= day:
            best = (d, c)
        else:
            break
    return best


def evaluate_target(o: dict, prices: list[tuple[str, float]], as_of: str) -> dict | None:
    """Direction and target error at the stated horizon, or None when the horizon hasn't
    passed, isn't stated, or prices don't cover both ends."""
    days = horizon_days(o.get("horizon_value"), o.get("horizon_unit"))
    if not days or not o.get("published_at") or not o.get("target_price"):
        return None
    end_day = (date.fromisoformat(o["published_at"]) + timedelta(days=days)).isoformat()
    if end_day > as_of:
        return None
    start = price_on_or_before(prices, o["published_at"])
    end = price_on_or_before(prices, end_day)
    if not start or not end or not prices or prices[0][0] > o["published_at"]:
        return None
    ref = o.get("reference_price") or start[1]
    called = implied_return(o["target_price"], ref)
    actual = implied_return(end[1], start[1])
    flat = abs(actual) < NEAR_ZERO_RETURN
    return {
        "horizon_days": days,
        "start_price": start[1],
        "end_price": end[1],
        "direction_right": None if flat else (called > 0) == (actual > 0),
        "signed_error_pct": (o["target_price"] - end[1]) / end[1] * 100,
        "abs_error_pct": abs(o["target_price"] - end[1]) / end[1] * 100,
    }


def eps_error(forecast: float, actual: float) -> float | None:
    if abs(actual) < 0.5:  # near-zero EPS makes a percentage error meaningless
        return None
    return abs(forecast - actual) / abs(actual) * 100


def sample_note(n: int) -> str | None:
    if n < MIN_SAMPLE:
        return f"{n} eligible observations, below {MIN_SAMPLE}: shown one by one, not ranked."
    if n < SMALL_SAMPLE:
        return f"{n} eligible observations: a small sample."
    return None
