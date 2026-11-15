"""extract_person: who joined or left, from a management-change filing (FR-CARD-03).

Only facts stated in the filing's 'brief profile' are kept; unknown years stay null.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfReader

from app.intel.pdftext import filing_pdf
from app.llm import get_llm

PROMPT_VERSION = "person-v2"


class PriorRole(BaseModel):
    company: str
    title: str | None = None
    start_year: int | None = None
    end_year: int | None = None


class Education(BaseModel):
    school: str
    program: str | None = None


class FilingPerson(BaseModel):
    name: str = Field(description="Full name without honorifics (Mr/Ms/Shri/Dr)")
    role: str = Field(description="The position concerned, e.g. 'Chief Financial Officer'")
    direction: Literal["incoming", "outgoing", "reappointed", "redesignated"]
    effective_date: str | None = Field(description="YYYY-MM-DD if stated")
    is_senior: bool = Field(
        description="True for CEO/MD/CFO/COO/whole-time or independent "
        "directors/chairman/CXO-level senior management"
    )
    bio: str | None = Field(description="<= 40 words from the brief profile; null if none")
    prior_roles: list[PriorRole] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)


class FilingPeople(BaseModel):
    people: list[FilingPerson]


SYSTEM = """You extract people from Indian listed-company management-change filings \
(SEBI Regulation 30 disclosures). List every person whose appointment, resignation, \
retirement, re-appointment or cessation the filing announces. Do NOT list the company \
secretary who signs the letter unless their own position changes. Use only facts written in \
the filing, especially the 'brief profile' annexure: prior employers, titles, education. \
Never add facts from your own knowledge. Use null for anything not stated."""


_RELEVANT = re.compile(r"profile|appoint|resign|cessation|retire|designat|re-appoint", re.I)


def relevant_pages(path, max_chars: int = 16000) -> str:
    """Page 1 (the letter) + pages that talk about people. Management changes are often
    buried at the end of a long board-outcome filing, after the results statement."""
    try:
        pages = [(p.extract_text() or "") for p in PdfReader(str(path)).pages]
    except Exception:
        return ""
    keep = [pages[0]] + [t for t in pages[1:] if _RELEVANT.search(t)]
    text = "\n".join(f"[page]\n{re.sub(r'[ \t]+', ' ', t)}" for t in keep)
    return text[:max_chars]


def extract_people(pdf_url: str) -> FilingPeople | None:
    path = filing_pdf(pdf_url)
    if path is None:
        return None
    text = relevant_pages(path)
    if not text:
        return None
    return get_llm().run(
        "extract_person",
        system=SYSTEM,
        prompt=f"<filing>\n{text}\n</filing>\n\nExtract the people.",
        schema=FilingPeople,
        prompt_version=PROMPT_VERSION,
        max_tokens=3000,
    )
