"""The app's notion of 'now'.

Fixtures freeze data at snapshot time, so a wall-clock 'last 24h' would eventually be empty.
`FINN_NOW` pins the clock (ISO timestamp); otherwise we use the newest announcement in the DB,
which makes the demo behave as if it were opened just after the last snapshot.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from app.db import session


def now() -> datetime:
    pinned = os.getenv("FINN_NOW", "").strip()
    if pinned:
        return datetime.fromisoformat(pinned)
    with session() as db:
        row = db.execute("SELECT MAX(ts) FROM announcements").fetchone()
    if row and row[0]:
        return datetime.fromisoformat(row[0]) + timedelta(minutes=1)
    return datetime.now()


WINDOWS = {
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
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
