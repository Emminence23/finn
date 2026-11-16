"""Per-account holdings (edit your portfolio).

Every account starts on the demo universe's weights. The first edit copies them into the
`holdings` table for that account, and from then on Today, alerts and the portfolio page
read the account's own list. Reset deletes the rows, which restores the default. Only
companies FINN has data for can be added (in fixture mode, the 21 in the demo universe).
"""

from __future__ import annotations

from app.db import session
from app.network.owner import current_owner

MIN_WEIGHT = 0.005
NEW_WEIGHT = 0.03  # a new holding comes in at 3%; the rest scale down to make room


def _default(db) -> dict[str, float]:
    return {
        r["symbol"]: float(r["weight"] or 0)
        for r in db.execute("SELECT symbol, weight FROM companies WHERE in_portfolio=1")
    }


def is_custom(owner: str | None = None) -> bool:
    with session() as db:
        return bool(
            db.execute(
                "SELECT 1 FROM holdings WHERE owner_id=? LIMIT 1", (owner or current_owner(),)
            ).fetchone()
        )


def get_holdings(owner: str | None = None) -> dict[str, float]:
    """{symbol: weight}, weights summing to 1."""
    owner = owner or current_owner()
    with session() as db:
        rows = {
            r["symbol"]: float(r["weight"])
            for r in db.execute("SELECT symbol, weight FROM holdings WHERE owner_id=?", (owner,))
        }
        w = rows or _default(db)
    total = sum(w.values()) or 1.0
    return {s: v / total for s, v in sorted(w.items(), key=lambda kv: -kv[1])}


def _known(db) -> set[str]:
    return {r[0] for r in db.execute("SELECT symbol FROM companies")}


def set_holdings(weights: dict[str, float]) -> dict[str, float]:
    """Replace the account's holdings. Weights may be in any scale; they are normalised."""
    w = {s.upper(): float(v) for s, v in weights.items() if v and float(v) > 0}
    if not w:
        raise ValueError("a portfolio needs at least one holding")
    with session() as db:
        unknown = sorted(set(w) - _known(db))
        if unknown:
            raise KeyError(f"no data for {', '.join(unknown)}")
        total = sum(w.values())
        w = {s: v / total for s, v in w.items()}
        if min(w.values()) < MIN_WEIGHT:
            raise ValueError("each holding needs at least 0.5%")
        owner = current_owner()
        db.execute("DELETE FROM holdings WHERE owner_id=?", (owner,))
        db.executemany(
            "INSERT INTO holdings (owner_id, symbol, weight) VALUES (?,?,?)",
            [(owner, s, v) for s, v in w.items()],
        )
    return get_holdings()


def add_holding(symbol: str, weight: float = NEW_WEIGHT) -> dict[str, float]:
    cur = get_holdings()
    symbol = symbol.upper()
    if symbol in cur:
        return cur
    if not 0 < weight < 1:
        raise ValueError("weight must be between 0 and 100%")
    scaled = {s: v * (1 - weight) for s, v in cur.items()}
    return set_holdings({**scaled, symbol: weight})


def remove_holding(symbol: str) -> dict[str, float]:
    cur = get_holdings()
    symbol = symbol.upper()
    if symbol not in cur:
        raise KeyError(f"{symbol} is not held")
    rest = {s: v for s, v in cur.items() if s != symbol}
    return set_holdings(rest)


def reset_holdings() -> dict[str, float]:
    with session() as db:
        db.execute("DELETE FROM holdings WHERE owner_id=?", (current_owner(),))
    return get_holdings()


def candidates() -> list[dict]:
    """Companies that can be added: known to FINN and not held."""
    held = get_holdings()
    with session() as db:
        return [
            {"symbol": r["symbol"], "name": r["name"], "sector": r["sector"]}
            for r in db.execute("SELECT symbol, name, sector FROM companies ORDER BY symbol")
            if r["symbol"] not in held
        ]
