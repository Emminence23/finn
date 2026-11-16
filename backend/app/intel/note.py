"""Today as a written note: a lead sentence, then Act / Know / Set aside (code, no AI).

The digest ranks cards; this turns the ranking into something read in ten seconds. Every
sentence is assembled in code from fields FINN already computed (results rows, position
size, the level rule, contacts), so nothing here can say what the data doesn't.

Bands, each one rule:
- Act: Important, and a real position (at least half an equal share of the portfolio).
  These are the items that could change a decision.
- Know: everything else worth a line: Important at a small position, Notable, followed
  companies outside the portfolio.
- Set aside: Notable items FINN rates under 30 for how much they matter, with no price
  reaction, plus the routine filings. Counted and named, never hidden.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta

from app.db import session
from app.intel.taxonomy import CATEGORY_WEIGHT
from app.intel.units import normalise

REAL_POSITION = 0.5  # of an equal share: below this a holding is "small"
SET_ASIDE_BELOW = 30  # materiality under which a Notable card is set aside
CARRY_DAYS = 14  # "still open": Important events at real positions this far back
CARRY_CATEGORIES = ("management_change", "M&A", "litigation", "fund_raise", "capex")
CARRY_MIN_MATERIALITY = 70
EVENT_WORD = {
    "management_change": "management change",
    "M&A": "deal",
    "litigation": "legal case",
    "fund_raise": "fund raise",
    "capex": "expansion",
}
NUMBER_WORDS = [
    "Nothing",
    "One thing",
    "Two things",
    "Three things",
    "Four things",
    "Five things",
    "Six things",
    "Seven things",
    "Eight things",
    "Nine things",
    "Ten things",
]


# names people actually say, where trimming legal words isn't enough
SPOKEN = {
    "Cholamandalam Investment and Finance": "Cholamandalam",
    "CG Power and Industrial Solutions": "CG Power",
    "Sun Pharmaceutical": "Sun Pharma",
}


def short(company: str) -> str:
    s = _trim(company)
    return SPOKEN.get(s, s)


def _trim(company: str) -> str:
    s = re.sub(
        r"\b(Limited|Ltd\.?|India|Industries|Company|Technologies|Technology)\b", "", company
    )
    return re.sub(r"\s+", " ", s.replace("()", "")).strip(" (")


def possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def rupees(v: float | None) -> str | None:
    if not v:
        return None
    if v >= 1e7:
        return f"₹{v / 1e7:.1f} Cr"
    if v >= 1e5:
        return f"₹{v / 1e5:.1f} lakh"
    return f"₹{round(v):,}"


def _pct(v: float) -> str:
    return f"{abs(v):.0f}%"


def line(card: dict) -> str:
    """What happened, as a sentence with the company as its subject."""
    name = short(card["company"])
    r = card.get("results")
    if card["kind"] == "results" and r:
        rows = {x["metric"]: x for x in r.get("rows", [])}
        p, v = (rows.get(m, {}) for m in ("pat", "revenue"))
        top = "interest income" if r.get("revenue_label") == "Interest earned" else "revenue"
        if p.get("yoy") is not None and v.get("yoy") is not None:
            pw = "rose" if p["yoy"] >= 0 else "fell"
            vw = "up" if v["yoy"] >= 0 else "down"
            return (
                f"{possessive(name)} profit {pw} {_pct(p['yoy'])} from a year ago, "
                f"on {top} {vw} {_pct(v['yoy'])}."
            )
        if p.get("yoy_note"):
            return f"{possessive(name)} profit: {p['yoy_note']} from a year ago."
    title = normalise(card["title"] or "").rstrip(".")
    for full in (card["company"], _trim(card["company"])):
        if title.startswith(full + " "):  # "Cholamandalam Investment and Finance approved"
            title = name + title[len(full) :]
            break
    first = title.split(" ", 1)[0] if title else ""
    if first.endswith("ed") and first[:1].isupper() and " " in title:
        return f"{name} {first.lower()} {title.split(' ', 1)[1]}."
    if title.startswith("Board "):
        return f"{possessive(name)} board {title[6:]}."
    if title.lower().startswith(name.lower()) or not title:
        return f"{title or name}."
    return f"{name}: {title}."


def stake(card: dict, n_held: int, value: float | None) -> tuple[bool, str]:
    """(is a real position, how big it is in words)."""
    if not card["in_portfolio"]:
        return False, "Not in your portfolio; you follow it."
    w = card.get("weight") or 0.0
    real = w >= REAL_POSITION * 100 / max(n_held, 1)
    size = f"{w:.1f}%" if w < 1 else f"{w:.0f}%"
    money = rupees(value)
    held = f"{size} of your portfolio" + (f" ({money})" if money else "")
    if real:
        return True, f"It's {held}."
    return False, f"It's {held}, so read it rather than act on it."


def questions(card: dict, helper: dict) -> list[str]:
    """Two questions worth asking this contact about this card, from its own facts."""
    name = short(card["company"])
    inside = any("Works at" in r for r in helper.get("reasons", [])[:1]) or helper.get("insider")
    qs: list[str] = []
    r = card.get("results")
    if card["kind"] == "results" and r:
        rows = {x["metric"]: x for x in r.get("rows", [])}
        p, v = rows.get("pat", {}), rows.get("revenue", {})
        if p.get("yoy") is not None and v.get("yoy") is not None and (p["yoy"] < 0 <= v["yoy"]):
            qs.append(
                f"Revenue grew but profit fell {_pct(p['yoy'])}. Is that costs, mix or a one-off?"
            )
        elif p.get("yoy") is not None:
            qs.append(f"Is a {_pct(p['yoy'])} move in profit the new run-rate or a one-off?")
        qs.append(f"What would make you change your view of {name} after this quarter?")
    elif card["kind"] == "management_change":
        inc = [x for x in card.get("people") or [] if x["direction"] == "incoming"]
        who = inc[0]["name"] if inc else "the new person"
        qs.append(f"What will {who} change first at {name}?")
        qs.append("Is the departure planned, or is there more to it?")
    else:
        qs.append(f"How much does this matter to {possessive(name)} numbers, and when?")
        qs.append("Is the market reading it right?")
    if inside:
        qs = [q + " (public information only)" if i == 0 else q for i, q in enumerate(qs)]
    return qs[:2]


def _carry(t0: datetime, real: dict[str, dict], carded: set[tuple[str, str]]) -> list[dict]:
    """Important events at real positions from the two weeks before the window, still worth
    keeping in view on a quiet day (a closure order doesn't stop mattering after 24 hours)."""
    if not real:
        return []
    q = ",".join("?" * len(real))
    cats = ",".join("?" * len(CARRY_CATEGORIES))
    with session() as db:
        rows = db.execute(
            f"""SELECT id, symbol, ts, category, summary, subject, pdf_url, materiality
            FROM announcements WHERE ts >= ? AND ts < ? AND symbol IN ({q})
            AND category IN ({cats}) ORDER BY materiality DESC, ts DESC""",
            (
                (t0 - timedelta(days=CARRY_DAYS)).isoformat(),
                t0.isoformat(),
                *real,
                *CARRY_CATEGORIES,
            ),
        ).fetchall()
    out, seen = [], set(carded)
    by_event: dict[tuple[str, str], list] = {}
    for r in rows:
        by_event.setdefault((r["symbol"], r["category"]), []).append(r)
    for r in rows:
        k = (r["symbol"], r["category"])
        if k in seen or (r["materiality"] or 0) < CARRY_MIN_MATERIALITY:
            continue  # later, smaller filings of the event still show as its update
        seen.add(k)
        co = real[r["symbol"]]
        newest = max(by_event[k], key=lambda x: x["ts"])
        update = None
        if newest["id"] != r["id"]:
            dt = datetime.fromisoformat(newest["ts"])
            update = (
                f"Latest, {dt.day} {dt:%b}: "
                + normalise(newest["summary"] or newest["subject"]).rstrip(".")
                + "."
            )
        out.append(
            {
                "update": update,
                "id": r["id"],
                "symbol": r["symbol"],
                "company": co["company"],
                "ts": r["ts"],
                "category": r["category"],
                "line": line(
                    {
                        "company": co["company"],
                        "kind": "filing",
                        "title": r["summary"] or r["subject"],
                    }
                ),
                "weight": co["weight"],
                "materiality": r["materiality"],
                "pdf_url": r["pdf_url"],
            }
        )
    # size of the position x how much it matters x how much the kind of event matters
    out.sort(key=lambda x: -x["weight"] * x["materiality"] * CATEGORY_WEIGHT[x["category"]])
    for x in out:
        x.pop("materiality")
    return out[:3]


def _unexplained_moves(d: dict, names: dict[str, str]) -> list[str]:
    """Price moves at holdings with no filing to explain them: none in the window's cards,
    and none from that company in the few days before the move (a filing just before the
    window still explains it)."""
    from app.intel.digest import REACTION_DAYS

    carded = {c["symbol"] for c in d["cards"]}
    out = []
    for a in sorted(d["alerts"], key=lambda a: -abs(a.get("value") or 0)):
        if a["kind"] != "price" or a["symbol"] in carded or a["symbol"] not in names:
            continue
        dt = datetime.fromisoformat(a["ts"])
        with session() as db:
            filed = db.execute(
                "SELECT 1 FROM announcements WHERE symbol=? AND ts BETWEEN ? AND ? "
                "AND category NOT IN "
                "('investor_meetings', 'postal_ballot', 'agm_egm', 'unclassified') "
                "LIMIT 1",
                (
                    a["symbol"],
                    (dt - timedelta(days=REACTION_DAYS)).date().isoformat(),
                    f"{dt.date().isoformat()}T15:30:00",
                ),
            ).fetchone()
        carded.add(a["symbol"])
        if filed:
            continue
        word = "rose" if a["value"] > 0 else "fell"
        out.append(
            f"{short(names[a['symbol']])} {word} {abs(a['value']):.1f}% on "
            f"{dt.day} {dt:%b} with no filing to explain it."
        )
    return out[:2]


def annotate(d: dict) -> dict:
    """Adds `band`, `line`, `stake` and contact questions to each card, and the note's
    `lead`, `carry`, `moves_note` and `set_aside` summary to the digest."""
    from app.portfolio.holdings import get_positions

    pos = {p["symbol"]: p for p in get_positions()["positions"]}
    n_held = len(pos) or 1
    for c in d["cards"]:
        c["short"] = short(c["company"])
        c["line"] = line(c)
        real, c["stake"] = stake(c, n_held, (pos.get(c["symbol"]) or {}).get("value"))
        moved = any(a["kind"] == "price" for a in c["alerts"])
        if c["level"] == "important" and real:
            c["band"] = "act"
        elif (
            c["level"] == "notable"
            and (c["materiality"] or 0) < SET_ASIDE_BELOW
            and not moved
            and not c.get("unsure")
        ):
            c["band"] = "aside"
        else:
            c["band"] = "know"
        if c["helpers"]:
            c["helpers"][0]["ask"] = questions(c, c["helpers"][0])

    t0 = datetime.fromisoformat(d["window"]["start"])
    real_pos = {
        s: {"company": p["name"], "weight": round(100 * p["weight"], 1)}
        for s, p in pos.items()
        if p["weight"] >= REAL_POSITION / n_held
    }
    carded = {(c["symbol"], c["category"]) for c in d["cards"]}
    d["carry"] = _carry(t0, real_pos, carded)
    d["moves_note"] = _unexplained_moves(d, {s: p["name"] for s, p in pos.items()})

    aside = [c for c in d["cards"] if c["band"] == "aside"]
    kinds = Counter(r["category"] for r in d["routine"]["items"])
    d["set_aside"] = {
        "count": d["routine"]["count"] + len(aside),
        "low_rated": len(aside),
        "by_kind": [{"category": k, "count": n} for k, n in kinds.most_common()],
        "rule": f"Routine paperwork, and items FINN rates under {SET_ASIDE_BELOW} of 100 "
        "with no price reaction.",
    }
    d["lead"] = lead(d)
    return d


def lead(d: dict) -> str:
    """One paragraph a fund manager could read aloud: how many things need them, the first
    of them with its size, anything still open from earlier, and unexplained moves."""
    act = [c for c in d["cards"] if c["band"] == "act"]
    know = [c for c in d["cards"] if c["band"] == "know"]
    carry = d.get("carry") or []
    moves = " ".join(d.get("moves_note") or [])
    parts: list[str] = []
    if act:
        n = len(act)
        count = NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else f"{n} things"
        parts.append(
            f"{count} need{'s' if n == 1 else ''} you" + ("; the biggest:" if n > 3 else ".")
        )
        parts.append(f"{act[0]['line']} {act[0]['stake']}")
        others = list(dict.fromkeys(c["short"] for c in act[1:] if c["short"] != act[0]["short"]))
        if others and n <= 3:
            parts.append(f"Also {' and '.join(others[:2])}.")
    elif carry:
        parts.append("Nothing new needs a decision.")
        if know:
            k = know[0]
            parts.append(f"{k['line']} {k['stake']}")
        named = [
            f"{possessive(short(c['company']))} {EVENT_WORD[c['category']]}" for c in carry[:2]
        ]
        parts.append(f"Still open from earlier: {' and '.join(named)}.")
    elif know:
        k = know[0]
        parts.append("Nothing needs a decision.")
        parts.append(f"The biggest item: {k['line']} {k['stake']}")
    else:
        n = d["counts"]["filings"]
        parts.append(f"Quiet. Nothing in {n} filing{'s' if n != 1 else ''} needs you.")
    if moves:
        parts.append(moves)
    return " ".join(parts)
