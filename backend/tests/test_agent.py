"""The Ask pipeline (FR-PULL-18): plan in code, fetch with tools, analyse and report in code.
Offline: the tools are fed the committed L&T accounts and a synthetic price series."""

from __future__ import annotations

import pytest

from app.agent import analyse as an
from app.agent import plan as pl
from app.agent import reports, tools


def test_growth_and_change_words():
    assert an.pct(110, 100) == 10.0
    assert an.pct(5, -10) is None  # a loss base has no meaningful %
    assert an.change_note(-5, -10) == "loss narrowed"
    assert an.change_note(5, -10) == "turned profitable"
    assert an.cagr(100, 133.1, 3) == 10.0
    assert an.fq("2026-09") == "Q2 FY27" and an.fq("2026-03") == "Q4 FY26"


def test_results_compare_quarter_with_last_quarter_and_a_year_ago():
    fin = {
        "is_financial": False,
        "quarters": [
            {"period": "2025-09", "revenue": 100, "op_profit": 20, "pbt": 15, "pat": 10, "opm": 20},
            {"period": "2026-06", "revenue": 110, "op_profit": 21, "pbt": 16, "pat": 12, "opm": 19},
            {"period": "2026-09", "revenue": 121, "op_profit": 24, "pbt": 18, "pat": 13, "opm": 20},
        ],
    }
    r = an.results(fin)
    rev = r["rows"][0]
    assert (r["quarter"], r["prev_quarter"], r["year_ago_quarter"]) == (
        "Q2 FY27",
        "Q1 FY27",
        "Q2 FY26",
    )
    assert (rev["qoq"], rev["yoy"]) == (10.0, 21.0)
    assert [x["label"] for x in r["rows"]] == ["Revenue", "EBITDA", "PBT", "PAT"]


def test_lenders_show_net_interest_income_not_ebitda():
    fin = {
        "is_financial": True,
        "quarters": [
            {"period": "2026-06", "revenue": 100, "interest": 60, "pbt": 20, "pat": 15},
            {"period": "2026-09", "revenue": 110, "interest": 62, "pbt": 22, "pat": 16},
        ],
    }
    r = an.results(fin)
    nii = next(x for x in r["rows"] if x["metric"] == "nii")
    assert nii["label"] == "Net interest income" and nii["value"] == 48 and nii["prev"] == 40
    assert r["margin"]["now"] is None


def test_valuation_grade_weighs_pe_with_growth():
    assert an.value_grade({"pe": 14, "peg": 3.0}) == "strong"  # a low P/E isn't stretched
    assert an.value_grade({"pe": 40, "peg": 1.0}) == "strong"
    assert an.value_grade({"pe": 88, "peg": 1.4}) == "fair"
    assert an.value_grade({"pe": 60, "peg": 3.0}) == "weak"
    assert an.value_grade({"pe": None, "peg": None}) is None


def test_guidance_sentences_are_quoted_from_the_page():
    pages = [
        "Opening remarks. We expect revenue growth of 15% in FY27 as new capacity comes on stream.",
        "Analyst: what about margins? Thank you.",
    ]
    out = an.guidance_sentences(pages)
    assert out and out[0]["page"] == 1 and out[0]["text"] in pages[0]


@pytest.mark.parametrize(
    "msg,report,tickers",
    [
        ("Should I buy Trent?", "verdict", ["TRENT"]),
        ("compare tcs and infosys", "compare", ["TCS", "INFY"]),
        ("How was HDFC Bank's latest quarter?", "results", ["HDFCBANK"]),
        ("Is Titan expensive?", "valuation", ["TITAN"]),
        ("bull vs bear on Eternal", "bull_bear", ["ETERNAL"]),
        ("trent results", "results", ["TRENT"]),
        ("How is my portfolio doing?", "portfolio", []),
    ],
)
def test_rules_plan_without_a_model(seeded, msg, report, tickers):
    p = pl.plan(msg, use_model=False)
    assert (p.report, p.tickers, p.by) == (report, tickers, "rules")


def test_follow_up_stays_on_the_company_and_compare_adds_it(seeded):
    assert pl.plan("Is it cheap?", context="LT", use_model=False).tickers == ["LT"]
    assert pl.plan("Compare it with Siemens", context="LT", use_model=False).tickers == [
        "LT",
        "SIEMENS",
    ]


@pytest.fixture
def offline(seeded, monkeypatch):
    """Tools that read the committed L&T accounts and a rising price series."""
    from app.research.service import load_fundamentals

    real = tools.TOOLS["financials"].fn

    def fake_fin(ticker):
        import app.ingest.fundamentals as f

        monkeypatch.setattr(f, "fetch_fundamentals", lambda t: load_fundamentals(t))
        return real(ticker)

    closes = [3000 + i * 4 for i in range(250)]
    fakes = {
        "financials": fake_fin,
        "prices": lambda ticker, period="1y": {
            "ticker": ticker,
            "period": period,
            "dates": [f"d{i}" for i in range(250)],
            "close": closes,
            "volume": [1000] * 250,
        },
        "filings": lambda ticker, days=60: [],
        "holding": lambda ticker: None,
    }
    tools._cache.clear()
    for name, fn in fakes.items():
        monkeypatch.setitem(tools.TOOLS, name, tools.Tool(name, fn, tools.TOOLS[name].args, ""))
    yield
    tools._cache.clear()


def test_every_report_builds_from_code_alone(offline, monkeypatch):
    import app.llm as llm

    monkeypatch.setattr(llm, "get_llm", lambda: (_ for _ in ()).throw(AssertionError("no model")))
    for kind in ("snapshot", "results", "bull_bear", "verdict", "valuation", "momentum", "full"):
        out = reports.build(kind, ["LT"])
        assert out["blocks"] and out["title"] == reports.KINDS[kind], kind
        assert out["blocks"][-1]["type"] == "note"
    v = reports.build("verdict", ["LT"])
    assert v["blocks"][0]["text"].startswith("FINN doesn't tell you to buy or sell")
    assert "Larsen" in v["digest"] and len(v["digest"]) < 2500  # what a model would get


def test_chat_answers_an_unread_company_without_a_model(offline, monkeypatch):
    from fastapi.testclient import TestClient

    import app.llm as llm
    from app.main import app

    monkeypatch.setattr(llm, "get_llm", lambda: (_ for _ in ()).throw(AssertionError("no model")))
    c = TestClient(app)
    j = c.post("/pull/chat", json={"message": "Is L&T expensive?"}).json()
    assert (j["kind"], j["intent"], j["symbol"]) == ("reply", "valuation", "LT")
    j = c.post(
        "/pull/chat", json={"message": "Results", "symbol": "LT", "intent": "results"}
    ).json()
    assert j["blocks"][0]["type"] == "table" and j["blocks"][0]["columns"][2] == "QoQ"
