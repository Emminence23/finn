"""PU-4 calibration: priority levels against hand labels fixed before tuning.

The labels (data/fixtures/eval/materiality_labels.json) are 100 portfolio filings drawn
with a fixed seed and labelled from their text alone. This test seeds the real fixtures and
checks the two acceptance numbers from plan v2:
  - at least 95% of filings labelled material are outside Routine;
  - Important holds at most 20% of digest items (cards plus folded filings) on the 7- and
    30-day windows. The 24-hour window has too few items to hold to a share.
"""

import json
from pathlib import Path

import pytest

REPO_FIXTURES = Path(__file__).parents[1] / "data" / "fixtures"


def _where(digest: dict) -> dict[str, str]:
    out = {}
    for c in digest["cards"]:
        for fid in [c["id"], *(r["id"] for r in c["related"])]:
            out[fid] = c["level"]
    for r in digest["routine"]["items"]:
        out[r["id"]] = "routine"
    return out


def test_material_filings_are_not_routine(seeded):
    from app.intel.digest import build_digest

    labels = json.loads((REPO_FIXTURES / "eval" / "materiality_labels.json").read_text())
    material = [x["id"] for x in labels["labels"] if x["material"]]
    where = _where(build_digest(start="2026-01-01T00:00:00", end="2026-12-31T23:59:59"))
    outside = [i for i in material if where.get(i) in ("important", "notable")]
    assert len(material) >= 20
    assert len(outside) / len(material) >= 0.95, set(material) - set(outside)


@pytest.mark.parametrize("window", ["7d", "30d"])
def test_important_is_rare(seeded, window):
    from app.intel.digest import build_digest

    d = build_digest(window)
    items = len(d["cards"]) + d["counts"]["routine"]
    important = sum(c["level"] == "important" for c in d["cards"])
    assert important / items <= 0.20
    assert all(c["level_reason"] for c in d["cards"])


def test_results_are_important_only_when_the_numbers_move():
    from app.intel.digest import level

    def card(pat_yoy, note=None):
        return {
            "kind": "results",
            "category": "results",
            "materiality": 85,
            "alerts": [],
            "results": {
                "rows": [
                    {"metric": "pat", "yoy": pat_yoy, "yoy_note": note},
                    {"metric": "revenue", "yoy": 8.0, "yoy_note": None},
                ]
            },
        }

    assert level(card(6.0)) == ("notable", "Neither PAT nor revenue moved 15% YoY")
    assert level(card(-36.0))[0] == "important"
    assert level(card(None, "turned profitable"))[0] == "important"


def test_every_card_opens_a_next_action(seeded):
    """PLAN v2 principle 5: a card leads to a person, the research or the source."""
    from app.intel.digest import build_digest
    from app.research.service import ready_symbols

    researched = ready_symbols()
    seen = set()
    for window in ("7d", "30d"):
        for c in build_digest(window)["cards"]:
            a = c["next_action"]
            assert a["label"] and a["why"], c["title"]
            assert a["href"].startswith(("/people/", "/c/", "http")), a
            seen.add(c["kind"])
            if c["kind"] == "results" and c["symbol"] in researched:
                assert a["href"] == f"/c/{c['symbol']}#promises"
    assert {"results", "filing"} <= seen
    # the management-change demo case leads to the incoming person
    cards = build_digest(start="2026-10-01", end="2026-10-15")["cards"]
    cfo = next(c for c in cards if c["symbol"] == "PIDILITIND" and c["kind"] == "management_change")
    assert cfo["next_action"]["href"] == "/people/fp_amit_agarwal_pidilite"
    assert cfo["next_action"]["label"] == "See how you reach Amit"
