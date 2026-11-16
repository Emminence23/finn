"""Bring your own network (N-1 onboarding, production path in miniature).

A visitor gets a private sandbox account, tells FINN where they worked and studied, and adds
the people they know: by hand, or from the Connections.csv LinkedIn lets every member export.
Everything FINN computes on read (paths, overlaps, who can help, nudges, meeting questions)
then works on their network instead of the synthetic one.

Privacy rules, same as the demo network and enforced here:
- only professional facts are kept: name, company, title, years, how you know them;
- e-mail addresses and profile URLs in the export are dropped on import, never stored;
- nothing here is ever sent to an LLM;
- a sandbox is deleted after SANDBOX_DAYS, and the visitor can delete it at any time.
"""

from __future__ import annotations

import csv
import io
import secrets
from datetime import datetime, timedelta

from app.db import session
from app.ingest.seed import _insert_person
from app.network.owner import current_owner, investor_id, is_sandbox

SANDBOX_DAYS = 7
MAX_CONTACTS = 3000
MAX_CSV_BYTES = 2_000_000
MAX_ROLES = 12
LINKEDIN_STRENGTH = 0.3  # a connection, not a friendship: weaker than anything declared by hand


def _purge_expired(db) -> None:
    cutoff = (datetime.now() - timedelta(days=SANDBOX_DAYS)).isoformat()
    for (owner,) in db.execute("SELECT owner_id FROM sandboxes WHERE created_at < ?", (cutoff,)):
        _wipe(db, owner)
        db.execute("DELETE FROM sandboxes WHERE owner_id=?", (owner,))


def _wipe(db, owner: str) -> None:
    for table in ("relationships", "identity_answers", "notes", "meetings", "alert_rules"):
        db.execute(f"DELETE FROM {table} WHERE owner_id=?", (owner,))
    db.execute("DELETE FROM people WHERE owner_id=?", (owner,))


def _blank_investor(db, owner: str) -> None:
    _insert_person(
        db,
        {"id": investor_id(owner), "name": "You", "headline": None},
        owner=owner,
        is_contact=False,
    )


def create_sandbox() -> str:
    owner = "u_" + secrets.token_hex(8)
    with session() as db:
        _purge_expired(db)
        db.execute(
            "INSERT INTO sandboxes VALUES (?, ?)",
            (owner, datetime.now().isoformat(timespec="seconds")),
        )
        _blank_investor(db, owner)
    return owner


def _require_sandbox() -> str:
    owner = current_owner()
    if not is_sandbox(owner):
        raise PermissionError("the demo networks are read-only here; create your own first")
    return owner


def _year(v) -> int | None:
    try:
        y = int(str(v).strip()[:4])
    except (TypeError, ValueError):
        return None
    return y if 1950 <= y <= 2100 else None


def _clean(s, n: int = 120) -> str:
    return " ".join(str(s or "").split())[:n]


def set_career(roles: list[dict], education: list[dict], name: str | None = None) -> dict:
    """Replace the investor's own employers and schools."""
    owner = _require_sandbox()
    me = investor_id(owner)
    rs = [
        {
            "company": _clean(r.get("company")),
            "title": _clean(r.get("title")) or None,
            "start_year": _year(r.get("start_year")),
            "end_year": _year(r.get("end_year")),
        }
        for r in roles[:MAX_ROLES]
        if _clean(r.get("company"))
    ]
    es = [
        {
            "school": _clean(e.get("school")),
            "program": _clean(e.get("program")) or None,
            "start_year": _year(e.get("start_year")),
            "end_year": _year(e.get("end_year")),
        }
        for e in education[:MAX_ROLES]
        if _clean(e.get("school"))
    ]
    with session() as db:
        db.execute("DELETE FROM people WHERE id=? AND owner_id=?", (me, owner))
        _insert_person(
            db,
            {"id": me, "name": _clean(name, 60) or "You", "roles": rs, "education": es},
            owner=owner,
            is_contact=False,
        )
    return {"roles": len(rs), "education": len(es)}


def _count(db, owner: str) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM people WHERE owner_id=? AND is_contact=1", (owner,)
    ).fetchone()[0]


def _add(db, owner: str, c: dict, rel_type: str, strength: float, last_contact: str | None) -> str:
    pid = "m_" + secrets.token_hex(6)
    _insert_person(db, {**c, "id": pid}, owner=owner, is_contact=True)
    db.execute(
        "INSERT INTO relationships (owner_id, person_id, other_id, type, strength, last_contact) "
        "VALUES (?,?,?,?,?,?)",
        (owner, pid, None, rel_type, strength, last_contact),
    )
    return pid


def add_contact(body: dict) -> dict:
    owner = _require_sandbox()
    name, company = _clean(body.get("name"), 80), _clean(body.get("company"))
    if not name or not company:
        raise ValueError("a contact needs a name and a company")
    role = {
        "company": company,
        "title": _clean(body.get("title")) or None,
        "start_year": _year(body.get("start_year")),
        "end_year": _year(body.get("end_year")),
    }
    school = _clean(body.get("school"))
    c = {
        "name": name,
        "headline": role["title"],
        "roles": [role],
        "education": [{"school": school}] if school else [],
        "themes": [],
    }
    strength = {"close": 0.8, "good": 0.6, "acquaintance": 0.35}.get(body.get("closeness"), 0.5)
    with session() as db:
        if _count(db, owner) >= MAX_CONTACTS:
            raise ValueError("contact limit reached")
        pid = _add(db, owner, c, _clean(body.get("how"), 40) or "contact", strength, None)
    return {"id": pid}


def _connected_on(v: str) -> str | None:
    for fmt in ("%d %b %Y", "%d-%b-%y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(v.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def import_linkedin(text: str) -> dict:
    """LinkedIn's Connections.csv: a few lines of notes, then First Name, Last Name, URL,
    Email Address, Company, Position, Connected On. Only name, company, position and the
    connection date are kept. The export has no tenure, so the current role has no years:
    overlaps through it say "years unknown", exactly as for filing people."""
    owner = _require_sandbox()
    if len(text.encode()) > MAX_CSV_BYTES:
        raise ValueError("file too large (2 MB max)")
    lines = text.lstrip("﻿").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.lower().startswith("first name")), None)
    if start is None:
        raise ValueError("this doesn't look like LinkedIn's Connections.csv")
    rows = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    added = skipped = 0
    with session() as db:
        room = MAX_CONTACTS - _count(db, owner)
        for r in rows:
            name = _clean(f"{r.get('First Name', '')} {r.get('Last Name', '')}", 80)
            company = _clean(r.get("Company"))
            if not name or not company or added >= room:
                skipped += 1
                continue
            title = _clean(r.get("Position")) or None
            c = {
                "name": name,
                "headline": title,
                "roles": [{"company": company, "title": title}],
                "education": [],
                "themes": [],
            }
            _add(
                db,
                owner,
                c,
                "LinkedIn connection",
                LINKEDIN_STRENGTH,
                _connected_on(r.get("Connected On", "")),
            )
            added += 1
    return {"imported": added, "skipped": skipped}


def reset_sandbox() -> int:
    owner = _require_sandbox()
    with session() as db:
        _wipe(db, owner)
        _blank_investor(db, owner)
    return 0


def delete_sandbox() -> None:
    owner = _require_sandbox()
    with session() as db:
        _wipe(db, owner)
        db.execute("DELETE FROM sandboxes WHERE owner_id=?", (owner,))
