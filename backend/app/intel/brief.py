"""A spoken version of Today (FR-PUSH-11): a short script for the commute.

Written in code from the digest, never by a model, so it says exactly what the cards say
and costs nothing. The phone's own speech engine reads it. The text is shaped for the ear:
rupees and crore spelled out, "year on year" instead of "YoY", at most five items, each
followed by who to call.
"""

from __future__ import annotations

import re

from app.db import session
from app.intel.digest import build_digest

MAX_ITEMS = 5
WORDS_PER_MINUTE = 150

_SAY = [
    (r"₹\s?|\bRs\.?\s?|\bINR\s?", "rupees "),
    (r"(\d)\+", r"\1 plus"),
    (r"\bCr\b", "crore"),
    (r"\bYoY\b", "year on year"),
    (r"\bQoQ\b", "quarter on quarter"),
    (r"\bPAT\b", "profit"),
    (r"\bPBT\b", "pre-tax profit"),
    (r"\bFY\s?(\d{2})\b", r"F Y \1"),
    (r"\bH1\b", "first half"),
    (r"\bH2\b", "second half"),
    (r"(\d)\s?×", r"\1 times"),
    (r"%", " percent"),
    (r"&", " and "),
]
_SPANS = {
    "24h": "the last day",
    "3d": "the last three days",
    "7d": "the last week",
    "14d": "the last two weeks",
    "21d": "the last three weeks",
    "30d": "the last month",
}
_TITLES = ("Dr", "Mr", "Mrs", "Ms")


def spoken(text: str) -> str:
    for pat, rep in _SAY:
        text = re.sub(pat, rep, text)
    return re.sub(r"\s+", " ", text).strip()


def short(company: str) -> str:
    """Same rule as the app's shortName, so the brief names companies as the cards do."""
    s = re.sub(
        r"\b(Limited|Ltd\.?|India|Industries|Company|Technologies|Technology)\b", "", company
    )
    return re.sub(r"\s+", " ", s).strip(" (")


def _first(name: str) -> str:
    parts = name.split()
    if parts and parts[0].rstrip(".") in _TITLES:
        return " ".join(parts[:2])
    return parts[0] if parts else name


def results_takeaway(r: dict) -> str | None:
    """Same rule as the card headline (frontend resultsTakeaway)."""
    rows = {x["metric"]: x for x in r.get("rows", [])}
    p = (rows.get("pat") or {}).get("yoy")
    v = (rows.get("revenue") or {}).get("yoy")
    top = "interest income" if r.get("revenue_label") == "Interest earned" else "revenue"
    note = (rows.get("pat") or {}).get("yoy_note")
    if p is None and note and v is not None:
        way = "up" if v >= 0 else "down"
        return f"{note[0].upper() + note[1:]} year on year; {top} {way} {abs(v):.0f}%"
    if p is None or v is None:
        return None
    P, V = f"{abs(p):.0f}%", f"{abs(v):.0f}%"
    if p < 0 <= v:
        return f"profit down {P} year on year even as {top} grew {V}"
    if v < 0 <= p:
        return f"profit up {P} year on year despite {top} falling {V}"
    if p < 0:
        return f"{top} down {V}, profit down {P} year on year"
    return f"profit up {P} year on year on {V} {top} growth"


def _names(symbols: set[str]) -> dict[str, str]:
    if not symbols:
        return {}
    q = ",".join("?" * len(symbols))
    with session() as db:
        rows = db.execute(
            f"SELECT symbol, name FROM companies WHERE symbol IN ({q})", tuple(symbols)
        )
        return {r["symbol"]: r["name"] or r["symbol"] for r in rows}


def build_brief(window: str = "24h", start: str | None = None, end: str | None = None) -> dict:
    d = build_digest(window, start=start, end=end)
    cards = d["cards"]
    n, routine = len(cards), d["counts"]["routine"]
    span = "the dates you picked" if start else _SPANS.get(window, "the last month")
    if n == 0:
        intro = f"Nothing material across your portfolio in {span}. Quiet is good."
    else:
        if n == 1:
            lead = "one thing matters"
        elif n > MAX_ITEMS:
            lead = f"{MAX_ITEMS} things matter most"
        else:
            lead = f"{n} things matter"
        tail = f", and {routine} routine filings are folded away" if routine else ""
        intro = f"Across your portfolio in {span}, {lead}{tail}."
    lines = [{"id": "intro", "text": intro}]

    named: set[str] = set()
    last = None
    for c in cards[:MAX_ITEMS]:
        headline = (c.get("results") and results_takeaway(c["results"])) or c["title"].rstrip(".")
        name = short(c["company"])
        text = f"Also at {name}: {headline}." if name == last else f"{name}: {headline}."
        last = name
        if c.get("level") == "important" and c["kind"] != "results":
            text = f"Important. {text}"
        h = (c.get("helpers") or [None])[0]
        if h and c["symbol"] not in named and (c["kind"] != "filing" or h["score"] >= 0.5):
            named.add(c["symbol"])
            text += f" {_first(h['contact']['name'])} is your best call on this."
        lines.append({"id": str(c["id"]), "text": spoken(text)})

    moves = [a for a in d["alerts"] if a["kind"] in ("price", "volume")][:3]
    if moves:
        names = _names({a["symbol"] for a in moves})
        bits = []
        for a in moves:
            pct = a.get("price_change_pct")
            move = "" if pct is None else f"{'up' if pct >= 0 else 'down'} {abs(pct):.1f}%"
            heavy = " on heavy volume" if a["kind"] == "volume" else ""
            bits.append(f"{short(names.get(a['symbol'], a['symbol']))} {move}".strip() + heavy)
        lines.append({"id": "moves", "text": spoken("Price moves: " + "; ".join(bits) + ".")})

    lines.append(
        {"id": "outro", "text": "That's the brief. Everything else is on the Today screen."}
    )
    words = sum(len(x["text"].split()) for x in lines)
    return {"window": d["window"], "lines": lines, "seconds": round(words * 60 / WORDS_PER_MINUTE)}
