"""EOD prices from Yahoo Finance (yfinance). NSE tickers use the .NS suffix."""

from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)


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
