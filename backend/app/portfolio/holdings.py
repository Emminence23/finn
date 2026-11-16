"""Per-account positions: shares held and the average price paid.

The demo portfolio is seeded as positions under the owner `__demo__` (dummy share counts,
bought at the closing prices on the universe's `bought_on` date). An account reads the
demo's positions until its first edit, which copies them into its own rows; reset deletes
those rows again. Weights are never stored: they are each position's market value at the
latest close, divided by the total, so they move with prices like a real portfolio.

Changing a quantity is plain bookkeeping. Buying more blends the new shares into the
average cost at today's price; selling some leaves the average cost unchanged.
"""

from __future__ import annotations

from app.db import session
from app.network.owner import current_owner

DEMO_OWNER = "__demo__"
MIN_WEIGHT = 0.005
NEW_WEIGHT = 0.03  # "add" buys a position worth about 3% of the portfolio


def latest_prices(symbols: list[str] | None = None) -> dict[str, float]:
    """Latest close per symbol."""
    with session() as db:
        rows = db.execute(
            """SELECT p.symbol, p.close FROM prices p
               JOIN (SELECT symbol, MAX(date) d FROM prices GROUP BY symbol) m
                 ON p.symbol = m.symbol AND p.date = m.d"""
        ).fetchall()
    px = {r["symbol"]: float(r["close"]) for r in rows}
    return {s: px[s] for s in symbols if s in px} if symbols is not None else px


def _rows(db, owner: str) -> dict[str, tuple[float, float]]:
    return {
        r["symbol"]: (float(r["qty"]), float(r["avg_cost"]))
        for r in db.execute("SELECT symbol, qty, avg_cost FROM holdings WHERE owner_id=?", (owner,))
    }


def _raw(owner: str | None = None) -> dict[str, tuple[float, float]]:
    owner = owner or current_owner()
    with session() as db:
        rows = _rows(db, owner) or _rows(db, DEMO_OWNER)
        if rows:
            return rows
        # no seeded positions (a bare database): the portfolio flag and weights, valued at
        # an arbitrary 10 lakh so weights come out right
        flagged = {
            r["symbol"]: float(r["weight"] or 1)
            for r in db.execute("SELECT symbol, weight FROM companies WHERE in_portfolio=1")
        }
    px = latest_prices(list(flagged))
    total = sum(flagged.values()) or 1.0
    return {
        s: (w / total * 1e6 / px[s], px[s]) if s in px else (1.0, 1.0) for s, w in flagged.items()
    }


def is_custom(owner: str | None = None) -> bool:
    with session() as db:
        return bool(
            db.execute(
                "SELECT 1 FROM holdings WHERE owner_id=? LIMIT 1", (owner or current_owner(),)
            ).fetchone()
        )


def get_positions(owner: str | None = None) -> dict:
    """Positions with price, value, cost and weight, largest first, plus the totals."""
    raw = _raw(owner)
    px = latest_prices(list(raw))
    with session() as db:
        names = {r["symbol"]: r["name"] for r in db.execute("SELECT symbol, name FROM companies")}
    rows = []
    for s, (qty, cost) in raw.items():
        price = px.get(s, cost)
        rows.append(
            {
                "symbol": s,
                "name": names.get(s, s),
                "qty": qty,
                "avg_cost": round(cost, 2),
                "price": price,
                "value": qty * price,
                "invested": qty * cost,
            }
        )
    value = sum(r["value"] for r in rows) or 1.0
    invested = sum(r["invested"] for r in rows)
    for r in rows:
        r["weight"] = r["value"] / value
        r["gain_pct"] = (r["price"] / r["avg_cost"] - 1) * 100 if r["avg_cost"] else 0.0
    rows.sort(key=lambda r: -r["value"])
    return {
        "positions": rows,
        "value": value,
        "invested": invested,
        "gain": value - invested,
        "gain_pct": (value / invested - 1) * 100 if invested else 0.0,
    }


def get_holdings(owner: str | None = None) -> dict[str, float]:
    """{symbol: weight} by market value, weights summing to 1, largest first."""
    return {p["symbol"]: p["weight"] for p in get_positions(owner)["positions"]}


def _known(db) -> set[str]:
    return {r[0] for r in db.execute("SELECT symbol FROM companies")}


def set_positions(qty: dict[str, float]) -> dict[str, float]:
    """Replace the account's positions with these share counts (whole shares)."""
    want = {s.upper(): round(float(v)) for s, v in qty.items() if v and round(float(v)) > 0}
    if not want:
        raise ValueError("a portfolio needs at least one holding")
    old = _raw()
    px = latest_prices(list(want))
    with session() as db:
        unknown = sorted(set(want) - _known(db))
        if unknown:
            raise KeyError(f"no data for {', '.join(unknown)}")
        missing = sorted(s for s in want if s not in px)
        if missing:
            raise KeyError(f"no price for {', '.join(missing)}")
        rows = []
        for s, q in want.items():
            q0, c0 = old.get(s, (0.0, px[s]))
            cost = (
                c0 if q <= q0 else (q0 * c0 + (q - q0) * px[s]) / q
            )  # buys blend in at today's price
            rows.append((s, q, cost))
        owner = current_owner()
        db.execute("DELETE FROM holdings WHERE owner_id=?", (owner,))
        db.executemany(
            "INSERT INTO holdings (owner_id, symbol, qty, avg_cost) VALUES (?,?,?,?)",
            [(owner, s, q, c) for s, q, c in rows],
        )
    return get_holdings()


def set_holdings(weights: dict[str, float]) -> dict[str, float]:
    """Re-weight to these proportions (any scale) at today's prices, keeping the total value:
    share counts are rounded to whole shares, so weights land within a share of the target."""
    w = {s.upper(): float(v) for s, v in weights.items() if v and float(v) > 0}
    if not w:
        raise ValueError("a portfolio needs at least one holding")
    total_w = sum(w.values())
    if min(w.values()) / total_w < MIN_WEIGHT:
        raise ValueError("each holding needs at least 0.5%")
    value = get_positions()["value"]
    px = latest_prices(list(w))
    missing = sorted(set(w) - set(px))
    if missing:
        raise KeyError(f"no data for {', '.join(missing)}")
    return set_positions({s: max(1, round(v / total_w * value / px[s])) for s, v in w.items()})


def add_holding(symbol: str, weight: float = NEW_WEIGHT) -> dict[str, float]:
    """Buy a new position worth `weight` of the portfolio's current value."""
    symbol = symbol.upper()
    raw = _raw()
    if symbol in raw:
        return get_holdings()
    if not 0 < weight < 1:
        raise ValueError("weight must be between 0 and 100%")
    px = latest_prices([symbol])
    if symbol not in px:
        raise KeyError(f"no data for {symbol}")
    value = get_positions()["value"]
    q = max(1, round(weight * value / px[symbol]))
    return set_positions({**{s: v[0] for s, v in raw.items()}, symbol: q})


def remove_holding(symbol: str) -> dict[str, float]:
    raw = _raw()
    symbol = symbol.upper()
    if symbol not in raw:
        raise KeyError(f"{symbol} is not held")
    return set_positions({s: v[0] for s, v in raw.items() if s != symbol})


def reset_holdings() -> dict[str, float]:
    with session() as db:
        db.execute("DELETE FROM holdings WHERE owner_id=?", (current_owner(),))
    return get_holdings()


def candidates() -> list[dict]:
    """Companies that can be added: known to FINN, priced, and not held."""
    held = _raw()
    px = latest_prices()
    with session() as db:
        return [
            {
                "symbol": r["symbol"],
                "name": r["name"],
                "sector": r["sector"],
                "price": px[r["symbol"]],
            }
            for r in db.execute("SELECT symbol, name, sector FROM companies ORDER BY symbol")
            if r["symbol"] not in held and r["symbol"] in px
        ]
