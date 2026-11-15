"""SQLite storage (REQUIREMENTS §6.5). One file, WAL mode, schema created idempotently."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    isin TEXT,
    sector TEXT,
    industry TEXT,
    in_portfolio INTEGER NOT NULL DEFAULT 0,
    in_research_set INTEGER NOT NULL DEFAULT 0,
    weight REAL
);

CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS announcements (
    id TEXT PRIMARY KEY,               -- NSE seq_id
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,                  -- ISO-8601, IST
    exch_category TEXT,                -- NSE 'desc'
    subject TEXT,                      -- NSE 'attchmntText'
    pdf_url TEXT,
    category TEXT,                     -- FINN category (reference doc taxonomy)
    category_source TEXT,              -- 'rules' | 'llm' | 'fixture'
    materiality INTEGER,
    summary TEXT,
    enrichment_json TEXT,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_ann_ts ON announcements (ts);
CREATE INDEX IF NOT EXISTS ix_ann_symbol_ts ON announcements (symbol, ts);

CREATE TABLE IF NOT EXISTS financials_quarterly (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,              -- e.g. 2026-09 (quarter end)
    revenue REAL, ebitda REAL, pbt REAL, pat REAL,
    source TEXT NOT NULL,              -- 'screener' | 'filing'
    PRIMARY KEY (symbol, period, source)
);

CREATE TABLE IF NOT EXISTS financials_annual (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,              -- fiscal year end, e.g. 2026-03
    data_json TEXT NOT NULL,           -- full P&L / BS / CF row set
    PRIMARY KEY (symbol, period)
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,               -- sha256 of url
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,                -- annual_report | transcript | ppt | results
    period TEXT,
    url TEXT NOT NULL,
    local_path TEXT,
    sha256 TEXT
);

-- Network (owner-scoped for privacy, REQUIREMENTS §6.4)
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL DEFAULT 'demo',
    name TEXT NOT NULL,
    headline TEXT,
    is_contact INTEGER NOT NULL DEFAULT 0,
    themes_json TEXT,
    bio TEXT,
    expires_at TEXT                    -- filing-person bios expire (retention policy)
);
CREATE TABLE IF NOT EXISTS roles (
    person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    company TEXT NOT NULL,
    symbol TEXT,
    title TEXT,
    start_year INTEGER,
    end_year INTEGER                   -- NULL = current
);
CREATE TABLE IF NOT EXISTS education (
    person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    school TEXT NOT NULL,
    program TEXT,
    start_year INTEGER,
    end_year INTEGER
);
CREATE TABLE IF NOT EXISTS relationships (
    owner_id TEXT NOT NULL DEFAULT 'demo',
    person_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    other_id TEXT,                     -- NULL = relationship with the investor (1st degree)
    type TEXT,
    strength REAL,
    last_contact TEXT
);
CREATE TABLE IF NOT EXISTS company_links (
    symbol TEXT NOT NULL,
    other TEXT NOT NULL,
    kind TEXT NOT NULL,                -- competitor | supplier | customer
    PRIMARY KEY (symbol, other, kind)
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id TEXT NOT NULL DEFAULT 'demo',
    kind TEXT NOT NULL,                -- volume | price | category
    params_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,               -- deterministic: rule+symbol+date (idempotent runs)
    rule_id INTEGER,
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload_json TEXT
);

-- LLM cache + usage log (NFR-03, NFR-12)
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    output TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    cache_hit INTEGER NOT NULL,
    input_tokens INTEGER, output_tokens INTEGER,
    latency_ms INTEGER,
    cost_usd REAL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS research_cache (
    symbol TEXT NOT NULL,
    key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, key)
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
