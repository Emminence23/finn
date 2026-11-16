"""The whole portfolio, and a suggested re-weighting of the same holdings.

All of it is deterministic: prices and reported financials go in, numbers come out, and the
same inputs always give the same answer. The only model call is the optional review in
`review.py`, which may nudge the suggestion within limits enforced here.

What the suggestion is, in plain terms:
1. Balance risk. Equal risk contribution: each holding contributes the same share of the
   portfolio's day-to-day swings, measured on the last six months of daily prices. The
   covariance is shrunk halfway towards a constant-correlation target, because six months
   of 18 stocks is too little to trust every pairwise correlation.
2. Tilt towards quality. A composite of returns on capital, growth, cash conversion,
   gearing, valuation and management's delivery record (each z-scored across the holdings
   and capped at ±2) scales each risk-balanced weight by exp(tilt × score).
3. Keep within the investor's rules (settings.py, per account): each holding between a
   minimum and maximum, each theme under a cap, and no holding moving more than one step
   from today's weight in one go. Any of these can be switched off.

It does not forecast returns. The point is a portfolio whose risk isn't concentrated by
accident and whose weights lean towards the businesses the numbers favour.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pandas as pd

from app.db import session
from app.portfolio.holdings import get_holdings, get_positions
from app.portfolio.settings import DEFAULTS as _DEF
from app.portfolio.settings import limits as _limits

TRADING_DAYS = 252
SHRINK = 0.5  # weight on the constant-correlation target (a statistical choice, not a rule)
# The investor's rules (holding and theme limits, step size, tilt, risk window) live in
# settings.py, per account. These names are the defaults, kept for reference.
WINDOW = int(_DEF["risk_days"])
TILT = float(_DEF["tilt"])
MIN_W, MAX_W = float(_DEF["min_pct"]) / 100, float(_DEF["max_pct"]) / 100
THEME_CAP = float(_DEF["theme_cap_pct"]) / 100
MAX_STEP = float(_DEF["max_step_pct"]) / 100

# factor: (metric, higher is better, weight in the composite)
FACTORS = {
    "returns": 0.25,  # ROCE, or ROE for lenders
    "growth": 0.25,  # 3-year revenue and profit growth
    "cash": 0.15,  # 3-year cash conversion (non-lenders)
    "balance": 0.10,  # debt / equity, lower is better (non-lenders)
    "value": 0.15,  # earnings yield, 1 / PE
    "delivery": 0.10,  # promise scorecard, where one is built
}


# ------------------------------------------------------------------ inputs
def _prices(symbols: list[str]) -> pd.DataFrame:
    q = ",".join("?" * len(symbols))
    with session() as db:
        rows = db.execute(
            f"SELECT symbol, date, close FROM prices WHERE symbol IN ({q}) ORDER BY date",
            symbols,
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    return df.pivot(index="date", columns="symbol", values="close").sort_index().ffill()


def _recent(px: pd.DataFrame, days: int = WINDOW) -> pd.DataFrame:
    """The risk window: the last `days` sessions of returns (days + 1 closes)."""
    return px.iloc[-(days + 1) :]


def _benchmark(dates: list[str]) -> pd.Series | None:
    with session() as db:
        rows = db.execute(
            "SELECT date, close FROM benchmark WHERE name='NIFTY 50' ORDER BY date"
        ).fetchall()
    if not rows:
        return None
    b = pd.Series({r["date"]: r["close"] for r in rows})
    return b.reindex(sorted(set(b.index) | set(dates))).ffill().reindex(dates)


def _history(px: pd.DataFrame, qty: dict[str, float]) -> dict:
    """Value of today's positions over the past year (buy and hold), next to the Nifty 50
    scaled to the same starting value. Both in rupees, so they share one axis."""
    cols = [s for s in qty if s in px.columns]
    full = px[cols].bfill()
    value = (full * pd.Series({s: qty[s] for s in cols})).sum(axis=1)
    dates = list(value.index)
    bench = _benchmark(dates)
    out = []
    for d, v in value.items():
        row = {"date": d, "value": round(float(v), 2)}
        if bench is not None and pd.notna(bench[d]) and pd.notna(bench.iloc[0]):
            row["nifty"] = round(float(value.iloc[0] * bench[d] / bench.iloc[0]), 2)
        out.append(row)
    ret = float(value.iloc[-1] / value.iloc[0] - 1) * 100 if len(value) > 1 else 0.0
    nifty = (
        float(bench.iloc[-1] / bench.iloc[0] - 1) * 100
        if bench is not None and pd.notna(bench.iloc[0]) and pd.notna(bench.iloc[-1])
        else None
    )
    curve = value / value.iloc[0]
    return {
        "series": out,
        "start": dates[0] if dates else None,
        "return": ret,
        "nifty_return": nifty,
        "max_drawdown": float((curve / curve.cummax() - 1).min()) * 100,
    }


def _meta(symbols: list[str]) -> dict[str, dict]:
    q = ",".join("?" * len(symbols))
    with session() as db:
        return {
            r["symbol"]: dict(r)
            for r in db.execute(
                f"SELECT symbol, name, sector FROM companies WHERE symbol IN ({q})", symbols
            )
        }


@lru_cache(maxsize=256)
def _fin_values(symbol: str) -> dict | None:
    """Reported-financial metrics for a company (cached: the tables change once a quarter)."""
    from app.research.compare import _values
    from app.research.financials import build_financials
    from app.research.service import load_fundamentals

    try:
        fin = build_financials(load_fundamentals(symbol))
    except Exception:
        return None
    return {**_values(fin), "is_lender": fin["is_lender"]}


def _fundamentals(symbol: str) -> dict | None:
    """Numbers used by the tilt and the summary, with the current promise score."""
    from app.research.service import get_cached

    v = _fin_values(symbol)
    if v is None:
        return None
    p = (get_cached(symbol) or {}).get("promises") or {}
    return {**v, "delivery": p.get("score") if p.get("items") else None}


def _factor_scores(symbols: list[str]) -> tuple[dict[str, float], dict[str, dict]]:
    """Composite quality score per holding (mean 0 across holdings) and the raw factors."""
    raw: dict[str, dict] = {}
    for s in symbols:
        f = _fundamentals(s) or {}
        lender = bool(f.get("is_lender"))
        pe = f.get("pe")
        growth = [x for x in (f.get("revenue_3y"), f.get("pat_3y")) if x is not None]
        raw[s] = {
            "returns": f.get("roe_pct") if lender else f.get("roce_pct"),
            "growth": sum(growth) / len(growth) if growth else None,
            "cash": None if lender else f.get("cfo_to_pat_3y"),
            "balance": None if lender or f.get("debt_to_equity") is None else -f["debt_to_equity"],
            "value": 100 / pe if pe and pe > 0 else None,
            "delivery": f.get("delivery"),
            "_lender": lender,
            "_pe": pe,
            "_roe": f.get("roe_pct"),
            "_roce": f.get("roce_pct"),
            "_revenue_3y": f.get("revenue_3y"),
            "_debt_to_equity": f.get("debt_to_equity"),
        }
    z: dict[str, dict[str, float]] = {s: {} for s in symbols}
    for k in FACTORS:
        vals = {s: raw[s][k] for s in symbols if raw[s][k] is not None}
        if len(vals) < 3:
            continue
        arr = np.array(list(vals.values()), dtype=float)
        mu, sd = float(np.median(arr)), float(np.std(arr)) or 1.0
        for s, v in vals.items():
            z[s][k] = max(-2.0, min(2.0, (v - mu) / sd))
    score = {}
    for s in symbols:
        have = {k: FACTORS[k] for k in z[s]}
        tot = sum(have.values())
        score[s] = sum(z[s][k] * w for k, w in have.items()) / tot if tot else 0.0
    mean = sum(score.values()) / len(score) if score else 0.0
    return {s: v - mean for s, v in score.items()}, {s: raw[s] | {"z": z[s]} for s in symbols}


def _covariance(px: pd.DataFrame) -> np.ndarray:
    """Annualised covariance of daily log returns, shrunk towards constant correlation."""
    r = np.log(px).diff().dropna(how="all").fillna(0.0)
    s = np.cov(r.values, rowvar=False) * TRADING_DAYS
    sd = np.sqrt(np.diag(s))
    corr = s / np.outer(sd, sd)
    n = len(sd)
    avg = (corr.sum() - n) / (n * (n - 1)) if n > 1 else 0.0
    target = avg * np.outer(sd, sd)
    np.fill_diagonal(target, sd**2)
    return SHRINK * target + (1 - SHRINK) * s


def _erc(cov: np.ndarray, iters: int = 500) -> np.ndarray:
    """Equal risk contribution by cyclical coordinate descent (Griveau-Billion et al.)."""
    n = cov.shape[0]
    w = np.ones(n) / n
    b = np.ones(n) / n
    for _ in range(iters):
        for i in range(n):
            c = cov[i] @ w - cov[i, i] * w[i]
            w[i] = (-c + math.sqrt(c * c + 4 * cov[i, i] * b[i])) / (2 * cov[i, i])
    return w / w.sum()


def _project(
    w: dict[str, float], theme: dict[str, str], lo: dict, hi: dict, cap: float = THEME_CAP
) -> dict:
    """Weights summing to 1 within per-name bounds and theme caps (iterative water-filling)."""
    w = dict(w)
    for _ in range(200):
        total = sum(w.values())
        w = {s: v / total for s, v in w.items()}
        changed = False
        # theme caps: scale an over-cap theme down to the cap
        by: dict[str, float] = {}
        for s, v in w.items():
            by[theme[s]] = by.get(theme[s], 0) + v
        for t, tw in by.items():
            if tw > cap + 1e-9:
                f = cap / tw
                for s in w:
                    if theme[s] == t:
                        w[s] *= f
                changed = True
        # name bounds
        for s in w:
            if w[s] > hi[s] + 1e-9:
                w[s], changed = hi[s], True
            elif w[s] < lo[s] - 1e-9:
                w[s], changed = lo[s], True
        # hand the slack to names with room, in proportion to their weight
        slack = 1 - sum(w.values())
        if abs(slack) > 1e-9:
            changed = True
            room = [
                s
                for s in w
                if (slack > 0 and w[s] < hi[s] - 1e-9 and by.get(theme[s], 0) < cap - 1e-9)
                or (slack < 0 and w[s] > lo[s] + 1e-9)
            ]
            if not room:
                break
            base = sum(w[s] for s in room)
            for s in room:
                w[s] += slack * w[s] / base
        if not changed:
            break
    total = sum(w.values())
    return {s: v / total for s, v in w.items()}


# ------------------------------------------------------------------ stats
def _stats(w: np.ndarray, cov: np.ndarray, symbols, theme, raw) -> dict:
    vol = float(math.sqrt(w @ cov @ w))
    rc = w * (cov @ w) / (vol * vol) if vol else np.zeros_like(w)
    by: dict[str, float] = {}
    for s, x in zip(symbols, w, strict=True):
        by[theme[s]] = by.get(theme[s], 0) + float(x)
    top_theme = max(by.items(), key=lambda kv: kv[1])

    def wavg(key):
        pairs = [
            (float(x), raw[s][key])
            for s, x in zip(symbols, w, strict=True)
            if raw[s][key] is not None
        ]
        tot = sum(p[0] for p in pairs)
        return sum(a * b for a, b in pairs) / tot if tot else None

    pe_pairs = [
        (float(x), raw[s]["_pe"])
        for s, x in zip(symbols, w, strict=True)
        if raw[s]["_pe"] and raw[s]["_pe"] > 0
    ]
    pe = (sum(a for a, _ in pe_pairs) / sum(a / b for a, b in pe_pairs)) if pe_pairs else None
    return {
        "volatility": vol * 100,
        "effective_holdings": float(1 / (w @ w)),
        "top5": float(np.sort(w)[-5:].sum()) * 100,
        "largest_theme": {"theme": top_theme[0], "weight": top_theme[1] * 100},
        "pe": pe,
        "roe": wavg("_roe"),
        "revenue_growth_3y": wavg("_revenue_3y"),
        "risk_share": {s: float(x) * 100 for s, x in zip(symbols, rc, strict=True)},
    }


def _returns(px: pd.DataFrame, days: int) -> pd.Series:
    if len(px) <= days:
        days = len(px) - 1
    return (px.iloc[-1] / px.iloc[-1 - days] - 1) * 100


# ------------------------------------------------------------------ API
def overview() -> dict:
    """The portfolio as it stands: holdings, themes, risk, returns, quality."""
    pos = get_positions()
    held = {p["symbol"]: p["weight"] for p in pos["positions"]}
    symbols = list(held)
    meta = _meta(symbols)
    px_all = _prices(symbols)
    themes_n = len({(m.get("sector") or "other") for m in meta.values()})
    L = _limits(len(symbols), themes_n)
    px = _recent(px_all, L["risk_days"])
    have = [s for s in symbols if s in px.columns]
    w = np.array([held[s] for s in have])
    w = w / w.sum()
    cov = _covariance(px[have])
    theme = {s: (meta.get(s, {}).get("sector") or "other") for s in have}
    _, raw = _factor_scores(have)
    st = _stats(w, cov, have, theme, raw)

    daily = np.log(px[have]).diff().fillna(0.0)
    port = (np.exp(daily) - 1).values @ w
    curve = np.cumprod(1 + port)
    r6, r1 = _returns(px[have], len(px) - 1), _returns(px[have], 21)
    hist = _history(px_all, {p["symbol"]: p["qty"] for p in pos["positions"]})
    by_sym = {p["symbol"]: p for p in pos["positions"]}

    rows = []
    for i, s in enumerate(have):
        rows.append(
            {
                "symbol": s,
                "name": meta.get(s, {}).get("name", s),
                "theme": theme[s],
                "weight": float(w[i]) * 100,
                "qty": by_sym[s]["qty"],
                "price": by_sym[s]["price"],
                "value": by_sym[s]["value"],
                "avg_cost": by_sym[s]["avg_cost"],
                "gain_pct": by_sym[s]["gain_pct"],
                "return_6m": float(r6[s]),
                "return_1m": float(r1[s]),
                "contribution_6m": float(w[i] * r6[s]),
                "volatility": float(math.sqrt(cov[i, i])) * 100,
                "risk_share": st["risk_share"][s],
                "pe": raw[s]["_pe"],
                "roe": raw[s]["_roe"],
                "is_lender": raw[s]["_lender"],
                "delivery": raw[s]["delivery"],
            }
        )
    themes: dict[str, dict] = {}
    for r in rows:
        t = themes.setdefault(
            r["theme"],
            {
                "theme": r["theme"],
                "weight": 0.0,
                "risk_share": 0.0,
                "contribution_6m": 0.0,
                "symbols": [],
            },
        )
        t["weight"] += r["weight"]
        t["risk_share"] += r["risk_share"]
        t["contribution_6m"] += r["contribution_6m"]
        t["symbols"].append(r["symbol"])

    r = np.log(px[have]).diff().dropna()
    corr = r.corr().values
    pairs = sorted(
        ((corr[i, j], have[i], have[j]) for i in range(len(have)) for j in range(i + 1, len(have))),
        reverse=True,
    )[:3]

    flags = []
    # your own rules first: holdings outside the minimum and maximum you set
    s_ = L["settings"]
    for limit, side, word in ((s_["max_pct"], 1, "above your"), (s_["min_pct"], -1, "below your")):
        if not limit:
            continue
        out = sorted(
            (x for x in rows if side * (x["weight"] - limit) > 0.05),
            key=lambda x: -side * x["weight"],
        )
        if out:
            names = ", ".join(f"{x['symbol']} {x['weight']:.1f}%" for x in out[:3])
            more = f" and {len(out) - 3} more" if len(out) > 3 else ""
            kind = "maximum" if side > 0 else "minimum"
            flags.append(
                f"{len(out)} {'holding is' if len(out) == 1 else 'holdings are'} {word} "
                f"{limit:g}% {kind}: {names}{more}."
            )
    cap = L["settings"]["theme_cap_pct"]  # your theme cap is also the warning line
    if cap is not None and st["largest_theme"]["weight"] > cap:
        flags.append(
            f"{st['largest_theme']['theme'].capitalize()} is "
            f"{st['largest_theme']['weight']:.0f}% of the portfolio."
        )
    lenders = sum(x["weight"] for x in rows if x["is_lender"])
    if cap is not None and lenders > cap:
        flags.append(f"Lenders together are {lenders:.0f}% of the portfolio.")
    for x in sorted(rows, key=lambda x: -(x["risk_share"] - x["weight"])):
        if x["risk_share"] > 1.5 * x["weight"] and x["risk_share"] > 6:
            flags.append(
                f"{x['symbol']} is {x['weight']:.0f}% of the money but "
                f"{x['risk_share']:.0f}% of the risk."
            )
    if pairs and pairs[0][0] > 0.6:
        c, a, b = pairs[0]
        flags.append(f"{a} and {b} move together (correlation {c:.2f}).")

    return {
        "as_of": px.index[-1] if len(px) else None,
        "days": int(len(px)),
        "custom": _is_custom(),
        "summary": {
            "holdings": len(rows),
            "value": pos["value"],
            "invested": pos["invested"],
            "gain": pos["gain"],
            "gain_pct": pos["gain_pct"],
            "return_6m": float(curve[-1] - 1) * 100,
            "return_1m": float(np.prod(1 + port[-21:]) - 1) * 100,
            "return_1y": hist["return"],
            "nifty_1y": hist["nifty_return"],
            "max_drawdown": hist["max_drawdown"],
            **{k: v for k, v in st.items() if k != "risk_share"},
        },
        "history": hist,
        "holdings": rows,
        "themes": sorted(themes.values(), key=lambda t: -t["weight"]),
        "correlated": [{"a": a, "b": b, "corr": float(c)} for c, a, b in pairs],
        "flags": flags[:6],
    }


def _is_custom() -> bool:
    from app.portfolio.holdings import is_custom

    return is_custom()


def bounds(held: dict[str, float], symbols: list[str], L: dict | None = None) -> tuple[dict, dict]:
    """Per-holding limits: within the investor's min..max and at most one step from today's
    weight. A holding already outside min..max moves one full step towards it."""
    L = L or {"min": MIN_W, "max": MAX_W, "step": MAX_STEP}
    mn, mx, step = L["min"], L["max"], L["step"]
    lo, hi = {}, {}
    for s in symbols:
        c = held[s]
        if c - step > mx:
            lo[s] = hi[s] = c - step
        elif c + step < mn:
            lo[s] = hi[s] = c + step
        else:
            lo[s], hi[s] = max(mn, c - step), min(mx, c + step)
    return lo, hi


def suggest() -> dict:
    """Code's suggested weights for the same holdings, with the reason for each change."""
    held = get_holdings()
    meta = _meta(list(held))
    L = _limits(len(held), len({(m.get("sector") or "other") for m in meta.values()}))
    px = _recent(_prices(list(held)), L["risk_days"])
    symbols = [s for s in held if s in px.columns]
    cur = np.array([held[s] for s in symbols])
    cur = cur / cur.sum()
    cov = _covariance(px[symbols])
    theme = {s: (meta.get(s, {}).get("sector") or "other") for s in symbols}
    score, raw = _factor_scores(symbols)

    base = _erc(cov)
    tilted = base * np.exp(L["tilt"] * np.array([score[s] for s in symbols]))
    lo, hi = bounds(held, symbols, L)
    tilted_n = tilted / tilted.sum()
    target = _project(dict(zip(symbols, tilted, strict=True)), theme, lo, hi, L["theme_cap"])
    new = np.array([target[s] for s in symbols])

    before, after = (_stats(x, cov, symbols, theme, raw) for x in (cur, new))
    by_theme: dict[str, float] = {}
    for i, s in enumerate(symbols):
        by_theme[theme[s]] = by_theme.get(theme[s], 0.0) + float(new[i])
    capped = {t for t, v in by_theme.items() if v >= L["theme_cap"] - 1e-4}
    # a cut the step limit slowed keeps weight that the others then do without
    slowed = any(
        abs(new[i] - lo[s]) < 1e-4 and lo[s] > L["min"] + 1e-4 and new[i] < cur[i]
        for i, s in enumerate(symbols)
    )
    rows = []
    for i, s in enumerate(symbols):
        rows.append(
            {
                "symbol": s,
                "name": meta.get(s, {}).get("name", s),
                "theme": theme[s],
                "current": float(cur[i]) * 100,
                "risk_balanced": float(base[i]) * 100,
                "suggested": float(new[i]) * 100,
                "change": float(new[i] - cur[i]) * 100,
                "lo": lo[s] * 100,
                "hi": hi[s] * 100,
                "score": score[s],
                "factors": {k: round(v, 2) for k, v in raw[s]["z"].items()},
                "reason": _reason(
                    cur[i],
                    base[i],
                    tilted_n[i],
                    new[i],
                    before["risk_share"][s],
                    raw[s],
                    lo[s],
                    hi[s],
                    len(symbols),
                    L,
                    theme_capped=theme[s] in capped,
                    step_slowed=slowed,
                ),
            }
        )
    rows.sort(key=lambda r: -abs(r["change"]))
    return {
        "holdings": rows,
        "before": {k: v for k, v in before.items() if k != "risk_share"},
        "after": {k: v for k, v in after.items() if k != "risk_share"},
        "turnover": float(np.abs(new - cur).sum() / 2) * 100,
        "rules": {
            "min": L["min"] * 100,
            "max": L["max"] * 100,
            "theme_cap": L["theme_cap"] * 100,
            "max_step": L["step"] * 100,
            "tilt": L["tilt"],
            "shrink": SHRINK,
            "days": int(len(px)) - 1,
            "factors": FACTORS,
            "settings": L["settings"],
            "notes": L["notes"],
        },
    }


_FACTOR_WORDS = {
    "returns": ("high returns on capital", "low returns on capital"),
    "growth": ("fast growth", "slow growth"),
    "cash": ("strong cash conversion", "weak cash conversion"),
    "balance": ("little debt", "high debt"),
    "value": ("a cheaper valuation", "an expensive valuation"),
    "delivery": ("management delivering on promises", "management missing its promises"),
}


def _reason(
    cur,
    base,
    tilted,
    new,
    risk_share,
    raw,
    lo,
    hi,
    n,
    L=None,
    theme_capped=False,
    step_slowed=False,
) -> str:
    """What moved this weight, stage by stage: risk balance, quality tilt, then the limits."""
    d = (new - cur) * 100
    if abs(d) < 0.25:
        return "Roughly where it is."
    parts = []
    risk_d, tilt_d, limit_d = (base - cur) * 100, (tilted - base) * 100, (new - tilted) * 100
    equal = 100 / n
    if abs(risk_d) >= 0.5 and (risk_d > 0) == (d > 0):
        parts.append(
            f"carries {risk_share:.1f}% of the risk against an equal share of {equal:.1f}%"
        )
    z = raw["z"]
    if abs(tilt_d) >= 0.3 and z:
        up = tilt_d > 0
        k = max(z, key=lambda k: z[k] * FACTORS[k] * (1 if up else -1))
        if (z[k] > 0) == up:
            words = _FACTOR_WORDS[k][0 if up else 1]
            if up == (d > 0):
                parts.append(words)
            else:
                parts.append(f"held back by {words}" if d > 0 else f"cut less thanks to {words}")
    tol = 1e-4
    if abs(limit_d) >= 0.3:
        mx, mn = (L["max"], L["min"]) if L else (MAX_W, MIN_W)
        step = L["step"] if L else MAX_STEP
        if abs(new - mx) < tol:
            parts.append(f"held at your {mx * 100:.3g}% maximum")
        elif abs(new - mn) < tol and mn > 0:
            parts.append(f"held at your {mn * 100:.3g}% minimum")
        elif abs(new - hi) < tol or abs(new - lo) < tol:
            parts.append(f"limited to your {step * 100:.3g}-point step this time")
        elif limit_d > 0:
            parts.append("picks up weight that capped holdings couldn't take")
        elif theme_capped:
            parts.append(
                "trimmed to keep its theme within the cap"
                if d < 0
                else "held back to keep its theme within the cap"
            )
        elif step_slowed:
            # not this holding's own limit: the large cuts are spread over several rounds
            parts.append(
                f"cut a little further while your {step * 100:.3g}-point step slows the larger cuts"
                if d < 0
                else f"short of its target while your {step * 100:.3g}-point step slows the "
                "larger cuts"
            )
        else:
            parts.append(
                "trimmed to fund holdings your limits kept higher"
                if d < 0
                else "short of its target to fund holdings your limits kept higher"
            )
    if not parts:
        parts.append(
            "trimmed to fund the other changes"
            if d < 0
            else "picks up weight that capped holdings couldn't take"
        )
    txt = "; ".join(parts)
    return txt[0].upper() + txt[1:] + "."
