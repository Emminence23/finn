"""Questions worth asking before a meeting: built in code from FINN's research, each with its
source, worded by how the person knows the company, and never through an LLM."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

FIX = Path(__file__).parents[1] / "data" / "fixtures"


def _client():
    from app.main import app

    return TestClient(app)


def _id(c, prefix):
    return next(p["id"] for p in c.get("/people").json() if p["name"].startswith(prefix))


def test_questions_rest_on_the_research_and_fit_the_relation(seeded, monkeypatch):
    from app.llm import router

    def no_llm(*a, **k):
        raise AssertionError("meeting questions must not call a model")

    monkeypatch.setattr(router, "get_llm", no_llm)
    lt = json.loads((FIX / "research/LT.json").read_text())
    misses = {i["target"].rstrip(".") for i in lt["promises"]["items"] if i["verdict"] == "missed"}
    with _client() as c:
        out = c.get(f"/people/{_id(c, 'Vivek')}/questions").json()
        g = next(x for x in out["groups"] if x["symbol"] == "LT")
        assert g["relation"] == "former" and not g["insider"]
        assert 1 <= len(g["questions"]) <= 3
        first = g["questions"][0]
        assert first["basis"]["kind"] == "promise" and first["basis"]["page"]
        assert any(m in first["question"] for m in misses)
        assert "From your time at" in first["question"]
        total = 0
        for p in c.get("/people").json():
            for grp in c.get(f"/people/{p['id']}/questions").json()["groups"]:
                total += len(grp["questions"])
                for q in grp["questions"]:
                    b = q["basis"]
                    assert b["kind"] in ("promise", "flag")
                    if b["kind"] == "promise":
                        assert b["said_in"] and b["doc_id"]
        assert total > 0
        assert c.get("/people/nobody/questions").status_code == 404


def test_people_who_work_there_now_are_marked_insiders(seeded):
    from app.network import graph
    from app.network.diligence import _companies

    people = graph.load_people()
    insider = next(
        p
        for p in people.values()
        if p.is_contact and any(r.end is None and r.symbol for r in p.roles)
    )
    rels = dict(_companies(insider, people))
    current = next(r.symbol for r in insider.roles if r.end is None and r.symbol)
    assert rels[current] == "current"
