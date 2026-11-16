"""Fixes from the fresh-reviewer pass: numbers that must agree across screens."""

import pytest


def test_moves_count_only_as_a_reaction_to_the_filing():
    from app.intel.digest import reaction

    a = [{"kind": "price", "ts": f"2026-11-{d:02d}T15:30:00", "value": 5.0} for d in (2, 3, 4, 9)]
    # filed after the close on the 2nd: the reaction starts on the 3rd, runs a few days
    got = [x["ts"][:10] for x in reaction("2026-11-02T18:10:00", a)]
    assert got == ["2026-11-03", "2026-11-04"]
    # filed during market hours: that session counts
    assert reaction("2026-11-02T11:00:00", a)[0]["ts"].startswith("2026-11-02")


def test_position_size_weighs_on_priority():
    from app.intel.digest import _priority

    card = {"category": "M&A", "materiality": 70, "alerts": [], "helpers": [], "kind": "filing"}
    small = _priority(card, {"in_portfolio": 1, "weight": 0.005}, 18)
    equal = _priority(card, {"in_portfolio": 1, "weight": 1 / 18}, 18)
    big = _priority(card, {"in_portfolio": 1, "weight": 0.12}, 18)
    assert small < equal < big


def test_newer_results_filing_becomes_the_latest_quarter(seeded):
    from app.research.compare import _fq, compare
    from app.research.service import get_cached

    v = get_cached("KAYNES")
    last = v["financials"]["trajectory"]["quarterly"][-1]
    assert v["latest_quarter"] == "2026-09" and last["source"] == "results filing"
    assert last["revenue_yoy"] == pytest.approx(4.4)  # the same figure Today's card shows
    row = next(m for m in compare("KAYNES", "DIXON")["metrics"] if m["key"] == "revenue_yoy_q")
    assert row["values"][0] == pytest.approx(4.4)
    assert (_fq("2026-09"), _fq("2026-06"), _fq("2026-03")) == ("Q2 FY27", "Q1 FY27", "Q4 FY26")


def test_answer_figures_missing_from_the_cited_page_are_marked():
    from app.research.qa import _figures, unchecked_numbers

    assert _figures("Rs 1,365 crore in FY2026, 12 sites, 1,311.4 crore") == {"1365", "1311.4"}
    pages = {"AR": ["Trade receivables 1,365.20 crore"]}
    cites = [{"doc": "AR", "page": 1}]
    assert unchecked_numbers("Receivables Rs 1,365 crore", cites, pages, "") == []
    assert unchecked_numbers("Rose from Rs 1,158 crore", cites, pages, "") == ["1158"]


def test_as_it_stands_names_holdings_outside_your_limits(seeded):
    from app.portfolio import analytics

    flags = analytics.overview()["flags"]
    assert any(f.startswith("6 holdings are above your 9% maximum: TITAN") for f in flags)
    assert any("below your 2% minimum: KAYNES" in f for f in flags)


def test_suggestion_reasons_name_the_limit_that_binds(seeded):
    from app.portfolio import analytics

    sug = analytics.suggest()
    by_theme: dict[str, float] = {}
    for h in sug["holdings"]:
        by_theme[h["theme"]] = by_theme.get(h["theme"], 0) + h["suggested"]
    cap = sug["rules"]["theme_cap"]
    for h in sug["holdings"]:
        if "theme within the cap" in h["reason"]:
            assert by_theme[h["theme"]] >= cap - 0.01, h
    themes = {h["symbol"]: h["theme"] for h in sug["holdings"]}
    assert themes["CGPOWER"] == themes["POLYCAB"] == "capital goods"
    assert themes["KAYNES"] == themes["DIXON"] == "electronics manufacturing"


def test_reset_can_be_undone_with_the_same_buy_prices(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    h = {"X-Finn-User": "demo2"}
    with TestClient(app) as c:
        pos = c.get("/portfolio/holdings", headers=h).json()["positions"]
        qty = {p["symbol"]: p["qty"] for p in pos}
        qty[pos[0]["symbol"]] += 10  # an edit: buys at today's price, blending the cost
        c.put("/portfolio/holdings", json={"qty": qty}, headers=h)
        before = {
            p["symbol"]: (p["qty"], p["avg_cost"])
            for p in c.get("/portfolio/holdings", headers=h).json()["positions"]
        }
        undo = c.post("/portfolio/holdings/reset", headers=h).json()["undo"]
        assert undo and c.post("/portfolio/holdings/reset", headers=h).json()["undo"] is None
        c.post("/portfolio/holdings/restore", json={"positions": undo}, headers=h)
        after = {
            p["symbol"]: (p["qty"], p["avg_cost"])
            for p in c.get("/portfolio/holdings", headers=h).json()["positions"]
        }
        assert after == before
        assert (
            c.post(
                "/portfolio/holdings/restore", json={"positions": {"TCS": [0, 1]}}, headers=h
            ).status_code
            == 400
        )
        c.post("/portfolio/holdings/reset", headers=h)
