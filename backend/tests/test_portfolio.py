"""Portfolio page and suggested weights: deterministic code, AI only nudges within limits."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

DEMO = {"X-Finn-User": "demo"}
OTHER = {"X-Finn-User": "demo2"}


def _client():
    from app.main import app

    return TestClient(app)


def test_overview_adds_up(seeded):
    with _client() as c:
        o = c.get("/portfolio", headers=DEMO).json()
    assert o["summary"]["holdings"] == 20 and not o["custom"]
    assert sum(h["weight"] for h in o["holdings"]) == pytest.approx(100)
    assert sum(t["weight"] for t in o["themes"]) == pytest.approx(100)
    assert sum(h["risk_share"] for h in o["holdings"]) == pytest.approx(100)
    assert any("Lenders together are 21%" in f for f in o["flags"])
    assert {o["correlated"][0]["a"], o["correlated"][0]["b"]} == {
        "BAJFINANCE",
        "JIOFIN",
    }  # the most alike pair
    s = o["summary"]
    assert s["value"] == pytest.approx(sum(h["qty"] * h["price"] for h in o["holdings"]))
    # the demo was bought on the chart's first day: the curve starts at the money invested
    first, last = o["history"]["series"][0], o["history"]["series"][-1]
    assert first["value"] == pytest.approx(s["invested"], rel=1e-6) == first["nifty"]
    assert last["value"] == pytest.approx(s["value"], rel=1e-6)
    assert s["return_1y"] == pytest.approx(s["gain_pct"], abs=0.01)
    assert len(o["history"]["series"]) > 240 and o["days"] == 127  # a year shown, 6 months of risk


def test_suggestion_respects_every_rule_and_is_repeatable(seeded):
    from app.portfolio import analytics as a

    s1, s2 = a.suggest(), a.suggest()
    assert s1 == s2  # same inputs, same answer
    rows = s1["holdings"]
    assert sum(r["suggested"] for r in rows) == pytest.approx(100)
    for r in rows:
        assert abs(r["change"]) <= a.MAX_STEP * 100 + 1e-6
        if a.MIN_W * 100 <= r["current"] + r["change"] <= a.MAX_W * 100 + 1e-6:
            continue
        # outside the band only when a full step can't reach it
        assert abs(r["change"]) == pytest.approx(a.MAX_STEP * 100) and r["current"] > a.MAX_W * 100
        assert r["reason"].endswith(".")
    themes = {}
    for r in rows:
        themes[r["theme"]] = themes.get(r["theme"], 0) + r["suggested"]
    assert max(themes.values()) <= a.THEME_CAP * 100 + 1e-6
    assert s1["after"]["volatility"] < s1["before"]["volatility"]
    dabur = next(r for r in rows if r["symbol"] == "DABUR")  # the smallest risk share
    assert dabur["change"] == pytest.approx(3) and "3-point step" in dabur["reason"]
    top = max(a.overview()["holdings"], key=lambda h: h["risk_share"])["symbol"]
    assert next(r for r in rows if r["symbol"] == top)["change"] < 0  # the most risk comes down


def test_equal_risk_contribution_is_inverse_vol_without_correlation():
    from app.portfolio.analytics import _erc

    vol = np.array([0.1, 0.2, 0.4])
    w = _erc(np.diag(vol**2))
    assert w == pytest.approx((1 / vol) / (1 / vol).sum(), rel=1e-6)


def test_holdings_are_per_account_and_today_follows(seeded):
    from app.intel.digest import build_digest
    from app.network.owner import set_owner

    with _client() as c:
        before = c.get("/portfolio/holdings", headers=DEMO).json()
        assert (
            c.post("/portfolio/holdings", json={"symbol": "PERSISTENT"}, headers=DEMO).status_code
            == 200
        )
        h = c.delete("/portfolio/holdings/IDEA", headers=DEMO).json()["holdings"]
        assert "IDEA" not in h and h["PERSISTENT"] == pytest.approx(0.03, abs=0.002)
        assert sum(h.values()) == pytest.approx(1)
        # buying more blends the new shares in at today's price; selling keeps the cost
        pos = {
            p["symbol"]: p for p in c.get("/portfolio/holdings", headers=DEMO).json()["positions"]
        }
        t = pos["RELIANCE"]
        qty = {s: p["qty"] for s, p in pos.items()} | {"RELIANCE": t["qty"] + 10, "TCS": 1}
        assert c.put("/portfolio/holdings", json={"qty": qty}, headers=DEMO).status_code == 200
        after = {
            p["symbol"]: p for p in c.get("/portfolio/holdings", headers=DEMO).json()["positions"]
        }
        blended = (t["qty"] * t["avg_cost"] + 10 * t["price"]) / (t["qty"] + 10)
        assert after["RELIANCE"]["avg_cost"] == pytest.approx(blended, abs=0.01)
        assert after["TCS"]["qty"] == 1 and after["TCS"]["avg_cost"] == pos["TCS"]["avg_cost"]
        assert before["value"] == pytest.approx(sum(p["value"] for p in before["positions"]))
        assert "IDEA" in c.get("/portfolio/holdings", headers=OTHER).json()["holdings"]
        assert (
            c.post("/portfolio/holdings", json={"symbol": "NOPE"}, headers=DEMO).status_code == 404
        )
        assert c.put("/portfolio/holdings", json={"weights": {}}, headers=DEMO).status_code == 400
        assert c.get("/portfolio", headers=DEMO).json()["custom"] is True

    set_owner("demo")
    cards = build_digest("30d")["cards"]
    assert not any(x["symbol"] == "IDEA" and x["in_portfolio"] for x in cards)
    set_owner("demo2")
    assert any(x["symbol"] == "IDEA" and x["in_portfolio"] for x in build_digest("30d")["cards"])

    with _client() as c:
        back = c.post("/portfolio/holdings/reset", headers=DEMO).json()["holdings"]
    assert "IDEA" in back and "PERSISTENT" not in back


def test_ai_review_is_clipped_cited_and_bounded(seeded):
    from app.portfolio import analytics, review

    sug = analytics.suggest()
    events = [{"id": "A:1", "symbol": "TCS", "what": "x"}]
    records = [{"id": "F:PAYTM", "symbol": "PAYTM", "what": "y"}]
    res = review.Review(
        summary="s",
        adjustments=[
            review.Adjustment(symbol="PAYTM", delta_pp=-5, reason="cash", cites=["F:PAYTM"]),
            review.Adjustment(symbol="TCS", delta_pp=1, reason="order", cites=["A:1"]),
            review.Adjustment(symbol="INFY", delta_pp=2, reason="vibes", cites=["A:999"]),
            review.Adjustment(symbol="ZOMATO", delta_pp=1, reason="?", cites=["A:1"]),
        ],
    )
    out = review.apply(sug, res, events, records)
    kept = {k["symbol"]: k for k in out["adjustments"]}
    assert set(kept) == {"PAYTM", "TCS"} and kept["PAYTM"]["delta"] == -2
    assert {d["symbol"] for d in out["dropped"]} == {"INFY", "ZOMATO"}
    assert sum(out["weights"].values()) == pytest.approx(100)
    rows = {r["symbol"]: r for r in sug["holdings"]}
    for s, v in out["weights"].items():  # a nudge stretches code's step by 2 points at most
        assert rows[s]["lo"] - 2 - 0.2 <= v <= rows[s]["hi"] + 2 + 0.2
        assert v >= analytics.MIN_W * 100 - 1e-6
        assert v <= max(analytics.MAX_W * 100, rows[s]["hi"]) + 1e-6


def test_review_runs_only_when_asked_and_once(seeded, monkeypatch):
    from app.portfolio import review

    calls = []

    class FakeLLM:
        def run(self, task, **kw):
            calls.append(task)
            return review.Review(summary="Nothing in the filings changes this.", adjustments=[])

    monkeypatch.setattr("app.llm.get_llm", lambda: FakeLLM())
    with _client() as c:
        # (the demo's shipped review matches only the day it was written: the daily data
        # refresh changes its inputs, so it isn't asserted here)
        c.delete("/portfolio/holdings/IDEA", headers=DEMO)
        assert c.get("/portfolio/suggested", headers=DEMO).json()["review"]["status"] == "not_run"
        assert not calls
        r = c.post("/portfolio/suggested/review", headers=DEMO).json()
        assert r["status"] == "done" and calls == ["portfolio_review"]
        again = c.get("/portfolio/suggested", headers=DEMO).json()["review"]
        assert again["status"] == "done" and calls == ["portfolio_review"]  # stored, no call


def test_limits_are_the_investors_and_can_be_switched_off(seeded):
    """Nothing is hard-wired: change the maximum, drop the step, remove the theme cap."""
    from app.network.owner import set_owner
    from app.portfolio import analytics as a

    with _client() as c:
        r = c.put("/portfolio/settings", json={"max_pct": 15, "max_step_pct": None}, headers=DEMO)
        assert r.status_code == 200 and r.json()["settings"]["max_step_pct"] is None
        assert c.put("/portfolio/settings", json={"max_pct": 0.5}, headers=DEMO).status_code == 400
        assert (
            c.put(
                "/portfolio/settings", json={"min_pct": 20, "max_pct": 10}, headers=DEMO
            ).status_code
            == 400
        )
        assert c.put("/portfolio/settings", json={"tilt": None}, headers=DEMO).status_code == 400
        assert c.put("/portfolio/settings", json={"bogus": 1}, headers=DEMO).status_code == 400
        assert c.get("/portfolio/settings", headers=OTHER).json()["settings"]["max_pct"] == 9.0
    set_owner("demo")
    s = a.suggest()
    assert s["rules"]["max"] == 15 and s["rules"]["max_step"] == 100
    assert all(r["suggested"] <= 15 + 1e-6 for r in s["holdings"])
    assert any(abs(r["change"]) > 3 for r in s["holdings"])  # no step limit: straight to target
    with _client() as c:
        c.put("/portfolio/settings", json={"theme_cap_pct": None, "min_pct": 10}, headers=DEMO)
    s = a.suggest()
    assert s["rules"]["min"] == pytest.approx(100 / 20) and s["rules"]["notes"]  # relaxed, said so
    o = a.overview()
    assert not any("Lenders" in f for f in o["flags"])  # no theme cap, no concentration warning
    with _client() as c:
        c.post("/portfolio/settings/reset", headers=DEMO)
    assert a.suggest()["rules"]["max"] == 9


def test_ai_limits_follow_settings(seeded):
    from app.network.owner import set_owner
    from app.portfolio import analytics, review, settings

    set_owner("demo")
    settings.set_settings({"ai_nudge_pct": 0.5, "ai_max_adjust": 1})
    sug = analytics.suggest()
    res = review.Review(
        summary="s",
        adjustments=[
            review.Adjustment(symbol="TCS", delta_pp=1.5, reason="order", cites=["A:1"]),
            review.Adjustment(symbol="INFY", delta_pp=0.3, reason="order", cites=["A:1"]),
        ],
    )
    out = review.apply(sug, res, [{"id": "A:1", "symbol": "TCS", "what": "x"}], [])
    assert [k["symbol"] for k in out["adjustments"]] == ["TCS"]
    assert out["adjustments"][0]["delta"] == 0.5
    assert "between -0.5 and +0.5" in review.system_prompt(0.5, 1)
    settings.set_settings({"ai_max_adjust": 0})
    assert review.get_review(run=True)["status"] == "off"  # never calls the model


def test_new_holding_and_lot_sizes_are_settings(seeded):
    with _client() as c:
        assert c.get("/portfolio/settings", headers=DEMO).json()["settings"]["lot_pct"] == 0.5
        c.put("/portfolio/settings", json={"new_holding_pct": 6.5, "lot_pct": 1.25}, headers=DEMO)
        h = c.post("/portfolio/holdings", json={"symbol": "PERSISTENT"}, headers=DEMO).json()
        assert h["holdings"]["PERSISTENT"] == pytest.approx(0.065, abs=0.002)
        assert c.put("/portfolio/settings", json={"lot_pct": 0}, headers=DEMO).status_code == 400
