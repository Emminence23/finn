"""Notes from contacts are kept apart from evidence: private to the owner, never sent to an
LLM, never citable, and deleted with the contact they came from."""

import json
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

FIX = Path(__file__).parents[1] / "data" / "fixtures"
DEMO = {"X-Finn-User": "demo"}
OTHER = {"X-Finn-User": "demo2"}
SECRET = "Vivek-says-metro-margins-are-zebra-42"


def _client():
    from app.main import app

    return TestClient(app)


def _vivek(c):
    return next(
        p["id"] for p in c.get("/people", headers=DEMO).json() if p["name"].startswith("Vivek")
    )


def test_notes_are_private_and_go_with_their_contact(seeded):
    with _client() as c:
        k = _vivek(c)
        n = c.post("/notes", json={"symbol": "lt", "text": SECRET, "contact": k}, headers=DEMO)
        assert n.status_code == 200 and n.json()["contact"]["id"] == k
        mine = c.post("/notes", json={"symbol": "LT", "text": "my own view"}, headers=DEMO)
        assert [x["text"] for x in c.get("/notes?symbol=LT", headers=DEMO).json()["notes"]] == [
            "my own view",
            SECRET,
        ]
        assert c.get("/notes?symbol=LT", headers=OTHER).json()["notes"] == []
        assert c.delete(f"/notes/{mine.json()['id']}", headers=OTHER).status_code == 404
        # cannot attribute a note to someone else's contact
        bad = {"symbol": "LT", "text": "x", "contact": k}
        assert c.post("/notes", json=bad, headers=OTHER).status_code == 404
        assert (
            c.post("/notes", json={"symbol": "LT", "text": "  "}, headers=DEMO).status_code == 400
        )

        c.delete(f"/people/{k}", headers=DEMO)
        left = c.get("/notes?symbol=LT", headers=DEMO).json()["notes"]
        assert [x["text"] for x in left] == ["my own view"]  # the investor's own note stays
        c.post("/people/reset", headers=DEMO)
        assert c.get("/notes?symbol=LT", headers=DEMO).json()["notes"] == []


def test_notes_never_reach_the_model_or_the_research_view(seeded, monkeypatch):
    from app.research import qa

    with _client() as c:
        c.post(
            "/notes",
            json={"symbol": "LT", "text": SECRET, "contact": _vivek(c)},
            headers=DEMO,
        )
        assert SECRET not in c.get("/research/LT", headers=DEMO).text

    seen = []

    class SpyLLM:
        @contextmanager
        def recording(self):
            yield {"answer_question": "spy/model"}

        def run(self, task, **kw):
            seen.append(json.dumps(kw, default=str))
            return qa.Answer(answerable="no", points=[], follow_ups=[])

    monkeypatch.setattr(qa, "get_llm", lambda: SpyLLM())
    view = json.loads((FIX / "research/LT.json").read_text())
    qa.answer(view, "What do my contacts say about OSAT yields?")
    assert seen and all(SECRET not in s and "zebra" not in s for s in seen)
