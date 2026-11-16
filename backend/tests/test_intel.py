from datetime import datetime

import pytest

from app.intel.results import (
    PeriodFigures,
    ResultsExtraction,
    build_results_card,
    change_note,
    pct_change,
    refresh_changes,
)
from app.intel.taxonomy import classify_rules, folds_as_routine
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
    assert pct_change(1, 0) is None and pct_change(None, 5) is None


@pytest.mark.parametrize(
    ("new", "old", "note"),
    [
        (5, -10, "turned profitable"),  # would print +150% with an abs() base
        (-50, -100, "loss narrowed"),
        (-120, -100, "loss widened"),
        (-5, 0, "loss from nil"),
        (110, 100, None),
    ],
)
def test_no_percentage_off_a_loss_or_zero_base(new, old, note):
    """PU-8: a move off a loss or zero shows both values and words, never a %."""
    if note:
        assert pct_change(new, old) is None
    assert change_note(new, old) == note


def test_stored_cards_follow_the_current_rule():
    card = {"rows": [{"metric": "pat", "value": 5, "prev": -10, "year_ago": 4, "qoq": 150.0}]}
    row = refresh_changes(card)["rows"][0]
    assert row["qoq"] is None and row["qoq_note"] == "turned profitable" and row["yoy"] == 25.0


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


def test_inferred_links_are_worded_as_overlap_never_as_knowing():
    """N-2: an overlap is inferred from two career records and says so."""
    a = _person("a", [Role("SRF", "SRF", "x", 2012, 2018)], [School("IIM A", None, 2008, 2010)])
    b = _person("b", [Role("SRF", "SRF", "y", 2016, 2020)], [School("IIM A", None, 2009, 2011)])
    found = overlaps(a, b)
    assert found and all(o.basis == "inferred" for o in found)
    for o in found:
        assert o.detail.startswith("Both") and "with" not in o.detail and "know" not in o.detail
        assert any(ch.isdigit() for ch in o.detail)  # confirmed overlaps carry their years


def test_current_employee_is_marked_as_insider(monkeypatch):
    """N-4: a contact who works at the company now is shown, and marked."""
    from app.network import graph

    monkeypatch.setattr(graph, "company_links", lambda: {})
    monkeypatch.setattr(graph, "_theme_for", lambda s: None)
    now = _person("now", [Role("Kaynes Technology", "KAYNES", "CFO", 2021, None)])
    was = _person("was", [Role("Kaynes Technology", "KAYNES", "VP", 2015, 2019)])
    for p in (now, was):
        p.relationship = {"type": "friend", "strength": 0.6}
    ranked = {h["contact"]["id"]: h for h in graph.who_can_help("KAYNES", {"now": now, "was": was})}
    assert ranked["now"]["insider"] is True and ranked["was"]["insider"] is False


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


def _split_setup(with_filing: bool):
    from app.db import session

    with session() as db:
        db.execute("INSERT INTO companies (symbol, name, in_portfolio) VALUES ('ABC','Abc',1)")
        for i in range(25):
            close, vol = (100, 1000) if i < 24 else (50.5, 2600)  # 1:2 split, volume doubles
            db.execute(
                "INSERT INTO prices VALUES ('ABC', ?, 0,0,0, ?, ?)",
                (f"2026-10-{i + 1:02d}", close, vol),
            )
        if with_filing:
            db.execute(
                "INSERT INTO announcements (id, symbol, ts, subject, category) VALUES "
                "('s1','ABC','2026-09-20T10:00:00','Record date for sub-division','bonus_split')"
            )


@pytest.mark.parametrize("with_filing", [True, False])
def test_split_day_raises_no_price_or_volume_alert(with_filing):
    """PU-11: a 1:2 split halves the price. With a split filing on record it is not news;
    the same drop with no such filing still alerts."""
    from app.intel import alerts

    _split_setup(with_filing)
    alerts.set_rules({"volume_multiple": 2.0, "price_abs_pct": 5.0, "categories": []})
    found = alerts.evaluate(datetime(2026, 10, 25), datetime(2026, 10, 25, 23))
    assert (found == []) is with_filing


def test_adjustment_ratio_needs_a_standard_ratio():
    from datetime import date

    from app.intel.alerts import is_adjustment_day

    filed = [date(2026, 9, 20)]
    assert is_adjustment_day(-66.0, date(2026, 10, 1), filed)  # 1:2 bonus → 1/3
    assert not is_adjustment_day(-12.0, date(2026, 10, 1), filed)  # a real fall
    assert not is_adjustment_day(-50.0, date(2027, 3, 1), filed)  # filing too old


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


# ------------------------------------------------------------------ unsure is not routine (PU-5)
@pytest.mark.parametrize(
    ("cat", "materiality", "desc", "subject", "folds"),
    [
        # rules could not place it and the model scored it material: stays visible
        ("unclassified", 70, "General Updates", "Jio Platforms IPO issue price", False),
        # rules could not place it and triage never ran: stays visible
        ("unclassified", None, "Updates", "Something new", False),
        # rules could not place it; the model read it and called it paperwork
        ("unclassified", 5, "Updates", "Unclaimed dividend reminder", True),
        # known paperwork, confidently routine
        ("unclassified", 3, "Trading Window", "Closure of trading window", True),
        ("agm_egm", 40, "Shareholders Meeting", "Notice of AGM", True),
        ("results", 80, "Outcome of Board Meeting", "Financial results", False),
    ],
)
def test_unsure_filings_are_not_folded(cat, materiality, desc, subject, folds):
    assert folds_as_routine(cat, materiality, desc, subject) is folds
