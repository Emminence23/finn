"""Two companies side by side: computed from reported financials, direction-aware, and
honest about what isn't comparable."""

from fastapi.testclient import TestClient


def _client():
    from app.main import app

    return TestClient(app)


def test_lt_against_bhel(seeded, monkeypatch):
    from app.llm import router

    monkeypatch.setattr(router, "get_llm", lambda: (_ for _ in ()).throw(AssertionError("no LLM")))
    with _client() as c:
        r = c.get("/compare?a=lt&b=BHEL").json()
    assert [x["short"] for x in r["companies"]] == ["Larsen & Toubro", "Bharat Heavy Electricals"]
    m = {x["key"]: x for x in r["metrics"]}
    # higher margin wins; fewer working-capital days win; size and valuation pick no side
    assert (
        m["margin_pct"]["better"] == 0
        and m["margin_pct"]["values"][0] > m["margin_pct"]["values"][1]
    )
    wc = m["working_capital_days"]
    assert wc["better"] == (0 if wc["values"][0] < wc["values"][1] else 1)
    assert m["revenue"]["better"] is None and m["pe"]["better"] is None
    assert r["wins"] == [sum(x["better"] == i for x in r["metrics"]) for i in (0, 1)]
    # every sentence names the winner first and quotes the winning value
    assert r["lines"] and "Larsen & Toubro earns a wider margin: 13.0%" in " ".join(r["lines"])
    assert r["companies"][0]["promises"]["score"] is not None  # L&T has a scorecard


def test_lender_rows_are_dropped_not_misread(seeded):
    with _client() as c:
        r = c.get("/compare?a=HDFCBANK&b=TITAN").json()
    keys = {x["key"] for x in r["metrics"]}
    assert not keys & {
        "margin_pct",
        "cfo_to_pat_3y",
        "working_capital_days",
        "debt_to_equity",
        "roce_pct",
    }
    assert any("lender" in n for n in r["notes"])


def test_refusals_and_peers(seeded):
    with _client() as c:
        assert c.get("/compare?a=LT&b=lt").status_code == 400
        peers = c.get("/compare/peers?symbol=LT").json()["peers"]
        assert peers[0] == {
            "symbol": "BHEL",
            "name": "Bharat Heavy Electricals Limited",
            "kind": "competitor",
        }
        assert "LT" not in {p["symbol"] for p in peers}
