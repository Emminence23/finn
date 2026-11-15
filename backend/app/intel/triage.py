"""Batched LLM triage: category (when rules are unsure), materiality, and a one-liner.

One call handles a batch of filings: about 10x fewer requests than one call per filing,
which matters on free-tier rate limits (NFR-03).
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.intel.taxonomy import CATEGORIES
from app.llm import get_llm

log = logging.getLogger(__name__)
PROMPT_VERSION = "triage-v1"

Category = Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]


class TriageItem(BaseModel):
    id: str
    category: Category
    materiality: int = Field(ge=0, le=100)
    one_liner: str = Field(description="<= 20 words, plain English, facts from the filing only")


class TriageBatch(BaseModel):
    items: list[TriageItem]


SYSTEM = f"""You triage Indian stock-exchange filings for a long-only fund manager who owns \
the stock. For each filing return:
- category: one of {", ".join(CATEGORIES)}. A rule-based guess is given; keep it unless the \
filing clearly says otherwise.
- materiality 0-100: how likely this changes the investment view or moves the stock. \
Routine compliance = 0-10; results, M&A, top-management change, large orders, regulator \
action, fund raises = 60-100; scale by size and surprise.
- one_liner: at most 20 words, what actually happened, with the key number if there is one. \
Use only facts in the filing text. No adjectives, no advice, no company boilerplate.
Category guide: results = quarterly/annual results and their decks, press releases or ads; \
management_change = CEO/CFO/MD/director/KMP/senior management joining, leaving or retiring; \
M&A = acquisitions, JVs, mergers, demergers, subsidiary stake changes; fund_raise = QIP, \
rights, preferential allotment, buyback, debt or commercial paper issuance; litigation = \
lawsuits, regulatory orders, fines, insolvency; capex = new plant or capacity; \
unclassified = routine paperwork."""


def triage(items: list[dict], batch_size: int = 10) -> dict[str, TriageItem]:
    """items: [{id, symbol, exch_category, subject, rule_category, excerpt}] → {id: TriageItem}"""
    llm = get_llm()
    out: dict[str, TriageItem] = {}
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        blocks = [
            f'<filing id="{x["id"]}" company="{x["symbol"]}" exchange_category="'
            f'{x["exch_category"]}" rule_guess="{x["rule_category"]}">\n'
            f"subject: {x['subject']}\n{x.get('excerpt') or '(attachment unavailable)'}\n"
            f"</filing>"
            for x in batch
        ]
        try:
            res = llm.run(
                "triage_filings",
                system=SYSTEM,
                prompt="Triage these filings. Return one item per filing id.\n\n"
                + "\n\n".join(blocks),
                schema=TriageBatch,
                prompt_version=PROMPT_VERSION,
                max_tokens=4000,
            )
        except Exception as e:
            log.error("triage batch %d failed: %s", i // batch_size, e)
            continue
        wanted = {x["id"] for x in batch}
        for item in res.items:
            if item.id in wanted:
                out[item.id] = item
        log.info("triage batch %d: %d/%d", i // batch_size, len(res.items), len(batch))
    return out
