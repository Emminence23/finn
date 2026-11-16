"""Groww-style additions: day returns, a watchlist per account, the day's movers."""

import pytest


def test_day_returns_add_up(seeded):
    from app.portfolio.holdings import get_positions

    pos = get_positions()
    assert sum(p["day_change"] for p in pos["positions"]) == pytest.approx(pos["day_gain"])
    yesterday = pos["value"] - pos["day_gain"]
    assert pos["day_gain_pct"] == pytest.approx(pos["day_gain"] / yesterday * 100)
    p = pos["positions"][0]
    assert p["day_pct"] == pytest.approx((p["price"] / p["prev_price"] - 1) * 100)


def test_watchlist_is_per_account_and_can_be_emptied(seeded):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.portfolio.watchlist import DEMO

    a, b = {"X-Finn-User": "demo2"}, {"X-Finn-User": "demo"}
    with TestClient(app) as c:
        c.post("/watchlist/reset", headers=a)
        assert [w["symbol"] for w in c.get("/watchlist", headers=a).json()["items"]] == list(DEMO)
        got = c.post("/watchlist", json={"symbol": "tcs"}, headers=a).json()
        assert got["items"][-1]["symbol"] == "TCS" and got["items"][-1]["held"]
        assert "TCS" not in [w["symbol"] for w in c.get("/watchlist", headers=b).json()["items"]]
        for s in [*DEMO, "TCS"]:
            c.delete(f"/watchlist/{s}", headers=a)
        empty = c.get("/watchlist", headers=a).json()
        assert empty["items"] == [] and empty["custom"]  # emptied, not back to the demo
        assert c.post("/watchlist", json={"symbol": "NOPE"}, headers=a).status_code == 404
        unpriced = c.post("/watchlist", json={"symbol": "TATAELXSI"}, headers=a)
        assert unpriced.status_code in (400, 404)
        c.post("/watchlist/reset", headers=a)


def test_movers_rank_holdings_and_watchlist_by_the_day(seeded):
    from app.portfolio.watchlist import movers

    m = movers(3)
    assert all(r["day_pct"] > 0 for r in m["gainers"])
    assert all(r["day_pct"] < 0 for r in m["losers"])
    ups = [r["day_pct"] for r in m["gainers"]]
    assert ups == sorted(ups, reverse=True)
    downs = [r["day_pct"] for r in m["losers"]]
    assert downs == sorted(downs)
    assert any(not r["held"] for r in m["gainers"] + m["losers"]) or m["count"] > 18
