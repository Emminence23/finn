"""Whose network a request sees (N-7).

Every network row carries an owner. A request names its owner in the `X-Finn-User` header,
checked against the known demo accounts; the API sets it here for the request and every
network query reads it. People named in public filings are stored once under PUBLIC and
are visible to everyone; contacts and relationships are never shared.

This is a demo switch, not authentication. Production takes the owner from the signed-in
user and enforces the same split in the database with row-level security.
"""

from __future__ import annotations

from contextvars import ContextVar

PUBLIC = "public"
DEFAULT = "demo"
# owner id -> its network fixture
ACCOUNTS = {"demo": "network.json", "demo2": "network_demo2.json"}

_current: ContextVar[str] = ContextVar("finn_owner", default=DEFAULT)


def current_owner() -> str:
    return _current.get()


def set_owner(owner: str):
    if owner not in ACCOUNTS:
        raise ValueError(f"unknown account '{owner}'")
    return _current.set(owner)


def investor_id(owner: str) -> str:
    return "me" if owner == DEFAULT else f"me@{owner}"
