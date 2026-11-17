"""Brokerage intelligence (brief §12): formulas, checks, history, point-in-time, samples."""

import base64
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIX = Path(__file__).parents[1] / "data" / "fixtures"
DEMO = {"X-Finn-User": "demo"}


def _client():
    from app.main import app

    return TestClient(app)


# ---- formulas -------------------------------------------------------------------------


def test_implied_return_and_revisions():
    from app.brokerage import calc

    assert calc.implied_return(4710, 3860) == pytest.approx(22.02, abs=0.01)
    assert calc.implied_return(4710, 0) is None and calc.implied_return(None, 3860) is None
    assert calc.implied_return(-1, 3860) is None
    assert calc.pct_change(4437, 4425) == pytest.approx(0.271, abs=0.001)
    assert calc.pct_change(5, -5) is None  # a change of sign has no percentage
    assert calc.pct_change(5, 0) is None


def test_stats_percentiles_and_outliers():
    from app.brokerage import calc

    st = calc.stats([4400, 4437, 4710, 4700])
    assert st["median"] == pytest.approx(4568.5) and st["min"] == 4400 and st["max"] == 4710
    assert st["p25"] == pytest.approx(4427.75) and st["p75"] == pytest.approx(4702.5)
    assert calc.stats([]) is None
    out = calc.outliers([("a", 100), ("b", 102), ("c", 99), ("d", 140)])
    assert [o["brokerage_id"] for o in out] == ["d"]
    assert calc.outliers([("a", 100), ("b", 140)]) == []  # two points make no outlier


def test_ratings_horizons_units_and_periods():
    from app.brokerage import calc
    from app.brokerage.extract import normalise_period, normalise_rating

    assert normalise_rating("BUY") == "positive" and normalise_rating("Accumulate") == "positive"
    assert normalise_rating("Hold") == "neutral" and normalise_rating("Underperform") == "negative"
    assert normalise_rating("Trading Buy") is None  # not in the table: not forced
    assert calc.horizon_bucket(12, "months") == calc.horizon_bucket(1, "year") == "12 months"
    assert calc.horizon_bucket(None, None) == "not stated"
    assert calc.to_crore(3140.5, "INR b") == pytest.approx(314050)
    assert calc.to_crore(3161070, "INR mn") == pytest.approx(316107)
    assert calc.to_crore(78750, "₹ crore") == 78750
    assert calc.to_crore(146.2, "INR/share") is None and calc.to_crore(9.3, "%") is None
    assert normalise_period("FY27E") == "FY27" and normalise_period("FY2028") == "FY28"
    assert normalise_period("Q2FY27") == "Q2 FY27" and normalise_period("CY27") is None


def test_estimates_compare_only_like_with_like():
    from app.brokerage import calc

    base = {"metric": "EPS", "fiscal_period": "FY27", "unit": "INR/share", "is_actual": 0}
    assert calc.comparable_key(base) == calc.comparable_key(base | {"unit": "INR"})
    assert calc.comparable_key(base) != calc.comparable_key(base | {"fiscal_period": "FY28"})
    assert calc.comparable_key(base) != calc.comparable_key(base | {"definition": "adjusted"})
    assert calc.comparable_key(base | {"is_actual": 1}) is None
    other = base | {"other_basis": True}
    assert calc.comparable_key(other) is None  # never against another house
    assert calc.comparable_key(other, across_brokerages=False)  # fine against its own past
    prev = {
        "brokerage_id": "x",
        "report_id": "1",
        "published_at": "2026-07-01",
        "rating": "positive",
        "rating_raw": "BUY",
        "target_price": 100,
        "estimates": [base | {"value": 100}, base | {"fiscal_period": "FY28", "value": 50}],
    }
    cur = prev | {
        "report_id": "2",
        "published_at": "2026-10-01",
        "rating": "neutral",
        "rating_raw": "HOLD",
        "target_price": 90,
        "estimates": [
            base | {"value": 110, "definition": "adjusted"},
            base | {"fiscal_period": "FY28", "value": 45},
        ],
    }
    r = calc.revision(prev, cur)
    assert r["rating_move"] == "downgrade" and r["target_change_pct"] == pytest.approx(-10)
    # FY27 changed definition, so only FY28 is a revision
    assert [(e["fiscal_period"], round(e["change_pct"], 1)) for e in r["estimates"]] == [
        ("FY28", -10.0)
    ]


def test_basis_check_uses_the_reports_own_reported_years():
    from app.brokerage import calc

    reported = {"FY26": {"revenue": 285874, "EPS": 116.92}}
    same = [
        {
            "metric": "revenue",
            "fiscal_period": "FY26",
            "is_actual": 1,
            "value": 2858.7,
            "value_cr": 285870,
        }
    ]
    other = [
        {
            "metric": "revenue",
            "fiscal_period": "FY26",
            "is_actual": 1,
            "value": 153680,
            "value_cr": 153680,
        }
    ]
    assert calc.basis_check(same, reported)["revenue"]["same_basis"]
    assert not calc.basis_check(other, reported)["revenue"]["same_basis"]
    eps = [{"metric": "EPS", "fiscal_period": "FY26", "is_actual": 1, "value": 126.2}]
    assert calc.basis_check(eps, reported) == {}  # adjusted EPS differs by definition, not basis


def test_evaluation_is_point_in_time_and_waits_for_the_horizon():
    from app.brokerage import calc

    prices = [
        ("2025-01-02", 100.0),
        ("2025-06-02", 110.0),
        ("2026-01-02", 120.0),
        ("2026-01-05", 999.0),
    ]
    o = {
        "published_at": "2025-01-03",
        "target_price": 130,
        "reference_price": 100,
        "horizon_value": 12,
        "horizon_unit": "months",
    }
    ev = calc.evaluate_target(o, prices, "2026-01-04")
    assert ev["start_price"] == 100 and ev["end_price"] == 120  # never the later 999
    assert ev["direction_right"] is True
    assert ev["signed_error_pct"] == pytest.approx((130 - 120) / 120 * 100)
    assert calc.evaluate_target(o, prices, "2025-12-31") is None  # horizon not yet passed
    assert calc.evaluate_target(o | {"horizon_value": None}, prices, "2026-06-01") is None
    assert calc.eps_error(10, 0.1) is None and calc.eps_error(110, 100) == pytest.approx(10)


# ---- extraction checks ----------------------------------------------------------------


def test_code_verifies_every_material_field_against_its_page():
    from app.brokerage.extract import Evidence, Extraction, validate

    pages = ["CMP: ₹3860 Target ₹ 4710 (22%) Target Period: 12 months BUY October 28, 2026"]
    ex = Extraction(
        brokerage="X",
        published_at="2026-10-28",
        title="t",
        report_type="results update",
        rating_raw="BUY",
        target_price=4710,
        target_currency="INR",
        reference_price=3860,
        horizon_raw="Target Period: 12 months",
        horizon_value=12,
        horizon_unit="months",
        valuation_method=None,
        thesis_summary=None,
        evidence=[
            Evidence(field="rating", page=1, excerpt="Target Period: 12 months BUY"),
            Evidence(field="target_price", page=1, excerpt="Target ₹ 4710 (22%)"),
            Evidence(field="reference_price", page=1, excerpt="CMP: ₹3860"),
            Evidence(field="horizon", page=1, excerpt="Target Period: 12 months"),
            Evidence(field="published_at", page=1, excerpt="October 28, 2026"),
        ],
    )
    v = validate(ex, pages)
    assert v["needs_review"] == [] and v["confidence"] == 1.0 and v["currency"] == "INR"
    wrong = ex.model_copy(update={"target_price": 4750.0})  # a number not on the page
    v = validate(wrong, pages)
    assert (
        v["fields"]["target_price"]["status"] == "unverified"
        and "target_price" in v["needs_review"]
    )
    moved = ex.model_copy(
        update={
            "evidence": [
                e if e.field != "rating" else Evidence(field="rating", page=2, excerpt="BUY")
                for e in ex.evidence
            ]
        }
    )
    assert validate(moved, pages)["fields"]["rating"]["status"] == "unverified"  # page 2 absent


def test_extraction_matches_the_hand_checked_gold_set(seeded):
    from app.brokerage.eval import run

    r = run()
    assert r["misses"] == [] and all(v == "12 of 12" for v in r["fields"].values())
    assert r["evidence_verified"] == "12 of 12 reports"


# ---- the L&T demo, end to end on the stored reports -----------------------------------


def test_overview_never_pools_unlike_horizons(seeded):
    with _client() as c:
        o = c.get("/companies/LT/brokerage/overview", headers=DEMO).json()
    assert o["reports"] == 12 and o["brokerages"] == 4
    horizons = {g["horizon"]: g for g in o["targets"]}
    assert set(horizons) == {"12 months", "not stated"}
    assert (
        horizons["12 months"]["targets"]["max"] == 4710 and horizons["12 months"]["brokerages"] == 2
    )
    assert not horizons["12 months"]["consensus_label"]  # two houses make a range, not a consensus
    assert any("Sharekhan" in w and "not in the ranges" in w for w in o["warnings"])
    for r in o["latest"]:  # every forecast with brokerage, date, horizon and source
        assert r["brokerage"] and r["published_at"] and r["horizon"] and r["source"]["url"]


def test_history_is_kept_and_revisions_are_per_brokerage(seeded):
    with _client() as c:
        reps = c.get(
            "/companies/LT/brokerage/reports?brokerage_id=icici-securities", headers=DEMO
        ).json()
        r = c.get("/companies/LT/brokerage/revisions", headers=DEMO).json()
    assert [x["target_price"] for x in reps["items"]] == [4710, 5000, 4955, 5030]  # all four kept
    icici = next(e for e in r["events"] if e["brokerage_id"] == "icici-securities")
    assert (icici["target_from"], icici["target_to"]) == (5000, 4710)
    assert icici["target_change_pct"] == pytest.approx(-5.8, abs=0.05)
    m90 = next(m for m in r["momentum"] if m["days"] == 90)
    assert m90["brokerages"] == 3 and m90["target_down"] == 2 and m90["target_up"] == 1


def test_divergence_keeps_another_basis_out(seeded):
    with _client() as c:
        d = c.get("/companies/LT/brokerage/divergence", headers=DEMO).json()
    names = {v["brokerage"] for e in d["estimates"] for v in e["values"]}
    assert not any(n.startswith("ICICI") for n in names)  # its table isn't consolidated
    rev = next(
        e for e in d["estimates"] if e["metric"] == "revenue" and e["fiscal_period"] == "FY27"
    )
    assert rev["unit"] == "INR crore" and len(rev["values"]) == 2 and rev["spread_pct"] < 1
    assert next(g for g in d["targets"] if g["horizon"] == "not stated")["stats"] is None


def test_track_record_is_suppressed_until_there_is_enough(seeded):
    with _client() as c:
        t = c.get("/companies/LT/brokerage/track-record", headers=DEMO).json()
    assert not t["targets"]["available"]
    assert (
        t["targets"]["message"]
        == "Track record unavailable — insufficient comparable observations."
    )
    f = t["forecasts"]
    assert f["ranking"] is None and "not ranked" in f["note"]
    # FY26 forecasts made in January, checked against what was reported after March
    assert all(r["fiscal_period"] == "FY26" and r["published_at"] < "2026-03-31" for r in f["rows"])
    assert not any(r["brokerage"].startswith("ICICI") for r in f["rows"])  # another basis


def test_explanation_points_with_unsourced_figures_are_dropped():
    from app.brokerage.explain import Explanation, Point, check

    pack = {
        "reports": [
            {
                "id": "a",
                "brokerage": "A",
                "date": "d",
                "target": 4710.0,
                "assumptions": ["core: 25x Dec'28E EPS"],
            }
        ],
        "computed": {},
    }
    ex = Explanation(
        summary="One view.",
        points=[
            Point(text="A values the core at 25x and targets 4710.", cites=["a"]),
            Point(text="A expects 18% growth.", cites=["a"]),
            Point(text="Someone else says 4710.", cites=["zzz"]),
        ],
    )
    out = check(ex, pack)
    assert [p["text"] for p in out["points"]] == ["A values the core at 25x and targets 4710."]
    assert len(out["dropped"]) == 2


def test_stored_explanation_serves_the_demo_without_a_call(seeded, monkeypatch):
    from app.llm import router

    monkeypatch.setattr(router, "get_llm", lambda: (_ for _ in ()).throw(AssertionError("no LLM")))
    with _client() as c:
        d = c.get("/companies/LT/brokerage/divergence", headers=DEMO).json()
    e = d["explanation"]
    assert e["status"] == "done" and e["points"] and all(p["cites"] for p in e["points"])


# ---- uploads: private, deduplicated, history-preserving -------------------------------


def _sandbox(c):
    return {"X-Finn-User": c.post("/people/mine", headers=DEMO).json()["account"]}


def test_upload_is_private_deduplicated_and_never_overwrites(seeded, monkeypatch):
    from app.brokerage import jobs
    from app.brokerage.extract import Evidence, Extraction
    from app.research import docs

    page = "Example Securities  CMP: ₹4000 TP: ₹4800 BUY  12-month target  November 10, 2026 Larsen"
    monkeypatch.setattr(docs, "page_texts", lambda pdf: [page])
    fake = Extraction(
        brokerage="Example Securities",
        published_at="2026-11-10",
        title="t",
        report_type="company update",
        rating_raw="BUY",
        target_price=4800,
        target_currency="INR",
        reference_price=4000,
        horizon_raw="12-month target",
        horizon_value=12,
        horizon_unit="months",
        horizon_basis="on the target",
        valuation_method=None,
        thesis_summary=None,
        evidence=[
            Evidence(field=f, page=1, excerpt=x)
            for f, x in [
                ("rating", "TP: ₹4800 BUY"),
                ("target_price", "TP: ₹4800"),
                ("reference_price", "CMP: ₹4000"),
                ("horizon", "12-month target"),
                ("published_at", "November 10, 2026"),
            ]
        ],
    )
    monkeypatch.setattr(jobs, "extract", lambda pages, hint="": fake)
    pdf = base64.b64encode(b"%PDF-1.4 fake bytes").decode()
    body = {"symbol": "LT", "brokerage": "Example Securities", "pdf_base64": pdf, "permitted": True}
    with _client() as c:
        assert c.post("/brokerage/reports/ingest", json=body, headers=DEMO).status_code == 403
        me = _sandbox(c)
        assert (
            c.post(
                "/brokerage/reports/ingest", json=body | {"permitted": False}, headers=me
            ).status_code
            == 400
        )
        bad = body | {"pdf_base64": base64.b64encode(b"not a pdf").decode()}
        assert c.post("/brokerage/reports/ingest", json=bad, headers=me).status_code == 400

        def run():
            job = c.post("/brokerage/reports/ingest", json=body, headers=me).json()["job_id"]
            for _ in range(100):
                s = c.get(f"/brokerage/ingest/{job}", headers=me).json()
                if s["status"] != "running":
                    return s
                time.sleep(0.05)
            raise AssertionError("job never finished")

        first = run()
        assert first["status"] == "done" and first["needs_review"] == []
        assert run()["status"] == "duplicate"  # same bytes: nothing replaced
        mine = c.get("/companies/LT/brokerage/reports", headers=me).json()
        theirs = c.get("/companies/LT/brokerage/reports", headers=DEMO).json()
        assert mine["total"] == 13 and theirs["total"] == 12  # private to the uploader
        assert c.get(f"/brokerage/ingest/{first['id']}", headers=DEMO).status_code == 404


def test_reseeding_keeps_uploads_and_rebuilds_the_shared_set(seeded):
    from app.brokerage.store import save_report, seed_from_fixtures
    from app.db import session

    rec = json.loads((FIX / "brokerage" / "LT.json").read_text())["reports"][0]
    with _client() as c:
        owner = _sandbox(c)["X-Finn-User"]
    assert save_report(rec, owner) and not save_report(rec, owner)
    assert seed_from_fixtures() == 12
    with session() as db:
        n = db.execute(
            "SELECT COUNT(*) FROM brokerage_reports WHERE owner_id=?", (owner,)
        ).fetchone()[0]
    assert n == 1


def test_ask_routes_broker_questions_to_the_brokerage_view(seeded):
    from app.research.pull import route

    assert route("What do brokers expect for L&T?") == "brokers"
    assert route("L&T target price") == "brokers" and route("guidance for FY27") == "guidance"
    with _client() as c:
        r = c.post(
            "/pull/chat", json={"message": "What do brokers expect for L&T?"}, headers=DEMO
        ).json()
    assert r["kind"] == "reply" and r["intent"] == "brokers"
    b = r["blocks"][0]
    assert b["type"] == "brokers" and b["overview"]["reports"] == 12 and b["track"]
    with _client() as c:
        none = c.post("/pull/chat", json={"message": "TCS broker views"}, headers=DEMO).json()
    said = " ".join(b.get("text", "") for b in none["blocks"])
    assert "No bank or broker calls" in said and "holds no brokerage reports" in said
    assert not any(b["type"] in ("brokers", "table") for b in none["blocks"])  # never invents


def test_broker_summary_check_allows_the_year_of_a_given_date_only():
    from app.brokerage.news import check_summary

    f = {
        "last_close": 400, "low": 470, "high": 635, "median": 552, "houses": 2,
        "with_target": 2, "positive": ["Elara", "Motilal Oswal"], "negative": [],
        "neutral_or_unrated": [], "median_vs_close_pct": 38.1,
        "calls": [
            {"house": "Elara", "target": 635, "previous_target": None,
             "vs_close_pct": 58.8, "date": "2026-11-06"},
            {"house": "Motilal Oswal", "target": 470, "previous_target": None,
             "vs_close_pct": 17.6, "date": "2026-11-06"},
        ],
    }  # fmt: skip
    assert check_summary("On 6 November 2026 Elara and Motilal Oswal said Buy.", f) is None
    assert check_summary("Elara sees ₹2,026.", f)  # a year is not a price
    assert check_summary("In 2027 Elara expects more.", f)  # a year the facts don't give
