"""The app's notion of 'now'.

Fixtures freeze data at snapshot time, so a wall-clock 'last 24h' would eventually be empty.
`FINN_NOW` pins the clock (ISO timestamp); otherwise we use the newest announcement in the DB,
which makes the demo behave as if it were opened just after the last snapshot.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta

from app.db import session


def now() -> datetime:
    pinned = os.getenv("FINN_NOW", "").strip()
    if pinned:
        return datetime.fromisoformat(pinned)
    with session() as db:
        row = db.execute("SELECT MAX(ts) FROM announcements").fetchone()
    newest = datetime.fromisoformat(row[0]) + timedelta(minutes=1) if row and row[0] else None
    # with the live refresh running, "now" is when NSE was last checked, not the last filing
    from app.live import last_refresh

    checked = last_refresh()
    return max(d for d in (newest, checked) if d) if (newest or checked) else datetime.now()


WINDOWS = {
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
    "14d": timedelta(days=14),
    "21d": timedelta(days=21),
    "30d": timedelta(days=30),
}


def window_bounds(
    window: str = "24h", start: str | None = None, end: str | None = None
) -> tuple[datetime, datetime]:
    """Named window ending at now(), or an explicit custom range (FR-PUSH-01)."""
    if start:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end) if end else now()
        return s, e
    if window not in WINDOWS:
        raise ValueError(f"unknown window '{window}' (use {', '.join(WINDOWS)} or start/end)")
    e = now()
    return e - WINDOWS[window], e


# NSE closes at 15:30 IST; EOD files are reliably out by 18:00.
EOD_READY = time(18, 0)


def latest_session(at: datetime) -> date:
    """The last trading day whose EOD data should be available at `at`. Weekends are skipped;
    exchange holidays are not modelled, so a holiday can show one session behind."""
    d = at.date() if at.time() >= EOD_READY else at.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def sessions_between(older: date, newer: date) -> int:
    """Weekdays after `older`, up to and including `newer`."""
    n, d = 0, older
    while d < newer:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def _checked() -> str | None:
    from app.live import last_refresh

    c = last_refresh()
    return c.isoformat(timespec="seconds") if c else None


def _prices_live(p: str | None) -> str | None:
    """When today's price row is a trade in progress rather than a close: its check time."""
    from app.live import _state, market_open

    at = _state.get("prices_at")
    if p and at and at[:10] == p and market_open(datetime.fromisoformat(at)):
        return at
    return None


def freshness(at: datetime | None = None) -> dict:
    """Q-3: how old the data behind a view is. Prices are stale when the latest finished
    session is not loaded."""
    at = at or now()
    with session() as db:
        p = db.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        f = db.execute("SELECT MAX(ts) FROM announcements").fetchone()[0]
    behind = sessions_between(date.fromisoformat(p), latest_session(at)) if p else None
    return {
        "prices_as_of": p,
        "checked_at": _checked(),
        "prices_live_at": _prices_live(p),
        "filings_as_of": f,
        "sessions_behind": behind,
        "stale": behind is None or behind >= 1,
    }
