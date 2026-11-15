import json
from pathlib import Path

import pytest

from app.research.docs import fiscal_label, quarter_discussed, select_docs
from app.research.financials import build_financials, cagr
from app.research.guidance import locate
from app.research.narrative import _clean_cites
from app.research.promises import Scorecard, Verdict, horizon_end, validate

FIXTURES = Path(__file__).parents[1] / "data" / "fixtures"  # repo copy, not the test tmp


# ------------------------------------------------------------------ docs
@pytest.mark.parametrize(
    "call,quarter,label",
    [
        ("2026-08", "2026-06", "Q1 FY27"),
        ("2025-12", "2025-09", "Q2 FY26"),
        ("2026-01", "2025-12", "Q3 FY26"),
        ("2026-05", "2026-03", "Q4 FY26"),
    ],
)
def test_call_month_maps_to_quarter_discussed(call, quarter, label):
    assert quarter_discussed(call) == quarter
    assert fiscal_label(quarter) == label


def test_select_docs_newest_transcripts_first():
    docs = [
        {"kind": "transcript", "period": p, "url": p, "label": ""}
        for p in ("2025-05", "2026-08", "2026-02", "2025-11", "2026-05")
    ] + [{"kind": "annual_report", "period": "FY2026", "url": "ar", "label": ""}]
    refs = select_docs(docs)
    assert [r.id for r in refs] == ["T1", "T2", "T3", "T4", "AR"]
    assert [r.period for r in refs[:4]] == ["2026-08", "2026-05", "2026-02", "2025-11"]


# ------------------------------------------------------------------ financials (FR-PULL-03/04/06/07)
def test_cagr_and_guards():
    assert cagr({"2023-03": 100.0, "2024-03": 121.0, "2025-03": 133.1, "TTM": 999.0}, 2) == 15.4
    assert cagr({"2024-03": -5.0, "2025-03": 10.0}, 1) is None  # undefined from a loss
    assert cagr({"2025-03": 10.0}, 3) is None


def test_kaynes_flags_are_computed_from_tables():
    f = json.loads((FIXTURES / "fundamentals" / "KAYNES.json").read_text())
    fin = build_financials(f)
    assert fin["snapshot"]["revenue"] == 3626.0 and fin["snapshot"]["debt_to_equity"] == 0.19
    ids = {x["id"]: x["tone"] for x in fin["flags"]}
    assert ids["fin:receivables"] == "negative"  # debtor days 77 -> 154
    assert ids["fin:cash_conversion"] == "negative"
    assert ids["fin:growth"] == "positive"


def test_lender_gets_no_ebitda_or_working_capital():
    f = json.loads((FIXTURES / "fundamentals" / "MANAPPURAM.json").read_text())
    fin = build_financials(f)
    assert fin["is_lender"] and fin["snapshot"]["margin_label"] == "Financing margin"
    assert fin["snapshot"]["debt_to_equity"] is None
    assert "debtor_days" not in fin["balance_sheet"]["annual"][-1]
    assert "asset_quality" in fin["balance_sheet"]


# ------------------------------------------------------------------ guidance quote check
def test_locate_finds_quote_across_line_breaks_and_wrong_page():
    pages = ["intro text " * 20, "we expect revenue\nto grow 30% in FY27, said the CFO"]
    page, score = locate("We expect revenue to grow 30% in FY27", pages, hint=1)
    assert page == 2 and score >= 90
    assert locate("we will triple margins next year", pages, hint=2)[1] < 85


# ------------------------------------------------------------------ promises (FR-PULL-05)
@pytest.mark.parametrize(
    "h,end",
    [
        ("FY27", "2027-03"),
        ("Q2 FY27", "2026-09"),
        ("H1 FY27", "2026-09"),
        ("by Mar 2027", "2027-03"),
        ("next 2-3 years", None),
        (None, None),
    ],
)
def test_horizon_end(h, end):
    assert horizon_end(h) == end


def _promise(pid, horizon):
    return {
        "id": pid,
        "quote": "q",
        "doc_label": "call",
        "doc_id": pid.split(".")[0],
        "page": 1,
        "target": "t",
        "horizon": horizon,
        "materiality": 3,
    }


def test_validator_drops_unknown_ids_and_guards_premature_miss():
    promises = [_promise("T2.1", "FY26"), _promise("T1.1", "FY28"), _promise("T1.2", "FY28")]
    updates = [{"id": "T1.9"}]
    acts = [{"id": "FY:2026-03"}]
    res = Scorecard(
        items=[
            Verdict(
                promise_ids=["T2.1"],
                verdict="missed",
                actual="a",
                evidence=["FY:2026-03", "made-up"],
                note="n",
            ),
            Verdict(
                promise_ids=["T1.1"],
                verdict="missed",
                actual="a",
                evidence=["FY:2026-03"],
                note="n",
            ),  # FY28 not over, no update
            Verdict(
                promise_ids=["T1.2"], verdict="missed", actual="a", evidence=["T1.9"], note="n"
            ),  # update admits a cut: allowed
            Verdict(
                promise_ids=["T9.9"],
                verdict="delivered",
                actual="a",
                evidence=["FY:2026-03"],
                note="n",
            ),  # invented promise
        ],
        credibility="c",
    )
    out = validate(res, promises, updates, acts, latest_period="2026-06")
    by = {i["promise_ids"][0]: i for i in out["items"]}
    assert set(by) == {"T2.1", "T1.1", "T1.2"}
    assert by["T2.1"]["verdict"] == "missed" and by["T2.1"]["evidence"] == ["FY:2026-03"]
    assert by["T1.1"]["verdict"] == "too_early" and by["T1.1"]["guard"]
    assert by["T1.2"]["verdict"] == "missed"
    assert out["counts"]["missed"] == 2 and out["score"] == 0


def test_unevidenced_verdict_after_deadline_is_unclear_and_unscored():
    promises = [_promise("T3.1", "FY26"), _promise("T3.2", "FY26")]
    res = Scorecard(
        items=[
            Verdict(promise_ids=["T3.1"], verdict="partly", actual="a", evidence=[], note="n"),
            Verdict(
                promise_ids=["T3.2"],
                verdict="delivered",
                actual="a",
                evidence=["FY:2026-03"],
                note="n",
            ),
        ],
        credibility="c",
    )
    out = validate(res, promises, [], [{"id": "FY:2026-03"}], latest_period="2026-06")
    assert [i["verdict"] for i in out["items"]] == ["delivered", "unclear"]
    assert out["score"] == 100  # unclear is excluded from the score


def test_citations_must_point_at_pages_we_sent():
    allowed = {"AR": {4, 12}, "T1": {1, 2, 3}}
    cites = [
        {"doc": "AR", "page": 4},
        {"doc": "AR", "page": 200},
        {"doc": "T9", "page": 1},
        {"doc": "fin:fcf", "page": None},
    ]
    got = _clean_cites(cites, allowed, {"fin:fcf"})
    assert sorted((c["doc"], c["page"] or 0) for c in got) == [("AR", 4), ("fin:fcf", 0)]


def test_select_docs_dedupes_same_month_transcripts():
    docs = [
        {"kind": "transcript", "period": p, "url": f"{p}-{i}", "label": ""}
        for i, p in enumerate(("2026-10", "2026-07", "2026-04", "2026-04", "2026-01"))
    ]
    assert [r.period for r in select_docs(docs)] == ["2026-10", "2026-07", "2026-04", "2026-01"]
