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
    assert o["summary"]["holdings"] == 18 and not o["custom"]
    assert sum(h["weight"] for h in o["holdings"]) == pytest.approx(100)
    assert sum(t["weight"] for t in o["themes"]) == pytest.approx(100)
    assert sum(h["risk_share"] for h in o["holdings"]) == pytest.approx(100)
    assert any("Lenders together are 26%" in f for f in o["flags"])
    assert o["correlated"][0]["a"] in {"INFY", "TCS"}  # the two IT majors move together


def test_suggestion_respects_every_rule_and_is_repeatable(seeded):
    from app.portfolio import analytics as a

    s1, s2 = a.suggest(), a.suggest()
    assert s1 == s2  # same inputs, same answer
    rows = s1["holdings"]
    assert sum(r["suggested"] for r in rows) == pytest.approx(100)
    for r in rows:
        assert a.MIN_W * 100 - 1e-6 <= r["suggested"] <= a.MAX_W * 100 + 1e-6
        assert abs(r["change"]) <= a.MAX_STEP * 100 + 1e-6
        assert r["reason"].endswith(".")
    themes = {}
    for r in rows:
        themes[r["theme"]] = themes.get(r["theme"], 0) + r["suggested"]
    assert max(themes.values()) <= a.THEME_CAP * 100 + 1e-6
    assert s1["after"]["volatility"] < s1["before"]["volatility"]
    rel = next(r for r in rows if r["symbol"] == "RELIANCE")
    assert rel["change"] == pytest.approx(-3) and "risk" in rel["reason"]


def test_equal_risk_contribution_is_inverse_vol_without_correlation():
    from app.portfolio.analytics import _erc

    vol = np.array([0.1, 0.2, 0.4])
    w = _erc(np.diag(vol**2))
    assert w == pytest.approx((1 / vol) / (1 / vol).sum(), rel=1e-6)


def test_holdings_are_per_account_and_today_follows(seeded):
    from app.intel.digest import build_digest
    from app.network.owner import set_owner

    with _client() as c:
        assert (
            c.post("/portfolio/holdings", json={"symbol": "PERSISTENT"}, headers=DEMO).status_code
            == 200
        )
        h = c.delete("/portfolio/holdings/KAYNES", headers=DEMO).json()["holdings"]
        assert "KAYNES" not in h and h["PERSISTENT"] == pytest.approx(
            0.03 / (1 - 0.04 * 0.97), rel=1e-6
        )
        assert sum(h.values()) == pytest.approx(1)
        assert "KAYNES" in c.get("/portfolio/holdings", headers=OTHER).json()["holdings"]
        assert (
            c.post("/portfolio/holdings", json={"symbol": "NOPE"}, headers=DEMO).status_code == 404
        )
        assert c.put("/portfolio/holdings", json={"weights": {}}, headers=DEMO).status_code == 400
        assert c.get("/portfolio", headers=DEMO).json()["custom"] is True

    set_owner("demo")
    cards = build_digest("30d")["cards"]
    assert not any(x["symbol"] == "KAYNES" and x["in_portfolio"] for x in cards)
    set_owner("demo2")
    assert any(x["symbol"] == "KAYNES" and x["in_portfolio"] for x in build_digest("30d")["cards"])

    with _client() as c:
        back = c.post("/portfolio/holdings/reset", headers=DEMO).json()["holdings"]
    assert "KAYNES" in back and "PERSISTENT" not in back


def test_ai_review_is_clipped_cited_and_bounded(seeded):
    from app.portfolio import analytics, review

    sug = analytics.suggest()
    events = [{"id": "A:1", "symbol": "TCS", "what": "x"}]
    records = [{"id": "F:KAYNES", "symbol": "KAYNES", "what": "y"}]
    res = review.Review(
        summary="s",
        adjustments=[
            review.Adjustment(symbol="KAYNES", delta_pp=-5, reason="cash", cites=["F:KAYNES"]),
            review.Adjustment(symbol="TCS", delta_pp=1, reason="order", cites=["A:1"]),
            review.Adjustment(symbol="INFY", delta_pp=2, reason="vibes", cites=["A:999"]),
            review.Adjustment(symbol="ZOMATO", delta_pp=1, reason="?", cites=["A:1"]),
        ],
    )
    out = review.apply(sug, res, events, records)
    kept = {k["symbol"]: k for k in out["adjustments"]}
    assert set(kept) == {"KAYNES", "TCS"} and kept["KAYNES"]["delta"] == -2
    assert {d["symbol"] for d in out["dropped"]} == {"INFY", "ZOMATO"}
    assert sum(out["weights"].values()) == pytest.approx(100)
    assert all(
        analytics.MIN_W * 100 - 1e-6 <= v <= analytics.MAX_W * 100 + 1e-6
        for v in out["weights"].values()
    )


def test_review_runs_only_when_asked_and_once(seeded, monkeypatch):
    from app.portfolio import review

    calls = []

    class FakeLLM:
        def run(self, task, **kw):
            calls.append(task)
            return review.Review(summary="Nothing in the filings changes this.", adjustments=[])

    monkeypatch.setattr("app.llm.get_llm", lambda: FakeLLM())
    with _client() as c:
        # the demo portfolio's review ships as a fixture; a changed portfolio has none yet
        assert c.get("/portfolio/suggested", headers=DEMO).json()["review"]["status"] == "done"
        c.delete("/portfolio/holdings/TRENT", headers=DEMO)
        assert c.get("/portfolio/suggested", headers=DEMO).json()["review"]["status"] == "not_run"
        assert not calls
        r = c.post("/portfolio/suggested/review", headers=DEMO).json()
        assert r["status"] == "done" and calls == ["portfolio_review"]
        again = c.get("/portfolio/suggested", headers=DEMO).json()["review"]
        assert again["status"] == "done" and calls == ["portfolio_review"]  # stored, no call
