"""Configurable alerts (FR-ALERT): unusual EOD volume/price moves and material filings."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd

from app.db import session
from app.ingest.prices import with_signals
from app.network.owner import current_owner

# Every threshold is the investor's (FR-ALERT-04). These are only starting values.
DEFAULTS = {
    "volume_multiple": 1.5,  # alert when volume is at least this multiple of its average...
    "volume_low_multiple": 0.5,  # ...or at most this multiple (an unusually quiet day)
    "volume_mode": "high",  # high | low | either
    "volume_window": 20,  # sessions in the average, excluding the day itself
    "price_abs_pct": 3.0,  # a large-cap moving 3% in a session is unusual
    "price_direction": "either",  # up | down | either
    "combine": "any",  # any: each condition alerts on its own (OR); all: only together (AND)
    "min_materiality": 50,  # filings: materiality score 0-100
    "categories": [],
    "enabled": {"volume": True, "price": True, "category": True},
}
VOLUME_MODES = ("high", "low", "either")
DIRECTIONS = ("up", "down", "either")
COMBINES = ("any", "all")


def get_rules(owner: str | None = None) -> dict:
    """Flattened view used by the UI (see DEFAULTS for the keys)."""
    owner = owner or current_owner()
    with session() as db:
        rows = db.execute(
            "SELECT kind, params_json, enabled FROM alert_rules WHERE owner_id=?", (owner,)
        ).fetchall()
    out = json.loads(json.dumps(DEFAULTS))
    if not rows:  # an account that never changed its rules gets the defaults
        from app.ingest.seed import DEFAULT_ALERT_RULES

        rows = [
            {"kind": k, "params_json": json.dumps(p), "enabled": 1} for k, p in DEFAULT_ALERT_RULES
        ]
    for r in rows:
        p = json.loads(r["params_json"])
        if r["kind"] in out["enabled"]:
            out["enabled"][r["kind"]] = bool(r["enabled"])
        if r["kind"] == "volume":
            out["volume_multiple"] = p.get("multiple", out["volume_multiple"])
            out["volume_low_multiple"] = p.get("low_multiple", out["volume_low_multiple"])
            out["volume_mode"] = p.get("mode", out["volume_mode"])
            out["volume_window"] = p.get("window", out["volume_window"])
        elif r["kind"] == "price":
            out["price_abs_pct"] = p.get("abs_pct", out["price_abs_pct"])
            out["price_direction"] = p.get("direction", out["price_direction"])
        elif r["kind"] == "category":
            out["categories"] = p.get("categories", [])
            out["min_materiality"] = p.get("min_materiality", out["min_materiality"])
        elif r["kind"] == "combine":
            out["combine"] = p.get("combine", out["combine"])
    return out


def set_rules(rules: dict, owner: str | None = None) -> dict:
    """Save rules; missing keys keep their current value."""
    owner = owner or current_owner()
    r = get_rules(owner) | {k: v for k, v in rules.items() if v is not None}
    if r["volume_mode"] not in VOLUME_MODES:
        raise ValueError(f"volume_mode must be one of {', '.join(VOLUME_MODES)}")
    if r["price_direction"] not in DIRECTIONS:
        raise ValueError(f"price_direction must be one of {', '.join(DIRECTIONS)}")
    if r["combine"] not in COMBINES:
        raise ValueError(f"combine must be one of {', '.join(COMBINES)}")
    params = {
        "volume": {
            "multiple": round(float(r["volume_multiple"]), 2),
            "low_multiple": round(float(r["volume_low_multiple"]), 2),
            "mode": r["volume_mode"],
            "window": int(r["volume_window"]),
        },
        "price": {
            "abs_pct": round(float(r["price_abs_pct"]), 2),
            "direction": r["price_direction"],
        },
        "category": {
            "categories": list(r["categories"]),
            "min_materiality": int(r["min_materiality"]),
        },
        "combine": {"combine": r["combine"]},
    }
    enabled = {**get_rules(owner)["enabled"], **(rules.get("enabled") or {})}
    with session() as db:
        db.execute("DELETE FROM alert_rules WHERE owner_id=?", (owner,))
        db.executemany(
            "INSERT INTO alert_rules (owner_id, kind, params_json, enabled) VALUES (?,?,?,?)",
            [(owner, k, json.dumps(v), int(enabled.get(k, True))) for k, v in params.items()],
        )
    return get_rules(owner)


# Close-to-close ratios a corporate action produces mechanically: a 1:n split, or a bonus
# of a new shares for every b held (price × b/(a+b)).
ADJUSTMENT_RATIOS = sorted(
    {1 / n for n in range(2, 11)} | {b / (a + b) for a in (1, 2, 3) for b in (1, 2, 3, 4, 5)}
)
ACTION_LOOKBACK_DAYS = 75  # an ex-date usually falls within weeks of the board approval


def _corporate_actions(symbols: list[str]) -> dict[str, list[date]]:
    """Dates of split / bonus filings per company, from the announcements feed."""
    if not symbols:
        return {}
    q = ",".join("?" * len(symbols))
    with session() as db:
        rows = db.execute(
            f"SELECT symbol, ts FROM announcements WHERE category='bonus_split' "
            f"AND symbol IN ({q})",
            symbols,
        ).fetchall()
    out: dict[str, list[date]] = {}
    for r in rows:
        out.setdefault(r["symbol"], []).append(datetime.fromisoformat(r["ts"]).date())
    return out


def is_adjustment_day(
    pct_change: float, day: date, actions: list[date], tolerance: float = 0.04
) -> bool:
    """PU-11: a move that is a split or bonus issue, not news. True only when the company
    filed a split or bonus in the lookback window *and* the price ratio matches a standard
    adjustment ratio, so a genuine 50% crash with no such filing still alerts. Yahoo
    back-adjusts history, but a same-day EOD feed is unadjusted, which is when this fires."""
    ratio = 1 + pct_change / 100
    recent = any(timedelta(0) <= day - d <= timedelta(ACTION_LOOKBACK_DAYS) for d in actions)
    return recent and any(abs(ratio / r - 1) <= tolerance for r in ADJUSTMENT_RATIOS)


def _signals(symbols: list[str] | None = None, window: int = 20) -> pd.DataFrame:
    with session() as db:
        df = pd.read_sql_query("SELECT * FROM prices", db)
    if symbols:
        df = df[df["symbol"].isin(symbols)]
    return with_signals(df, vol_window=window) if not df.empty else df


def _num(v: float) -> str:
    """Up to two decimals, no trailing zeros: 3.1, 0.45, 2."""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _volume_hit(m: float, rules: dict) -> str | None:
    """'high' or 'low' when the day's volume multiple meets the rule, else None."""
    mode = rules["volume_mode"]
    if mode in ("high", "either") and m >= rules["volume_multiple"]:
        return "high"
    if mode in ("low", "either") and m <= rules["volume_low_multiple"]:
        return "low"
    return None


def _price_hit(chg: float, rules: dict) -> bool:
    t = rules["price_abs_pct"]
    d = rules["price_direction"]
    return (d in ("up", "either") and chg >= t) or (d in ("down", "either") and chg <= -t)


def evaluate(start: datetime, end: datetime, rules: dict | None = None) -> list[dict]:
    """Alerts for the window. EOD alerts use trading days in the window, or the latest
    session before `end` if the window holds none (e.g. a weekend)."""
    rules = rules or get_rules()
    from app.portfolio.holdings import get_holdings

    portfolio = list(get_holdings())
    alerts: list[dict] = []

    sig = _signals(portfolio, int(rules.get("volume_window", 20)))
    on_vol, on_price = rules["enabled"].get("volume"), rules["enabled"].get("price")
    both = rules.get("combine") == "all" and on_vol and on_price
    if not sig.empty and (on_vol or on_price):
        days = sig[
            (sig["date"] >= start.date().isoformat()) & (sig["date"] <= end.date().isoformat())
        ]
        if days.empty:
            last = sig[sig["date"] <= end.date().isoformat()]["date"].max()
            days = sig[sig["date"] == last]
        actions = _corporate_actions(portfolio)
        for row in days.itertuples():
            if pd.notna(row.pct_change) and is_adjustment_day(
                float(row.pct_change),
                date.fromisoformat(row.date),
                actions.get(row.symbol, []),
            ):
                continue  # price and volume both move mechanically on an ex-date
            vol = _volume_hit(row.vol_multiple, rules) if pd.notna(row.vol_multiple) else None
            price = pd.notna(row.pct_change) and _price_hit(row.pct_change, rules)
            if both and not (vol and price):
                continue  # AND: only a day that meets both conditions
            if on_vol and vol:
                quiet = vol == "low"
                alerts.append(
                    {
                        "id": f"volume:{row.symbol}:{row.date}",
                        "kind": "volume",
                        "symbol": row.symbol,
                        "ts": f"{row.date}T15:30:00",
                        "reason": f"Volume {_num(row.vol_multiple)}× its "
                        f"{int(rules.get('volume_window', 20))}-day average"
                        + (", unusually quiet" if quiet else ""),
                        "value": round(float(row.vol_multiple), 2),
                        "low": quiet,
                        "price_change_pct": round(float(row.pct_change), 2)
                        if pd.notna(row.pct_change)
                        else None,
                    }
                )
            if on_price and price:
                alerts.append(
                    {
                        "id": f"price:{row.symbol}:{row.date}",
                        "kind": "price",
                        "symbol": row.symbol,
                        "ts": f"{row.date}T15:30:00",
                        "reason": f"{'Up' if row.pct_change > 0 else 'Down'} "
                        f"{abs(row.pct_change):.1f}% on the day",
                        "value": round(float(row.pct_change), 2),
                    }
                )

    if rules["enabled"].get("category") and rules["categories"] and portfolio:
        q = ",".join("?" * len(rules["categories"]))
        p = ",".join("?" * len(portfolio))
        with session() as db:
            rows = db.execute(
                f"""SELECT a.id, a.symbol, a.ts, a.category, a.summary, a.materiality
                    FROM announcements a
                    WHERE a.symbol IN ({p}) AND a.ts BETWEEN ? AND ?
                      AND a.category IN ({q}) AND a.materiality >= ?
                    ORDER BY a.materiality DESC""",
                (
                    *portfolio,
                    start.isoformat(),
                    end.isoformat(),
                    *rules["categories"],
                    int(rules.get("min_materiality", 50)),
                ),
            ).fetchall()
        for r in rows:
            alerts.append(
                {
                    "id": f"category:{r['id']}",
                    "kind": "category",
                    "symbol": r["symbol"],
                    "ts": r["ts"],
                    "reason": f"Material {r['category'].replace('_', ' ')} filing",
                    "value": r["materiality"],
                    "announcement_id": r["id"],
                    "title": r["summary"],
                }
            )
    return sorted(alerts, key=lambda a: a["ts"], reverse=True)


def run_and_store(start: datetime, end: datetime) -> int:
    """Idempotent: deterministic ids mean re-runs never duplicate (FR-ALERT-06)."""
    alerts = evaluate(start, end)
    with session() as db:
        db.executemany(
            "INSERT OR IGNORE INTO alerts (id, rule_id, symbol, ts, reason, payload_json) "
            "VALUES (?,?,?,?,?,?)",
            [(a["id"], None, a["symbol"], a["ts"], a["reason"], json.dumps(a)) for a in alerts],
        )
    return len(alerts)
