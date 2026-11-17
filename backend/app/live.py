"""Live refresh inside the API: new NSE filings and prices every half hour (every 15 minutes
while the market is open, with today's price as it trades and hourly bars), so the
Today page is current without waiting for the morning job (which still commits fixtures).

Each run:
  1. fetches the last 3 days of filings for every tracked company and adds the new ones;
  2. fetches the last few days' prices (today's row is the latest trade while NSE is open)
     and today's hourly bars, plus the Nifty;
  3. runs the enrichment pipeline, which reads only filings it hasn't seen (rules first, the
     free model triages the rest in one batch, results cards from screener when it has them);
  4. saves what it added to the Key Value store, so a redeploy or restart starts from it
     instead of paying the model again for the same filings.

A source that fails (NSE blocks some cloud IPs, Yahoo hiccups) is logged and skipped; the
stored data stays. Set FINN_LIVE_REFRESH=0 to turn it off (tests, offline demos).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import store
from app.db import session

log = logging.getLogger("live")
IST = ZoneInfo("Asia/Kolkata")
SNAPSHOT_KEY = "live:snapshot"
SNAPSHOT_TTL = 4 * 24 * 3600
EVERY_S = 30 * 60
MARKET_EVERY_S = 15 * 60  # while NSE is open, prices are checked every quarter hour
MARKET_OPEN, MARKET_CLOSE = (9, 15), (15, 30)

_lock = threading.Lock()
_state: dict = {
    "last_ok": None,
    "last_try": None,
    "running": False,
    "error": None,
    "added": 0,
    "prices_at": None,
}


def ist_now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def last_refresh() -> datetime | None:
    v = _state["last_ok"]
    return datetime.fromisoformat(v) if v else None


def status() -> dict:
    return dict(_state) | {"market_open": market_open()}


def market_open(at: datetime | None = None) -> bool:
    at = at or ist_now()
    return at.weekday() < 5 and MARKET_OPEN <= (at.hour, at.minute) < MARKET_CLOSE


def interval_s() -> int:
    return MARKET_EVERY_S if market_open() else EVERY_S


def enabled() -> bool:
    return os.getenv("FINN_LIVE_REFRESH", "1") != "0"


# -- writes into the live DB -------------------------------------------------------------
def _add_announcements(rows: list[dict]) -> int:
    with session() as db:
        before = db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
        db.executemany(
            "INSERT OR IGNORE INTO announcements (id, symbol, ts, exch_category, subject, "
            "pdf_url, raw_json) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    a["id"],
                    a["symbol"],
                    a["ts"],
                    a["exch_category"],
                    a["subject"],
                    a["pdf_url"],
                    json.dumps(a, ensure_ascii=False),
                )
                for a in rows
            ],
        )
        return db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] - before


def _put_prices(prices: list[list], bench: list[list]) -> None:
    with session() as db:
        db.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)", prices)
        db.executemany("INSERT OR REPLACE INTO benchmark VALUES ('NIFTY 50', ?, ?)", bench)


def _put_intraday(bars: list[list]) -> None:
    """Today's hourly prices (symbol, IST time, close); older days are dropped."""
    today = ist_now().date().isoformat()
    with session() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS intraday (symbol TEXT NOT NULL, ts TEXT NOT NULL, "
            "close REAL NOT NULL, PRIMARY KEY (symbol, ts))"
        )
        db.execute("DELETE FROM intraday WHERE ts < ?", (today,))
        db.executemany("INSERT OR REPLACE INTO intraday VALUES (?,?,?)", bars)


def intraday(symbol: str) -> list[dict]:
    try:
        with session() as db:
            rows = db.execute(
                "SELECT ts, close FROM intraday WHERE symbol=? ORDER BY ts", (symbol,)
            ).fetchall()
    except Exception:  # noqa: BLE001 - no table before the first refresh
        return []
    return [dict(r) for r in rows]


# -- sources ------------------------------------------------------------------------------
def _fetch_filings() -> list[dict]:
    """The last 3 days for every tracked company, by India's date (the server runs on UTC,
    which is still yesterday until 05:30 IST). NSE's bot check often refuses the first
    requests of a session with a 403, so refused companies are asked again, twice."""
    from app.http import get_fetcher
    from app.ingest.announcements import fetch_announcements
    from app.ingest.universe import all_symbols

    end = ist_now().date()
    start = end - timedelta(days=3)
    seen: dict[str, dict] = {}
    todo = list(all_symbols())
    for attempt in range(3):
        failed = []
        for s in todo:
            try:
                for a in fetch_announcements(s, start, end):
                    seen[a["id"]] = a
            except Exception as e:  # noqa: BLE001
                failed.append(s)
                log.info("filings %s refused (try %d): %s", s, attempt + 1, type(e).__name__)
        if not failed:
            break
        todo = failed
        f = get_fetcher()
        f._nse_primed = False  # fresh cookies before the next pass
        time.sleep(5 * (attempt + 1))
    else:
        log.warning("filings: NSE still refused %s", ", ".join(todo))
    return sorted(seen.values(), key=lambda a: a["ts"], reverse=True)


def _fetch_prices() -> tuple[list[list], list[list]]:
    import yfinance as yf

    from app.ingest.prices import fetch_prices
    from app.ingest.universe import all_symbols

    df = fetch_prices(all_symbols(), period="5d")
    prices = df[["symbol", "date", "open", "high", "low", "close", "volume"]].values.tolist()
    n = yf.download("^NSEI", period="5d", interval="1d", auto_adjust=True, progress=False)
    closes = n["Close"].iloc[:, 0] if n["Close"].ndim > 1 else n["Close"]
    bench = [[d.strftime("%Y-%m-%d"), round(float(c), 2)] for d, c in closes.dropna().items()]
    return prices, bench


def _fetch_hourly() -> list[list]:
    """Hourly bars for today. Today's daily row (above) already carries the latest price;
    these give the shape of the day."""
    import yfinance as yf

    from app.ingest.universe import all_symbols

    syms = all_symbols()
    raw = yf.download(
        [f"{s}.NS" for s in syms],
        period="1d",
        interval="60m",
        group_by="ticker",
        progress=False,
        threads=True,
    )
    out = []
    for s in syms:
        key = f"{s}.NS"
        if key not in raw.columns.get_level_values(0):
            continue
        for ts, c in raw[key]["Close"].dropna().items():
            t = ts.tz_convert(IST) if ts.tzinfo else ts
            out.append([s, t.strftime("%Y-%m-%dT%H:%M"), round(float(c), 2)])
    return out


# -- snapshot in Key Value ----------------------------------------------------------------
def _save_snapshot(new_filings: list[dict], prices: list[list], bench: list[list]) -> None:
    from app.ingest.universe import fixtures_dir
    from app.intel.enrich import ENRICHMENT_FILE

    prev = store.get(SNAPSHOT_KEY)
    old = prev[0] if prev else {}
    cutoff = (ist_now() - timedelta(days=4)).isoformat()
    filings = {a["id"]: a for a in old.get("filings", []) if a["ts"] >= cutoff}
    filings |= {a["id"]: a for a in new_filings}
    price_map = {(r[0], r[1]): r for r in old.get("prices", [])} | {(r[0], r[1]): r for r in prices}
    bench_map = {r[0]: r for r in old.get("bench", [])} | {r[0]: r for r in bench}
    path = fixtures_dir() / ENRICHMENT_FILE
    enrichment = json.loads(path.read_text()) if path.exists() else {}
    # keep only what the snapshot's filings need: the baked fixtures cover the rest
    ids = set(filings)
    slim = {
        part: {k: v for k, v in enrichment.get(part, {}).items() if k in ids}
        for part in ("announcements", "results", "people")
    }
    store.put(
        SNAPSHOT_KEY,
        {
            "filings": sorted(filings.values(), key=lambda a: a["ts"]),
            "prices": sorted(price_map.values())[-400:],
            "bench": sorted(bench_map.values())[-10:],
            "enrichment": slim,
            "refreshed_at": _state["last_ok"],
            "prices_at": _state["prices_at"],
        },
        ttl=SNAPSHOT_TTL,
    )


def restore() -> int:
    """At startup: bring back what earlier runs added (newer than the baked fixtures)."""
    from app.ingest.universe import fixtures_dir
    from app.intel.enrich import ENRICHMENT_FILE, apply_enrichment

    got = store.get(SNAPSHOT_KEY)
    if not got:
        return 0
    snap = got[0]
    added = _add_announcements(snap.get("filings", []))
    _put_prices(snap.get("prices", []), snap.get("bench", []))
    path = fixtures_dir() / ENRICHMENT_FILE
    base = json.loads(path.read_text()) if path.exists() else {}
    for part, vals in snap.get("enrichment", {}).items():
        base.setdefault(part, {}).update(vals)
    path.write_text(json.dumps(base, indent=1, ensure_ascii=False))
    apply_enrichment()
    _state["last_ok"] = snap.get("refreshed_at")
    _state["prices_at"] = snap.get("prices_at")
    log.info("restored %d filings and %d price rows from the store", added, len(snap["prices"]))
    return added


# -- one run ------------------------------------------------------------------------------
def refresh() -> dict:
    if not _lock.acquire(blocking=False):
        return status()
    _state.update(running=True, last_try=ist_now().isoformat(timespec="seconds"), error=None)
    errors = []
    try:
        try:
            filings = _fetch_filings()
        except Exception as e:  # noqa: BLE001
            filings, _ = [], errors.append(f"filings: {type(e).__name__}")
        added = _add_announcements(filings) if filings else 0
        if not filings:
            errors.append("filings: NSE returned nothing")
        try:
            prices, bench = _fetch_prices()
            _put_prices(prices, bench)
            _state["prices_at"] = ist_now().isoformat(timespec="minutes")
            try:
                _put_intraday(_fetch_hourly())
            except Exception as e:  # noqa: BLE001
                errors.append(f"hourly: {type(e).__name__}")
        except Exception as e:  # noqa: BLE001
            prices, bench = [], []
            errors.append(f"prices: {type(e).__name__}")
        if added:
            from app.intel.enrich import run

            try:
                run()
            except Exception as e:  # noqa: BLE001 - rules already gave every filing a category
                errors.append(f"enrich: {type(e).__name__}")
        if filings or prices:
            _state["last_ok"] = ist_now().isoformat(timespec="seconds")
            _save_snapshot(filings, prices, bench)
        _state.update(added=added, error="; ".join(errors) or None)
        log.info("refresh: %d new filings, %d price rows; %s", added, len(prices), errors or "ok")
    finally:
        _state["running"] = False
        _lock.release()
    return status()


def refresh_in_background() -> None:
    threading.Thread(target=refresh, daemon=True, name="finn-refresh").start()


def maybe_refresh() -> None:
    """Called on page loads: start a run when the last one is older than the interval."""
    if not enabled() or _state["running"]:
        return
    last = _state["last_try"]
    if last and ist_now() - datetime.fromisoformat(last) < timedelta(seconds=interval_s()):
        return
    refresh_in_background()


def start() -> None:
    """Restore the stored snapshot, then refresh now and every half hour while awake."""
    if not enabled():
        return
    try:
        restore()
    except Exception as e:  # noqa: BLE001
        log.warning("restore failed: %s", e)

    def loop() -> None:
        while True:
            refresh()
            time.sleep(interval_s())

    threading.Thread(target=loop, daemon=True, name="finn-refresh-loop").start()
