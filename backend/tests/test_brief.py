"""FR-PUSH-11: the spoken brief says what the cards say, in words a voice reads cleanly."""

import re

from fastapi.testclient import TestClient

from app.intel.brief import MAX_ITEMS, spoken


def test_spoken_spells_out_what_a_voice_would_garble():
    assert spoken("PAT ₹40 Cr, -66% YoY; Rs 992.25; INR 100,000+ million") == (
        "profit rupees 40 crore, -66 percent year on year; rupees 992.25; rupees 100,000 plus million"
    )
    assert spoken("H1 FY27 & 5.1× volume") == "first half F Y 27 and 5.1 times volume"


def test_brief_follows_the_digest_and_stays_short(seeded):
    from app.intel.digest import build_digest
    from app.main import app

    with TestClient(app) as c:
        for w in ("24h", "7d", "30d"):
            b = c.get(f"/digest/brief?window={w}").json()
            cards = build_digest(w)["cards"]
            ids = [x["id"] for x in b["lines"] if x["id"] not in ("intro", "moves", "outro")]
            assert ids == [str(x["id"]) for x in cards[:MAX_ITEMS]]  # same items, same order
            text = " ".join(x["text"] for x in b["lines"])
            assert not re.search(r"%|₹|\bRs\b|\bYoY\b|\bCr\b|\bINR\b", text), text
            assert b["seconds"] <= 120
        quiet = c.get("/digest/brief?start=2020-01-04T00:00:00&end=2020-01-04T23:59:59").json()
        assert len(quiet["lines"]) == 2 and "Quiet is good" in quiet["lines"][0]["text"]
