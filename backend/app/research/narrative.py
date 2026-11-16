"""Business snapshot (FR-PULL-08) and bull vs bear (FR-PULL-09), grounded in primary sources.

Every claim must cite [doc id, page] pairs taken from the text we sent (or a `fin:` flag id
computed in code). Code drops citations to pages that were not in the prompt and drops
claims left with no valid citation.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from app.llm import get_llm
from app.llm.safety import UNTRUSTED_INPUT
from app.research.docs import DocRef, as_paged_text

PROMPT_VERSION = "narrative-v1"

GROUNDING = (
    """Use ONLY the documents provided. Do not use outside knowledge about the company,
its peers or the market, even if you have it. If the documents do not say something, leave it
out. Every claim cites one or more sources as {"doc": "<document id>", "page": <page N marker>}.
Amounts: keep the unit the document uses (Rs crore, Rs million, $ million).
"""
    + UNTRUSTED_INPUT
)


class Cite(BaseModel):
    doc: str
    page: int | None = None


class Claim(BaseModel):
    text: str
    cites: list[Cite]


class Segment(BaseModel):
    name: str
    share: str | None = Field(None, description="share of revenue as stated, e.g. '38%'")
    cites: list[Cite]


class Snapshot(BaseModel):
    what_they_do: Claim
    segments: list[Segment]
    customers_and_markets: list[Claim]
    recent_developments: list[Claim]


class BullBear(BaseModel):
    bull: list[Claim]
    bear: list[Claim]
    watch: list[Claim] = Field(description="1-3 things to check next quarter")


def _doc_block(docs: list[tuple[DocRef, list[str], list[int] | None]]) -> str:
    return "\n\n".join(
        f'<document id="{r.id}" title="{r.label}">\n{as_paged_text(p, only)}\n</document>'
        for r, p, only in docs
    )


def _allowed(docs) -> dict[str, set[int]]:
    return {r.id: set(only if only is not None else range(1, len(p) + 1)) for r, p, only in docs}


def _clean_cites(cites: list, allowed: dict[str, set[int]], fin_ids: set[str]) -> list[dict]:
    out = []
    for c in cites:
        c = c if isinstance(c, dict) else c.model_dump()
        if c["doc"] in fin_ids:
            out.append({"doc": c["doc"], "page": None})
        elif c["doc"] in allowed and c.get("page") in allowed[c["doc"]]:
            out.append(c)
    return [dict(t) for t in {tuple(sorted(d.items())) for d in out}]


def _clean_text(t: str) -> str:
    """Drop a dangling inline citation the model began before the structured one."""
    t = re.sub(r"[\s{(\[]+$", "", t)
    return re.sub(r"\s*\[(T\d|AR)[^\]]*\]\s*$", "", t)


def _claims(claims, allowed, fin_ids) -> list[dict]:
    out = []
    for c in claims:
        cites = _clean_cites(c.cites, allowed, fin_ids)
        if cites:
            out.append({"text": _clean_text(c.text), "cites": cites})
    return out


def business_snapshot(company: str, docs) -> dict | None:
    if not docs:
        return None
    res = get_llm().run(
        "business_snapshot",
        system=f"You write the 'Business snapshot' section of an equity research note on "
        f"{company}, for a portfolio manager. Be specific and short.\n{GROUNDING}\n"
        "what_they_do: 2-3 sentences. segments: the reporting or business segments with revenue "
        "share if stated. customers_and_markets: 2-4 claims (end markets, key customers, export "
        "mix, geography). recent_developments: 2-4 claims from the latest documents (capacity, "
        "acquisitions, new businesses).",
        prompt=_doc_block(docs),
        schema=Snapshot,
        prompt_version=PROMPT_VERSION,
        max_tokens=16000,  # headroom for thinking models used as fallbacks
    )
    allowed = _allowed(docs)
    w = _claims([res.what_they_do], allowed, set())
    return {
        "what_they_do": w[0] if w else None,
        "segments": [
            {"name": s.name, "share": s.share, "cites": c}
            for s in res.segments
            if (c := _clean_cites(s.cites, allowed, set()))
        ],
        "customers_and_markets": _claims(res.customers_and_markets, allowed, set()),
        "recent_developments": _claims(res.recent_developments, allowed, set()),
    }


def bull_bear(company: str, docs, fin: dict, scorecard: dict) -> dict | None:
    if not docs:
        return None
    flags = fin.get("flags", [])
    fin_ids = {f["id"] for f in flags}
    record = [
        {"verdict": i["verdict"], "target": i["target"], "actual": i["actual"]}
        for i in scorecard.get("items", [])
    ]
    res = get_llm().run(
        "bull_bear",
        system=f"You write the 'Bull vs bear' section of an equity research note on {company}. "
        f"Give exactly 3 bull points and 3 bear points, each one sentence with a number where "
        f"possible, then 1-3 'watch' items for next quarter.\n{GROUNDING}\nYou may also cite "
        f'the computed FINANCIAL FLAGS by their id (e.g. {{"doc": "fin:cash_conversion"}}). '
        f"Weigh management's delivery record: a bear point can be that they missed guidance.",
        prompt=(
            f"FINANCIAL FLAGS (computed from reported financials)\n{json.dumps(flags)}\n\n"
            f"DELIVERY RECORD\n{json.dumps(record, ensure_ascii=False)}\n\n{_doc_block(docs)}"
        ),
        schema=BullBear,
        prompt_version=PROMPT_VERSION,
        max_tokens=16000,  # headroom for thinking models used as fallbacks
    )
    allowed = _allowed(docs)
    return {
        "bull": _claims(res.bull, allowed, fin_ids)[:3],
        "bear": _claims(res.bear, allowed, fin_ids)[:3],
        "watch": _claims(res.watch, allowed, fin_ids)[:3],
    }
