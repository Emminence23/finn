"""Bring your own network: a private sandbox, the visitor's own career, contacts by hand or
from LinkedIn's Connections.csv, and everything FINN derives working on them."""

from fastapi.testclient import TestClient

CSV = """Notes:
"When exporting your connection data, you may notice that some of the email addresses are missing."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Riya,Menon,https://www.linkedin.com/in/riya-x,riya@example.com,Larsen & Toubro Limited,Head of Sales,14 Mar 2024
Sam,Iyer,https://www.linkedin.com/in/sam-x,,HDFC Bank,Credit Manager,02 Jan 2023
No,Company,https://www.linkedin.com/in/nc,,,,05 May 2022
"""


def _client():
    from app.main import app

    return TestClient(app)


def _mine(c):
    acct = c.post("/people/mine").json()["account"]
    return {"X-Finn-User": acct}


def test_import_keeps_professional_facts_only_and_drives_who_can_help(seeded):
    with _client() as c:
        me = _mine(c)
        assert c.get("/people", headers=me).json() == []  # starts empty
        r = c.post("/people/mine/linkedin", json={"csv": CSV}, headers=me).json()
        assert r == {"imported": 2, "skipped": 1}
        people = {p["name"]: p for p in c.get("/people", headers=me).json()}
        assert set(people) == {"Riya Menon", "Sam Iyer"}
        riya = c.get(f"/people/{people['Riya Menon']['id']}", headers=me).json()
        assert riya["relationship"]["type"] == "LinkedIn connection"
        assert riya["relationship"]["last_contact"] == "2024-03-14"
        assert "example.com" not in str(riya) and "linkedin.com" not in str(riya)
        helpers = c.get("/people/help?symbol=LT", headers=me).json()["helpers"]
        assert helpers[0]["contact"]["name"] == "Riya Menon" and helpers[0]["insider"]

        # none of it leaks into the demo, and the demo's people don't leak in
        demo_names = {p["name"] for p in c.get("/people", headers={"X-Finn-User": "demo"}).json()}
        assert "Riya Menon" not in demo_names


def test_raw_database_never_holds_emails_or_profile_urls(seeded):
    from app.db import session

    with _client() as c:
        me = _mine(c)
        c.post("/people/mine/linkedin", json={"csv": CSV}, headers=me)
    with session() as db:
        dump = "\n".join(
            str(tuple(r))
            for t in ("people", "roles", "relationships")
            for r in db.execute(f"SELECT * FROM {t}")
        )
    assert "riya@example.com" not in dump and "linkedin.com/in" not in dump


def test_own_career_creates_paths_to_filing_people(seeded):
    with _client() as c:
        me = _mine(c)
        # Meesho's new independent director spent two decades at Hindustan Unilever
        assert c.get("/people/fp_sudhir_sitapati_meesho/paths", headers=me).json()["direct"] == []
        c.put(
            "/people/mine/career",
            json={
                "roles": [
                    {"company": "Hindustan Unilever Limited", "start_year": 2010, "end_year": 2015}
                ],
                "education": [],
            },
            headers=me,
        )
        direct = c.get("/people/fp_sudhir_sitapati_meesho/paths", headers=me).json()["direct"]
        assert direct and "Hindustan Unilever" in direct[0]["detail"]
        assert direct[0]["basis"] == "inferred"

        added = c.post(
            "/people/mine/contacts",
            json={
                "name": "Tara Das",
                "company": "Godrej Consumer Products Limited",
                "title": "Finance Director",
                "start_year": 2019,
                "end_year": 2024,
                "closeness": "close",
                "how": "ex-colleague",
            },
            headers=me,
        ).json()
        via = c.get("/people/fp_sudhir_sitapati_meesho/paths", headers=me).json()["via"]
        assert via[0]["contact"]["id"] == added["id"]


def test_sandbox_rules(seeded):
    with _client() as c:
        # the demo networks can't be edited through these routes
        assert (
            c.post(
                "/people/mine/contacts",
                json={"name": "X", "company": "Y"},
                headers={"X-Finn-User": "demo"},
            ).status_code
            == 403
        )
        # a made-up sandbox id is refused: only the server creates them
        assert c.get("/people", headers={"X-Finn-User": "u_0123456789abcdef"}).status_code == 400
        me = _mine(c)
        assert (
            c.post("/people/mine/linkedin", json={"csv": "a,b\n1,2"}, headers=me).status_code == 400
        )
        assert (
            c.post("/people/mine/contacts", json={"name": "No company"}, headers=me).status_code
            == 400
        )
        assert c.delete("/people/mine", headers=me).json() == {"deleted": True}
        assert c.get("/people", headers=me).status_code == 400  # gone


def test_expired_sandboxes_are_deleted(seeded):
    from app.db import session

    with _client() as c:
        old = _mine(c)
        c.post("/people/mine/linkedin", json={"csv": CSV}, headers=old)
        with session() as db:
            db.execute(
                "UPDATE sandboxes SET created_at='2000-01-01T00:00:00' WHERE owner_id=?",
                (old["X-Finn-User"],),
            )
        _mine(c)  # creating any sandbox purges expired ones
        assert c.get("/people", headers=old).status_code == 400
    with session() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM people WHERE owner_id=?", (old["X-Finn-User"],)
            ).fetchone()[0]
            == 0
        )
