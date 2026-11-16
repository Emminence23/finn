"""Persist extracted reports (insert-only) and read them back as plain dicts."""

from __future__ import annotations

import json

from app.brokerage.calc import to_crore
from app.brokerage.extract import normalise_period
from app.db import session
from app.ingest.universe import fixtures_dir


def _round(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None


def _definition(d: str | None) -> str | None:
    """Keep only what changes a figure's meaning (adjusted, recurring, reported, diluted);
    words like 'consolidated' describe the table, not the figure."""
    if not d:
        return None
    words = [w for w in ("adjusted", "recurring", "reported", "diluted", "core") if w in d.lower()]
    return " ".join(words) or None


def save_brokerages(brokerages: dict) -> None:
    with session() as db:
        for bid, b in brokerages.items():
            db.execute(
                "INSERT OR IGNORE INTO brokerages (id, name, aliases_json, website) "
                "VALUES (?,?,?,?)",
                (bid, b["name"], json.dumps(b.get("aliases", [])), b.get("website")),
            )


def save_report(rec: dict, owner: str | None = None) -> bool:
    """Insert one report with its observation and estimates. Returns False for a duplicate
    (same company, brokerage, date and bytes): nothing already stored is ever replaced."""
    ex, chk = rec["extraction"], rec["checks"]
    rid = rec["id"] if owner is None else f"{rec['id']}-{owner}"
    with session() as db:
        dup = db.execute(
            "SELECT 1 FROM brokerage_reports WHERE symbol=? AND brokerage_id=? AND "
            "content_hash=? AND owner_id IS ?",
            (rec["symbol"], rec["brokerage_id"], rec["content_hash"], owner),
        ).fetchone()
        if dup:
            return False
        db.execute(
            "INSERT INTO brokerage_reports (id, symbol, brokerage_id, owner_id, analyst_name, "
            "title, report_type, published_at, ingested_at, source_type, source_url, "
            "storage_uri, content_hash, page_count, extraction_status, extraction_version, "
            "checks_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                rec["symbol"],
                rec["brokerage_id"],
                owner,
                ", ".join(ex.get("analysts") or []) or None,
                ex.get("title"),
                ex.get("report_type"),
                ex.get("published_at"),
                rec["ingested_at"],
                rec["source_type"],
                rec.get("source_url"),
                rec.get("file"),
                rec["content_hash"],
                rec.get("page_count"),
                rec.get("extraction_status", "parsed"),
                rec["extraction_version"],
                json.dumps(chk),
            ),
        )
        oid = f"{rid}-o"
        db.execute(
            "INSERT INTO brokerage_observations (id, report_id, symbol, rating, rating_raw, "
            "target_price, target_currency, reference_price, reference_price_date, "
            "horizon_value, horizon_unit, horizon_raw, horizon_basis, previous_target, "
            "previous_rating, thesis_summary, catalysts_json, risks_json, valuation_method, "
            "valuation_assumptions_json, evidence_json, extraction_confidence, review_status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                oid,
                rid,
                rec["symbol"],
                rec.get("rating_normalized"),
                ex.get("rating_raw"),
                ex.get("target_price"),
                chk.get("currency"),
                ex.get("reference_price"),
                ex.get("reference_price_date"),
                ex.get("horizon_value"),
                ex.get("horizon_unit"),
                ex.get("horizon_raw"),
                ex.get("horizon_basis") if ex.get("horizon_raw") else None,
                ex.get("previous_target"),
                ex.get("previous_rating"),
                ex.get("thesis_summary"),
                json.dumps(ex.get("catalysts") or []),
                json.dumps(ex.get("risks") or []),
                ex.get("valuation_method"),
                json.dumps(ex.get("valuation_assumptions") or []),
                json.dumps(chk["fields"]),
                chk.get("confidence"),
                rec.get("review_status", "unreviewed"),
            ),
        )
        for i, (e, c) in enumerate(zip(ex.get("estimates") or [], chk["estimates"], strict=True)):
            db.execute(
                "INSERT INTO brokerage_estimates (id, observation_id, metric, metric_raw, "
                "fiscal_period, fiscal_period_raw, value, unit, value_cr, is_actual, "
                "definition, scenario, source_page, source_excerpt, verified) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"{oid}-e{i}",
                    oid,
                    e["metric"],
                    e.get("metric_raw"),
                    normalise_period(e["fiscal_period"]),
                    e["fiscal_period"],
                    e["value"],
                    e["unit"],
                    _round(to_crore(e["value"], e["unit"])) if e["metric"] != "EPS" else None,
                    int(bool(e.get("is_actual"))),
                    _definition(e.get("definition")),
                    e.get("scenario"),
                    e.get("page"),
                    (e.get("excerpt") or "")[:300],
                    int(bool(c["ok"])),
                ),
            )
    return True


def seed_from_fixtures() -> int:
    d = fixtures_dir() / "brokerage"
    if not (d / "sources.json").exists():
        return 0
    # the shared set is rebuilt from the fixtures; reports investors uploaded are kept
    with session() as db:
        shared = "SELECT id FROM brokerage_reports WHERE owner_id IS NULL"
        obs = f"SELECT id FROM brokerage_observations WHERE report_id IN ({shared})"
        db.execute(f"DELETE FROM forecast_evaluations WHERE observation_id IN ({obs})")
        db.execute(f"DELETE FROM brokerage_estimates WHERE observation_id IN ({obs})")
        db.execute(f"DELETE FROM brokerage_observations WHERE report_id IN ({shared})")
        db.execute("DELETE FROM brokerage_reports WHERE owner_id IS NULL")
    save_brokerages(json.loads((d / "sources.json").read_text())["brokerages"])
    n = 0
    for f in sorted(d.glob("*.json")):
        if f.name == "sources.json" or f.name.startswith("explain"):
            continue
        for rec in json.loads(f.read_text())["reports"]:
            n += save_report(rec)
    return n


def brokerage_names() -> dict[str, str]:
    with session() as db:
        return {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM brokerages")}


def observations(symbol: str, owner: str | None = None) -> list[dict]:
    """Every observation for a company visible to this investor (FINN's shared set plus
    reports they uploaded), oldest first, each with its report's metadata and estimates."""
    with session() as db:
        rows = db.execute(
            "SELECT o.*, r.brokerage_id, r.published_at, r.title, r.report_type, "
            "r.analyst_name, r.source_type, r.source_url, r.owner_id, r.page_count, "
            "r.checks_json, r.extraction_version, r.ingested_at, b.name AS brokerage "
            "FROM brokerage_observations o JOIN brokerage_reports r ON r.id = o.report_id "
            "JOIN brokerages b ON b.id = r.brokerage_id "
            "WHERE o.symbol=? AND (r.owner_id IS NULL OR r.owner_id=?) "
            "ORDER BY r.published_at, r.brokerage_id",
            (symbol.upper(), owner),
        ).fetchall()
        est = {}
        for e in db.execute(
            "SELECT e.* FROM brokerage_estimates e JOIN brokerage_observations o "
            "ON o.id = e.observation_id WHERE o.symbol=?",
            (symbol.upper(),),
        ):
            est.setdefault(e["observation_id"], []).append(dict(e))
    out = []
    for r in rows:
        o = dict(r)
        for k in ("catalysts", "risks", "valuation_assumptions", "evidence", "checks"):
            o[k] = json.loads(o.pop(f"{k}_json"))
        o["estimates"] = est.get(o["id"], [])
        out.append(o)
    return out
