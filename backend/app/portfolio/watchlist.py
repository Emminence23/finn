"""Companies an account follows without holding them, and the day's movers.

Like holdings, an account sees the demo list until its first edit; from then on its own
rows (even an empty list) are what it sees. Everything here is arithmetic on end-of-day
closes and stored filings; no AI.
"""

from __future__ import annotations

from datetime import timedelta

from app.clock import now
from app.db import session
from app.intel.taxonomy import folds_as_routine
from app.network.owner import current_owner
from app.portfolio.holdings import get_positions, last_two_closes

DEMO = ("PERSISTENT", "MANAPPURAM", "AARTIIND")
SPARK_DAYS = 30
MAX_ITEMS = 50


def _priced(db) -> set[str]:
    return {r[0] for r in db.execute("SELECT DISTINCT symbol FROM prices")}


def symbols(owner: str | None = None) -> list[str]:
    owner = owner or current_owner()
    with session() as db:
        if db.execute("SELECT 1 FROM watchlist_owners WHERE owner_id=?", (owner,)).fetchone():
            return [
                r[0]
                for r in db.execute(
                    "SELECT symbol FROM watchlist WHERE owner_id=? ORDER BY added_at, symbol",
                    (owner,),
                )
            ]
    return list(DEMO)


def _write(owner: str, syms: list[str]) -> None:
    stamp = now()
    with session() as db:
        db.execute("INSERT OR IGNORE INTO watchlist_owners VALUES (?)", (owner,))
        db.execute("DELETE FROM watchlist WHERE owner_id=?", (owner,))
        db.executemany(
            "INSERT INTO watchlist VALUES (?,?,?)",
            [(owner, s, (stamp + timedelta(seconds=i)).isoformat()) for i, s in enumerate(syms)],
        )


def add(symbol: str) -> list[str]:
    symbol = symbol.strip().upper()
    with session() as db:
        if not db.execute("SELECT 1 FROM companies WHERE symbol=?", (symbol,)).fetchone():
            raise KeyError(f"no company {symbol}")
        if symbol not in _priced(db):
            raise ValueError(f"FINN has no prices for {symbol} in this snapshot")
    cur = symbols()
    if symbol in cur:
        return cur
    if len(cur) >= MAX_ITEMS:
        raise ValueError(f"a watchlist holds up to {MAX_ITEMS} companies")
    _write(current_owner(), [*cur, symbol])
    return symbols()


def remove(symbol: str) -> list[str]:
    symbol = symbol.strip().upper()
    _write(current_owner(), [s for s in symbols() if s != symbol])
    return symbols()


def reset() -> list[str]:
    owner = current_owner()
    with session() as db:
        db.execute("DELETE FROM watchlist WHERE owner_id=?", (owner,))
        db.execute("DELETE FROM watchlist_owners WHERE owner_id=?", (owner,))
    return symbols()


def _spark(db, symbol: str) -> list[float]:
    rows = db.execute(
        "SELECT close FROM prices WHERE symbol=? ORDER BY date DESC LIMIT ?", (symbol, SPARK_DAYS)
    ).fetchall()
    return [float(r[0]) for r in reversed(rows)]


def items(owner: str | None = None) -> dict:
    """Each followed company: price, day move, a month of closes, and its latest filing."""
    syms = symbols(owner)
    two = last_two_closes(syms)
    week_ago = (now() - timedelta(days=7)).replace(tzinfo=None).isoformat(timespec="seconds")
    held = {p["symbol"] for p in get_positions(owner)["positions"]}
    out = []
    with session() as db:
        names = {
            r["symbol"]: r["name"]
            for r in db.execute(
                f"SELECT symbol, name FROM companies WHERE symbol IN ({','.join('?' * len(syms))})",
                syms,
            )
        }
        for s in syms:
            prev, last, _ = two.get(s, (None, None, None))
            # the latest filing Today wouldn't set aside as routine
            latest = next(
                (
                    r
                    for r in db.execute(
                        """SELECT ts, summary, subject, category, materiality, exch_category
                           FROM announcements WHERE symbol=? ORDER BY ts DESC LIMIT 40""",
                        (s,),
                    )
                    if not folds_as_routine(
                        r["category"],
                        r["materiality"],
                        r["exch_category"] or "",
                        r["subject"] or "",
                    )
                ),
                None,
            )
            week = db.execute(
                "SELECT COUNT(*) FROM announcements WHERE symbol=? AND ts>=?", (s, week_ago)
            ).fetchone()[0]
            out.append(
                {
                    "symbol": s,
                    "name": names.get(s, s),
                    "held": s in held,
                    "price": last,
                    "day_change": (last - prev) if last is not None else None,
                    "day_pct": (last / prev - 1) * 100 if last is not None and prev else None,
                    "spark": _spark(db, s),
                    "filings_7d": week,
                    "latest_filing": (
                        {
                            "ts": latest["ts"],
                            "text": latest["summary"] or latest["subject"] or "",
                            "category": latest["category"],
                        }
                        if latest
                        else None
                    ),
                }
            )
    with session() as db:
        custom = bool(
            db.execute(
                "SELECT 1 FROM watchlist_owners WHERE owner_id=?", (owner or current_owner(),)
            ).fetchone()
        )
        addable = [
            {"symbol": r["symbol"], "name": r["name"], "held": r["symbol"] in held}
            for r in db.execute(
                "SELECT symbol, name FROM companies WHERE symbol IN "
                "(SELECT DISTINCT symbol FROM prices) ORDER BY symbol"
            )
            if r["symbol"] not in syms
        ]
    return {
        "items": out,
        "custom": custom,
        "as_of": max((v[2] for v in two.values()), default=None),
        "addable": addable,
    }


def movers(limit: int = 3) -> dict:
    """The day's biggest rises and falls across holdings and the watchlist, by % move."""
    pos = get_positions()
    rows = {
        p["symbol"]: {
            "symbol": p["symbol"],
            "name": p["name"],
            "price": p["price"],
            "day_pct": p["day_pct"],
            "day_change": p["price"] - p["prev_price"],
            "held": True,
        }
        for p in pos["positions"]
    }
    for w in items()["items"]:
        if w["symbol"] not in rows and w["day_pct"] is not None:
            rows[w["symbol"]] = {
                k: w[k] for k in ("symbol", "name", "price", "day_pct", "day_change")
            } | {"held": False}
    ranked = sorted(rows.values(), key=lambda r: -r["day_pct"])
    up = [r for r in ranked if r["day_pct"] > 0][:limit]
    down = [r for r in reversed(ranked) if r["day_pct"] < 0][:limit]
    return {"as_of": pos["as_of"], "gainers": up, "losers": down, "count": len(rows)}
