"""Meeting prep: a planned meeting puts a prep card on Today from two days before, built
from the digest and the research, private to the account."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

DEMO = {"X-Finn-User": "demo"}
OTHER = {"X-Finn-User": "demo2"}


def _client():
    from app.main import app

    return TestClient(app)


def _karthik(c):
    return next(
        p["id"] for p in c.get("/people", headers=DEMO).json() if p["name"].startswith("Karthik")
    )


def test_prep_shows_two_days_ahead_with_changes_and_questions(seeded):
    with _client() as c:
        today = date.fromisoformat(c.get("/people/meetings", headers=DEMO).json()["today"])
        k = _karthik(c)
        soon = c.post(
            "/people/meetings",
            json={"person": k, "day": (today + timedelta(days=1)).isoformat(), "note": "coffee"},
            headers=DEMO,
        ).json()
        assert soon["when"] == "tomorrow"
        c.post(
            "/people/meetings",
            json={"person": k, "day": (today + timedelta(days=9)).isoformat()},
            headers=DEMO,
        )

        prep = c.get("/people/meetings/prep", headers=DEMO).json()["prep"]
        assert len(prep) == 1 and prep[0]["id"] == soon["id"]  # the far one waits
        card = prep[0]
        assert {"symbol": "KAYNES", "relation": "former"} in card["companies"]
        assert card["changed"] and all(
            x["symbol"] in {s["symbol"] for s in card["companies"]} for x in card["changed"]
        )
        assert 1 <= len(card["questions"]) <= 2 and "Kaynes" in card["questions"][0]

        # private, and gone with the contact
        assert c.get("/people/meetings/prep", headers=OTHER).json()["prep"] == []
        assert c.delete(f"/people/meetings/{soon['id']}", headers=OTHER).status_code == 404
        c.delete(f"/people/{k}", headers=DEMO)
        assert c.get("/people/meetings", headers=DEMO).json()["meetings"] == []


def test_meeting_refusals(seeded):
    with _client() as c:
        k = _karthik(c)
        assert (
            c.post(
                "/people/meetings", json={"person": k, "day": "2000-01-01"}, headers=DEMO
            ).status_code
            == 400
        )
        assert (
            c.post(
                "/people/meetings", json={"person": k, "day": "not-a-date"}, headers=DEMO
            ).status_code
            == 400
        )
        assert (
            c.post(
                "/people/meetings", json={"person": k, "day": "2099-01-01"}, headers=OTHER
            ).status_code
            == 404
        )
