"""Evaluate extract_person against the hand-extracted golden set (filing_people.json).

    uv run python -m app.intel.eval_people

Scores: person found (name match), role match (fuzzy), and recall of prior employers and
schools stated in the filing. Uses the LLM cache, so re-runs are free.
"""

from __future__ import annotations

import json

from rapidfuzz import fuzz

from app.db import init_db, session
from app.ingest.universe import fixtures_dir
from app.intel.people import extract_people
from app.network.companies import normalise_company


def _recall(expected: list[str], got: list[str]) -> tuple[int, int]:
    got_n = [normalise_company(g) for g in got]
    hit = sum(
        any(fuzz.token_set_ratio(normalise_company(e), g) >= 85 for g in got_n) for e in expected
    )
    return hit, len(expected)


def _role(r: str) -> str:
    r = r.lower().replace("&", "and")
    for a, b in (
        ("chief executive officer", "ceo"),
        ("chief financial officer", "cfo"),
        ("managing director", "md"),
        ("non-executive", "non executive"),
    ):
        r = r.replace(a, b)
    return r.split("(")[0].strip()


def main() -> None:
    init_db()
    golden = json.loads((fixtures_dir() / "filing_people.json").read_text())["people"]
    with session() as db:
        urls = {r["id"]: r["pdf_url"] for r in db.execute("SELECT id, pdf_url FROM announcements")}
    found = role_ok = 0
    emp = [0, 0]
    edu = [0, 0]
    for g in golden:
        res = extract_people(urls[g["announcement_id"]])
        people = res.people if res else []
        match = max(people, key=lambda p: fuzz.token_set_ratio(p.name, g["name"]), default=None)
        if match is None or fuzz.token_set_ratio(match.name, g["name"]) < 85:
            print(f"MISS  {g['name']:22} extracted={[p.name for p in people]}")
            emp[1] += len(g["roles"])
            edu[1] += len(g["education"])
            continue
        found += 1
        r_ok = fuzz.partial_ratio(_role(match.role), _role(g["role"])) >= 80
        role_ok += r_ok
        e = _recall([r["company"] for r in g["roles"]], [r.company for r in match.prior_roles])
        s = _recall([x["school"] for x in g["education"]], [x.school for x in match.education])
        emp = [emp[0] + e[0], emp[1] + e[1]]
        edu = [edu[0] + s[0], edu[1] + s[1]]
        print(
            f"OK    {g['name']:22} role={'✓' if r_ok else '✗'} ({match.role[:40]}) "
            f"employers {e[0]}/{e[1]} schools {s[0]}/{s[1]}"
        )
    n = len(golden)
    print(
        f"\npeople found {found}/{n} · roles {role_ok}/{n} · "
        f"prior employers {emp[0]}/{emp[1]} · schools {edu[0]}/{edu[1]}"
    )


if __name__ == "__main__":
    main()
