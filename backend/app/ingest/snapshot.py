"""Fetch live data and freeze it into committed fixtures (NFR-02: the demo never depends on
live scraping).

    uv run python -m app.ingest.snapshot all            # everything below
    uv run python -m app.ingest.snapshot prices|announcements|fundamentals|symbols
    uv run python -m app.ingest.snapshot docs           # PDFs for the research set (cache only)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sys

from app.config import get_settings
from app.http import get_fetcher
from app.ingest.announcements import fetch_universe_announcements
from app.ingest.fundamentals import NotCovered, fetch_fundamentals
from app.ingest.prices import fetch_prices
from app.ingest.universe import all_symbols, fixtures_dir, portfolio_symbols, research_symbols

log = logging.getLogger("snapshot")
SYMBOLS_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"


def snap_prices() -> None:
    df = fetch_prices(all_symbols(), period="1y")
    df.to_csv(fixtures_dir() / "prices.csv", index=False)
    log.info("prices: %d rows, %d symbols", len(df), df["symbol"].nunique())
    import yfinance as yf

    n = yf.download("^NSEI", period="1y", interval="1d", auto_adjust=True, progress=False)
    closes = n["Close"].iloc[:, 0] if n["Close"].ndim > 1 else n["Close"]
    out = closes.round(2).rename("close").rename_axis("date").reset_index()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(fixtures_dir() / "benchmark_nifty50.csv", index=False)


def snap_announcements(days: int = 60) -> None:
    """New filings merged into the stored ones within the window. A run where NSE answered
    nothing (blocked, down) leaves the file as it was rather than emptying the demo."""
    from datetime import date, timedelta

    rows = fetch_universe_announcements(all_symbols(), days=days)
    path = fixtures_dir() / "announcements.json"
    if not rows:
        log.error("announcements: NSE returned nothing; keeping %s unchanged", path.name)
        return
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    old = json.loads(path.read_text()) if path.exists() else []
    merged = {a["id"]: a for a in old if a["ts"][:10] >= cutoff} | {a["id"]: a for a in rows}
    out = sorted(merged.values(), key=lambda a: a["ts"], reverse=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    log.info("announcements: %d fetched, %d kept -> %s", len(rows), len(out), path)


def snap_fundamentals() -> None:
    out = fixtures_dir() / "fundamentals"
    out.mkdir(exist_ok=True)
    for s in all_symbols():
        try:
            data = fetch_fundamentals(s)
        except NotCovered as e:
            log.error("%s", e)
            continue
        (out / f"{s}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
        log.info("fundamentals %s: %s, %d docs", s, data["basis"], len(data["documents"]))


def snap_symbols() -> None:
    text = get_fetcher().get_text(SYMBOLS_URL)
    reader = csv.DictReader(io.StringIO(text))
    rows = [
        {
            "symbol": r["SYMBOL"].strip(),
            "name": r["NAME OF COMPANY"].strip(),
            "isin": r[" ISIN NUMBER"].strip() if " ISIN NUMBER" in r else r.get("ISIN NUMBER", ""),
        }
        for r in reader
        if r.get(" SERIES", r.get("SERIES", "")).strip() in ("EQ", "BE")
    ]
    with (fixtures_dir() / "symbols.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["symbol", "name", "isin"])
        w.writeheader()
        w.writerows(rows)
    log.info("symbols: %d", len(rows))


def snap_docs(n_transcripts: int = 4) -> None:
    """Download the latest AR + last N transcripts for the research set into cache/docs/."""
    f = get_fetcher()
    root = get_settings().cache_dir / "docs"
    for s in research_symbols():
        path = fixtures_dir() / "fundamentals" / f"{s}.json"
        if not path.exists():
            log.error("no fundamentals fixture for %s; run `snapshot fundamentals` first", s)
            continue
        docs = json.loads(path.read_text())["documents"]
        wanted = [d for d in docs if d["kind"] == "annual_report"][:1]
        wanted += [d for d in docs if d["kind"] == "transcript"][:n_transcripts]
        for d in wanted:
            dest = root / s / f"{d['kind']}_{d['period']}.pdf"
            try:
                f.download(d["url"], dest)
                log.info(
                    "doc %s %s %s (%d KB)", s, d["kind"], d["period"], dest.stat().st_size // 1024
                )
            except Exception as e:
                log.error("doc %s %s failed: %s", s, d["url"], e)


STEPS = {
    "symbols": snap_symbols,
    "prices": snap_prices,
    "announcements": snap_announcements,
    "fundamentals": snap_fundamentals,
    "docs": snap_docs,
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    steps = list(STEPS) if step == "all" else [step]
    for s in steps:
        if s not in STEPS:
            sys.exit(__doc__)
        log.info(
            "== %s (portfolio=%d, research=%d)",
            s,
            len(portfolio_symbols()),
            len(research_symbols()),
        )
        STEPS[s]()


if __name__ == "__main__":
    main()
