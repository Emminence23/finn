"""Load committed fixtures into SQLite. Idempotent: wipes and reloads fixture-owned tables.

uv run python -m app.ingest.seed          (or: make seed)
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from datetime import date, timedelta

import pandas as pd

from app.db import init_db, session
from app.ingest.universe import fixtures_dir, load_universe
from app.network.companies import company_aliases, company_links, resolve_symbol
from app.network.owner import ACCOUNTS, PUBLIC

log = logging.getLogger("seed")

FIXTURE_TABLES = [
    "companies",
    "prices",
    "announcements",
    "financials_quarterly",
    "financials_annual",
    "documents",
    "education",
    "roles",
    "relationships",
    "people",
    "company_links",
]
DEFAULT_ALERT_RULES = [
    ("volume", {"multiple": 2.0}),
    ("price", {"abs_pct": 5.0}),
    (
        "category",
        {
            "categories": [
                "results",
                "M&A",
                "management_change",
                "litigation",
                "fund_raise",
                "capex",
                "credit_rating",
                "pledging",
            ]
        },
    ),
]


def _load_json(name: str):
    return json.loads((fixtures_dir() / name).read_text())


def seed_companies(db) -> None:
    uni = load_universe()
    weights = {p["symbol"]: p["weight"] for p in uni["portfolio"]}
    themes = {p["symbol"]: p["theme"] for p in uni["portfolio"]}
    industries = {a["symbol"]: a.get("industry") for a in _load_json("announcements.json")}
    rows = []
    with (fixtures_dir() / "symbols.csv").open() as fh:
        for r in csv.DictReader(fh):
            s = r["symbol"]
            rows.append(
                (
                    s,
                    r["name"],
                    r["isin"],
                    themes.get(s),
                    industries.get(s),
                    int(s in weights),
                    int(s in uni["research_set"]),
                    weights.get(s),
                )
            )
    db.executemany("INSERT INTO companies VALUES (?,?,?,?,?,?,?,?)", rows)
    log.info("companies: %d (portfolio %d)", len(rows), len(weights))


def seed_prices(db) -> None:
    df = pd.read_csv(fixtures_dir() / "prices.csv")
    db.executemany(
        "INSERT INTO prices VALUES (?,?,?,?,?,?,?)",
        df[["symbol", "date", "open", "high", "low", "close", "volume"]].itertuples(index=False),
    )
    log.info("prices: %d rows", len(df))


def seed_announcements(db) -> None:
    rows = _load_json("announcements.json")
    db.executemany(
        """INSERT INTO announcements (id, symbol, ts, exch_category, subject, pdf_url, raw_json)
           VALUES (?,?,?,?,?,?,?)""",
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
    log.info("announcements: %d", len(rows))


def seed_fundamentals(db) -> None:
    n_q = n_docs = 0
    for path in sorted((fixtures_dir() / "fundamentals").glob("*.json")):
        f = json.loads(path.read_text())
        sym = f["symbol"]
        for q in f["quarterly_headline"]:
            db.execute(
                "INSERT INTO financials_quarterly VALUES (?,?,?,?,?,?,?)",
                (sym, q["period"], q["revenue"], q["ebitda"], q["pbt"], q["pat"], "screener"),
            )
            n_q += 1
        by_period: dict[str, dict] = {}
        for table in ("annual_pl", "balance_sheet", "cash_flow", "ratios"):
            for label, series in f["tables"].get(table, {}).items():
                for period, value in series.items():
                    by_period.setdefault(period, {}).setdefault(table, {})[label] = value
        for period, data in by_period.items():
            db.execute(
                "INSERT INTO financials_annual VALUES (?,?,?)", (sym, period, json.dumps(data))
            )
        for d in f["documents"]:
            doc_id = hashlib.sha256(d["url"].encode()).hexdigest()[:16]
            db.execute(
                "INSERT OR IGNORE INTO documents (id, symbol, kind, period, url) "
                "VALUES (?,?,?,?,?)",
                (doc_id, sym, d["kind"], d["period"], d["url"]),
            )
            n_docs += 1
    log.info("fundamentals: %d quarterly rows, %d documents", n_q, n_docs)


def _insert_person(
    db,
    p: dict,
    *,
    owner: str,
    is_contact: bool,
    bio: str | None = None,
    expires_at: str | None = None,
) -> None:
    db.execute(
        "INSERT INTO people (id, owner_id, name, headline, is_contact, themes_json, bio, "
        "expires_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            p["id"],
            owner,
            p["name"],
            p.get("headline") or p.get("role"),
            int(is_contact),
            json.dumps(p.get("themes", [])),
            bio,
            expires_at,
        ),
    )
    for r in p.get("roles", []):
        db.execute(
            "INSERT INTO roles VALUES (?,?,?,?,?,?)",
            (
                p["id"],
                r["company"],
                r.get("symbol") or resolve_symbol(r["company"]),
                r.get("title"),
                r.get("start_year"),
                r.get("end_year"),
            ),
        )
    for e in p.get("education", []):
        db.execute(
            "INSERT INTO education VALUES (?,?,?,?,?)",
            (p["id"], e["school"], e.get("program"), e.get("start_year"), e.get("end_year")),
        )


def seed_owner_network(db, owner: str) -> int:
    """One account's investor, contacts and relationships, all tagged with its owner (N-7)."""
    net = _load_json(ACCOUNTS[owner])
    _insert_person(db, net["investor"], owner=owner, is_contact=False)
    for c in net["contacts"]:
        _insert_person(db, c, owner=owner, is_contact=True)
        rel = c["relationship"]
        db.execute(
            "INSERT INTO relationships (owner_id, person_id, other_id, type, strength, "
            "last_contact) VALUES (?,?,?,?,?,?)",
            (owner, c["id"], None, rel["type"], rel["strength"], rel["last_contact"]),
        )
        for k in c.get("knows", []):
            db.execute(
                "INSERT INTO relationships (owner_id, person_id, other_id, type, strength) "
                "VALUES (?,?,?,?,?)",
                (owner, c["id"], k["person"], k["context"], k["strength"]),
            )
    return len(net["contacts"])


def seed_network(db) -> None:
    n = {owner: seed_owner_network(db, owner) for owner in ACCOUNTS}
    fps = _load_json("filing_people.json")["people"]
    for p in fps:
        # Retention policy (§6.4): filing-person bios expire 90 days after the event.
        expires = (date.fromisoformat(p["effective"]) + timedelta(days=90)).isoformat()
        name = company_aliases().get(p["symbol"], [p["symbol"]])[0]
        current = {
            "company": name,
            "symbol": p["symbol"],
            "title": p["role"],
            "start_year": int(p["effective"][:4]),
            "end_year": None,
        }
        _insert_person(
            db,
            {**p, "roles": [current, *p["roles"]]},
            owner=PUBLIC,  # public filing facts, visible to every account
            is_contact=False,
            bio=p["bio"],
            expires_at=expires,
        )
    for sym, links in company_links().items():
        for kind, others in links.items():
            for other in others:
                db.execute("INSERT OR IGNORE INTO company_links VALUES (?,?,?)", (sym, other, kind))
    log.info("network: contacts per account %s, %d public filing people", n, len(fps))


def seed_alert_rules(db) -> None:
    if db.execute("SELECT COUNT(*) FROM alert_rules").fetchone()[0]:
        return  # keep user-edited thresholds (FR-ALERT-04)
    db.executemany(
        "INSERT INTO alert_rules (kind, params_json) VALUES (?,?)",
        [(k, json.dumps(p)) for k, p in DEFAULT_ALERT_RULES],
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    init_db()
    with session() as db:
        for t in FIXTURE_TABLES:
            db.execute(f"DELETE FROM {t}")
        seed_companies(db)
        seed_prices(db)
        seed_announcements(db)
        seed_fundamentals(db)
        seed_network(db)
        seed_alert_rules(db)
    from app.intel.enrich import apply_enrichment

    log.info("enrichment applied to %d announcements", apply_enrichment())
    log.info("seed complete")


if __name__ == "__main__":
    main()
