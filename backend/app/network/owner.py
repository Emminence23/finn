"""Whose network a request sees (N-7).

Every network row carries an owner. A request names its owner in the `X-Finn-User` header,
checked against the known demo accounts; the API sets it here for the request and every
network query reads it. People named in public filings are stored once under PUBLIC and
are visible to everyone; contacts and relationships are never shared.

This is a demo switch, not authentication. Production takes the owner from the signed-in
user and enforces the same split in the database with row-level security.
"""

from __future__ import annotations

import re
from contextvars import ContextVar

PUBLIC = "public"
DEFAULT = "demo"
# owner id -> its network fixture
ACCOUNTS = {"demo": "network.json", "demo2": "network_demo2.json"}

# "Bring your own network": a private sandbox per browser, created by the server
SANDBOX = re.compile(r"u_[a-z0-9]{16}")

_current: ContextVar[str] = ContextVar("finn_owner", default=DEFAULT)


def is_sandbox(owner: str) -> bool:
    return bool(SANDBOX.fullmatch(owner))


def current_owner() -> str:
    return _current.get()


def set_owner(owner: str):
    if owner not in ACCOUNTS and not (is_sandbox(owner) and _sandbox_exists(owner)):
        raise ValueError("unknown account")
    return _current.set(owner)


def _sandbox_exists(owner: str) -> bool:
    from app.db import session

    with session() as db:
        return (
            db.execute("SELECT 1 FROM sandboxes WHERE owner_id=?", (owner,)).fetchone() is not None
        )


def investor_id(owner: str) -> str:
    return "me" if owner == DEFAULT else f"me@{owner}"
