"""The Network layer (FR-NET). Pure code over the owner-scoped tables: no LLM sees the
investor's contacts (D8, NFR-06).

Overlaps are derived from roles and education. Confidence is explicit:
  confirmed: same organisation and overlapping years
  possible:  same organisation, but at least one side's years are unknown
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from app.clock import now
from app.db import session
from app.ingest.universe import load_universe
from app.network.companies import company_aliases, company_links, normalise_company, resolve_symbol
from app.network.owner import ACCOUNTS, PUBLIC, current_owner, investor_id

ME = "me"  # the default account's investor; other accounts use investor_id(owner)
CURRENT_YEAR = date.today().year


@dataclass
class Role:
    company: str
    symbol: str | None
    title: str | None
    start: int | None
    end: int | None  # None = current

    @property
    def key(self) -> str:
        return self.symbol or normalise_company(self.company)

    def span(self) -> str:
        if self.start is None:
            return "years not disclosed"
        return f"{self.start}–{self.end or 'present'}"


@dataclass
class School:
    school: str
    program: str | None
    start: int | None
    end: int | None

    @property
    def key(self) -> str:
        return normalise_company(self.school)


@dataclass
class Person:
    id: str
    name: str
    headline: str | None
    is_contact: bool
    themes: list[str]
    bio: str | None
    roles: list[Role] = field(default_factory=list)
    education: list[School] = field(default_factory=list)
    relationship: dict | None = None  # 1st-degree link to the investor
    knows: list[dict] = field(default_factory=list)  # explicit edges to other people


@dataclass
class Overlap:
    kind: str  # worked_together | same_employer | studied_together | same_school
    org: str
    detail: str
    confidence: str  # confirmed (years intersect) | possible (years unknown)
    strength: float
    # N-2: every overlap is *inferred* from two career records. It is worded as an overlap
    # ("Both at X 2014–2018"), never as "worked with" or "knows". Only links the investor
    # recorded are "declared".
    basis: str = "inferred"


# ------------------------------------------------------------------ loading
def load_people(owner: str | None = None) -> dict[str, Person]:
    """The owner's contacts and investor, plus people from public filings (N-7)."""
    owner = owner or current_owner()
    with session() as db:
        people = {
            r["id"]: Person(
                r["id"],
                r["name"],
                r["headline"],
                bool(r["is_contact"]),
                json.loads(r["themes_json"] or "[]"),
                r["bio"],
            )
            for r in db.execute("SELECT * FROM people WHERE owner_id IN (?, ?)", (owner, PUBLIC))
        }
        # only this account's and public people's rows ever leave the database
        mine = (
            "SELECT {t}.* FROM {t} JOIN people p ON p.id = {t}.person_id WHERE p.owner_id IN (?, ?)"
        )
        for r in db.execute(mine.format(t="roles"), (owner, PUBLIC)):
            if r["person_id"] in people:
                people[r["person_id"]].roles.append(
                    Role(r["company"], r["symbol"], r["title"], r["start_year"], r["end_year"])
                )
        for r in db.execute(mine.format(t="education"), (owner, PUBLIC)):
            if r["person_id"] in people:
                people[r["person_id"]].education.append(
                    School(r["school"], r["program"], r["start_year"], r["end_year"])
                )
        for r in db.execute("SELECT * FROM relationships WHERE owner_id=?", (owner,)):
            p = people.get(r["person_id"])
            if p is None:
                continue
            if r["other_id"] is None:
                p.relationship = {
                    "type": r["type"],
                    "strength": r["strength"],
                    "last_contact": r["last_contact"],
                    "email": r["email"],
                    "phone": r["phone"],
                }
            else:
                p.knows.append(
                    {"person": r["other_id"], "context": r["type"], "strength": r["strength"]}
                )
    _attach_contexts(people, owner)
    return people


def investor(people: dict[str, Person]) -> Person:
    """The one investor loaded with this owner's network."""
    return next(p for p in people.values() if p.id == ME or p.id.startswith("me@"))


def _attach_contexts(people: dict[str, Person], owner: str) -> None:
    """Relationship 'context' notes live in the network fixture (not a DB column)."""
    from app.ingest.universe import fixtures_dir

    if owner not in ACCOUNTS:
        return  # a sandbox keeps its "how you know them" in the relationship type
    path = fixtures_dir() / ACCOUNTS[owner]
    if not path.exists():
        return
    for c in json.loads(path.read_text())["contacts"]:
        if c["id"] in people and people[c["id"]].relationship is not None:
            people[c["id"]].relationship["context"] = c["relationship"].get("context")


# ------------------------------------------------------------------ overlaps
def _years_overlap(a0, a1, b0, b1) -> tuple[int, int] | None:
    if a0 is None or b0 is None:
        return None
    lo, hi = max(a0, b0), min(a1 or CURRENT_YEAR, b1 or CURRENT_YEAR)
    return (lo, hi) if lo <= hi else None


def _same_org(a: Role, b: Role) -> bool:
    if a.symbol and b.symbol:
        return a.symbol == b.symbol
    return normalise_company(a.company) == normalise_company(b.company)


def overlaps(a: Person, b: Person) -> list[Overlap]:
    found: list[Overlap] = []
    for ra in a.roles:
        for rb in b.roles:
            if not _same_org(ra, rb):
                continue
            yrs = _years_overlap(ra.start, ra.end, rb.start, rb.end)
            if yrs:
                found.append(
                    Overlap(
                        "worked_together",
                        rb.company,
                        f"Both at {rb.company} {yrs[0]}–{yrs[1]}",
                        "confirmed",
                        0.7,
                    )
                )
            elif ra.start is not None and rb.start is not None:
                continue  # same employer, provably different years: not a useful link
            else:
                found.append(
                    Overlap(
                        "same_employer",
                        rb.company,
                        f"Both worked at {rb.company} (tenure overlap not disclosed)",
                        "possible",
                        0.35,
                    )
                )
    for sa in a.education:
        for sb in b.education:
            if sa.key != sb.key:
                continue
            yrs = _years_overlap(sa.start, sa.end, sb.start, sb.end)
            if yrs:
                found.append(
                    Overlap(
                        "studied_together",
                        sb.school,
                        f"Both at {sb.school} {yrs[0]}–{yrs[1]}",
                        "confirmed",
                        0.55,
                    )
                )
            else:
                found.append(
                    Overlap("same_school", sb.school, f"Both {sb.school} alumni", "possible", 0.2)
                )
    return sorted(found, key=lambda o: -o.strength)


# ------------------------------------------------------------------ paths (FR-NET-04)
def paths_to(target_id: str, people: dict[str, Person] | None = None, limit: int = 5) -> dict:
    people = people or load_people()
    return paths_to_person(people[target_id], people, limit)


def _company_name(symbol: str) -> str:
    with session() as db:
        row = db.execute("SELECT name FROM companies WHERE symbol=?", (symbol,)).fetchone()
    return row["name"] if row and row["name"] else symbol


def person_from_extraction(p: dict, symbol: str, key: str) -> Person:
    """A transient Person built from an LLM-extracted filing person (not stored)."""
    roles = [Role(_company_name(symbol), symbol, p.get("role"), None, None)]
    roles += [
        Role(
            r["company"],
            resolve_symbol(r["company"]),
            r.get("title"),
            r.get("start_year"),
            r.get("end_year"),
        )
        for r in p.get("prior_roles", [])
    ]
    schools = [School(e["school"], e.get("program"), None, None) for e in p.get("education", [])]
    return Person(key, p["name"], p.get("role"), False, [], p.get("bio"), roles, schools)


# ------------------------------------------------------------------ identity (FR-NET-05)
def normalise_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z ]+", " ", name.lower()).split())


def identity_key(target: Person) -> str:
    """Stable across rebuilds: the filing company plus the normalised name."""
    sym = next((r.symbol for r in target.roles if r.end is None and r.symbol), "")
    return f"{sym}:{normalise_name(target.name)}"


def _answers(owner: str, key: str) -> dict[str, str]:
    with session() as db:
        return {
            r["contact_id"]: r["verdict"]
            for r in db.execute(
                "SELECT contact_id, verdict FROM identity_answers "
                "WHERE owner_id=? AND target_key=?",
                (owner, key),
            )
        }


def same_name_contacts(target: Person, people: dict[str, Person]) -> list[dict]:
    """Contacts who share a filing person's name. A shared name alone proves nothing, so FINN
    only says "possible match"; it says "likely" when an employer or school also agrees, and
    asserts identity only after the investor says so. "Not them" hides the match for good."""
    name = normalise_name(target.name)
    if not name or target.is_contact:
        return []
    answers = _answers(current_owner(), identity_key(target))
    t_orgs = {r.key for r in target.roles} | {s.key for s in target.education}
    out = []
    for c in people.values():
        if not c.is_contact or normalise_name(c.name) != name:
            continue
        verdict = answers.get(c.id)
        if verdict == "different":
            continue
        agrees = sorted(
            {r.company for r in c.roles if r.key in t_orgs}
            | {s.school for s in c.education if s.key in t_orgs}
        )
        status = "confirmed" if verdict == "same" else "likely" if agrees else "possible"
        out.append({"contact": _contact_summary(c), "status": status, "agrees": agrees})
    return out


def answer_identity(target_id: str, contact_id: str, verdict: str) -> dict:
    if verdict not in ("same", "different"):
        raise ValueError("verdict must be 'same' or 'different'")
    people = load_people()
    target, contact = people.get(target_id), people.get(contact_id)
    if target is None or contact is None or not contact.is_contact:
        raise KeyError("unknown person")
    with session() as db:
        db.execute(
            "INSERT OR REPLACE INTO identity_answers VALUES (?,?,?,?)",
            (current_owner(), identity_key(target), contact_id, verdict),
        )
    return {"target": target_id, "contact": contact_id, "verdict": verdict}


def paths_to_person(target: Person, people: dict[str, Person], limit: int = 5) -> dict:
    target_id = target.id
    me = investor(people)
    direct = [o.__dict__ for o in overlaps(me, target)]
    same_name = same_name_contacts(target, people)
    for m in same_name:
        if m["status"] == "confirmed":
            c = m["contact"]
            direct.insert(
                0,
                {
                    "kind": "contact",
                    "org": None,
                    "confidence": "confirmed",
                    "basis": "declared",
                    "detail": f"Your {c['relationship'] or 'contact'} {c['name']} (you confirmed)",
                    "strength": c["strength"] or 0.5,
                },
            )
    if target.relationship:
        direct.insert(
            0,
            {
                "kind": "contact",
                "org": None,
                "confidence": "confirmed",
                "basis": "declared",
                "detail": f"Your {target.relationship['type']}",
                "strength": target.relationship["strength"],
            },
        )
    namesakes = {m["contact"]["id"] for m in same_name}  # shown apart, never as a path
    via: list[dict] = []
    for c in people.values():
        if not c.is_contact or c.id == target_id or not c.relationship or c.id in namesakes:
            continue
        explicit = [k for k in c.knows if k["person"] == target_id]
        links = [
            {
                "kind": "knows",
                "detail": k["context"],
                "confidence": "confirmed",
                "basis": "declared",  # recorded by the investor, not inferred
                "strength": k["strength"],
            }
            for k in explicit
        ]
        links += [o.__dict__ for o in overlaps(c, target)]
        if not links:
            continue
        best = max(links, key=lambda x: x["strength"])
        via.append(
            {
                "contact": _contact_summary(c),
                "link": best,
                "other_links": [x for x in links if x is not best][:2],
                "strength": round(c.relationship["strength"] * best["strength"], 2),
            }
        )
    via.sort(key=lambda v: -v["strength"])
    return {
        "target": _person_summary(target),
        "direct": direct,
        "via": via[:limit],
        "same_name": same_name,
    }


# ------------------------------------------------------------------ who can help (FR-NET-03)
def _company_names(symbol: str) -> set[str]:
    return {normalise_company(n) for n in [symbol, *company_aliases().get(symbol, [])]}


def _role_matches(role: Role, symbol: str) -> bool:
    return role.symbol == symbol or normalise_company(role.company) in _company_names(symbol)


def _theme_for(symbol: str) -> str | None:
    for p in load_universe()["portfolio"]:
        if p["symbol"] == symbol:
            return p["theme"]
    return None


def who_can_help(
    symbol: str,
    people: dict[str, Person] | None = None,
    limit: int = 5,
    extra_themes: list[str] | None = None,
) -> list[dict]:
    people = people or load_people()
    links = company_links().get(symbol, {})
    linked = {}
    for kind, names in links.items():
        for n in names:
            linked[normalise_company(n)] = kind
            if s := resolve_symbol(n):
                linked[s] = kind
    themes = {t.lower() for t in [_theme_for(symbol), *(extra_themes or [])] if t}

    ranked = []
    for c in people.values():
        if not c.is_contact or not c.relationship:
            continue
        reasons: list[tuple[float, str]] = []
        insider = False
        for r in c.roles:
            if _role_matches(r, symbol):
                if r.end is None:
                    insider = True
                    reasons.append((1.0, f"Works at {r.company} as {r.title}"))
                else:
                    decay = max(0.55, 1 - 0.04 * (CURRENT_YEAR - r.end))
                    reasons.append((0.85 * decay, f"Was {r.title} at {r.company} ({r.span()})"))
            elif kind := linked.get(r.key) or linked.get(normalise_company(r.company)):
                w = 0.6 if kind == "competitor" else 0.55
                tense = "Is" if r.end is None else "Was"
                reasons.append((w, f"{tense} at {r.company}, a {kind} ({r.span()})"))
        matched = sorted(t for t in c.themes if t.lower() in themes)
        if matched:
            reasons.append((0.35, f"Tracks {', '.join(matched)}"))
        if not reasons:
            continue
        reasons.sort(key=lambda x: -x[0])
        base = reasons[0][0] + 0.1 * sum(w for w, _ in reasons[1:])
        score = round(min(1.0, base) * (0.5 + 0.5 * c.relationship["strength"]), 3)
        ranked.append(
            {
                "contact": _contact_summary(c),
                "score": score,
                "why": reasons[0][1],
                "reasons": [t for _, t in reasons],
                # N-4: a current employee may hold unpublished price-sensitive information.
                # Shown, never hidden: the investor decides, with compliance, how to talk.
                "insider": insider,
            }
        )
    ranked.sort(key=lambda x: -x["score"])
    return ranked[:limit]


# ------------------------------------------------------------------ expertise (FR-NET-06)
def expertise(theme: str, people: dict[str, Person] | None = None, limit: int = 8) -> list[dict]:
    from rapidfuzz import fuzz

    people = people or load_people()
    q = theme.lower().strip()
    out = []
    for c in people.values():
        if not c.is_contact or not c.relationship:
            continue
        hits = [t for t in c.themes if fuzz.partial_ratio(q, t.lower()) >= 85]
        if not hits:
            continue
        out.append(
            {
                "contact": _contact_summary(c),
                "themes": hits,
                "score": round(c.relationship["strength"] + 0.1 * len(hits), 2),
            }
        )
    return sorted(out, key=lambda x: -x["score"])[:limit]


def all_themes(people: dict[str, Person] | None = None) -> list[dict]:
    people = people or load_people()
    counts: dict[str, int] = {}
    for c in people.values():
        if c.is_contact:
            for t in c.themes:
                counts[t] = counts.get(t, 0) + 1
    return [{"theme": t, "contacts": n} for t, n in sorted(counts.items(), key=lambda x: -x[1])]


# ------------------------------------------------------------------ nudges (FR-NET-07)
NUDGE_CATEGORIES = ("results", "M&A", "management_change", "capex", "litigation", "fund_raise")


def reconnect_nudges(
    start: str,
    end: str,
    stale_days: int = 90,
    people: dict[str, Person] | None = None,
    limit: int = 6,
) -> list[dict]:
    people = people or load_people()
    today = now().date()
    with session() as db:
        events = db.execute(
            f"""SELECT id, symbol, ts, category, summary, subject FROM announcements
                WHERE ts BETWEEN ? AND ? AND category IN ({",".join("?" * len(NUDGE_CATEGORIES))})
                ORDER BY materiality DESC, ts DESC""",
            (start, end, *NUDGE_CATEGORIES),
        ).fetchall()
    by_symbol: dict[str, list] = {}
    for e in events:
        by_symbol.setdefault(e["symbol"], []).append(dict(e))
    out = []
    for c in people.values():
        if not c.is_contact or not c.relationship or not c.relationship.get("last_contact"):
            continue
        days = (today - date.fromisoformat(c.relationship["last_contact"])).days
        if days < stale_days:
            continue
        for r in c.roles:
            evs = by_symbol.get(r.symbol or "")
            if not evs:
                continue
            ev = evs[0]
            rel = "current employer" if r.end is None else "former employer"
            out.append(
                {
                    "contact": _contact_summary(c),
                    "days_since_contact": days,
                    "event": {k: ev[k] for k in ("id", "symbol", "ts", "category")}
                    | {"title": ev["summary"] or ev["subject"]},
                    "reason": f"Last spoke {_ago(days)}. {r.company}, their {rel}, just posted "
                    f"{_category_phrase(ev['category'])}.",
                }
            )
            break
    out.sort(key=lambda n: (-n["contact"]["strength"], -n["days_since_contact"]))
    return out[:limit]


def _ago(days: int) -> str:
    return f"{days // 30} months ago" if days >= 60 else f"{days} days ago"


def _category_phrase(cat: str) -> str:
    return {
        "results": "results",
        "M&A": "a deal",
        "management_change": "a leadership change",
        "capex": "a capacity expansion",
        "litigation": "a legal/regulatory update",
        "fund_raise": "a fund raise",
    }.get(cat, "news")


# ------------------------------------------------------------------ person page (FR-NET-08)
def person_profile(person_id: str) -> dict | None:
    people = load_people()
    p = people.get(person_id)
    if p is None:
        return None
    out = _person_summary(p) | {
        "bio": p.bio,
        "themes": p.themes,
        "roles": [r.__dict__ | {"span": r.span()} for r in p.roles],
        "education": [e.__dict__ for e in p.education],
        "relationship": p.relationship,
        "overlaps_with_you": [o.__dict__ for o in overlaps(investor(people), p)],
    }
    if not p.is_contact:
        out["paths"] = paths_to(person_id, people)
    else:
        out["knows"] = [
            {"person": _person_summary(people[k["person"]]), "context": k.get("context")}
            for k in p.knows
            if k["person"] in people
        ]
        out["can_help_on"] = can_help_on(person_id, people)
    return out


def can_help_on(person_id: str, people: dict[str, Person], top: int = 3) -> list[dict]:
    """Companies in the investor's universe where this contact ranks among the top helpers."""
    from app.ingest.universe import all_symbols

    out = []
    for sym in all_symbols():
        ranked = who_can_help(sym, people, limit=top)
        for rank, h in enumerate(ranked):
            if h["contact"]["id"] == person_id:
                out.append({"symbol": sym, "rank": rank + 1, "score": h["score"], "why": h["why"]})
    return sorted(out, key=lambda x: (-x["score"], x["rank"]))


# ------------------------------------------------------------------ serialisers
def _person_summary(p: Person) -> dict:
    current = next((r for r in p.roles if r.end is None), None)
    return {
        "id": p.id,
        "name": p.name,
        "headline": p.headline,
        "current": f"{current.title}, {current.company}"
        if current and current.title
        else (current.company if current else None),
        "is_contact": p.is_contact,
    }


def _contact_summary(c: Person) -> dict:
    rel = c.relationship or {}
    return _person_summary(c) | {
        "relationship": rel.get("type"),
        "strength": rel.get("strength"),
        "last_contact": rel.get("last_contact"),
        "context": rel.get("context"),
        "email": rel.get("email"),
        "phone": rel.get("phone"),
    }


# ------------------------------------------------------------------ owner's controls (N-7)
def delete_contact(person_id: str, owner: str | None = None) -> bool:
    """Remove a contact and everything derived from it, for this owner only. Paths, overlaps,
    who-can-help and nudges are computed on read, so deleting the person, their roles and
    schools (cascade) and every relationship row that names them removes them everywhere.
    Public filing people and the investor cannot be deleted here."""
    owner = owner or current_owner()
    with session() as db:
        row = db.execute(
            "SELECT is_contact FROM people WHERE id=? AND owner_id=?", (person_id, owner)
        ).fetchone()
        if row is None or not row["is_contact"] or person_id == investor_id(owner):
            return False
        db.execute(
            "DELETE FROM relationships WHERE owner_id=? AND (person_id=? OR other_id=?)",
            (owner, person_id, person_id),
        )
        db.execute(
            "DELETE FROM identity_answers WHERE owner_id=? AND contact_id=?", (owner, person_id)
        )
        db.execute("DELETE FROM notes WHERE owner_id=? AND contact_id=?", (owner, person_id))
        db.execute("DELETE FROM meetings WHERE owner_id=? AND person_id=?", (owner, person_id))
        db.execute("DELETE FROM people WHERE id=? AND owner_id=?", (person_id, owner))
    return True


def reset_network(owner: str | None = None) -> int:
    """Restore an account's demo network from its fixture (undo deletions on the demo)."""
    from app.ingest.seed import seed_owner_network
    from app.network.owner import is_sandbox

    owner = owner or current_owner()
    if is_sandbox(owner):
        from app.network.mine import reset_sandbox

        return reset_sandbox()
    with session() as db:
        db.execute("DELETE FROM relationships WHERE owner_id=?", (owner,))
        db.execute("DELETE FROM identity_answers WHERE owner_id=?", (owner,))
        db.execute("DELETE FROM notes WHERE owner_id=?", (owner,))
        db.execute("DELETE FROM meetings WHERE owner_id=?", (owner,))
        db.execute("DELETE FROM people WHERE owner_id=?", (owner,))
        return seed_owner_network(db, owner)
