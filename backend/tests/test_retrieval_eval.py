"""Ask FINN retrieval (no AI): the answer page must be among the pages sent to the model."""


def _found(s: str) -> int:
    return int(s.split(" of ")[0])


def test_answer_pages_reach_the_model(seeded):
    from app.research.retrieval_eval import run

    r = run()
    assert r["tuning"]["found"] == "13 of 13"
    # written after the synonym list and never used to change it: a floor, not a target
    assert _found(r["held-out"]["found"]) >= 21


def test_investor_words_reach_filing_words():
    from app.research.qa import _query

    q = _query("How long do customers take to pay?")
    assert q["receivable"] < q["customers"] == 1.0  # added, at a lower weight
    assert "receivable" not in _query("What is the order book?")
