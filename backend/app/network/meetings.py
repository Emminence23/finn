"""Meeting prep from a date (calendar-aware prep, without calendar access).

The investor notes "I'm meeting Karthik on Thursday". From two days before until the day
itself, Today leads with a prep card: what changed in the last 30 days at the companies
that person knows, and the first "Before you meet" questions. Everything is assembled in
code from the digest and the research, so nothing about the meeting or the person reaches
an LLM. Meetings are private to the account, like the rest of the network, and go with the
contact when the contact is deleted.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.clock import now
from app.db import session
from app.network import graph
from app.network.owner import current_owner

LEAD_DAYS = 2  # prep shows from two days before the meeting until the day itself
MAX_NOTE = 200


def today() -> date:
    return now().date()


def _when(d: date, ref: date) -> str:
    gap = (d - ref).days
    return {0: "today", 1: "tomorrow"}.get(gap, f"on {d.strftime('%a %d %b')}")


def list_meetings() -> list[dict]:
    people = graph.load_people()
    ref = today()
    with session() as db:
        rows = db.execute(
            "SELECT id, person_id, day, note FROM meetings WHERE owner_id=? AND day>=? "
            "ORDER BY day, id",
            (current_owner(), ref.isoformat()),
        ).fetchall()
    out = []
    for r in rows:
        p = people.get(r["person_id"])
        if p is None:
            continue
        d = date.fromisoformat(r["day"])
        out.append(
            {
                "id": r["id"],
                "day": r["day"],
                "when": _when(d, ref),
                "note": r["note"],
                "person": {"id": p.id, "name": p.name},
            }
        )
    return out


def add_meeting(person_id: str, day: str, note: str | None = None) -> dict:
    p = graph.load_people().get(person_id)
    if p is None or p is graph.investor(graph.load_people()):
        raise KeyError("no such person in your network")
    d = date.fromisoformat(day)
    if d < today():
        raise ValueError("pick today or a later date")
    with session() as db:
        cur = db.execute(
            "INSERT INTO meetings (owner_id, person_id, day, note) VALUES (?,?,?,?)",
            (current_owner(), person_id, d.isoformat(), " ".join((note or "").split())[:MAX_NOTE]),
        )
        mid = cur.lastrowid
    return next(m for m in list_meetings() if m["id"] == mid)


def delete_meeting(meeting_id: int) -> bool:
    with session() as db:
        cur = db.execute(
            "DELETE FROM meetings WHERE id=? AND owner_id=?", (meeting_id, current_owner())
        )
        return cur.rowcount > 0


def _headline(card: dict) -> str:
    """Results say what the numbers did, as on the card; other filings keep their summary."""
    from app.intel.brief import results_takeaway

    t = card.get("results") and results_takeaway(card["results"])
    return f"{t[0].upper()}{t[1:]}." if t else card["title"]


def prep() -> list[dict]:
    """Prep cards for meetings in the next LEAD_DAYS days."""
    from app.intel.digest import build_digest
    from app.network.diligence import _companies, meeting_questions

    ref = today()
    soon = [
        m
        for m in list_meetings()
        if date.fromisoformat(m["day"]) <= ref + timedelta(days=LEAD_DAYS)
    ]
    if not soon:
        return []
    people = graph.load_people()
    cards = build_digest("30d")["cards"]
    out = []
    for m in soon:
        p = people[m["person"]["id"]]
        knows = _companies(p, people)
        syms = [s for s, _ in knows]
        rank = {sym: i for i, sym in enumerate(syms)}  # where they worked first, then peers
        hits, per = [], {}
        for c in sorted((c for c in cards if c["symbol"] in rank), key=lambda c: rank[c["symbol"]]):
            per[c["symbol"]] = per.get(c["symbol"], 0) + 1
            if per[c["symbol"]] <= 2:  # leave room for the next company they know
                hits.append(c)
        changed = [
            {
                "symbol": c["symbol"],
                "company": c["company"],
                "title": _headline(c),
                "level": c["level"],
                "ts": c["ts"],
            }
            for c in hits
        ][:3]
        qs = meeting_questions(p.id) or {"groups": []}
        questions = [q["question"] for g in qs["groups"] for q in g["questions"]][:2]
        out.append(
            {
                **m,
                "companies": [{"symbol": s, "relation": r} for s, r in knows][:3],
                "changed": changed,
                "questions": questions,
            }
        )
    return out
