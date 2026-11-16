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
from app.llm.safety import UNTRUSTED_INPUT

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
SYSTEM += "\n" + UNTRUSTED_INPUT


def triage(items: list[dict], batch_size: int = 10) -> dict[str, TriageItem]:
    """items: [{id, symbol, exch_category, subject, rule_category, excerpt}] → {id: TriageItem}

    Every filing sent must come back exactly once. Unknown ids are dropped, a duplicate
    keeps its first answer, and filings the model left out are sent once more on their
    own. Any still missing keep their rule-based category and are logged by id, so a
    short answer never passes silently as a complete one."""
    out: dict[str, TriageItem] = {}
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        got = _triage_batch(batch, i // batch_size)
        missing = [x for x in batch if x["id"] not in got]
        if missing:
            got |= _triage_batch(missing, i // batch_size, retry=True)
        out |= got
        left = [x["id"] for x in batch if x["id"] not in got]
        if left:
            log.warning(
                "triage batch %d: no answer for %s (rule category kept)", i // batch_size, left
            )
    return out


def _triage_batch(batch: list[dict], n: int, retry: bool = False) -> dict[str, TriageItem]:
    llm = get_llm()
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
            prompt=f"Triage these {len(batch)} filings. Return exactly one item per filing id."
            "\n\n" + "\n\n".join(blocks),
            schema=TriageBatch,
            prompt_version=PROMPT_VERSION,
            max_tokens=4000,
        )
    except Exception as e:
        log.error("triage batch %d%s failed: %s", n, " (retry)" if retry else "", e)
        return {}
    wanted = {x["id"] for x in batch}
    got: dict[str, TriageItem] = {}
    for item in res.items:
        if item.id in wanted and item.id not in got:
            got[item.id] = item
    extra = len(res.items) - len(got)
    log.info(
        "triage batch %d%s: %d/%d answered%s",
        n,
        " (retry)" if retry else "",
        len(got),
        len(batch),
        f", {extra} unknown or duplicate dropped" if extra else "",
    )
    return got
