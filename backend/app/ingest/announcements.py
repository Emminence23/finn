"""Corporate announcements from NSE's corporate-announcements API (REQUIREMENTS §5)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.http import Fetcher, get_fetcher

log = logging.getLogger(__name__)
NSE_ANN_URL = "https://www.nseindia.com/api/corporate-announcements"


def _nse_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def parse_ts(an_dt: str) -> str:
    """'13-Nov-2026 18:25:01' -> '2026-11-13T18:25:01' (IST)."""
    return datetime.strptime(an_dt, "%d-%b-%Y %H:%M:%S").isoformat()


def normalise(row: dict) -> dict:
    return {
        "id": str(row["seq_id"]),
        "symbol": row["symbol"],
        "ts": parse_ts(row["an_dt"]),
        "exch_category": (row.get("desc") or "").strip(),
        "subject": (row.get("attchmntText") or "").strip(),
        "pdf_url": row.get("attchmntFile") or None,
        "company": row.get("sm_name"),
        "isin": row.get("sm_isin"),
        "industry": row.get("smIndustry"),
        "has_xbrl": bool(row.get("hasXbrl")),
    }


def fetch_announcements(
    symbol: str, start: date, end: date, fetcher: Fetcher | None = None, use_cache: bool = False
) -> list[dict]:
    f = fetcher or get_fetcher()
    rows = f.get_json(
        NSE_ANN_URL,
        params={
            "index": "equities",
            "symbol": symbol,
            "from_date": _nse_date(start),
            "to_date": _nse_date(end),
        },
        headers={
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
        },
        use_cache=use_cache,
    )
    out = [normalise(r) for r in rows if r.get("seq_id") and r.get("an_dt")]
    log.info("NSE %s: %d announcements %s..%s", symbol, len(out), start, end)
    return out


def fetch_universe_announcements(symbols: list[str], days: int = 60) -> list[dict]:
    from app.live import ist_now

    end = ist_now().date()  # India's date, also on a UTC server
    start = end - timedelta(days=days)
    seen: dict[str, dict] = {}
    for s in symbols:
        try:
            for a in fetch_announcements(s, start, end):
                seen[a["id"]] = a
        except Exception as e:  # one bad symbol must not kill the snapshot
            log.error("announcements failed for %s: %s", s, e)
    return sorted(seen.values(), key=lambda a: a["ts"], reverse=True)
