from datetime import datetime

import pytest

from app.intel.results import PeriodFigures, ResultsExtraction, build_results_card, pct_change
from app.intel.taxonomy import classify_rules
from app.network.graph import Person, Role, School, overlaps


# ------------------------------------------------------------------ classifier (FR-PUSH-02)
@pytest.mark.parametrize(
    "desc,subject,expected,confident",
    [
        (
            "Outcome of Board Meeting",
            "submitted the financial results for the period ended September 30",
            "results",
            True,
        ),
        (
            "Outcome of Board Meeting",
            "Outcome of Board Meeting held on November 12",
            "results",
            False,
        ),
        ("Change in Management", "informed about change in Management", "management_change", True),
        ("Resignation of Director/KMP/SMP", "", "management_change", True),
        ("Acquisition", "Incorporation of wholly owned subsidiary", "M&A", True),
        ("Agreements", "Joint Venture Agreements", "M&A", True),
        ("Capacity addition", "", "capex", True),
        ("Corporate Insolvency Resolution Process", "NCLAT order", "litigation", True),
        (
            "Analysts/Institutional Investor Meet/Con. Call Updates",
            "Transcript of the call",
            "earnings_call",
            True,
        ),
        (
            "Analysts/Institutional Investor Meet/Con. Call Updates",
            "Pre-CLSA investor meet",
            "investor_meetings",
            True,
        ),
        (
            "Copy of Newspaper Publication",
            "Newspaper publication of Unaudited Financial Results",
            "results",
            True,
        ),
        ("Copy of Newspaper Publication", "Notice to shareholders", "unclassified", True),
        ("ESOP/ESOS/ESPS", "", "unclassified", True),
        ("Allotment of Securities", "allotment pursuant to ESOP", "unclassified", True),
        ("Shareholders meeting", "Postal Ballot Notice", "postal_ballot", True),
        ("Credit Rating", "", "credit_rating", True),
        ("Updates", "regarding 'Transcript of Earnings Call'", "earnings_call", True),
        ("General Updates", "Redemption of Commercial Paper", "unclassified", True),
        ("General Updates", "something unusual", "unclassified", False),
    ],
)
def test_rules(desc, subject, expected, confident):
    r = classify_rules(desc, subject)
    assert (r.category, r.confident) == (expected, confident)


# ------------------------------------------------------------------ results maths (FR-CARD-01)
def _p(period, rev, oi, fin, dep, pbt, pat):
    return PeriodFigures(
        label=period,
        period_end=period,
        revenue_from_operations=rev,
        other_income=oi,
        finance_costs=fin,
        depreciation=dep,
        profit_before_tax=pbt,
        profit_after_tax=pat,
    )


def test_results_card_computes_ebitda_qoq_yoy_in_crore():
    ex = ResultsExtraction(
        found=True,
        basis="consolidated",
        unit="lakh",
        is_lender=False,
        current=_p("2026-09", 490420, 2494, 7094, 22884, 67104, 50912),
        previous_quarter=_p("2026-06", 503326, 3391, 6862, 22286, 97915, 75887),
        year_ago_quarter=_p("2025-09", 364019, 2571, 7068, 21213, 51705, 38818),
    )
    card = build_results_card("NOPE", ex)
    rows = {r["metric"]: r for r in card["rows"]}
    assert rows["revenue"]["value"] == pytest.approx(4904.2)
    assert rows["ebitda"]["value"] == pytest.approx(945.88)  # 671.04 + 70.94 + 228.84 - 24.94
    assert rows["pat"]["qoq"] == pytest.approx(-32.9)
    assert rows["revenue"]["yoy"] == pytest.approx(34.7)
    assert card["ebitda_margin"] == pytest.approx(19.3)
    assert card["cross_check"]["status"] == "unavailable"  # no screener row for NOPE


def test_lender_has_no_ebitda():
    ex = ResultsExtraction(
        found=True,
        basis="standalone",
        unit="crore",
        is_lender=True,
        current=_p("2026-09", 100, 5, 50, 2, 30, 22),
        previous_quarter=None,
        year_ago_quarter=None,
    )
    rows = {r["metric"]: r for r in build_results_card("X", ex)["rows"]}
    assert rows["ebitda"]["value"] is None and rows["revenue"]["qoq"] is None


def test_pct_change_edge_cases():
    assert pct_change(110, 100) == 10.0
    assert pct_change(-50, -100) == 50.0  # loss narrowed
    assert pct_change(1, 0) is None and pct_change(None, 5) is None


# ------------------------------------------------------------------ overlaps (FR-NET-02)
def _person(pid, roles=(), schools=()):
    return Person(pid, pid, None, True, [], None, list(roles), list(schools))


def test_overlap_confirmed_when_years_intersect():
    a = _person("a", [Role("ICICI Bank Limited", "ICICIBANK", "x", 2013, 2021)])
    b = _person("b", [Role("ICICI Group", "ICICIBANK", "y", 1992, None)])
    (o,) = overlaps(a, b)
    assert o.kind == "worked_together" and o.confidence == "confirmed"


def test_overlap_possible_when_years_unknown_and_none_when_disjoint():
    a = _person("a", [Role("Tetra Pak", None, "x", 2015, 2021)])
    b = _person("b", [Role("Tetra Pak AB", None, "y", None, None)])
    (o,) = overlaps(a, b)
    assert o.kind == "same_employer" and o.confidence == "possible"
    c = _person("c", [Role("Tetra Pak", None, "z", 2001, 2005)])
    assert overlaps(a, c) == []  # provably different years


def test_school_overlap():
    a = _person("a", schools=[School("IIT Bombay", None, 2004, 2008)])
    b = _person("b", schools=[School("IIT Bombay", None, 2006, 2008)])
    c = _person("c", schools=[School("IIT Bombay", None, None, None)])
    assert overlaps(a, b)[0].kind == "studied_together"
    assert overlaps(a, c)[0].kind == "same_school"


# ------------------------------------------------------------------ alerts (FR-ALERT)
def test_alerts_volume_and_price_thresholds():
    from app.db import session
    from app.intel import alerts

    with session() as db:
        db.execute("INSERT INTO companies (symbol, name, in_portfolio) VALUES ('ABC','Abc',1)")
        for i in range(25):
            vol = 1000 if i < 24 else 3100
            close = 100 if i < 24 else 107
            db.execute(
                "INSERT INTO prices VALUES ('ABC', ?, 0,0,0, ?, ?)",
                (f"2026-10-{i + 1:02d}", close, vol),
            )
    rules = alerts.set_rules({"volume_multiple": 3.0, "price_abs_pct": 6.0, "categories": []})
    found = alerts.evaluate(datetime(2026, 10, 25), datetime(2026, 10, 25, 23))
    kinds = {a["kind"]: a for a in found}
    assert kinds["volume"]["reason"] == "Volume 3.1× its 20-day average"
    assert kinds["price"]["value"] == pytest.approx(7.0)
    alerts.set_rules(rules | {"volume_multiple": 3.5, "price_abs_pct": 8.0})
    assert alerts.evaluate(datetime(2026, 10, 25), datetime(2026, 10, 25, 23)) == []


def test_is_bank_ignores_ttm_row_without_balance_sheet():
    import json

    from app.db import session
    from app.intel.results import is_bank

    with session() as db:
        for sym, bs in (("BANKX", {"Deposits": {"2026-03": 1.0}}), ("NBFCX", {"Borrowing": {}})):
            db.execute(
                "INSERT INTO financials_annual VALUES (?,?,?)",
                (sym, "2026-03", json.dumps({"balance_sheet": bs})),
            )
            db.execute(
                "INSERT INTO financials_annual VALUES (?,?,?)",
                (sym, "TTM", json.dumps({"annual_pl": {}})),
            )
    assert is_bank("BANKX") and not is_bank("NBFCX")


@pytest.mark.parametrize(
    "pat,status",
    [(100.0, "match"), (94.0, "pat_basis"), (100.0 * 0.5, "pat_basis")],
)
def test_cross_check_separates_pat_basis_gap(pat, status):
    from app.db import session
    from app.intel.results import cross_check

    with session() as db:
        db.execute(
            "INSERT OR REPLACE INTO financials_quarterly VALUES (?,?,?,?,?,?,?)",
            ("XCHK", "2026-09", 1000.0, None, 130.0, 100.0, "screener"),
        )
    cur = {"period": "2026-09", "revenue": 1000.0, "pbt": 130.0, "pat": pat}
    assert cross_check("XCHK", cur)["status"] == status
    assert cross_check("XCHK", {**cur, "revenue": 900.0})["status"] == "differs"
