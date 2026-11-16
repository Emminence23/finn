"""N-7: a network is visible only to its owner, and deleting a contact removes every link
derived from it. Runs on the real seeded fixtures through the API."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

FIX = Path(__file__).parents[1] / "data" / "fixtures"
DEMO = {"X-Finn-User": "demo"}
OTHER = {"X-Finn-User": "demo2"}


def _client():
    from app.main import app

    return TestClient(app)


def _ids(c, headers):
    return {p["id"] for p in c.get("/people", headers=headers).json()}


def test_second_account_cannot_see_the_first_accounts_network(seeded):
    demo_ids = {x["id"] for x in json.loads((FIX / "network.json").read_text())["contacts"]}
    with _client() as c:
        assert _ids(c, DEMO) == demo_ids
        other = _ids(c, OTHER)
        assert other and other.isdisjoint(demo_ids)
        one = next(iter(demo_ids))
        assert c.get(f"/people/{one}", headers=OTHER).status_code == 404
        assert c.get(f"/people/{one}/paths", headers=OTHER).status_code == 404
        assert c.delete(f"/people/{one}", headers=OTHER).status_code == 404
        # who-can-help and the digest only ever name the caller's own contacts
        for sym in ("KAYNES", "HDFCBANK", "TRENT", "MANAPPURAM"):
            helpers = c.get(f"/people/help?symbol={sym}", headers=OTHER).json()["helpers"]
            assert {h["contact"]["id"] for h in helpers} <= other
        cards = c.get("/digest?window=30d", headers=OTHER).json()["cards"]
        named = {h["contact"]["id"] for card in cards for h in card["helpers"]}
        assert named <= other
        assert c.get("/people/account", headers=OTHER).json()["investor"] == "Second investor"


def test_public_filing_people_are_visible_to_every_account(seeded):
    fp = json.loads((FIX / "filing_people.json").read_text())["people"][0]["id"]
    with _client() as c:
        for h in (DEMO, OTHER):
            r = c.get(f"/people/{fp}", headers=h)
            assert r.status_code == 200
            via = {v["contact"]["id"] for v in r.json()["paths"]["via"]}
            assert via <= _ids(c, h)  # reached only through the caller's own contacts


def test_unknown_account_is_refused(seeded):
    with _client() as c:
        assert c.get("/people", headers={"X-Finn-User": "mallory"}).status_code == 400


def test_deleting_a_contact_removes_every_derived_link(seeded):
    with _client() as c:
        # find a contact who is both a path to a filing person and a helper for a company
        fps = json.loads((FIX / "filing_people.json").read_text())["people"]
        target, contact = None, None
        for fp in fps:
            via = c.get(f"/people/{fp['id']}/paths", headers=DEMO).json()["via"]
            if via:
                target, contact = fp, via[0]["contact"]["id"]
                break
        assert contact
        helped = [
            s
            for s in ("KAYNES", "HDFCBANK", "SRF", "POLYCAB", "TITAN", target["symbol"])
            if contact
            in {
                h["contact"]["id"]
                for h in c.get(f"/people/help?symbol={s}&limit=20").json()["helpers"]
            }
        ]
        assert helped, "pick a contact who also helps on a company"
        other_before = _ids(c, OTHER)

        assert c.delete(f"/people/{contact}", headers=DEMO).json() == {"deleted": contact}

        assert contact not in _ids(c, DEMO)
        assert c.get(f"/people/{contact}", headers=DEMO).status_code == 404
        via = c.get(f"/people/{target['id']}/paths", headers=DEMO).json()["via"]
        assert contact not in {v["contact"]["id"] for v in via}
        for s in helped:
            helpers = c.get(f"/people/help?symbol={s}&limit=20", headers=DEMO).json()["helpers"]
            assert contact not in {h["contact"]["id"] for h in helpers}
        nudges = c.get("/people/nudges", headers=DEMO).json()["nudges"]
        assert contact not in {n["contact"]["id"] for n in nudges}
        for p in c.get("/people", headers=DEMO).json():
            profile = c.get(f"/people/{p['id']}", headers=DEMO).json()
            assert contact not in {k["person"]["id"] for k in profile.get("knows", [])}
        assert _ids(c, OTHER) == other_before  # the other account is untouched

        # deletion persists; reset restores the demo network
        assert contact not in _ids(c, DEMO)
        c.post("/people/reset", headers=DEMO)
        assert contact in _ids(c, DEMO)
