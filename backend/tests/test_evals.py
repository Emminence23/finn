"""The accuracy page reports what the tests check, from the live data."""

from fastapi.testclient import TestClient


def test_accuracy_page_matches_the_calibration(seeded):
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/eval").json()
        labels = c.get("/eval/labels").json()["filings"]
    live = {x["what"]: x for x in r["live"]}
    assert live["Material filings kept out of Routine"]["result"] == "25 of 25"
    assert all(x["passes"] in (True, None) for x in r["live"])
    assert len(labels) == 100 and sum(f["material"] for f in labels) == 25
    assert all(f["agrees"] for f in labels if f["material"])  # no material filing folded away
    assert all(f["title"] and f["finn_level"] for f in labels)
    assert r["measured"] and all(m["how"] for m in r["measured"])
