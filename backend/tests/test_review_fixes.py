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
    import copy

    from app.research.compare import _fq
    from app.research.service import add_filed_quarter, get_cached

    # the standardised table stops a quarter short: L&T's results filing of 27 Oct fills it
    fin = copy.deepcopy(get_cached("LT")["financials"])
    fin["trajectory"]["quarterly"] = fin["trajectory"]["quarterly"][:-1]
    assert add_filed_quarter(fin, "LT")["period"] == "2026-09"
    last = fin["trajectory"]["quarterly"][-1]
    assert last["source"] == "results filing" and last["filed"].startswith("2026-10-27")
    assert last["revenue_yoy"] == pytest.approx(15.8)  # the same figure Today's card shows
    assert add_filed_quarter(fin, "LT") is None  # never added twice
    assert (_fq("2026-09"), _fq("2026-06"), _fq("2026-03")) == ("Q2 FY27", "Q1 FY27", "Q4 FY26")


def test_answer_figures_missing_from_the_cited_page_are_marked():
    from app.research.qa import _figures, unchecked_numbers

    assert _figures("Rs 1,365 crore in FY2026, 12 sites, 1,311.4 crore") == {"1365", "1311.4"}
    pages = {"AR": ["Trade receivables 1,365.20 crore"]}
    cites = [{"doc": "AR", "page": 1}]
    assert unchecked_numbers("Receivables Rs 1,365 crore", cites, pages, "") == []
    assert unchecked_numbers("Rose from Rs 1,158 crore", cites, pages, "") == ["1158"]


def test_as_it_stands_names_holdings_outside_your_limits(seeded):
    from app.network.owner import set_owner
    from app.portfolio import analytics, settings

    set_owner("demo")
    assert not any("maximum" in f or "minimum" in f for f in analytics.overview()["flags"])
    settings.set_settings({"max_pct": 7.5, "min_pct": 3.5})
    flags = analytics.overview()["flags"]
    assert "1 holding is above your 7.5% maximum: ICICIBANK 7.9%." in flags
    assert any(f.startswith("4 holdings are below your 3.5% minimum: DABUR") for f in flags)


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
    assert themes["LT"] == themes["BHEL"] == "capital goods"
    assert themes["HDFCBANK"] == themes["ICICIBANK"] == "private banking"


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


def test_symbols_are_checked_before_use(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        assert c.get("/research/..%2F..%2Fetc").status_code in (400, 404)
        assert c.get("/compare", params={"a": "KAYNES", "b": "../x"}).status_code == 400
        assert c.get("/research/KAYNES").status_code == 200
        assert c.get("/companies/M&M/prices").status_code != 400  # & is a real NSE symbol


def test_cagr_needs_the_year_exactly_n_back():
    from app.research.financials import cagr

    full = {"2021-03": 100, "2022-03": 110, "2023-03": 121, "2024-03": 133.1}
    assert cagr(full, 3) == pytest.approx(10.0)
    gap = {"2020-03": 100, "2022-03": 110, "2023-03": 121, "2024-03": 133.1}  # 2021 missing
    assert cagr(gap, 3) is None  # four points, but 2021 isn't there: no "3-year" growth
    assert cagr({"2021-03": 100, "2024-03": 133.1}, 3) == pytest.approx(10.0)


def _fin(cfo, pat, equity=(10, 90), debt=50):
    from app.research.financials import build_financials

    ys = ["2022-03", "2023-03", "2024-03"]
    return build_financials(
        {
            "tables": {
                "annual_pl": {
                    "Sales": dict.fromkeys(ys, 1000),
                    "Net Profit": dict(zip(ys, pat, strict=True)),
                },
                "cash_flow": {"Cash from Operating Activity": dict(zip(ys, cfo, strict=True))},
                "balance_sheet": {
                    "Equity Capital": dict.fromkeys(ys, equity[0]),
                    "Reserves": dict.fromkeys(ys, equity[1]),
                    "Borrowings": dict.fromkeys(ys, debt),
                },
            }
        }
    )


def test_cash_conversion_needs_three_full_years_and_a_profit():
    ok = _fin([90, 100, 110], [100, 100, 100])["cash_quality"]
    assert ok["cfo_to_pat_3y"] == pytest.approx(1.0) and ok["coverage"]["cfo"] == "3/3"
    gap = _fin([90, None, 110], [100, 100, 100])["cash_quality"]
    assert gap["cfo_to_pat_3y"] is None and gap["coverage"]["cfo"] == "2/3"  # not zero
    loss = _fin([90, 100, 110], [-50, -60, 20])["cash_quality"]
    assert loss["cfo_to_pat_3y"] is None and loss["pat_3y"] == -90  # shown, not divided


def test_negative_net_worth_is_flagged_not_called_lightly_geared():
    f = _fin([90, 100, 110], [100, 100, 100], equity=(10, -60))
    ids = {x["id"] for x in f["flags"]}
    assert f["balance_sheet"]["annual"][-1]["debt_to_equity"] is None
    assert "fin:negative_equity" in ids and "fin:leverage" not in ids


def test_unrelated_filings_of_one_category_are_separate_events():
    from app.intel.digest import split_events

    def a(i, day, text):
        return {"id": i, "ts": f"2026-11-{day:02d}T10:00:00", "summary": text, "subject": ""}

    groups = {
        ("KAYNES", "M&A"): [
            a("1", 12, "Executed a binding term sheet with Vishay Intertechnology"),
            a("2", 15, "Board approved a joint venture with Toyokawa Techno for TFT modules"),
        ],
        ("CGPOWER", "litigation"): [
            a("3", 5, "Pollution board directed closure of manufacturing operations at Waluj unit"),
            a("4", 7, "High Court stayed pollution board closure direction for manufacturing unit"),
        ],
        ("TITAN", "results"): [a("5", 5, "Approved results"), a("6", 6, "Newspaper publication")],
    }
    out = split_events(groups)
    assert len([k for k in out if k[0] == "KAYNES"]) == 2  # two deals, two cards
    assert len([k for k in out if k[0] == "CGPOWER"]) == 1  # the order and its stay
    assert len(out[("TITAN", "results")]) == 2  # one results event per period


def test_research_view_says_when_its_inputs_changed(seeded, monkeypatch):
    from app.research import service

    assert service.get_cached("KAYNES")["freshness"]["status"] == "fresh"
    monkeypatch.setattr(service, "VERSIONS", ("research-v2",))  # e.g. a prompt changed
    v = service.get_cached("KAYNES")
    assert v is not None and v["freshness"]["status"] == "stale"  # still served, marked
