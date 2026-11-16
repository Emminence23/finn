"""Notes from contacts (PLAN v2, Pull "Should").

What a contact told the investor about a company is useful and is not evidence. Notes are:
- private to the owner, like the rest of the network;
- shown on the company page in their own section, never mixed into the research view;
- never sent to an LLM, so Ask FINN can neither read nor cite them (the research module
  does not import this one; a test checks the prompt);
- deleted with the contact they are attributed to.
"""

from __future__ import annotations

import re

from app.clock import now
from app.db import session
from app.network import graph
from app.network.owner import current_owner

MAX_LEN = 600


def list_notes(symbol: str) -> list[dict]:
    people = graph.load_people()
    with session() as db:
        rows = db.execute(
            "SELECT id, contact_id, text, created_at FROM notes WHERE owner_id=? AND symbol=? "
            "ORDER BY created_at DESC, id DESC",
            (current_owner(), symbol.upper()),
        ).fetchall()
    out = []
    for r in rows:
        c = people.get(r["contact_id"]) if r["contact_id"] else None
        out.append(
            {
                "id": r["id"],
                "text": r["text"],
                "created_at": r["created_at"],
                "contact": {"id": c.id, "name": c.name} if c else None,
            }
        )
    return out


def add_note(symbol: str, text: str, contact_id: str | None = None) -> dict:
    text = " ".join(text.split())[:MAX_LEN]
    if not re.fullmatch(r"[A-Z0-9&-]{1,20}", symbol.upper()):
        raise ValueError("bad symbol")
    if not text:
        raise ValueError("empty note")
    if contact_id:
        c = graph.load_people().get(contact_id)
        if c is None or not c.is_contact:
            raise KeyError("no such contact in your network")
    with session() as db:
        cur = db.execute(
            "INSERT INTO notes (owner_id, symbol, contact_id, text, created_at) VALUES (?,?,?,?,?)",
            (
                current_owner(),
                symbol.upper(),
                contact_id,
                text,
                now().isoformat(timespec="seconds"),
            ),
        )
        note_id = cur.lastrowid
    return next(n for n in list_notes(symbol) if n["id"] == note_id)


def delete_note(note_id: int) -> bool:
    with session() as db:
        cur = db.execute("DELETE FROM notes WHERE id=? AND owner_id=?", (note_id, current_owner()))
        return cur.rowcount > 0
