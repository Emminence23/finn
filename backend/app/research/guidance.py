"""extract_guidance: what management promised, and what it later said about delivery
(FR-PULL-05 input). One call per transcript (fast tier), cached per document.

The model must quote verbatim. Code then checks each quote against the page text and
re-locates it if the page number is off; quotes that cannot be found are dropped, so a
hallucinated promise never reaches the scorecard.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.llm import get_llm
from app.llm.safety import UNTRUSTED_INPUT
from app.research.docs import DocRef, as_paged_text

PROMPT_VERSION = "guidance-v1"

SYSTEM = """You read Indian listed-company earnings-call transcripts for an equity investor.
Extract statements by MANAGEMENT (not analysts, not the moderator) of two kinds:

1. "guidance": a forward-looking commitment that can later be checked. Revenue/volume growth,
   margin targets, capex or capacity commissioning dates, order-book or customer wins
   expected, debt reduction, working-capital or cash-flow targets, product launches with a
   timeline, asset-quality or loan-growth targets. Skip vague optimism ("we are confident
   about the future") unless it names a metric or a timeline.
2. "update": a statement about whether an EARLIER target was met, delayed or changed
   ("the plant was commissioned in March as planned", "we are revising growth to 15%").

Rules:
- "quote" must be copied VERBATIM from the transcript (one or two sentences, no ellipses
  joining distant text). It will be string-matched against the source.
- "page" is the [page N] marker the quote appears under.
- "target" restates the commitment in a few words ("FY27 revenue growth 30-35%").
- "target_value"/"unit" only when a number is stated; otherwise null.
- "horizon" is when it should be judged: "FY27", "Q2 FY27", "H2 FY27", "by Mar 2027",
  "next 2-3 years". Use null if none is stated.
- "materiality": 3 = core financial guidance (growth, margins, profit), 2 = capacity, capex,
  orders, balance sheet, 1 = everything else.
- Use only the transcript. Do not add knowledge from outside it.
Return at most 15 statements, most material first."""
SYSTEM += "\n" + UNTRUSTED_INPUT


class Statement(BaseModel):
    kind: Literal["guidance", "update"]
    metric: str = Field(
        description="revenue_growth, ebitda_margin, pat, capex, capacity, "
        "order_book, debt, working_capital, aum_growth, asset_quality, other"
    )
    quote: str
    page: int
    speaker: str | None = None
    target: str
    target_value: float | None = None
    unit: str | None = None
    horizon: str | None = None
    materiality: int = Field(ge=1, le=3)


class Extraction(BaseModel):
    statements: list[Statement]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w%.\s]", " ", s.lower())).strip()


def locate(quote: str, pages: list[str], hint: int) -> tuple[int | None, float]:
    """Find the page that contains the quote. Tries the cited page first, then all pages.
    PDF text breaks lines mid-sentence, so compare whitespace-normalised text."""
    q = _norm(quote)
    if len(q) < 15:
        return None, 0.0
    order = [i for i in [hint] + list(range(1, len(pages) + 1)) if 0 < i <= len(pages)]
    order = list(dict.fromkeys(order))
    best: tuple[int | None, float] = (None, 0.0)
    # Pass 1: a single page. Pass 2: the page plus the start of the next (quotes can straddle
    # a page break; they are attributed to the page they start on).
    for straddle in (False, True):
        for i in order:
            text = pages[i - 1]
            if straddle and i < len(pages):
                text += " " + pages[i][:600]
            score = fuzz.partial_ratio(q, _norm(text))
            if score >= 90:
                return i, score
            if score > best[1]:
                best = (i, score)
    return best


def extract_guidance(ref: DocRef, pages: list[str]) -> list[dict]:
    if not pages:
        return []
    res = get_llm().run(
        "extract_guidance",
        system=SYSTEM,
        prompt=f'<transcript title="{ref.label}">\n{as_paged_text(pages)}\n</transcript>',
        schema=Extraction,
        prompt_version=PROMPT_VERSION,
        max_tokens=16000,  # headroom for thinking models used as fallbacks
    )
    out = []
    for n, st in enumerate(res.statements):
        page, score = locate(st.quote, pages, st.page)
        if page is None or score < 85:
            continue  # unverifiable quote: drop rather than show
        out.append(
            st.model_dump()
            | {
                "id": f"{ref.id}.{n + 1}",
                "doc_id": ref.id,
                "doc_label": ref.label,
                "quarter": ref.quarter,
                "page": page,
                "quote_match": round(score),
            }
        )
    return out
