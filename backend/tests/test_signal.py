"""Signal-to-Network (Task C): attention score, facts, contact matching, privacy, fallbacks."""

from fastapi.testclient import TestClient

from app.intel import signal
from app.network import match
from app.network.graph import Person, Role


def score(**kw):
    base = dict(
        category="unclassified",
        subject="",
        summary=None,
        ts="2026-11-01T10:00:00",
        facts=[],
        symbol="X",
        scale={},
    )
    return signal.attention(**(base | kw))


# ------------------------------------------------------------------ facts
def test_facts_carry_their_sentence_and_missing_amounts_stay_missing():
    facts = signal.extract_facts(
        "Appointment of Mr A as CFO w.e.f. 1st December 2026",
        "Board approved a capex of Rs 450 crore for a new plant.",
        {},
    )
    by = {f["field"]: f for f in facts}
    assert by["effective_date"]["value"] == "2026-12-01"
    assert by["amount"]["value"] == 450 and "capex" in by["amount"]["source_quote"]
    assert by["amount"]["source"] == "filing summary (AI)"
    assert not [
        f for f in signal.extract_facts("Appointment of CFO", None, {}) if f["field"] == "amount"
    ]


# ------------------------------------------------------------------ attention
def test_a_large_deal_outscores_routine_paperwork_and_stays_in_range():
    deal = score(
        category="M&A",
        subject="Acquisition of 100% stake in Y for Rs 900 crore",
        facts=[{"field": "amount", "value": 900.0}],
        scale={"market_cap": 6000},
    )
    routine = score(category="investor_meetings", subject="Schedule of analyst meet")
    assert deal["score"] > routine["score"] and routine["score"] >= 0 and deal["score"] <= 100
    assert deal["breakdown"]["financial_magnitude"] == 25  # 15% of market value
    assert routine["priority"] == "routine"


def test_unknown_size_is_reported_not_scored_as_zero():
    s = score(category="fund_raise", subject="QIP opened")
    assert s["breakdown"]["financial_magnitude"] is None
    assert s["unknown_components"]


def test_imminent_dates_add_urgency_and_holding_is_only_a_small_bonus():
    later = score(
        category="management_change",
        subject="Appointment of CFO",
        facts=[{"field": "effective_date", "value": "2027-06-01"}],
    )
    soon = score(
        category="management_change",
        subject="Appointment of CFO",
        facts=[{"field": "effective_date", "value": "2026-11-20"}],
    )
    assert soon["score"] > later["score"]
    held = score(
        category="management_change", subject="Appointment of CFO", in_portfolio=True, weight=0.12
    )
    assert held["breakdown"]["portfolio_relevance"] <= 5


def test_a_routine_reappointment_is_not_a_leadership_change():
    s = score(category="management_change", subject="Re-appointment of Mr X as Executive Director")
    assert s["breakdown"]["category_base"] == 6 and s["breakdown"]["strategic_significance"] == 0


# ------------------------------------------------------------------ the spec's demo network
def demo_people():
    def rel(s):
        return {
            "type": "colleague",
            "strength": s,
            "last_contact": None,
            "email": None,
            "phone": None,
        }

    b = Person(
        "b",
        "Contact B",
        None,
        True,
        [],
        None,
        [Role("Example Motors Limited", "EXMO", "Manager, Corporate Finance", 2019, 2023)],
        relationship=rel(0.7),
    )
    c = Person(
        "c",
        "Contact C",
        None,
        True,
        [],
        None,
        [Role("Rival Motors", None, "Head, Corporate Finance", 2020, None)],
        relationship=rel(0.7),
    )
    d = Person(
        "d",
        "Contact D",
        None,
        True,
        [],
        None,
        [Role("Some Bank", None, "Analyst", 2018, None)],
        relationship=rel(0.6),
    )
    d.knows.append({"person": "aud", "context": "Former colleague", "strength": 0.6})
    aud = Person(
        "aud",
        "Auditor A",
        None,
        False,
        [],
        None,
        [Role("Example Motors Limited", "EXMO", "Statutory Audit Partner", 2016, 2021)],
    )
    e = Person(
        "e",
        "Contact E",
        None,
        True,
        ["enterprise software"],
        None,
        [Role("Soft Corp", None, "Software Sales", 2015, None)],
        relationship=rel(0.9),
    )
    return {p.id: p for p in (b, c, d, aud, e)}


def demo_find(**kw):
    return match.find(
        "EXMO",
        "management_change",
        text="Appointment of Chief Financial Officer",
        people=demo_people(),
        names={"example motors"},
        linked={"rival motors": "competitor"},
        theme="automobiles",
        **kw,
    )


def test_spec_demo_ranks_former_finance_then_competitor_then_second_degree_and_drops_unrelated():
    got = demo_find()
    ids = [m["person_id"] for m in got]
    assert ids[:2] == ["b", "c"]
    assert (
        "aud" in ids and next(m for m in got if m["person_id"] == "aud")["connection_degree"] == 2
    )
    assert "e" not in ids  # unrelated software sales is never recommended
    b = got[0]
    assert b["experience_period"] == {"start": 2019, "end": 2023} and b["connection_degree"] == 1
    assert "May provide context" in b["explanation"] and "unknown" in b["explanation"]
    assert "inside" not in b["explanation"].lower()


def test_second_degree_is_discounted_and_first_degree_only_hides_it():
    assert all(m["connection_degree"] == 1 for m in demo_find(max_degree=1))
    aud = next(m for m in demo_find() if m["person_id"] == "aud")
    assert aud["path"] == ["You", "Contact D", "Auditor A"]


def test_no_tie_returns_an_empty_list():
    assert (
        match.find(
            "NONE", "results", people=demo_people(), names={"nothing ltd"}, linked={}, theme=""
        )
        == []
    )


# ------------------------------------------------------------------ API: end to end, privacy, idempotence
def _ann_id():
    from app.db import session

    with session() as db:
        return db.execute(
            "SELECT id FROM announcements WHERE symbol='PIDILITIND' AND category='management_change' ORDER BY ts DESC"
        ).fetchone()["id"]


def test_analyze_end_to_end_is_idempotent_and_scoped_to_the_investor(seeded):
    from app.main import app

    aid = _ann_id()
    with TestClient(app) as c:
        a = c.post("/announcements/analyze", json={"announcement_id": aid}).json()
        assert a["event"]["category"] == "management_change"
        assert 0 <= a["materiality"]["score"] <= 100 and a["materiality"]["priority"]
        assert a["source"]["url"]
        demo_ids = {m["person_id"] for m in a["network_matches"]}
        assert demo_ids
        again = c.post("/announcements/analyze", json={"announcement_id": aid}).json()
        assert again["created_at"] == a["created_at"]  # stored once, not recomputed
        other = c.post(
            "/announcements/analyze",
            json={"announcement_id": aid},
            headers={"X-Finn-User": "demo2"},
        ).json()
        assert not demo_ids & {
            m["person_id"] for m in other["network_matches"] if m["connection_degree"] == 1
        }
        assert c.post("/announcements/analyze", json={"announcement_id": "nope"}).status_code == 404
        s = c.post(
            "/network/search", json={"company_ticker": "KAYNES", "theme": "operations"}
        ).json()
        assert (
            s["matches"]
            and s["matches"][0]["relevance_score"] >= s["matches"][-1]["relevance_score"]
        )
        assert (
            c.post(f"/signals/{aid}/feedback", json={"kind": "useful"}).json()["recorded"]
            == "useful"
        )
        assert c.post(f"/signals/{aid}/feedback", json={"kind": "bogus"}).status_code == 400


def test_signal_survives_the_network_failing(seeded, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(match, "find", boom)
    out = signal.analyze(_ann_id(), "demo2")
    assert out["network_matches"] == [] and out["network_note"]
    assert out["materiality"]["score"] > 0


def test_deleting_a_contact_drops_them_from_stored_signals(seeded):
    from app.network import graph

    aid = _ann_id()
    first = signal.analyze(aid, "demo")["network_matches"]
    pid = next(m["person_id"] for m in first if m["connection_degree"] == 1)
    assert graph.delete_contact(pid, "demo")
    assert pid not in {m["person_id"] for m in signal.analyze(aid, "demo")["network_matches"]}


def test_bands_against_hand_labels(seeded):
    ev = signal.eval_bands()
    up, n_mat = ev["material_at_medium_or_above"]
    down, n_non = ev["not_material_below_medium"]
    assert ev["n"] == 100 and up / n_mat >= 0.7 and down / n_non >= 0.95
