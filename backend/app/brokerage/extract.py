"""Brokerage report -> structured observation (brief §5).

The AI reads the report and returns only what the report states, each material field with
the page and a short verbatim excerpt. Code then checks every excerpt against that page's
text and every number against its excerpt. A field whose evidence doesn't hold is kept but
marked unverified, and the report goes to review: nothing is silently trusted, nothing is
silently dropped. Ratings are normalised only by an explicit table; horizons are kept as
written."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.llm import get_llm
from app.llm.safety import UNTRUSTED_INPUT

PROMPT_VERSION = "brokerage-extract-v2"


class Evidence(BaseModel):
    field: str = Field(description="rating, target_price, reference_price, horizon, published_at")
    page: int
    excerpt: str = Field(description="verbatim, at most 25 words, copied from that page")


class Estimate(BaseModel):
    metric: Literal["revenue", "EBITDA", "EBITDA margin", "PAT", "EPS", "order inflow", "other"]
    metric_raw: str = Field(description="the row label exactly as printed")
    fiscal_period: str = Field(description="as printed, e.g. FY27E, FY28E, Q2FY27")
    value: float
    unit: str = Field(description="e.g. INR crore, INR bn, INR/share, %")
    is_actual: bool = Field(
        description="true for reported history (FY25, FY26A), false for estimates"
    )
    definition: str | None = Field(None, description="e.g. adjusted, recurring, reported")
    scenario: str | None = Field(None, description="base/bull/bear only if the report says so")
    page: int
    excerpt: str = Field(description="the table row or sentence holding the value, verbatim")


class Assumption(BaseModel):
    item: str = Field(description="e.g. core E&C multiple, LTIMindtree value per share")
    value: str = Field(description="as written, e.g. 25x Dec'28E EPS")
    page: int
    excerpt: str


class Extraction(BaseModel):
    brokerage: str | None
    analysts: list[str] = []
    published_at: str | None = Field(description="YYYY-MM-DD, the date printed on the report")
    title: str | None = Field(description="the report's headline")
    report_type: Literal["results update", "company update", "initiation", "sector note", "other"]
    rating_raw: str | None = Field(description="exactly as printed, e.g. BUY, Accumulate")
    target_price: float | None = Field(description="base-case target price per share")
    target_currency: str | None = Field(description="INR only if ₹, Rs or INR is printed")
    reference_price: float | None = Field(description="the CMP or price the report used")
    reference_price_date: str | None = Field(None, description="YYYY-MM-DD only if stated")
    horizon_raw: str | None = Field(
        description="exactly as printed, e.g. 'Target Period: 12 months'"
    )
    horizon_value: float | None = None
    horizon_unit: str | None = Field(None, description="months, weeks, years")
    horizon_basis: Literal["on the target", "rating definition"] | None = Field(
        None,
        description="where the horizon is printed: beside the target, or only in the "
        "report's rating definitions (e.g. 'Expected return (over 12-month)')",
    )
    previous_target: float | None = Field(
        None, description="only if the report prints its old target"
    )
    previous_rating: str | None = Field(
        None, description="only if the report prints its old rating"
    )
    valuation_method: str | None = Field(description="e.g. SOTP, P/E on Sep'28E EPS")
    valuation_assumptions: list[Assumption] = []
    thesis_summary: str | None = Field(description="2 sentences, only from the report")
    catalysts: list[str] = []
    risks: list[str] = []
    estimates: list[Estimate] = []
    evidence: list[Evidence] = []


SYSTEM = """You extract one brokerage research report on an Indian listed company into JSON.
Rules:
- Extract only what the report states. Use null for anything absent or ambiguous. Never infer \
a target from a chart or narrative; never compute a number the report does not print.
- Keep the rating and horizon exactly as printed. Do not convert currencies or units.
- Target price is the base case. Bull/bear targets go nowhere unless labelled; skip them.
- Estimates: take the key financials table (revenue, EBITDA, EBITDA margin, PAT, EPS, and \
order inflow if tabled) for every fiscal year column, marking reported years as is_actual. \
Use the consolidated table if there are several. Copy the row as the excerpt.
- Horizon: if one is printed beside the target, use it (basis "on the target"). If not, but \
the rating definitions state the period of the expected return, use that (basis "rating \
definition") with its own page and excerpt. Otherwise null.
- Evidence: for rating, target_price, reference_price, horizon and published_at give the page \
number (as marked [page N]) and a verbatim excerpt of at most 25 words containing the value.
- valuation_assumptions: the multiples and per-share values the target is built from.
- thesis_summary, catalysts and risks: short, from the report's own words, no opinion."""
SYSTEM += "\n" + UNTRUSTED_INPUT

# brief §6.3: a fixed, visible table; anything not in it stays "not mapped"
RATING_MAP = {
    "buy": "positive",
    "strong buy": "positive",
    "outperform": "positive",
    "overweight": "positive",
    "accumulate": "positive",
    "add": "positive",
    "hold": "neutral",
    "neutral": "neutral",
    "market perform": "neutral",
    "equal weight": "neutral",
    "reduce": "negative",
    "sell": "negative",
    "underperform": "negative",
    "underweight": "negative",
}


def normalise_rating(raw: str | None) -> str | None:
    if not raw:
        return None
    return RATING_MAP.get(re.sub(r"\s+", " ", raw.strip().lower()))


def _squash(s: str) -> str:
    return re.sub(r"[\s ]+", " ", s).strip().lower()


def excerpt_on_page(excerpt: str, page: int, pages: list[str]) -> bool:
    """The excerpt really is on that page (pypdf breaks words and lines, so fuzzy)."""
    if not excerpt or not (1 <= page <= len(pages)):
        return False
    a, b = _squash(excerpt), _squash(pages[page - 1])
    if a in b:
        return True
    a2, b2 = re.sub(r"\s", "", a), re.sub(r"\s", "", b)
    return a2 in b2 or fuzz.partial_ratio(a2, b2) >= 92


def number_in(value: float, text: str) -> bool:
    """The value is printed in the text: 4710 matches '4,710' or '4710'; 8.7 matches '8.7'."""
    digits = {re.sub(r"[,\s]", "", m) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    want = {f"{value:g}", f"{value:.0f}" if value == int(value) else f"{value:g}"}
    for d in digits:
        try:
            if abs(float(d) - value) < 1e-6:
                return True
        except ValueError:
            continue
    return bool(want & digits)


def normalise_period(raw: str) -> str | None:
    """'FY27E' -> 'FY27'; 'FY2027' -> 'FY27'; 'Q2FY27' -> 'Q2 FY27'; else None (kept raw)."""
    s = raw.upper().replace(" ", "").replace("'", "")
    if m := re.fullmatch(r"(Q[1-4])?FY(?:20)?(\d{2})[EAP]?", s):
        return f"{m.group(1) + ' ' if m.group(1) else ''}FY{m.group(2)}"
    if m := re.fullmatch(r"(?:MAR|MARCH)-?(?:20)?(\d{2})[EAP]?", s):
        return f"FY{m.group(1)}"
    return None


MATERIAL = ("rating", "target_price", "reference_price", "horizon", "published_at")


def validate(ex: Extraction, pages: list[str]) -> dict:
    """Code's verdict on each material field and estimate. Returns the checks and whether
    the report needs a human look."""
    checks: dict[str, dict] = {}
    by_field = {e.field: e for e in ex.evidence}
    values = {
        "rating": ex.rating_raw,
        "target_price": ex.target_price,
        "reference_price": ex.reference_price,
        "horizon": ex.horizon_raw,
        "published_at": ex.published_at,
    }
    for f in MATERIAL:
        v, ev = values[f], by_field.get(f)
        if v is None:
            checks[f] = {"status": "not stated"}
            continue
        if ev is None:
            checks[f] = {"status": "no evidence"}
            continue
        on_page = excerpt_on_page(ev.excerpt, ev.page, pages)
        holds = True
        if isinstance(v, float):
            holds = number_in(v, ev.excerpt)
        elif f == "rating":
            holds = _squash(v) in _squash(ev.excerpt)
        checks[f] = {
            "status": "verified" if on_page and holds else "unverified",
            "page": ev.page,
            "excerpt": ev.excerpt.strip(),
            **({} if on_page else {"why": "excerpt not found on that page"}),
            **({} if holds else {"why": "value not in its excerpt"}),
        }
    if ex.target_price is not None and ex.target_price <= 0:
        checks["target_price"] = {"status": "rejected", "why": "not positive"}
    if ex.reference_price is not None and ex.reference_price <= 0:
        checks["reference_price"] = {"status": "rejected", "why": "not positive"}
    currency_ok = ex.target_currency == "INR" and any(
        s in (by_field.get("target_price").excerpt if by_field.get("target_price") else "")
        for s in ("₹", "Rs", "INR", "`")
    )
    est = []
    for e in ex.estimates:
        ok = excerpt_on_page(e.excerpt, e.page, pages) and number_in(e.value, e.excerpt)
        est.append({"ok": ok, "period": normalise_period(e.fiscal_period)})
    needs_review = [
        f for f in MATERIAL if checks[f]["status"] in ("unverified", "no evidence", "rejected")
    ]
    bad_est = sum(not x["ok"] for x in est)
    return {
        "fields": checks,
        "currency": "INR" if currency_ok else None,
        "estimates": est,
        "needs_review": needs_review + ([f"{bad_est} estimates"] if bad_est else []),
        "confidence": round(
            (
                sum(
                    checks[f]["status"] == "verified"
                    for f in MATERIAL
                    if checks[f]["status"] != "not stated"
                )
                + sum(x["ok"] for x in est)
            )
            / max(1, sum(checks[f]["status"] != "not stated" for f in MATERIAL) + len(est)),
            2,
        ),
    }


def extract(pages: list[str], hint: str = "", fresh: bool = False) -> Extraction:
    text = "\n\n".join(f"[page {i + 1}]\n{p}" for i, p in enumerate(pages))
    return get_llm().run(
        "extract_brokerage",
        system=SYSTEM,
        prompt=(f"{hint}\n\n" if hint else "") + "<report>\n" + text + "\n</report>",
        schema=Extraction,
        prompt_version=PROMPT_VERSION,
        max_tokens=16000,
        use_cache=not fresh,
    )
