"""Enrichment pipeline: classify → triage (LLM, batched) → results (screener first) → people.

Output goes to fixtures/enrichment.json so `make seed` replays it offline and for free.
Every LLM call is also cached, so re-running only pays for new filings.

    uv run python -m app.intel.enrich            (or: make enrich)
"""

from __future__ import annotations

import json
import logging
import re

from app.db import init_db, session
from app.ingest.universe import fixtures_dir
from app.intel.pdftext import filing_excerpt
from app.intel.results import (
    build_results_card,
    extract_results,
    quarter_for,
    screener_card_for,
)
from app.intel.taxonomy import ROUTINE, classify_rules

log = logging.getLogger("enrich")
ENRICHMENT_FILE = "enrichment.json"

# Confident-rule categories that still deserve an LLM summary + materiality
NEEDS_TRIAGE = {
    "results",
    "M&A",
    "management_change",
    "litigation",
    "fund_raise",
    "capex",
    "credit_rating",
    "pledging",
    "insider_trading",
    "press_release",
    "bonus_split",
}
DEFAULT_MATERIALITY = {
    "unclassified": 3,
    "investor_meetings": 5,
    "agm_egm": 5,
    "postal_ballot": 5,
    "dividend": 15,
    "earnings_call": 15,
}
_PREFIX = re.compile(
    r"^.*?has (informed|submitted to) the Exchange,? (about|regarding|that)?\s*", re.I
)


def clean_subject(subject: str) -> str:
    s = _PREFIX.sub("", subject or "").strip().rstrip(".")
    return (s[:1].upper() + s[1:]) if s else subject


def is_primary_results_filing(a: dict) -> bool:
    return a["exch_category"] in ("Outcome of Board Meeting", "Financial Result Updates") and bool(
        re.search(r"financial results?|unaudited|audited", a["subject"], re.I)
    )


def run(limit_triage: int | None = None) -> dict:
    from app.intel.people import extract_people
    from app.intel.triage import triage

    init_db()
    with session() as db:
        anns = [
            dict(r)
            for r in db.execute(
                "SELECT id, symbol, ts, exch_category, subject, pdf_url FROM announcements "
                "ORDER BY ts DESC"
            )
        ]
    log.info("%d announcements", len(anns))

    # 1. rules
    out: dict[str, dict] = {}
    todo = []
    for a in anns:
        rule = classify_rules(a["exch_category"], a["subject"])
        out[a["id"]] = {
            "category": rule.category,
            "category_source": "rules",
            "materiality": DEFAULT_MATERIALITY.get(rule.category, 30),
            "summary": clean_subject(a["subject"]),
        }
        if not rule.confident or rule.category in NEEDS_TRIAGE:
            todo.append(a | {"rule_category": rule.category})
    log.info("rules: %d confident-routine, %d need triage", len(anns) - len(todo), len(todo))

    # 2. batched LLM triage
    todo = todo[:limit_triage] if limit_triage else todo
    for i, a in enumerate(todo):
        a["excerpt"] = filing_excerpt(a["pdf_url"], limit=1800)
        if i % 25 == 0:
            log.info("excerpts %d/%d", i, len(todo))
    triaged = triage(todo)
    for aid, t in triaged.items():
        rule_cat = out[aid]["category"]
        out[aid].update(
            category=t.category,
            materiality=t.materiality,
            summary=t.one_liner,
            category_source="rules" if t.category == rule_cat else "llm",
        )
    log.info("triaged %d/%d", len(triaged), len(todo))

    # 3. results cards: newest primary results filing per company
    results: dict[str, dict] = {}
    seen: set[str] = set()
    for a in anns:
        if a["symbol"] in seen or out[a["id"]]["category"] != "results":
            continue
        if not is_primary_results_filing(a):
            continue
        seen.add(a["symbol"])
        # screener's table first: once it has the filed quarter, the card needs no model
        # call. Only a quarter screener hasn't added yet (usually the first day) is read
        # from the PDF.
        card = screener_card_for(a["symbol"], quarter_for(a["ts"]))
        if card:
            results[a["id"]] = card
            log.info("results %s %s: from screener", a["symbol"], card["period"])
            continue
        try:
            ex = extract_results(a["pdf_url"])
            card = build_results_card(a["symbol"], ex) if ex else None
        except Exception as e:
            log.error("results %s failed: %s", a["symbol"], e)
            card = None
        if card:
            results[a["id"]] = card
            log.info(
                "results %s %s: %s", a["symbol"], card["period"], card["cross_check"]["status"]
            )

    # 4. people in management-change filings (golden fixture ones are kept as-is)
    golden = {
        p["announcement_id"]
        for p in json.loads((fixtures_dir() / "filing_people.json").read_text())["people"]
    }
    people: dict[str, list] = {}
    for a in anns:
        if out[a["id"]]["category"] != "management_change" or a["id"] in golden:
            continue
        try:
            res = extract_people(a["pdf_url"])
        except Exception as e:
            log.error("people %s failed: %s", a["id"], e)
            continue
        if res and res.people:
            people[a["id"]] = [p.model_dump() for p in res.people]

    data = {"announcements": out, "results": results, "people": people}
    (fixtures_dir() / ENRICHMENT_FILE).write_text(json.dumps(data, indent=1, ensure_ascii=False))
    apply_enrichment()
    return data


def apply_enrichment() -> int:
    """Write enrichment.json into the announcements table (called by seed and by run())."""
    path = fixtures_dir() / ENRICHMENT_FILE
    if not path.exists():
        return 0
    data = json.loads(path.read_text())
    with session() as db:
        for aid, e in data["announcements"].items():
            extra = {}
            if aid in data.get("results", {}):
                extra["results"] = data["results"][aid]
            if aid in data.get("people", {}):
                extra["people"] = data["people"][aid]
            db.execute(
                "UPDATE announcements SET category=?, category_source=?, materiality=?, "
                "summary=?, enrichment_json=? WHERE id=?",
                (
                    e["category"],
                    e["category_source"],
                    e["materiality"],
                    e["summary"],
                    json.dumps(extra) if extra else None,
                    aid,
                ),
            )
    return len(data["announcements"])


def routine(category: str) -> bool:
    return category in ROUTINE


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "google_genai", "pypdf"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    run(int(sys.argv[1]) if len(sys.argv) > 1 else None)
