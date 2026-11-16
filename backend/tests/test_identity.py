"""FR-NET-05: a shared name is never treated as the same person. Uses the planted contacts:
a Jaipur accountant called Amit Agarwal (demo) next to Pidilite's incoming CFO, and a
Rajat Shah whose employer and school match CG Power's new VP Services (demo2)."""

from fastapi.testclient import TestClient

CFO = "fp_amit_agarwal_pidilite"
VP = "fp_rajat_shah_cgpower"
DEMO = {"X-Finn-User": "demo"}
OTHER = {"X-Finn-User": "demo2"}


def _client():
    from app.main import app

    return TestClient(app)


def _cfo_card(c, headers):
    cards = c.get("/digest?start=2026-10-01&end=2026-10-15", headers=headers).json()["cards"]
    card = next(
        x for x in cards if x["symbol"] == "PIDILITIND" and x["kind"] == "management_change"
    )
    return next(p for p in card["people"] if p["id"] == CFO)


def test_same_name_stranger_is_only_a_possible_match(seeded):
    with _client() as c:
        paths = c.get(f"/people/{CFO}/paths", headers=DEMO).json()
        assert paths["same_name"] == [
            {
                "contact": paths["same_name"][0]["contact"],
                "status": "possible",
                "agrees": [],
            }
        ]
        assert paths["same_name"][0]["contact"]["id"] == "c_amit_agarwal_ca"
        # never a "your contact" link, never a path through himself
        assert all(d["kind"] != "contact" for d in paths["direct"])
        assert "c_amit_agarwal_ca" not in {v["contact"]["id"] for v in paths["via"]}
        # the card the investor actually sees carries the same caution
        person = _cfo_card(c, DEMO)
        assert [m["status"] for m in person["paths"]["same_name"]] == ["possible"]


def test_agreeing_details_make_it_likely_not_certain(seeded):
    with _client() as c:
        m = c.get(f"/people/{VP}/paths", headers=OTHER).json()["same_name"]
        assert [(x["contact"]["id"], x["status"]) for x in m] == [("d2_rajat_shah", "likely")]
        assert set(m[0]["agrees"]) == {"Ingersoll Rand", "IIT Guwahati"}
        # the other account has no Rajat Shah, so sees no match at all
        assert c.get(f"/people/{VP}/paths", headers=DEMO).json()["same_name"] == []


def test_investor_answers_persist_and_stay_private(seeded):
    with _client() as c:
        r = c.put(
            f"/people/{VP}/identity",
            json={"contact": "d2_rajat_shah", "verdict": "same"},
            headers=OTHER,
        )
        assert r.status_code == 200
        p = c.get(f"/people/{VP}/paths", headers=OTHER).json()
        assert p["same_name"][0]["status"] == "confirmed"
        assert p["direct"][0]["kind"] == "contact" and "you confirmed" in p["direct"][0]["detail"]

        c.put(
            f"/people/{CFO}/identity",
            json={"contact": "c_amit_agarwal_ca", "verdict": "different"},
            headers=DEMO,
        )
        assert c.get(f"/people/{CFO}/paths", headers=DEMO).json()["same_name"] == []
        # one account's answer cannot touch another's, nor name its contacts
        bad = {"contact": "c_amit_agarwal_ca", "verdict": "same"}
        assert c.put(f"/people/{CFO}/identity", json=bad, headers=OTHER).status_code == 404
        wrong = {"contact": "c_amit_agarwal_ca", "verdict": "maybe"}
        assert c.put(f"/people/{CFO}/identity", json=wrong, headers=DEMO).status_code == 400
        # reset clears answers with the rest of the demo network
        c.post("/people/reset", headers=DEMO)
        assert c.get(f"/people/{CFO}/paths", headers=DEMO).json()["same_name"][0]["status"] == (
            "possible"
        )
