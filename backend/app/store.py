"""Saved reports, kept for a week. On Render the web service's SQLite is rebuilt on every deploy
(the daily refresh redeploys every morning), so a saved report lives in a separate Key Value
instance (Redis) when `REDIS_URL` is set, and in a local SQLite table otherwise.

Every value is stored with the time it was saved, so a page can say how old it is and offer a
fresh one. A failing store never breaks a page: reads return None, writes are skipped.
"""

from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache

from app.db import session

log = logging.getLogger(__name__)
WEEK_S = 7 * 24 * 3600
_PREFIX = "finn:"


_down_until = 0.0  # after a Key Value failure, use SQLite for a while instead of waiting


@lru_cache
def _client():
    import redis

    return redis.Redis.from_url(os.environ["REDIS_URL"], socket_timeout=2, socket_connect_timeout=2)


def _redis():
    if not os.environ.get("REDIS_URL") or time.time() < _down_until:
        return None
    return _client()


def _failed(e: Exception, what: str) -> None:
    global _down_until
    _down_until = time.time() + 300
    log.warning("store %s failed, using the local table for 5 minutes: %s", what, e)


def backend() -> str:
    """Where saved reports live right now: "key-value" (survives redeploys) or "local"."""
    r = _redis()
    if r is None:
        return "local"
    try:
        r.ping()
        return "key-value"
    except Exception as e:  # noqa: BLE001
        _failed(e, "ping")
        return "local"


def _table(db) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS saved (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
        "expires REAL NOT NULL)"
    )


def put(key: str, value: object, ttl: int = WEEK_S) -> float:
    """Save a value for `ttl` seconds; returns the time it was saved."""
    now = time.time()
    raw = json.dumps({"saved_at": now, "value": value}, ensure_ascii=False)
    try:
        if r := _redis():
            r.set(_PREFIX + key, raw, ex=ttl)
        else:
            with session() as db:
                _table(db)
                db.execute(
                    "INSERT OR REPLACE INTO saved (key, value, expires) VALUES (?,?,?)",
                    (key, raw, now + ttl),
                )
    except Exception as e:  # noqa: BLE001 - a saved copy is a convenience
        _failed(e, f"put {key}")
    return now


def get(key: str) -> tuple[object, float] | None:
    """(value, saved_at) while it hasn't expired, else None."""
    try:
        if r := _redis():
            raw = r.get(_PREFIX + key)
        else:
            with session() as db:
                _table(db)
                row = db.execute(
                    "SELECT value FROM saved WHERE key=? AND expires>?", (key, time.time())
                ).fetchone()
            raw = row["value"] if row else None
    except Exception as e:  # noqa: BLE001
        _failed(e, f"get {key}")
        return None
    if not raw:
        return None
    d = json.loads(raw)
    return d["value"], d["saved_at"]


def keys(prefix: str) -> list[str]:
    """Saved keys starting with `prefix` (without the store's own prefix)."""
    try:
        if r := _redis():
            return [
                k.decode()[len(_PREFIX) :] for k in r.scan_iter(_PREFIX + prefix + "*", count=200)
            ]
        with session() as db:
            _table(db)
            rows = db.execute(
                "SELECT key FROM saved WHERE key LIKE ? AND expires>?",
                (prefix.replace("%", "") + "%", time.time()),
            ).fetchall()
        return [r["key"] for r in rows]
    except Exception as e:  # noqa: BLE001
        _failed(e, f"keys {prefix}")
        return []
