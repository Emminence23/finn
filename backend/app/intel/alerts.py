"""Configurable alerts (FR-ALERT): unusual EOD volume/price moves and material filings."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from app.db import session
from app.ingest.prices import with_signals

OWNER = "demo"


def get_rules(owner: str = OWNER) -> dict:
    """Flattened view used by the UI: {volume_multiple, price_abs_pct, categories, enabled}."""
    with session() as db:
        rows = db.execute(
            "SELECT kind, params_json, enabled FROM alert_rules WHERE owner_id=?", (owner,)
        ).fetchall()
    out = {
        "volume_multiple": 2.0,
        "price_abs_pct": 5.0,
        "categories": [],
        "enabled": {"volume": True, "price": True, "category": True},
    }
    for r in rows:
        p = json.loads(r["params_json"])
        out["enabled"][r["kind"]] = bool(r["enabled"])
        if r["kind"] == "volume":
            out["volume_multiple"] = p["multiple"]
        elif r["kind"] == "price":
            out["price_abs_pct"] = p["abs_pct"]
        elif r["kind"] == "category":
            out["categories"] = p["categories"]
    return out


def set_rules(rules: dict, owner: str = OWNER) -> dict:
    params = {
        "volume": {"multiple": float(rules["volume_multiple"])},
        "price": {"abs_pct": float(rules["price_abs_pct"])},
        "category": {"categories": list(rules["categories"])},
    }
    enabled = rules.get("enabled", {})
    with session() as db:
        db.execute("DELETE FROM alert_rules WHERE owner_id=?", (owner,))
        db.executemany(
            "INSERT INTO alert_rules (owner_id, kind, params_json, enabled) VALUES (?,?,?,?)",
            [(owner, k, json.dumps(v), int(enabled.get(k, True))) for k, v in params.items()],
        )
    return get_rules(owner)


def _signals(symbols: list[str] | None = None) -> pd.DataFrame:
    with session() as db:
        df = pd.read_sql_query("SELECT * FROM prices", db)
    if symbols:
        df = df[df["symbol"].isin(symbols)]
    return with_signals(df) if not df.empty else df


def evaluate(start: datetime, end: datetime, rules: dict | None = None) -> list[dict]:
    """Alerts for the window. EOD alerts use trading days in the window, or the latest
    session before `end` if the window holds none (e.g. a weekend)."""
    rules = rules or get_rules()
    with session() as db:
        portfolio = [r[0] for r in db.execute("SELECT symbol FROM companies WHERE in_portfolio=1")]
    alerts: list[dict] = []

    sig = _signals(portfolio)
    if not sig.empty:
        days = sig[
            (sig["date"] >= start.date().isoformat()) & (sig["date"] <= end.date().isoformat())
        ]
        if days.empty:
            last = sig[sig["date"] <= end.date().isoformat()]["date"].max()
            days = sig[sig["date"] == last]
        for row in days.itertuples():
            if (
                rules["enabled"].get("volume")
                and pd.notna(row.vol_multiple)
                and row.vol_multiple >= rules["volume_multiple"]
            ):
                alerts.append(
                    {
                        "id": f"volume:{row.symbol}:{row.date}",
                        "kind": "volume",
                        "symbol": row.symbol,
                        "ts": f"{row.date}T15:30:00",
                        "reason": f"Volume {row.vol_multiple:.1f}× its 20-day average",
                        "value": round(float(row.vol_multiple), 2),
                        "price_change_pct": round(float(row.pct_change), 2)
                        if pd.notna(row.pct_change)
                        else None,
                    }
                )
            if (
                rules["enabled"].get("price")
                and pd.notna(row.pct_change)
                and abs(row.pct_change) >= rules["price_abs_pct"]
            ):
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

    if rules["enabled"].get("category") and rules["categories"]:
        q = ",".join("?" * len(rules["categories"]))
        with session() as db:
            rows = db.execute(
                f"""SELECT a.id, a.symbol, a.ts, a.category, a.summary, a.materiality
                    FROM announcements a JOIN companies c ON c.symbol = a.symbol
                    WHERE c.in_portfolio = 1 AND a.ts BETWEEN ? AND ?
                      AND a.category IN ({q}) AND a.materiality >= 50
                    ORDER BY a.materiality DESC""",
                (start.isoformat(), end.isoformat(), *rules["categories"]),
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
