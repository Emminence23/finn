"""The Push digest (FR-PUSH, FR-CARD): ranked cards for a window, routine items folded away.

Cards group related filings (e.g. results outcome + press release + newspaper ad) so the
investor sees one item per (company, event type).
"""

from __future__ import annotations

import json
from datetime import datetime

from app.clock import freshness, window_bounds
from app.db import session
from app.ingest.universe import fixtures_dir
from app.intel import alerts as alerts_mod
from app.intel.results import refresh_changes, screener_results_card
from app.intel.taxonomy import CATEGORY_WEIGHT, MATERIAL_EVENTS, folds_as_routine, is_unsure
from app.network import graph


def _golden_people() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in json.loads((fixtures_dir() / "filing_people.json").read_text())["people"]:
        out.setdefault(p["announcement_id"], []).append(p)
    return out


def _companies() -> dict[str, dict]:
    with session() as db:
        return {
            r["symbol"]: dict(r)
            for r in db.execute(
                "SELECT symbol, name, sector, in_portfolio, in_research_set, weight FROM companies "
                "WHERE in_portfolio=1 OR in_research_set=1"
            )
        }


def _people_block(ann: dict, enrichment: dict, golden: dict, people) -> list[dict]:
    """Incoming/outgoing people with bio and network paths (FR-CARD-03/04)."""
    out = []
    for gp in golden.get(ann["id"], []):
        paths = graph.paths_to(gp["id"], people)
        out.append(
            {
                "id": gp["id"],
                "name": gp["name"],
                "role": gp["role"],
                "direction": gp["direction"],
                "bio": gp["bio"],
                "source": "filing",
                "prior": [r["company"] for r in gp["roles"]],
                "education": [e["school"] for e in gp["education"]],
                "paths": paths,
            }
        )
    if out:
        return out
    seen: set[tuple[str, str]] = set()
    for i, p in enumerate(enrichment.get("people", [])):
        if not p.get("is_senior") and p["direction"] != "incoming":
            continue
        k = (" ".join(p["name"].lower().replace(".", " ").split()), p["direction"])
        if k in seen:  # one PDF often lists a person twice (letter + annexure)
            continue
        seen.add(k)
        person = graph.person_from_extraction(p, ann["symbol"], f"auto_{ann['id']}_{i}")
        out.append(
            {
                "id": None,
                "name": p["name"],
                "role": p["role"],
                "direction": p["direction"],
                "bio": p.get("bio"),
                "source": "filing (AI-extracted)",
                "prior": [r["company"] for r in p.get("prior_roles", [])],
                "education": [e["school"] for e in p.get("education", [])],
                "paths": graph.paths_to_person(person, people),
            }
        )
    return out


def build_digest(
    window: str = "24h",
    start: str | None = None,
    end: str | None = None,
    include_research_set: bool = False,
) -> dict:
    t0, t1 = window_bounds(window, start, end)
    companies = _companies()
    scope = [
        s
        for s, c in companies.items()
        if c["in_portfolio"] or (include_research_set and c["in_research_set"])
    ]
    q = ",".join("?" * len(scope))
    with session() as db:
        anns = [
            dict(r)
            for r in db.execute(
                f"""SELECT id, symbol, ts, exch_category, subject, pdf_url, category, materiality,
                       summary, enrichment_json FROM announcements
                WHERE ts BETWEEN ? AND ? AND symbol IN ({q}) ORDER BY ts DESC""",
                (t0.isoformat(), t1.isoformat(), *scope),
            )
        ]

    people = graph.load_people()
    golden = _golden_people()
    alerts = alerts_mod.evaluate(t0, t1)
    alerts_by_symbol: dict[str, list] = {}
    for a in alerts:
        alerts_by_symbol.setdefault(a["symbol"], []).append(a)

    groups: dict[tuple[str, str], list[dict]] = {}
    routine = []
    for a in anns:
        cat = a["category"] or "unclassified"
        if folds_as_routine(cat, a["materiality"], a["exch_category"], a["subject"]):
            routine.append(_item(a))
            continue
        # unrelated filings FINN couldn't place are never merged into one card
        key = f"{cat}:{a['id']}" if cat == "unclassified" else cat
        groups.setdefault((a["symbol"], key), []).append(a)

    cards = []
    for (symbol, key), items in groups.items():
        cat = key.split(":")[0]
        items.sort(key=lambda x: (-(x["materiality"] or 0), x["ts"]))
        enr_by_id = {x["id"]: json.loads(x["enrichment_json"] or "{}") for x in items}
        primary = next((x for x in items if "results" in enr_by_id[x["id"]]), items[0])
        enr = enr_by_id[primary["id"]]
        co = companies[symbol]
        card = {
            "id": primary["id"],
            "symbol": symbol,
            "company": co["name"],
            "ts": max(x["ts"] for x in items),
            "category": cat,
            "kind": "filing",
            "materiality": max(x["materiality"] or 0 for x in items),
            "title": primary["summary"] or primary["subject"],
            "pdf_url": primary["pdf_url"],
            "related": [_item(x) for x in items if x is not primary],
            "alerts": alerts_by_symbol.get(symbol, []),
            "in_portfolio": bool(co["in_portfolio"]),
            "unsure": is_unsure(cat, primary["exch_category"], primary["subject"]),
        }
        if cat == "results":
            card["kind"] = "results"
            card["results"] = refresh_changes(enr.get("results")) or screener_results_card(symbol)
        elif cat == "management_change":
            card["kind"] = "management_change"
            card["people"] = _people_block(primary, enr, golden, people)
        elif cat in MATERIAL_EVENTS:
            card["kind"] = "material_event"
        helpers = graph.who_can_help(symbol, people, limit=3)
        card["helpers"] = helpers if card["kind"] != "filing" else helpers[:1]
        card["priority"] = _priority(card, co)
        cards.append(card)

    cards.sort(key=lambda c: -c["priority"])
    return {
        "window": {
            "name": None if start else window,
            "start": t0.isoformat(),
            "end": t1.isoformat(),
        },
        "alerts": alerts,
        "cards": cards,
        "routine": {"count": len(routine), "items": routine},
        "nudges": graph.reconnect_nudges(t0.isoformat(), t1.isoformat(), people=people)
        if (t1 - t0).days >= 3
        else [],
        "freshness": freshness(),
        "counts": {
            "filings": len(anns),
            "cards": len(cards),
            "routine": len(routine),
            "alerts": len(alerts),
        },
    }


def _priority(card: dict, co: dict) -> float:
    """FR-PUSH-03: category weight × materiality, nudged by position size, alerts and
    whether the network can help."""
    # An unsure filing ranks as a mid-weight item on its triage score, not as paperwork
    weight = 0.5 if card.get("unsure") else CATEGORY_WEIGHT.get(card["category"], 0.1)
    base = weight * (card["materiality"] / 100)
    size = 1.0 + 2.0 * (co["weight"] or 0) if co["in_portfolio"] else 0.7
    boost = 0.05 * min(len(card["alerts"]), 2)
    if card.get("helpers") and card["helpers"][0]["score"] >= 0.5:
        boost += 0.05
    if card["kind"] in ("results", "management_change", "material_event"):
        boost += 0.05
    return round(base * size + boost, 4)


def _item(a: dict) -> dict:
    return {
        "id": a["id"],
        "symbol": a["symbol"],
        "ts": a["ts"],
        "category": a["category"] or "unclassified",
        "title": a["summary"] or a["subject"],
        "pdf_url": a["pdf_url"],
    }


def parse_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None
