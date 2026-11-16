"""The Push digest (FR-PUSH, FR-CARD): ranked cards for a window, routine items folded away.

Cards group related filings (e.g. results outcome + press release + newspaper ad) so the
investor sees one item per (company, event type).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from app.clock import freshness, window_bounds
from app.db import session
from app.ingest.universe import fixtures_dir
from app.intel import alerts as alerts_mod
from app.intel.results import refresh_changes, screener_results_card
from app.intel.taxonomy import CATEGORY_WEIGHT, MATERIAL_EVENTS, folds_as_routine, is_unsure
from app.intel.units import normalise
from app.network import graph
from app.research.service import ready_symbols


def _golden_people() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in json.loads((fixtures_dir() / "filing_people.json").read_text())["people"]:
        out.setdefault(p["announcement_id"], []).append(p)
    return out


def _companies() -> dict[str, dict]:
    """Followed companies, with portfolio membership and weight from the account's holdings."""
    from app.portfolio.holdings import get_holdings

    held = get_holdings()
    with session() as db:
        rows = [
            dict(r)
            for r in db.execute("SELECT symbol, name, sector, in_research_set FROM companies")
        ]
    out = {}
    for r in rows:
        if r["symbol"] in held or r["in_research_set"]:
            out[r["symbol"]] = {
                **r,
                "in_portfolio": int(r["symbol"] in held),
                "weight": held.get(r["symbol"]),
            }
    return out


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


def _first(name: str) -> str:
    parts = name.split()
    return (
        " ".join(parts[:2])
        if parts and parts[0].rstrip(".") in ("Dr", "Mr", "Mrs", "Ms")
        else (parts[0] if parts else name)
    )


def next_action(card: dict, researched: set[str]) -> dict:
    """PLAN v2 principle 5: every card opens the next step, chosen by code, never left
    implicit. A card leads to the person, the research or the source, in that order of
    usefulness for its kind."""
    sym = card["symbol"]
    if card["kind"] == "management_change":
        incoming = [p for p in card.get("people") or [] if p["direction"] == "incoming"]
        p = incoming[0] if incoming else None
        if p and p["id"]:
            via = p["paths"]["via"]
            why = (
                f"through {via[0]['contact']['name']}"
                if via
                else "career and paths from the filing"
            )
            return {
                "label": f"See how you reach {_first(p['name'])}",
                "href": f"/people/{p['id']}",
                "why": why,
            }
    helper = (card.get("helpers") or [None])[0]
    if card["kind"] == "material_event" and helper and helper["score"] >= 0.5:
        c = helper["contact"]
        return {  # opens how you know them, with Email / Call: the card can't dial itself
            "label": f"Ask {_first(c['name'])}",
            "href": f"/people/{c['id']}",
            "why": helper["why"],
        }
    if card["kind"] == "results":
        if sym in researched:
            return {
                "label": "Check their promises",
                "href": f"/c/{sym}#promises",
                "why": "promise scorecard from the last four calls",
            }
        return {
            "label": "Build the research",
            "href": f"/c/{sym}",
            "why": "builds live in about a minute",
        }
    if card.get("unsure") and card.get("pdf_url"):
        return {
            "label": "Open the filing",
            "href": card["pdf_url"],
            "why": "FINN couldn't place it",
        }
    return {"label": "Research", "href": f"/c/{sym}", "why": "snapshot, scorecard and numbers"}


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

    n_held = sum(1 for c in companies.values() if c["in_portfolio"]) or 1
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
    groups = split_events(groups)

    cards = []
    for (symbol, key), items in groups.items():
        cat = key.split(":")[0]
        # most material first; among equals, the newest
        items.sort(key=lambda x: x["ts"], reverse=True)
        items.sort(key=lambda x: -(x["materiality"] or 0))
        enr_by_id = {x["id"]: json.loads(x["enrichment_json"] or "{}") for x in items}
        primary = next((x for x in items if "results" in enr_by_id[x["id"]]), items[0])
        enr = enr_by_id[primary["id"]]
        co = companies[symbol]
        card = {
            "id": primary["id"],
            "symbol": symbol,
            "company": co["name"],
            # the headline filing's own time; latest_ts says when the group last changed
            "ts": primary["ts"],
            "latest_ts": max(x["ts"] for x in items),
            "category": cat,
            "kind": "filing",
            "materiality": max(x["materiality"] or 0 for x in items),
            "title": normalise(primary["summary"] or primary["subject"]),
            "pdf_url": primary["pdf_url"],
            "related": [_item(x) for x in items if x is not primary],
            "alerts": reaction(primary["ts"], alerts_by_symbol.get(symbol, [])),
            "in_portfolio": bool(co["in_portfolio"]),
            "weight": round(100 * co["weight"], 1) if co["in_portfolio"] and co["weight"] else None,
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
        card["priority"] = _priority(card, co, n_held)
        cards.append(card)

    _attach_results_decks(cards, routine)
    researched = ready_symbols()
    for c in cards:
        c["level"], c["level_reason"] = level(c)
        c["next_action"] = next_action(c, researched)
    cards.sort(key=lambda c: (c["level"] != "important", -c["priority"]))
    from app.intel.note import annotate

    return annotate(
        {
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
    )


DECK_DAYS = 3


def _attach_results_decks(cards: list[dict], routine: list[dict]) -> None:
    """PU-3, one item per event: an untitled "Investor Presentation" filed within a few days
    of the same company's results is the results deck. It joins the results card instead of
    being folded as an investor meeting."""
    results = {c["symbol"]: c for c in cards if c["kind"] == "results"}
    keep = []
    for r in routine:
        c = results.get(r["symbol"])
        if (
            c
            and r.get("exch_category") == "Investor Presentation"
            and abs((datetime.fromisoformat(r["ts"]) - datetime.fromisoformat(c["ts"])).days)
            <= DECK_DAYS
        ):
            c["related"].append(r | {"category": "results"})
        else:
            keep.append(r)
    routine[:] = keep


RESULTS_MOVE_PCT = 15.0  # a YoY move in PAT or revenue this big makes results Important


def _results_move(card: dict) -> tuple[bool, str]:
    """Do the numbers move? Uses YoY on PAT, then revenue, or a swing off a loss (PU-8)."""
    rows = {r["metric"]: r for r in (card.get("results") or {}).get("rows", [])}
    parts, big = [], False
    for m, label in (("pat", "PAT"), ("revenue", "revenue")):
        r = rows.get(m) or {}
        if r.get("yoy") is not None:
            parts.append(f"{label} {r['yoy']:+.0f}% YoY")
            big = big or abs(r["yoy"]) >= RESULTS_MOVE_PCT
        elif r.get("yoy_note"):
            parts.append(f"{label} {r['yoy_note']} YoY")
            big = True
    return big, ", ".join(parts[:2])


def level(card: dict) -> tuple[str, str]:
    """PU-4: Important or Notable, with a one-line reason that names what decided it.
    (Routine is the folded group.)

    Important = results whose numbers move (PAT or revenue YoY >= 15%, or a swing off a
    loss); a management change or material event with materiality >= 70; anything else
    scored >= 85; or a filing the market moved on (price alert, materiality >= 50).
    Thresholds were set after the hand labels in fixtures/eval were fixed; see build-log
    Phase 4d."""
    m = card["materiality"]
    moved = [a for a in card["alerts"] if a["kind"] == "price"]
    kind = card["kind"]
    market = bool(moved and m >= 50)
    stock = f"stock {moved[0]['value']:+.1f}% on {_day(moved[0]['ts'])}" if moved else ""
    if card.get("unsure"):
        return ("important" if market else "notable"), (
            "FINN couldn't place this filing, so it isn't folded away"
            + (f"; {stock}" if market else "")
        )
    if kind == "results":
        big, nums = _results_move(card)
        # the card's headline already gives the numbers; the reason gives the rule
        bar = f"{RESULTS_MOVE_PCT:.0f}%"
        if big:
            return "important", f"PAT or revenue moved {bar} or more YoY"
        if market:
            return "important", f"No {bar} move in PAT or revenue, but the {stock}"
        if nums:
            return "notable", f"Neither PAT nor revenue moved {bar} YoY"
        return "notable", "Quarterly results"
    label = {"management_change": "Management change", "material_event": None}.get(kind)
    label = label or (
        "M&A deal" if card["category"] == "M&A" else card["category"].replace("_", " ")
    )
    label = label[0].upper() + label[1:]
    if kind in ("management_change", "material_event") and m >= 70 or m >= 85:
        top = "Top-management change" if kind == "management_change" else label
        return "important", f"{_a(top)} FINN rates {m} of 100 for how much it matters"
    if market:
        return "important", f"{label}; {stock}"
    bar = 70 if kind in ("management_change", "material_event") else 85
    return "notable", f"{_a(label)} FINN rates {m} of 100; Important starts at {bar}"


def _a(label: str) -> str:
    """'Fund raise' -> 'a fund raise'; 'M&A deal' -> 'an M&A deal'."""
    keep = label.split(" ", 1)[0].isupper() or label.startswith(("M&A", "AGM"))
    word = label if keep else label[0].lower() + label[1:]
    return ("an " if word[0] in "aeiouAEIOU" or word.startswith("M&A") else "a ") + word


SAME_EVENT_SIMILARITY = 60  # token-sort ratio of two filings' summaries (0-100)
SAME_EVENT_DAYS = 30
# filings of one periodic event: the results, the call (transcript, recording, slides)
ONE_EVENT_PER_PERIOD = {"results", "earnings_call"}


def split_events(groups: dict) -> dict:
    """One card per underlying event, not per category. Results and earnings-call filings
    of a period stay together; other filings join the event whose summaries are closest
    to theirs (same deal, same person, same case), if close enough and within a month.
    Two separate deals are two cards even though both are M&A. Threshold set from real
    cases: same event 64-99 (a closure order and the court's stay of it: 64), different
    events 38-52 (two executives' appointments on the same day: 52)."""
    from rapidfuzz import fuzz

    def text(a: dict) -> str:
        return (a["summary"] or a["subject"] or "").lower()

    out: dict = {}
    for (symbol, key), items in groups.items():
        if key in ONE_EVENT_PER_PERIOD or ":" in key:
            out[(symbol, key)] = items
            continue
        events: list[list[dict]] = []
        for a in sorted(items, key=lambda x: x["ts"]):
            best, score = None, 0.0
            for ev in events:
                s = max(
                    (
                        fuzz.token_sort_ratio(text(a), text(b))
                        for b in ev
                        if abs((parse_dt(a["ts"]) - parse_dt(b["ts"])).days) <= SAME_EVENT_DAYS
                    ),
                    default=0.0,
                )
                if s > score:
                    best, score = ev, s
            if best is not None and score >= SAME_EVENT_SIMILARITY:
                best.append(a)
            else:
                events.append([a])
        for i, ev in enumerate(events):
            out[(symbol, key if i == 0 else f"{key}:{ev[0]['id']}")] = ev
    return out


REACTION_DAYS = 4  # calendar days after a filing that count as the market's reaction


def reaction(filed: str, alerts: list[dict]) -> list[dict]:
    """The price and volume alerts that can be a reaction to a filing: the session it was
    filed in (if filed before the 15:30 close) and the next few. A move from another day in
    the window is not shown against the filing."""
    f = datetime.fromisoformat(filed)
    first = f.date() if f.time() < time(15, 30) else f.date() + timedelta(days=1)
    last = f.date() + timedelta(days=REACTION_DAYS)
    return [a for a in alerts if first <= date.fromisoformat(a["ts"][:10]) <= last]


def _priority(card: dict, co: dict, n_held: int = 18) -> float:
    """FR-PUSH-03: category weight × materiality, nudged by position size, alerts and
    whether the network can help."""
    # An unsure filing ranks as a mid-weight item on its triage score, not as paperwork
    weight = 0.5 if card.get("unsure") else CATEGORY_WEIGHT.get(card["category"], 0.1)
    base = weight * (card["materiality"] / 100)
    # position size matters: a holding at an equal share counts 1×, a 0.5% position about
    # half, a 12% one about 1.5×; a followed company outside the portfolio counts half
    size = min(1.5, max(0.5, ((co["weight"] or 0) * n_held) ** 0.5)) if co["in_portfolio"] else 0.5
    boost = 0.05 * min(len(card["alerts"]), 2)
    if card.get("helpers") and card["helpers"][0]["score"] >= 0.5:
        boost += 0.05
    if card["kind"] in ("results", "management_change", "material_event"):
        boost += 0.05
    return round(base * size + boost, 4)


def _day(ts: str) -> str:
    d = date.fromisoformat(ts[:10])
    return f"{d.day} {d:%b}"


def _item(a: dict) -> dict:
    return {
        "id": a["id"],
        "symbol": a["symbol"],
        "ts": a["ts"],
        "category": a["category"] or "unclassified",
        "exch_category": a["exch_category"],
        "title": normalise(a["summary"] or a["subject"]),
        "pdf_url": a["pdf_url"],
    }


def parse_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None
