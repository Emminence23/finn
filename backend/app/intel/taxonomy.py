"""Announcement categories (reference doc) and the rules-first classifier (FR-PUSH-02).

Rules map NSE's own `desc` field plus subject keywords to a category. Each rule is either
confident or ambiguous; only ambiguous ones are sent to the LLM (NFR-03).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORIES = [
    "results",
    "M&A",
    "fund_raise",
    "management_change",
    "litigation",
    "insider_trading",
    "earnings_call",
    "investor_meetings",
    "credit_rating",
    "dividend",
    "bonus_split",
    "capex",
    "press_release",
    "postal_ballot",
    "agm_egm",
    "pledging",
    "unclassified",
]

# How much a category matters by default (0..1). Multiplied by per-item materiality.
CATEGORY_WEIGHT = {
    "results": 1.0,
    "M&A": 0.95,
    "management_change": 0.85,
    "litigation": 0.85,
    "fund_raise": 0.8,
    "capex": 0.8,
    "credit_rating": 0.7,
    "pledging": 0.75,
    "insider_trading": 0.6,
    "press_release": 0.55,
    "bonus_split": 0.5,
    "dividend": 0.4,
    "earnings_call": 0.35,
    "investor_meetings": 0.15,
    "agm_egm": 0.15,
    "postal_ballot": 0.15,
    "unclassified": 0.05,
}

# Collapsed under "Routine (n)" by default (FR-PUSH-04)
ROUTINE = {"unclassified", "investor_meetings", "postal_ballot", "agm_egm", "dividend"}

# Card kinds that get hero treatment (FR-CARD)
MATERIAL_EVENTS = {"M&A", "capex", "litigation", "fund_raise"}


def folds_as_routine(
    category: str | None, materiality: int | None, exch_category: str, subject: str
) -> bool:
    """Whether a filing goes into the folded "Routine (n)" group (PU-5).

    Push favours recall: a filing is folded only when FINN is sure it is routine. An
    "unclassified" filing the rules could not place stays visible unless the triage model
    read it and scored it as paperwork (materiality < 10). If triage never ran, it stays
    visible: FINN doesn't know, so it doesn't hide it.
    """
    cat = category or "unclassified"
    if cat == "unclassified" and not classify_rules(exch_category, subject).confident:
        return materiality is not None and materiality < 10
    return cat in ROUTINE or (materiality or 0) < 10


def is_unsure(category: str | None, exch_category: str, subject: str) -> bool:
    """Unclassified, and no confident rule says it is paperwork."""
    return (category or "unclassified") == "unclassified" and not classify_rules(
        exch_category, subject
    ).confident


@dataclass(frozen=True)
class RuleResult:
    category: str
    confident: bool
    rule: str


def _has(text: str, *words: str) -> bool:
    return any(re.search(w, text, re.I) for w in words)


RESULT_WORDS = (
    r"financial results?",
    r"unaudited",
    r"audited .*results",
    r"quarter.*ended",
    r"results? for the (quarter|period)",
)


def classify_rules(exch_category: str, subject: str) -> RuleResult:  # noqa: C901 - a rule table
    d = (exch_category or "").strip().lower()
    s = subject or ""
    both = f"{d} {s}"

    def r(cat: str, confident: bool = True) -> RuleResult:
        return RuleResult(cat, confident, d or "subject")

    # --- management
    if d in {
        "change in management",
        "appointment",
        "resignation",
        "retirement",
        "resignation of director/kmp/smp",
        "change in director(s)",
        "cessation",
        "change in key managerial personnel",
    }:
        return r("management_change")
    if _has(
        s,
        r"appointment of (senior management|key managerial|chief|director)",
        r"cessation of",
        r"resignation of",
    ):
        return r("management_change")
    # --- results
    if d == "outcome of board meeting":
        return r("results") if _has(s, *RESULT_WORDS) else r("results", False)
    if d == "financial result updates" or d.startswith("financial result"):
        return r("results")
    if d == "copy of newspaper publication":
        return r("results") if _has(s, *RESULT_WORDS) else r("unclassified")
    if d == "investor presentation":
        return r("results") if _has(s, *RESULT_WORDS, r"earnings") else r("investor_meetings")
    # --- calls and meetings
    if d.startswith("analysts/institutional investor meet"):
        if _has(
            s,
            r"transcript",
            r"recording",
            r"earnings call",
            r"con\.? ?call",
            r"conference call",
            r"audio",
        ):
            return r("earnings_call")
        return r("investor_meetings")
    # --- corporate events
    if d in {
        "acquisition",
        "sale or disposal",
        "amalgamation",
        "scheme of arrangement",
        "other restructuring",
        "demerger",
        "merger",
    }:
        return r("M&A")
    if d == "agreements":
        return (
            r("M&A")
            if _has(s, r"joint venture", r"acquisition", r"share purchase")
            else r("press_release", False)
        )
    if d in {
        "capacity addition",
        "commencement of commercial production/operations",
        "commencement of commercial production",
    }:
        return r("capex")
    if (
        d in {"action(s) taken or orders passed", "corporate insolvency resolution process"}
        or d.startswith("pendency of litigation")
        or _has(d, r"litigation", r"penalt")
    ):
        return r("litigation")
    if d.startswith("credit rating"):
        return r("credit_rating")
    if d in {
        "qualified institutional placement",
        "preferential issue",
        "issue of securities",
        "rights issue",
        "buyback",
        "commercial paper",
        "issue of commercial paper",
    }:
        return r("fund_raise")
    if d == "allotment of securities":
        return (
            r("unclassified")
            if _has(s, r"esop", r"esos", r"employee", r"stock option")
            else r("fund_raise", False)
        )
    if d == "dividend" and _has(s, *RESULT_WORDS):
        return r("results")  # boards often file results under "Dividend" when declaring one
    if d in {"dividend"} or (d == "record date" and _has(s, "dividend")):
        return r("dividend")
    if d == "record date":
        return (
            r("bonus_split")
            if _has(s, r"bonus", r"split", r"sub-?division")
            else r("dividend", False)
        )
    if _has(d, r"bonus", r"split", r"sub-?division"):
        return r("bonus_split")
    if _has(both, r"pledge"):
        return r("pledging")
    if d.startswith("disclosure under sebi takeover") or _has(d, r"insider trading", r"sast"):
        return r("insider_trading")
    if d == "shareholders meeting":
        return r("postal_ballot") if _has(s, r"postal ballot") else r("agm_egm")
    if _has(d, r"postal ballot"):
        return r("postal_ballot")
    if _has(d, r"agm", r"egm", r"annual general meeting"):
        return r("agm_egm")
    if d in {
        "news verification",
        "rumour verification - regulation 30(11)",
        "clarification - news item",
    } or d.startswith("rumour verification"):
        return r("press_release")
    if d == "press release":
        return r("results") if _has(s, *RESULT_WORDS) else r("press_release", False)
    # --- a fund-raise committee deciding the issue (price, allotment) is the fund raise
    if d == "committee meeting updates" and _has(
        s, r"\bqip\b", r"\bpi \d{4}\b", r"preferential", r"rights issue", r"fund rais"
    ):
        return r("fund_raise")
    # --- routine paperwork
    if d in {
        "esop/esos/esps",
        "trading window",
        "monitoring agency report",
        "corrigendum",
        "change in auditors",
        "amendment to aoa/moa",
        "committee meeting updates",
        "utilisation of funds",
        "conversion",
        "options to purchase securities",
        "statement of deviation(s) or variation(s) under reg. 32",
        "certificate under sebi (depositories and participants) regulations, 2018",
        "loss of share certificates",
        "duplicate share certificate",
        "suspension of trading",
        "book closure",
        "closure of trading window",
        "esg rating",
        "business responsibility and sustainability reporting",
    }:
        return r("unclassified")
    # --- catch-alls the LLM should look at
    if d in {"general updates", "updates", ""}:
        if _has(s, r"transcript", r"audio recording", r"link of recording"):
            return r("earnings_call")
        if _has(s, r"analyst", r"investor(s)? (meet|conference)", r"investor conference"):
            return r("investor_meetings")
        if _has(
            s,
            r"redemption of commercial paper",
            r"dematerial",
            r"certificate pursuant",
            r"change in (corporate office|registered office) address of",
        ):
            return r("unclassified")
        if _has(s, r"acquisition", r"joint venture", r"amalgamation"):
            return r("M&A", False)
        if _has(s, *RESULT_WORDS, r"earnings presentation"):
            return r("results", False)
        return r("unclassified", False)
    return r("unclassified", False)
