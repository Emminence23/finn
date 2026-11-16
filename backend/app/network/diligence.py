"""Questions worth asking before meeting someone (PLAN v2, Network "Should", A §4.5).

Built in code from FINN's own research on the companies the person knows from the inside
or from next door. No LLM is involved, so no network data leaves the server and no quota is
spent. Every question carries the source it rests on: a promise quoted at call and page, or
a flag computed from reported numbers.

The wording follows how the person knows the company:
- current: they work there now, so questions stay on public figures (insider rules);
- former: they saw it from inside, so ask whether a target was ever realistic;
- peer: they know the industry, so ask whether the issue is company-specific.
"""

from __future__ import annotations

from app.network import graph
from app.research.service import get_cached

PER_COMPANY = 3
TOTAL = 6


def _companies(p: graph.Person, people: dict[str, graph.Person]) -> list[tuple[str, str]]:
    out: dict[str, str] = {}
    for r in sorted(p.roles, key=lambda r: r.end is not None):  # current roles first
        if r.symbol and r.symbol not in out:
            out[r.symbol] = "current" if r.end is None else "former"
    if p.is_contact:
        for h in graph.can_help_on(p.id, people):
            out.setdefault(h["symbol"], "peer")
    return list(out.items())


def _q(text: str, basis: dict) -> dict:
    return {"question": text, "basis": basis}


def _for_company(view: dict, relation: str) -> list[dict]:
    short = view["company"].replace(" Limited", "").replace(" Ltd", "")
    items = view.get("promises", {}).get("items", [])
    out = []

    def promise_basis(it: dict) -> dict:
        return {
            "kind": "promise",
            "said_in": it.get("said_in"),
            "doc_id": it.get("doc_id"),
            "page": it.get("page"),
            "outcome": it.get("actual"),
            "verdict": it["verdict"],
        }

    for it in items:
        target = it["target"].rstrip(".")
        n_missed = sum(q["basis"].get("verdict") == "missed" for q in out)
        if it["verdict"] == "missed" and it.get("actual") and n_missed == 1:
            text = {
                "former": f"And “{target}”: what got in the way?",
                "current": f"“{target}” was also missed. Is it back on track?",
                "peer": f"“{target}” was also missed. Same cause?",
            }[relation]
            out.append(_q(text, promise_basis(it)))
        elif it["verdict"] == "missed" and it.get("actual") and n_missed == 0:
            text = {
                "former": f"They guided “{target}” and missed. From your time at {short}, "
                f"was that ever realistic?",
                "current": f"The reported result missed “{target}”. What changed after the "
                f"guidance was given?",
                "peer": f"{short} missed “{target}”. Was that specific to {short}, or "
                f"industry-wide?",
            }[relation]
            out.append(_q(text, promise_basis(it)))
        elif it["verdict"] == "revised":
            text = f"They revised “{target}”. What drove the change, and is the new number safe?"
            out.append(_q(text, promise_basis(it)))
    for f in view["financials"].get("flags", []):
        if f.get("tone") != "negative":
            continue
        topic = f["text"].rstrip(".")
        text = {
            "former": f"{topic}. Was it like that when you were there?",
            "current": f"{topic}. How does the team think about it?",
            "peer": f"{topic}. Is that normal for the industry, or specific to {short}?",
        }[relation]
        out.append(_q(text, {"kind": "flag", "id": f["id"], "outcome": f["text"]}))
        break  # one flag is enough next to the promises
    due = sorted(
        (i for i in items if i["verdict"] == "too_early" and i.get("deadline")),
        key=lambda i: i["deadline"],
    )
    for it in due[:1]:
        by = it.get("horizon") or it["deadline"]
        text = f"They committed to “{it['target'].rstrip('.')}” by {by}. What has to go right?"
        out.append(_q(text, promise_basis(it)))
    return out[:PER_COMPANY]


def meeting_questions(person_id: str) -> dict | None:
    people = graph.load_people()
    p = people.get(person_id)
    if p is None or p is graph.investor(people):
        return None
    groups, total = [], 0
    for symbol, relation in _companies(p, people):
        view = get_cached(symbol)
        if not view or total >= TOTAL:
            continue
        qs = _for_company(view, relation)[: TOTAL - total]
        if qs:
            total += len(qs)
            groups.append(
                {
                    "symbol": symbol,
                    "company": view["company"],
                    "relation": relation,
                    "insider": relation == "current",
                    "questions": qs,
                }
            )
    return {"person": p.id, "groups": groups}
