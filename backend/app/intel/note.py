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
    "Larsen & Toubro": "L&T",
    "Tata Motors Passenger Vehicles": "Tata Motors",
    "One 97 Communications": "Paytm",
    "Bharat Heavy Electricals": "BHEL",
    "Jio Financial Services": "Jio Financial",
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
    return False, f"It's {held}, a small holding."


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

    book = get_positions()
    pos = {p["symbol"]: p for p in book["positions"]}
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
    d["lead"] = lead(d, book)
    return d


def _span(w: dict) -> str:
    name = w.get("name") or ""
    if name == "24h":
        return "in the last day"
    m = re.fullmatch(r"(\d+)d", name)
    if m:
        return f"in the last {m.group(1)} days"
    a, b = (datetime.fromisoformat(w[k]) for k in ("start", "end"))
    return f"between {a.day} {a:%b} and {b.day} {b:%b}"


def _cap(t: str) -> str:
    return t[:1].upper() + t[1:]


def _again(text: str, name: str) -> str:
    """A second line about the same company, without repeating its name."""
    for head, repl in ((possessive(name) + " ", "Its "), (name + ": ", ""), (name + " ", "It ")):
        if text.startswith(head):
            rest = text[len(head) :]
            if repl:
                return repl + rest
            keep = rest[1:2].isupper() or rest[1:2].isdigit()  # "H1 FY27", "Q2"
            return "Also, " + (rest if keep else rest[:1].lower() + rest[1:])
    return text


def _size(c: dict, book: dict) -> str:
    """'0.5% of your portfolio, ₹27,440'"""
    pos = next((p for p in book["positions"] if p["symbol"] == c["symbol"]), None)
    money = rupees(pos["value"]) if pos else None
    w = c.get("weight") or 0.0
    pct = f"{w:.1f}%" if w < 1 else f"{w:.0f}%"
    return f"{pct} of your portfolio" + (f", {money}" if money else "")


def _day(book: dict, moves: list[str]) -> str | None:
    """The last close: the portfolio's move in rupees, and its biggest movers."""
    if not book.get("as_of") or not book.get("positions"):
        return None
    dt = datetime.fromisoformat(book["as_of"])
    g, gp = book["day_gain"], book["day_gain_pct"]
    if abs(gp) < 0.05:
        head = f"Your portfolio ended {dt.day} {dt:%b}, the last close, about flat"
    else:
        word = "up" if g > 0 else "down"
        head = (
            f"Your portfolio ended {dt.day} {dt:%b}, the last close, {word} "
            f"{abs(gp):.1f}% ({rupees(abs(g))}) at {rupees(book['value'])}"
        )
    big = sorted(
        (p for p in book["positions"] if abs(p["day_pct"]) >= 2),
        key=lambda p: -abs(p["day_pct"]),
    )[:2]
    if not big:
        return head + "."
    unexplained = " ".join(moves)
    said, prev = [], None
    for p in big:
        n = short(p["name"])
        verb = "rose" if p["day_pct"] > 0 else "fell"
        why = " with no filing to explain it" if n in unexplained else ""
        said.append(f"{n}{'' if verb == prev else ' ' + verb} {abs(p['day_pct']):.1f}%{why}")
        prev = verb
    return f"{head}; {' and '.join(said)}."


PARA = "\u00b6"


def lead(d: dict, book: dict | None = None) -> str:
    """A short paragraph a fund manager could read aloud: the last close, what came in and
    whether any of it needs a decision, the items themselves, what is still open from
    earlier, and what was set aside."""
    book = book or {"positions": []}
    act = [c for c in d["cards"] if c["band"] == "act"]
    know = [c for c in d["cards"] if c["band"] == "know"]
    carry = d.get("carry") or []
    moves = d.get("moves_note") or []
    span = _span(d["window"])
    parts: list[str] = []
    # the last close belongs in today's note, not in one about a past fortnight
    end = datetime.fromisoformat(d["window"]["end"]).date().isoformat()
    day = _day(book, moves) if end >= (book.get("as_of") or "9999") else None
    if day:
        parts += [day, PARA]
    named_moves = " ".join(parts)
    n_items = len(act) + len(know)
    if act:
        n = len(act)
        parts.append(
            f"{_cap(span)}, {n_items} {'item matters' if n_items == 1 else 'items matter'}"
            f" and {NUMBER_WORDS[min(n, 6)].split()[0].lower() if n <= 6 else n}"
            f" {'needs' if n == 1 else 'need'} a decision."
        )
        last = None
        for c in act[:2]:
            same = c["short"] == last
            parts.append(_again(c["line"], c["short"]) if same else c["line"])
            if not same:
                parts.append(f"{c['short']} is {_size(c, book)}.")
            last = c["short"]
        rest = list(dict.fromkeys(c["short"] for c in act[2:]))
        if rest:
            parts.append(f"Also at {' and '.join(rest[:2])}: see Needs you below.")
    elif know:
        parts.append(
            f"{_cap(span)}, {n_items} {'item matters' if n_items == 1 else 'items matter'} and"
            " none needs a decision."
        )
    else:
        n = d["counts"]["filings"]
        parts.append(f"{_cap(span)}, nothing in {n} filing{'s' if n != 1 else ''} needs you.")
    if not act and know:
        shown, last = [], None
        for c in know[:3]:
            shown.append(_again(c["line"], c["short"]) if c["short"] == last else c["line"])
            last = c["short"]
        parts.extend(shown)
        cos = list(dict.fromkeys(c["short"] for c in know[:3]))
        if len(cos) == 1 and not know[0]["in_portfolio"]:
            parts.append(f"You follow {cos[0]} but don't hold it.")
        elif len(cos) == 1:
            c = know[0]
            if "small holding" in c["stake"]:
                parts.append(
                    f"{cos[0]} is a small holding ({_size(c, book)}), so there's nothing to act on."
                )
            else:
                parts.append(f"{cos[0]} is {_size(c, book)}.")
        elif cos:
            sizes = []
            for co in cos:
                c = next(k for k in know if k["short"] == co)
                w = c.get("weight") or 0.0
                pct = f"{w:.1f}%" if w < 1 else f"{w:.0f}%"
                sizes.append(f"{co} {pct}" if sizes else f"{co} is {pct} of your portfolio")
            parts.append(
                ", ".join(sizes[:-1]) + f" and {sizes[-1]}." if len(sizes) > 1 else sizes[0] + "."
            )
    if carry or moves or (d.get("set_aside") or {}).get("count"):
        parts.append(PARA)
    if carry:
        n = len(carry[:2])
        named = [
            f"{possessive(short(c['company']))} {EVENT_WORD[c['category']]} "
            f"({c['weight']:.0f}%{' of your portfolio' if i == 0 else ''})"
            for i, c in enumerate(carry[:2])
        ]
        lead_in = "One earlier event" if n == 1 else "Two earlier events"
        parts.append(
            f"{lead_in} at larger holdings {'is' if n == 1 else 'are'} still open: "
            f"{' and '.join(named)}."
        )
    left = [m for m in moves if m.split(" ")[0] not in named_moves]
    parts.extend(left)
    aside = (d.get("set_aside") or {}).get("count") or 0
    if aside:
        parts.append(
            f"{aside} routine filing{'s were' if aside != 1 else ' was'} set aside, "
            "listed at the end."
        )
    # paragraphs: the last close; what came in; what is still open and what was set aside
    text = " ".join(parts).replace(f" {PARA} ", "\n\n").replace(PARA, "")
    return re.sub(r"(\n\n)+", "\n\n", text).strip()
