"""Today as a note (intel/note.py), units in FINN's own sentences, and asking before a
live research read: the UI/UX review's fixes."""

import pytest


def test_units_are_one_currency_and_one_minus():
    from app.intel.units import normalise as n

    assert n("revenue reached Rs 18,987 million") == "revenue reached ₹1,899 Cr"
    assert n("order book of INR 100,000+ million") == "order book of ₹10,000+ Cr"
    assert n("net sales of Rs 3,982 crores, up 21.7%") == "net sales of ₹3,982 Cr, up 21.7%"
    assert n("Rs -3,167 Cr loss") == "−₹3,167 Cr loss"
    assert n("cash conversion -0.71x") == "cash conversion −0.71×"
    assert n("allotted at Rs 1,010 each") == "allotted at ₹1,010 each"


def _card(**k):
    base = {
        "company": "Kaynes Technology India Limited",
        "kind": "filing",
        "title": "Executed a binding term sheet with Vishay",
        "in_portfolio": True,
        "weight": 0.5,
        "level": "important",
        "materiality": 70,
        "alerts": [],
        "helpers": [],
        "category": "M&A",
    }
    return base | k


def test_lines_put_the_company_first_and_say_the_size():
    from app.intel.note import line, short, stake

    assert line(_card()) == "Kaynes executed a binding term sheet with Vishay."
    assert short("CG Power and Industrial Solutions Limited") == "CG Power"
    res = {"rows": [{"metric": "pat", "yoy": -66.0}, {"metric": "revenue", "yoy": 4.2}]}
    assert line(_card(kind="results", results=res)) == (
        "Kaynes' profit fell 66% from a year ago, on revenue up 4%."
    )
    real, text = stake(_card(), 18, 27440)
    assert not real and text == ("It's 0.5% of your portfolio (₹27,440), a small holding.")
    assert stake(_card(weight=12.0), 18, 670000)[0]  # 12% of 18 holdings is a real position


def test_bands_follow_one_rule_each(seeded):
    from app.intel.digest import build_digest

    d = build_digest("30d")
    n = 18
    for c in d["cards"]:
        real = c["in_portfolio"] and (c["weight"] or 0) >= 0.5 * 100 / n
        if c["band"] == "act":
            assert c["level"] == "important" and real
        if c["band"] == "aside":
            assert c["level"] == "notable" and c["materiality"] < 30
    assert d["lead"] and d["set_aside"]["count"] >= d["routine"]["count"]


def test_last_day_leads_with_the_decision_and_keeps_open_events_in_view(seeded):
    from app.intel.digest import build_digest

    d = build_digest("24h")
    act = [c for c in d["cards"] if c["band"] == "act"]
    assert [c["symbol"] for c in act] == ["BAJFINANCE"]  # the QIP closed, a 6% position
    carried = {c["symbol"] for c in d["carry"]}
    assert {"TITAN", "BHEL"} <= carried  # bigger events from the days before stay open
    bhel = next(c for c in d["carry"] if c["symbol"] == "BHEL")
    assert bhel["update"] and "Power Grid" in bhel["update"]  # with its latest update
    lead = d["lead"]
    assert "1 item matters and one needs a decision" in lead and "Bajaj Finance is 6%" in lead
    assert "Two earlier events at larger holdings are still open" in lead
    assert lead.startswith("Your portfolio ended 13 Nov, the last close, down")


def test_note_for_a_past_window_leaves_out_the_last_close(seeded):
    from app.intel.digest import build_digest

    lead = build_digest("custom", start="2026-10-01", end="2026-10-15")["lead"]
    assert lead.startswith("Between 1 Oct and 15 Oct,") and "last close" not in lead


def test_contact_questions_come_from_the_card(seeded):
    from app.intel.digest import build_digest

    c = next(c for c in build_digest("24h")["cards"] if c["helpers"])
    ask = c["helpers"][0]["ask"]
    assert len(ask) == 2 and "Bajaj Finance" in ask[0]


def test_unknown_ticker_never_spends_a_live_read(seeded):
    from fastapi.testclient import TestClient

    from app.api import routes
    from app.main import app

    before = routes.BUDGET.left(10**6)
    with TestClient(app) as c:
        r = c.get("/research/ZZZZ")
        assert r.status_code == 404 and r.json()["detail"]["covered"] is None
        with c.stream("GET", "/research/ZZZZ/stream") as s:
            body = "".join(s.iter_text())
        assert "isn't an NSE-listed company" in body
        known = c.get("/research/TITAN").json()["detail"]
        assert known["covered"]["symbol"] == "TITAN" and known["builds_left"] >= 0
    assert routes.BUDGET.left(10**6) == before


@pytest.mark.parametrize("w", ["24h", "7d"])
def test_unexplained_moves_really_have_no_filing(seeded, w):
    from app.intel.digest import build_digest

    d = build_digest(w)
    for s in d["moves_note"]:
        assert "with no filing to explain it" in s
    assert not any(s.startswith("CG Power") for s in d["moves_note"])  # its stay, 7 Nov
