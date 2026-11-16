"""Pull as a conversation: the four-quarter ledger, routing, and the chat endpoint."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.research import pull

FIX = Path(__file__).parents[1] / "data" / "fixtures" / "research"


def view(sym: str) -> dict:
    return json.loads((FIX / f"{sym}.json").read_text())


def test_ledger_walks_the_last_four_calls_oldest_first():
    led = pull.ledger(view("KAYNES"))
    assert [c["quarter_label"] for c in led["calls"]] == [
        "Q2 FY26",
        "Q3 FY26",
        "Q4 FY26",
        "Q1 FY27",
    ]
    # each call carries what was reported for its quarter
    assert led["calls"][-1]["delivered"]["revenue"] == 946.0
    q3 = next(c for c in led["calls"] if c["quarter_label"] == "Q3 FY26")
    fy26 = next(p for p in q3["promised"] if "4,000" in p["target"])
    assert fy26["verdict"] == "missed" and "3,626" in fy26["actual"]


def test_ledger_summary_is_code_and_counts_a_repeated_promise_once():
    led = pull.ledger(view("KAYNES"))
    ids = [p.get("key") or p["id"] for c in led["calls"] for p in c["promised"]]
    assert sum(led["counts"].values()) == len(set(ids))
    text = " ".join(led["summary"])
    assert "4 missed" in text and "Largest miss" in text and "Revised along the way" in text
    assert "+41%" in text  # Q1 FY27 revenue growth, from the reported quarter


def test_ledger_shows_project_slips_beside_headline_numbers():
    led = pull.ledger(view("AARTIIND"))
    groups = {p["group"] for c in led["calls"] for p in c["promised"]}
    assert "projects" in groups
    assert any(
        u["revision"] and "delay" in u["target"].lower() for c in led["calls"] for u in c["updates"]
    )


def test_route_sends_each_phrase_to_its_output():
    cases = {
        "take the last four quarters: promised vs delivered": "ledger",
        "Did Aarti deliver on guidance?": "ledger",
        "narrative vs numbers": "narrative",
        "bull and bear case": "bull_bear",
        "what is the FY27 outlook": "guidance",
        "cash conversion": "cash",
        "how leveraged is the balance sheet": "balance",
        "multi-year trend": "trajectory",
        "key ratios": "financial",
        "what does Kaynes do": "business",
        "Kaynes": "overview",
        "Why did receivables go up?": "qa",
    }
    for msg, want in cases.items():
        assert pull.route(msg) == want, msg


def test_every_output_builds_for_every_company():
    for sym in ("KAYNES", "AARTIIND", "PERSISTENT", "MANAPPURAM"):
        v = view(sym)
        for intent, _ in pull.MENU:
            out = pull.reply(v, intent)
            assert out["blocks"], (sym, intent)
            assert all(m["intent"] != intent for m in out["menu"])


def test_chat_names_carries_and_asks(seeded):
    from app.main import app

    with TestClient(app) as c:
        r = c.post(
            "/pull/chat", json={"message": "Kaynes: promised vs delivered, last four quarters"}
        ).json()
        assert r["kind"] == "reply" and r["symbol"] == "KAYNES" and r["intent"] == "ledger"
        assert r["blocks"][0]["type"] == "ledger"
        # a follow-up that names no company stays on the one in the conversation
        r = c.post(
            "/pull/chat", json={"message": "and the balance sheet?", "symbol": "KAYNES"}
        ).json()
        assert r["symbol"] == "KAYNES" and r["intent"] == "balance"
        # a menu tap names its output directly
        r = c.post(
            "/pull/chat",
            json={"message": "Bull vs bear", "symbol": "KAYNES", "intent": "bull_bear"},
        ).json()
        assert r["intent"] == "bull_bear"
        # no company anywhere: ask which
        assert (
            c.post("/pull/chat", json={"message": "what should I look at"}).json()["kind"] == "pick"
        )
        # a company FINN hasn't read: offer the live read instead of guessing
        r = c.post("/pull/chat", json={"message": "tell me about DIXON"}).json()
        assert r["kind"] == "not_built" and r["symbol"] == "DIXON"


def test_an_open_question_without_a_model_still_answers_with_the_code_outputs(seeded):
    from app.main import app

    with TestClient(app) as c:
        r = c.post(
            "/pull/chat", json={"message": "Why did receivables go up?", "symbol": "KAYNES"}
        ).json()
    assert r["kind"] == "reply"
    if r["intent"] != "qa":  # no model configured in tests
        assert r["notice"] and r["intent"] == "overview"
