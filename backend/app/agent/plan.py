# ruff: noqa: E501  (rule text and table field lists read better unbroken)
"""Planning for the Ask pipeline: which report, about which tickers. Code decides first (the
company resolver and keyword rules); only a message the rules can't place goes to the free
model, which sees the question, the report list and the tool list, never any data, and
returns a few words of JSON. That call is small (a few hundred tokens) and cached by message.

    uv run python -m app.agent.plan "is trent cheap vs dmart?"
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Literal

from pydantic import BaseModel, Field

from app.agent import reports, tools
from app.db import session

log = logging.getLogger(__name__)
MAX_TICKERS = 3
Kind = Literal[
    "snapshot",
    "results",
    "bull_bear",
    "verdict",
    "valuation",
    "momentum",
    "filings",
    "guidance",
    "full",
    "compare",
    "portfolio",
]

# First match wins; the order puts the specific before the general.
_RULES: list[tuple[str, str]] = [
    (
        "portfolio",
        r"\bmy (portfolio|holdings|stocks|positions)\b|\bportfolio\b|which of my|across my",
    ),
    (
        "verdict",
        r"\bbuy\b|\bsell\b(?![- ]side)|\bhold\b(?! back| off)|\bexit\b|add (more|to)|accumulat|good (investment|stock|bet)|worth (it|buying|investing)|invest in|should i\b|what do you think|your (view|take)|recommend",
    ),
    ("bull_bear", r"\bbull|\bbear|case for|case against|pros and cons|upside|downside|risks?\b"),
    (
        "results",
        r"result|quarter|\bq[1-4]\b|earnings|qoq|yoy|\bprofit\b|revenue|ebitda|\bpat\b|\bpbt\b|numbers",
    ),
    (
        "valuation",
        r"valuation|valued|\bcheap|expensive|\bp/?e\b|multiple|\bpeg\b|price to book|fair value",
    ),
    (
        "momentum",
        r"\bprice\b|share price|stock price|fell|falling|\bdown\b|rally|\bup\b.*\bstock|momentum|52[- ]week|chart|returns?\b|moving average|volume",
    ),
    ("filings", r"filing|announcement|news|what happened|latest on|disclos|board meeting|update"),
    (
        "guidance",
        r"guid|outlook|management (said|say|expect)|concall|earnings call|commentary|plans?\b|target(s)? for",
    ),
    ("compare", r"\bcompare|\bvs\.?\b|versus|better than"),
    (
        "full",
        r"report on|research note|deep dive|full report|everything|analy[sz]e|analysis|tell me about|overview|summary|snapshot",
    ),
]


class Plan(BaseModel):
    report: Kind
    tickers: list[str] = Field(default_factory=list, description="NSE symbols, at most 3")
    by: Literal["rules", "model"] = "rules"


def _rows() -> list[dict]:
    with session() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT symbol, name, in_portfolio, in_research_set FROM companies"
            ).fetchall()
        ]


def find_tickers(message: str, rows: list[dict] | None = None) -> list[str]:
    """Every company the message names, in order, using FINN's resolver repeatedly."""
    from app.research import qa
    from app.research import service as rs

    rows = rows or _rows()
    ready = {s["symbol"] for s in rs.summaries()}
    found: list[str] = []
    text = message
    for _ in range(MAX_TICKERS):
        sym = qa.resolve_company(text, rows, ready)
        if not sym or sym in found:
            break
        found.append(sym)
        name = next(r["name"] for r in rows if r["symbol"] == sym)
        for w in sorted(
            [sym, name, " ".join(qa._core(name)), *qa._aliases().get(sym, [])],
            key=len,
            reverse=True,
        ):
            text = re.sub(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", " ", text, flags=re.I)
    return found


def rule_kind(message: str) -> str | None:
    m = message.lower()
    return next((k for k, pat in _RULES if re.search(pat, m)), None)


def plan(message: str, context: str | None = None, use_model: bool = True) -> Plan:
    rows = _rows()
    tickers = find_tickers(message, rows)
    tickers = list(dict.fromkeys(tickers + _by_name_word(message, rows)))[:MAX_TICKERS]
    kind = rule_kind(message)
    if kind == "compare" and len(tickers) == 1 and context and context not in tickers:
        tickers = [context, *tickers]  # "compare it with Siemens"
    if kind == "portfolio" and not tickers:
        return Plan(report="portfolio")
    if len(tickers) > 1:
        return Plan(report="compare", tickers=tickers)
    if tickers:
        return Plan(
            report=kind if kind and kind not in ("compare", "portfolio") else "snapshot",
            tickers=tickers,
        )
    # nothing named. A word that matches a listed company's name ("trent results", typed in
    # lowercase) goes to the model; otherwise it's a follow-up on the conversation's company.
    named = _name_words(message, rows)
    if context and not named:
        return Plan(
            report=kind if kind and kind not in ("compare", "portfolio") else "snapshot",
            tickers=[context],
        )
    if use_model:
        p = model_plan(message, rows, context)
        if p:
            return p
    return Plan(report=kind or "snapshot", tickers=[context] if context else [])


# ------------------------------------------------------------------ the small model call
SYSTEM = """You route an investor's question to one report about Indian listed companies.
Reply with JSON only: {"report": <one of the report names>, "tickers": [NSE symbols, at most 3]}.
Pick tickers only from the candidate list when one fits; otherwise use the NSE symbol you are sure of, or [] for a question about the investor's portfolio or with no company."""


_STOP = {
    "the",
    "and",
    "for",
    "buy",
    "sell",
    "stock",
    "stocks",
    "shares",
    "should",
    "what",
    "how",
    "about",
    "limited",
    "india",
    "indian",
    "ltd",
    "company",
    "results",
    "price",
    "news",
    "bull",
    "bear",
    "cheap",
    "margin",
    "growth",
    "capital",
    "finance",
    "bank",
    "power",
    "energy",
    "global",
    "best",
    "good",
    "value",
    "money",
    "life",
    "home",
    "first",
    "super",
    "prime",
    "future",
    "general",
    "national",
    "united",
    "standard",
    "max",
    "star",
    "gold",
    "steel",
    "infra",
    "industries",
    "motors",
    "report",
    "network",
    "contact",
    "contacts",
    "people",
    "someone",
    "help",
    "market",
    "markets",
    "sector",
    "group",
    "management",
    "quarter",
    "latest",
    "today",
    "share",
    "equity",
    "fund",
    "trust",
    "media",
    "health",
    "digital",
    "smart",
    "green",
    "solar",
    "metro",
    "urban",
    "ultra",
}


def _name_words(message: str, rows: list[dict]) -> list[str]:
    """Message words of five letters or more that are some listed company's first name word."""
    from app.research import qa

    firsts = {next((w for w in qa._core(r["name"]) if w not in qa._GENERIC), "") for r in rows}
    return [w for w in re.findall(r"[a-z]{5,}", message.lower()) if w in firsts and w not in _STOP]


def _by_name_word(message: str, rows: list[dict]) -> list[str]:
    """Companies named by a lowercase first name word ("trent results"): the one company
    that starts with it, or the shortest-named of several (Siemens over Siemens Energy)."""
    from app.research import qa

    out = []
    for w in _name_words(message, rows):
        hits = [
            r
            for r in rows
            if next((x for x in qa._core(r["name"]) if x not in qa._GENERIC), "") == w
        ]
        if hits:
            hits.sort(
                key=lambda r: (not (r["in_portfolio"] or r["in_research_set"]), len(r["name"]))
            )
            out.append(hits[0]["symbol"])
    return list(dict.fromkeys(out))[:MAX_TICKERS]


def _candidates(message: str, rows: list[dict]) -> list[str]:
    """Up to 12 listed companies sharing a word with the message, so the model chooses from
    real symbols instead of recalling them."""
    words = {w for w in re.findall(r"[a-z]{3,}", message.lower())} - _STOP
    hits = [
        r
        for r in rows
        if words & set(re.findall(r"[a-z]{3,}", r["name"].lower())) or r["symbol"].lower() in words
    ]
    hits.sort(key=lambda r: (not (r["in_portfolio"] or r["in_research_set"]), len(r["name"])))
    return [f"{r['symbol']} ({r['name']})" for r in hits[:12]]


def model_plan(message: str, rows: list[dict], context: str | None = None) -> Plan | None:
    from app.llm import get_llm

    known = {r["symbol"] for r in rows}
    cands = _candidates(message, rows)
    prompt = (
        "Reports:\n"
        + "\n".join(f"- {k}: {v}" for k, v in reports.KINDS.items())
        + "\n\nTools the report runs (for context):\n"
        + tools.manifest()
        + "\n\nCandidate companies:\n"
        + ("\n".join(cands) or "(none matched)")
        + (f"\n\nCompany already in the conversation: {context}" if context else "")
        + f"\n\nQuestion: {message}"
    )
    try:
        p = get_llm().run(
            "plan_question",
            system=SYSTEM,
            prompt=prompt,
            schema=Plan,
            prompt_version="plan-v1",
            max_tokens=200,
        )
    except Exception as e:  # noqa: BLE001 - no model, no plan: the caller asks which company
        log.warning("model plan failed: %s", e)
        return None
    ticks = [t.upper() for t in p.tickers if t.upper() in known][:MAX_TICKERS]
    report = p.report if p.report != "compare" or len(ticks) > 1 else "snapshot"
    if not ticks and report != "portfolio":
        return None
    return Plan(report=report, tickers=ticks, by="model")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    args = [a for a in sys.argv[1:] if a != "--model"]
    print(json.dumps(plan(" ".join(args), use_model="--model" in sys.argv).model_dump()))
