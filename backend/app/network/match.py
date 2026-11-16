# ruff: noqa: E501  (explanations are user-facing sentences)
"""Who in the investor's network may help understand an event (Signal-to-Network, spec 10-11).

Contact relevance, 0-100, from six visible parts:
    relationship strength (0-20) + company overlap (0-30) + role/function fit (0-20)
  + sector/ecosystem (0-15) + recency (0-10) + evidence quality (0-5)
then x degree (1st 1.0, 2nd 0.75) x evidence confidence (high 1.0, medium 0.8, low 0.5).

A person is only recommended with a tie to the company or its ecosystem or a matching
sector; function alone ("works in finance somewhere") is never enough, so unrelated
expertise can't outrank direct overlap. Explanations say what the person may give context
on and what is unknown; they never claim inside knowledge. Everything is computed for one
investor's network, loaded for that owner only.
"""

from __future__ import annotations

import re
from datetime import date

from app.network import graph
from app.network.companies import company_aliases, company_links, normalise_company, resolve_symbol

YEAR = date.today().year
MIN_SCORE = 30  # below this a match is noise; the card says "no relevant match" instead
DEGREE = {1: 1.0, 2: 0.75}
CONFIDENCE = {"high": 1.0, "medium": 0.8, "low": 0.5}

# What kind of experience helps with what kind of event (spec 10, "tailor the function match").
FUNCTIONS = {
    "finance": [
        "financ",
        "cfo",
        "audit",
        "controller",
        "treasur",
        "accounts",
        "tax",
        "investor relations",
        "chartered accountant",
    ],
    "leadership": [
        "ceo",
        "managing director",
        "director",
        "head",
        "president",
        "vp",
        "vice president",
        "strategy",
        "general manager",
        "partner",
    ],
    "operations": [
        "operations",
        "engineer",
        "plant",
        "procurement",
        "project",
        "manufactur",
        "supply chain",
        "production",
        "quality",
        "r&d",
    ],
    "deals": [
        "corporate development",
        "m&a",
        "investment bank",
        "strategy",
        "integration",
        "legal",
        "private equity",
        "deal",
    ],
    "legal": ["legal", "compliance", "regulat", "policy", "counsel", "risk"],
    "sales": [
        "sales",
        "business development",
        "procurement",
        "key account",
        "marketing",
        "commercial",
    ],
    "markets": [
        "analyst",
        "research",
        "fund",
        "portfolio",
        "investor relations",
        "treasury",
        "capital markets",
    ],
}
EVENT_FUNCTIONS = {
    "management_change": ["leadership", "finance"],
    "results": ["finance", "markets"],
    "capex": ["operations", "finance"],
    "M&A": ["deals", "finance"],
    "litigation": ["legal"],
    "fund_raise": ["finance", "markets"],
    "credit_rating": ["finance", "markets"],
    "order": ["sales", "operations"],
    "press_release": ["sales", "operations"],
}
TOPIC = {
    "management_change": "how the leadership and finance teams have worked, and how past transitions went",
    "results": "what drives the business and its numbers",
    "capex": "how the company runs projects and plants",
    "M&A": "how the company does deals and integrates them",
    "litigation": "the regulatory and legal backdrop",
    "fund_raise": "how the company funds itself",
    "order": "its customers and how orders turn into revenue",
}
# Free-text themes a Network query may name, mapped to the function lists above.
THEMES = {
    "corporate_finance": ["finance"],
    "finance": ["finance"],
    "cfo": ["finance", "leadership"],
    "capex": ["operations", "finance"],
    "operations": ["operations"],
    "legal": ["legal"],
    "regulation": ["legal"],
    "sales": ["sales"],
    "deals": ["deals"],
    "m&a": ["deals"],
    "management": ["leadership"],
    "leadership": ["leadership"],
}


def functions_for(
    category: str | None, text: str = "", roles: list[str] | None = None
) -> list[str]:
    """The kinds of experience that help with this event. A CFO change asks for finance
    before general leadership; a CEO change the other way round."""
    fns = list(EVENT_FUNCTIONS.get(category or "", ["leadership"]))
    hint = " ".join([text, *(roles or [])]).lower()
    if category == "management_change" and re.search(r"\b(cfo|chief financial|finance)\b", hint):
        fns = ["finance", "leadership"]
    return fns


def _fits(title: str | None, fns: list[str]) -> str | None:
    t = (title or "").lower()
    for f in fns:
        # word starts only: "vp" must not match inside another word
        if any(re.search(r"(?<![a-z])" + re.escape(k), t) for k in FUNCTIONS[f]):
            return f
    return None


def recency(end: int | None, current: bool) -> float:
    """Spec 10: recent experience counts more; an unknown end year is not assumed current."""
    if current:
        return 10.0
    if end is None:
        return 5.0
    ago = max(0, YEAR - end)
    return 10.0 if ago <= 2 else 7.0 if ago <= 5 else 4.0 if ago <= 10 else 1.0


def _names(symbol: str) -> set[str]:
    return {normalise_company(n) for n in [symbol, *company_aliases().get(symbol, [])]}


def _linked(symbol: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for kind, names in company_links().get(symbol, {}).items():
        for n in names:
            out[normalise_company(n)] = kind
            if s := resolve_symbol(n):
                out[s] = kind
    return out


def score_person(
    p: graph.Person,
    symbol: str,
    fns: list[str],
    names: set[str],
    linked: dict[str, str],
    themes: set[str],
    strength: float,
) -> dict | None:
    """The relevance parts for one person, or None when nothing ties them to the event."""
    best = None  # (overlap points, role, relation)
    for r in p.roles:
        same = r.symbol == symbol or normalise_company(r.company) in names
        kind = (
            None
            if same
            else (linked.get(r.symbol or "") or linked.get(normalise_company(r.company)))
        )
        if not same and not kind:
            continue
        pts = 30 if same else 18 if kind == "competitor" else 15
        cand = (pts, r, "company" if same else kind)
        # among equal ties, a role in the right function and the most recent one wins
        key = (pts, _fits(r.title, fns) is not None, r.end is None, r.end or 0)
        if best is None or key > best[0]:
            best = (key, cand)
    sector = sorted(t for t in p.themes if t.lower() in themes)
    if not best and not sector:
        return None
    parts = {"relationship_strength": round(20 * strength, 1)}
    reasons: list[str] = []
    unknown: list[str] = []
    role = None
    if best:
        pts, role, rel = best[1]
        parts["company_overlap"] = pts
        tense = "Works" if role.end is None else "Worked"
        what = "at the company" if rel == "company" else f"at a {rel}"
        reasons.append(
            f"{tense} {what}: {role.title or 'role not stated'} at {role.company} ({role.span()})"
        )
        parts["recency"] = recency(role.end, role.end is None)
        if role.start is None:
            unknown.append(f"Years at {role.company} aren't recorded.")
    else:
        parts["company_overlap"] = 0
        parts["recency"] = 0
    fit_role = _fits(role.title, fns) if role else None
    any_fit = next((f for r in p.roles if (f := _fits(r.title, fns))), None)
    parts["function_fit"] = 20 if fit_role else 10 if any_fit else 0
    if fit_role or any_fit:
        reasons.append(f"Has {fit_role or any_fit} experience" + ("" if fit_role else " elsewhere"))
    parts["sector"] = 15 if sector else 0
    if sector:
        reasons.append(f"Tracks {', '.join(sector)}")
    years_known = bool(role and role.start is not None)
    parts["evidence_quality"] = 5 if years_known else 3 if role else 2
    confidence = (
        "high"
        if role and years_known and parts["company_overlap"] == 30
        else "medium"
        if role
        else "low"
    )
    relevance = round(sum(parts.values()), 1)
    return {
        "parts": parts,
        "relevance": relevance,
        "reasons": reasons,
        "unknown": unknown,
        "role": role,
        "confidence": confidence,
    }


def _explain(name: str, s: dict, category: str, degree: int, via: str | None) -> str:
    role = s["role"]
    topic = TOPIC.get(category, "the company and its business")
    how = "A first-degree contact" if degree == 1 else f"One introduction away, through {via}"
    if role and role.end is None and s["parts"]["company_overlap"] == 30:
        lead = f"Works at {role.company} now ({role.title}). Keep the conversation to public information."
    elif role:
        verb = "Worked" if role.end is not None else "Works"
        span = (
            f" from {role.start} to {role.end}"
            if role.start and role.end
            else f" since {role.start}"
            if role.start
            else ""
        )
        lead = f"{verb} as {role.title or 'staff'} at {role.company}{span}."
    else:
        lead = s["reasons"][-1].replace("Tracks", "Follows", 1) + "."
    return f"{how}. {lead} May provide context on {topic}. Their knowledge of this event itself is unknown."


def find(
    symbol: str,
    category: str | None,
    *,
    text: str = "",
    roles: list[str] | None = None,
    owner: str | None = None,
    people: dict[str, graph.Person] | None = None,
    names: set[str] | None = None,
    linked: dict[str, str] | None = None,
    theme: str | None = None,
    functions: list[str] | None = None,
    max_degree: int = 2,
    limit: int = 5,
) -> list[dict]:
    """Ranked contacts for an event at `symbol`, for one investor (FR-5, FR-6)."""
    people = people if people is not None else graph.load_people(owner)
    names = names if names is not None else _names(symbol)
    linked = linked if linked is not None else _linked(symbol)
    themes = {t.lower() for t in [theme if theme is not None else graph._theme_for(symbol)] if t}
    fns = functions or functions_for(category, text, roles)
    out: dict[str, dict] = {}

    def add(pid: str, entry: dict) -> None:
        if pid not in out or entry["relevance_score"] > out[pid]["relevance_score"]:
            out[pid] = entry

    for c in people.values():
        if not c.is_contact or not c.relationship:
            continue
        s = score_person(c, symbol, fns, names, linked, themes, c.relationship["strength"] or 0.5)
        if s:
            final = round(s["relevance"] * DEGREE[1] * CONFIDENCE[s["confidence"]])
            add(c.id, _entry(c, s, 1, None, final, category))
        if max_degree < 2:
            continue
        for k in c.knows:
            p = people.get(k["person"])
            if p is None or p.is_contact:
                continue
            s2 = score_person(
                p,
                symbol,
                fns,
                names,
                linked,
                themes,
                (c.relationship["strength"] or 0.5) * (k["strength"] or 0.5),
            )
            if s2 and s2["parts"]["company_overlap"]:  # a 2nd-degree route needs a real tie
                final = round(s2["relevance"] * DEGREE[2] * CONFIDENCE[s2["confidence"]])
                e = _entry(p, s2, 2, c, final, category)
                e["path"] = ["You", c.name, p.name]
                e["introduced_by"] = {"id": c.id, "name": c.name, "context": k["context"]}
                add(p.id, e)
    ranked = sorted(
        (e for e in out.values() if e["relevance_score"] >= MIN_SCORE),
        key=lambda e: -e["relevance_score"],
    )
    return ranked[:limit]


def _entry(
    p: graph.Person,
    s: dict,
    degree: int,
    via: graph.Person | None,
    final: int,
    category: str | None,
) -> dict:
    role = s["role"]
    return {
        "person_id": p.id,
        "display_name": p.name,
        "headline": p.headline,
        "connection_degree": degree,
        "path": ["You", p.name] if degree == 1 else None,
        "relevance_score": final,
        "relevance": s["relevance"],
        "breakdown": s["parts"],
        "match_reasons": s["reasons"],
        "experience_period": {"start": role.start, "end": role.end} if role else None,
        "confidence": s["confidence"],
        "explanation": _explain(p.name, s, category or "", degree, via.name if via else None),
        "unknown": [*s["unknown"], "What they know about this specific event."],
        "insider": bool(role and role.end is None and s["parts"]["company_overlap"] == 30),
    }


def search(
    symbol: str,
    theme: str | None = None,
    max_degree: int = 2,
    limit: int = 5,
    owner: str | None = None,
) -> dict:
    """FR network search: who can help with a company, optionally on a theme."""
    key = (theme or "").strip().lower().replace(" ", "_")
    fns = THEMES.get(key) or ["leadership", "finance"]
    sector = None if key in THEMES or not key else theme
    matches = find(
        symbol, None, owner=owner, theme=sector, functions=fns, max_degree=max_degree, limit=limit
    )
    return {
        "query": {"company_ticker": symbol, "theme": theme, "max_degree": max_degree},
        "functions": fns,
        "matches": matches,
    }
