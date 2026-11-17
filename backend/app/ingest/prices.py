"""EOD prices from Yahoo Finance (yfinance). NSE tickers use the .NS suffix."""

from __future__ import annotations

import logging
import os
import threading
import time

import pandas as pd

log = logging.getLogger(__name__)

# Companies outside FINN's universe get prices on first need (a brokerage view on LIC needs
# its close); the live refresh then keeps them current with the rest.
_extra: set[str] = set()
_missed: dict[str, float] = {}  # symbol -> when Yahoo had nothing, so we don't ask every call
_lock = threading.Lock()
MISS_WAIT_S = 6 * 3600


def extra_symbols() -> list[str]:
    with _lock:
        return sorted(_extra)


def ensure(symbol: str) -> bool:
    """True when the database holds prices for `symbol`; fetches a year of them if not."""
    from app.db import session

    symbol = symbol.upper()
    with session() as db:
        if db.execute("SELECT 1 FROM prices WHERE symbol=? LIMIT 1", (symbol,)).fetchone():
            return True
    if os.environ.get("FINN_WEB_SEARCH", "1") == "0":  # tests: no outside calls
        return False
    with _lock:
        if time.time() - _missed.get(symbol, 0) < MISS_WAIT_S:
            return False
    try:
        df = fetch_prices([symbol], period="1y")
    except Exception as e:  # noqa: BLE001 - no price is shown as no price
        log.warning("prices for %s: %s", symbol, e)
        with _lock:
            _missed[symbol] = time.time()
        return False
    rows = df[["symbol", "date", "open", "high", "low", "close", "volume"]].values.tolist()
    with session() as db:
        db.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)", rows)
    with _lock:
        _extra.add(symbol)
    log.info("prices for %s fetched on demand: %d days", symbol, len(rows))
    return True


def fetch_prices(symbols: list[str], period: str = "6mo") -> pd.DataFrame:
    """Return long-format rows: symbol, date, open, high, low, close, volume."""
    import yfinance as yf

    raw = yf.download(
        [f"{s}.NS" for s in symbols],
        period=period,
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    frames = []
    for s in symbols:
        key = f"{s}.NS"
        if key not in raw.columns.get_level_values(0):
            log.warning("no price data for %s", s)
            continue
        df = raw[key].dropna(subset=["Close"]).reset_index()
        df.columns = [str(c).lower() for c in df.columns]
        df["symbol"] = s
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        frames.append(df[["symbol", "date", "open", "high", "low", "close", "volume"]])
    out = pd.concat(frames, ignore_index=True)
    out[["open", "high", "low", "close"]] = out[["open", "high", "low", "close"]].round(2)
    out["volume"] = out["volume"].astype("int64")
    return out


def with_signals(df: pd.DataFrame, vol_window: int = 20) -> pd.DataFrame:
    """Add pct_change, 20-day average volume (excluding today) and volume multiple."""
    df = df.sort_values(["symbol", "date"]).copy()
    g = df.groupby("symbol", group_keys=False)
    df["pct_change"] = g["close"].pct_change() * 100
    df["vol_avg"] = g["volume"].transform(
        lambda v: v.shift(1).rolling(vol_window, min_periods=vol_window // 2).mean()
    )
    df["vol_multiple"] = df["volume"] / df["vol_avg"]
    return df
