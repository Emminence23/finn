"""promise_vs_delivery (FR-PULL-05): the hero section.

Inputs are built in code: verified guidance quotes (with ids), later management updates
(with ids) and actual reported numbers (with ids like "Q:2026-06" or "FY:2026-03"). The
strong model may only cite those ids. Code then enforces:
  - every promise id and evidence id exists (unknown ids are dropped);
  - a promise whose deadline has not passed can't be "missed" without a management update
    admitting a delay or cut (otherwise it becomes "too_early");
  - counts and the credibility score are computed in code from the verdicts.

Then `annotate` (also code, and re-run on stored views) applies the statement rules:
  - each promise is typed: number (point or range), direction, milestone (a dated
    deliverable) or not measurable. Not-measurable statements get no verdict (PL-3);
  - a cited management update that revises, delays or withdraws a target marks the
    promise revised. Before its deadline the verdict is "revised"; after it, the verdict is
    judged against the latest target and the revision is shown beside it (PL-4).
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.llm import get_llm

PROMPT_VERSION = "promises-v2"
VERDICTS = ("delivered", "partly", "missed", "revised", "unclear", "too_early", "not_measurable")
SCORED = ("delivered", "partly", "missed")

SYSTEM = """You are a sceptical buy-side analyst checking whether an Indian listed company's
management delivered on what it promised on earnings calls.

You get PROMISES (verbatim quotes with ids), UPDATES (later management statements with ids),
and ACTUALS (reported numbers with ids). Use ONLY these inputs. No outside knowledge.

For each distinct promise (merge repeats of the same promise across calls into one item,
listing all their ids, oldest first), give:
- verdict: "delivered" (met or beaten), "partly" (meaningful progress but short of the target,
  or met late), "missed" (clearly short after the deadline, or abandoned or cut),
  "unclear" (deadline passed but the inputs cannot settle it, e.g. a segment number that is
  never reported), or "too_early" (deadline not reached and nothing settles it yet).
- actual: one line with the number or fact that decides it, e.g. "FY26 revenue Rs 3,626 Cr
  vs Rs 4,000 Cr+ guided (-9%)". Say "Not yet reported" for too_early.
- evidence: ids from UPDATES and ACTUALS that support the verdict. delivered, partly and
  missed must cite at least one. Never use "partly" just because the data is missing.
- note: one sentence of reasoning, plain English.

Respect "deadline_passed": if false, only use "missed" when an UPDATE shows management cut,
delayed or abandoned the target. A promise may be judged "delivered" early if ACTUALS show it.
Promises the inputs cannot check at all (e.g. a product launch nothing mentions again) are
"too_early" if the deadline has not passed, otherwise "unclear".

Then write "credibility": 2-3 sentences on management's track record from these verdicts:
do they over-promise, revise quietly, or deliver? Cite promise ids in brackets like [T3.1]."""


class Verdict(BaseModel):
    promise_ids: list[str]
    verdict: Literal["delivered", "partly", "missed", "unclear", "too_early"]
    actual: str
    evidence: list[str] = Field(default_factory=list)
    note: str


class Scorecard(BaseModel):
    items: list[Verdict]
    credibility: str


# ------------------------------------------------------------------ deadlines
def horizon_end(h: str | None) -> str | None:
    """Last month of the horizon as 'YYYY-MM' (Indian fiscal year), or None if open-ended."""
    if not h:
        return None
    s = h.upper().replace(" ", "")
    if m := re.search(r"Q([1-4])FY(\d{2,4})", s):
        q, fy = int(m.group(1)), int(m.group(2)) % 100 + 2000
        return {1: f"{fy - 1}-06", 2: f"{fy - 1}-09", 3: f"{fy - 1}-12", 4: f"{fy}-03"}[q]
    if m := re.search(r"H([12])FY(\d{2,4})", s):
        h_, fy = int(m.group(1)), int(m.group(2)) % 100 + 2000
        return f"{fy - 1}-09" if h_ == 1 else f"{fy}-03"
    if m := re.search(r"FY(\d{2,4})", s):
        return f"{int(m.group(1)) % 100 + 2000}-03"
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    if m := re.search(r"(" + "|".join(months) + r")[A-Z]*'?(\d{2,4})", s):
        return f"{int(m.group(2)) % 100 + 2000}-{months.index(m.group(1)) + 1:02d}"
    return None


# ------------------------------------------------------------------ evidence
def actuals(fin: dict) -> list[dict]:
    """Reported numbers the model may cite. Ids are stable and human-readable."""
    out = []
    for q in fin["trajectory"]["quarterly"]:
        out.append({"id": f"Q:{q['period']}", **q})
    bs = {b["period"]: b for b in fin["balance_sheet"]["annual"]}
    cash = {c["period"]: c for c in fin["cash_quality"]["annual"]}
    for a in fin["trajectory"]["annual"][-4:]:
        p = a["period"]
        row = {"id": f"FY:{p}", **a, **{k: v for k, v in cash.get(p, {}).items() if k != "period"}}
        row |= {k: v for k, v in bs.get(p, {}).items() if k != "period"}
        out.append(row)
    return out


def build_scorecard(statements: list[dict], fin: dict, latest_period: str) -> dict:
    promises = [s for s in statements if s["kind"] == "guidance" and s["materiality"] >= 2]
    promises.sort(key=lambda s: (-s["materiality"], s["id"]))
    promises = promises[:30]
    updates = [s for s in statements if s["kind"] == "update"]
    acts = actuals(fin)
    if not promises:
        return {"items": [], "credibility": None, "counts": {}, "score": None}

    def p_in(s):
        end = horizon_end(s["horizon"])
        return {
            "id": s["id"],
            "call": s["doc_label"],
            "quote": s["quote"],
            "target": s["target"],
            "horizon": s["horizon"],
            "deadline": end,
            "deadline_passed": bool(end and end <= latest_period),
        }

    upd = [{k: s[k] for k in ("id", "doc_label", "quote", "target")} for s in updates]
    prompt = (
        f"Latest reported quarter: {latest_period}. Amounts are Rs crore.\n\n"
        f"PROMISES\n{json.dumps([p_in(s) for s in promises], ensure_ascii=False)}\n\n"
        f"UPDATES\n{json.dumps(upd, ensure_ascii=False)}\n\n"
        f"ACTUALS\n{json.dumps(acts)}"
    )
    res = get_llm().run(
        "promise_vs_delivery",
        system=SYSTEM,
        prompt=prompt,
        schema=Scorecard,
        prompt_version=PROMPT_VERSION,
        max_tokens=20000,  # thinking models spend part of this budget reasoning
    )
    return validate(res, promises, updates, acts, latest_period)


def validate(res: Scorecard, promises, updates, acts, latest_period: str) -> dict:
    by_id = {p["id"]: p for p in promises}
    upd_ids = {u["id"] for u in updates}
    act_ids = {a["id"] for a in acts}
    seen: set[str] = set()
    items = []
    for v in res.items:
        ids = [i for i in v.promise_ids if i in by_id and i not in seen]
        if not ids:
            continue
        seen.update(ids)
        evidence = [e for e in v.evidence if e in upd_ids or e in act_ids]
        verdict = v.verdict
        main = by_id[ids[-1]]  # latest restatement carries the live target and horizon
        end = horizon_end(main["horizon"])
        passed = bool(end and end <= latest_period)
        guard = None
        if verdict == "missed" and not passed and not any(e in upd_ids for e in evidence):
            verdict, guard = "too_early", "deadline not reached and no update admits a miss"
        if verdict in ("delivered", "partly", "missed") and not evidence:
            verdict = "unclear" if passed else "too_early"
            guard = "no checkable evidence cited"
        items.append(
            {
                "promise_ids": ids,
                "verdict": verdict,
                "quote": by_id[ids[0]]["quote"],
                "said_in": by_id[ids[0]]["doc_label"],
                "doc_id": by_id[ids[0]]["doc_id"],
                "page": by_id[ids[0]]["page"],
                "target": main["target"],
                "horizon": main["horizon"],
                "deadline": end,
                "actual": v.actual if verdict != "too_early" or not guard else "Not yet reported",
                "evidence": evidence,
                "note": v.note,
                "guard": guard,
                "repeated_in": [by_id[i]["doc_label"] for i in ids[1:]],
            }
        )
    return annotate(
        {"items": items, "credibility": res.credibility}, promises + updates, latest_period
    )


# ------------------------------------------------------------------ statement rules
_UNIT = r"(%|x\b|×|cr\b|crore|bn\b|billion|mn\b|million|lakh|bps|days|times|mw|gw|tonnes?|units)"
_NUMBER = re.compile(r"\d[\d,.]*\s*" + _UNIT, re.I)
_DIRECTION = re.compile(
    r"\b(grow|growth|increas|improv|expan|higher|lower|reduc|declin|ramp|doubl|accelerat|"
    r"strengthen|maintain|sustain|outperform|better|faster|stabili[sz]|positive|negative|"
    r"accretive|pick up|moderat|contain|below|above|at least|cross|remove|exit|no new|zero)\w*",
    re.I,
)
_MILESTONE = re.compile(
    r"\b(commission|commenc|launch|complet|start|operational|go live|ready|begin|onboard|"
    r"acquir|clos|list|approv|receiv|sign|deliver|open)\w*",
    re.I,
)
# Words that mean management changed a target, not ordinary business words like "lower costs"
_CUT = re.compile(
    r"\b(revis\w*|defer\w*|delay\w*|postpon\w*|push(ed)? (out|back)|scal(e|ed) back|"
    r"withdr[ae]w\w*|recalibrat\w*|no longer|(cut|lowered|reduced|trimmed) (the |our )?"
    r"(guidance|target|outlook))",
    re.I,
)


def statement_type(s: dict) -> str:
    """PL-3: what kind of statement a promise is. The extractor already skips vague optimism,
    so "not measurable" is kept for what is left: no number, no direction and no date."""
    target = s.get("target") or ""
    if s.get("target_value") is not None or _NUMBER.search(target):
        return "number"
    if s.get("horizon") and (
        _MILESTONE.search(target) or s.get("metric") in {"capex", "capacity", "order_book"}
    ):
        return "milestone"
    if _DIRECTION.search(target):
        return "direction"
    if s.get("horizon"):
        return "milestone"
    return "not_measurable"


def revision(ids: list[str], evidence: list[str], stmts: dict[str, dict]) -> dict | None:
    """A cited management update that says the target was revised, delayed or withdrawn.

    Only an explicit, cited update counts. Comparing target numbers across merged
    restatements was tried and rejected: the model sometimes merges neighbouring promises
    (an ROA target with an ROE target), which would invent revisions."""
    chain = [stmts[i] for i in ids if i in stmts]
    metric = chain[-1].get("metric") if chain else None
    for e in evidence:
        u = stmts.get(e)
        if (
            u
            and u.get("kind") == "update"
            and (metric is None or u.get("metric") == metric)
            and _CUT.search(f"{u.get('target', '')} {u['quote']}")
        ):
            return {
                "from": chain[0]["target"] if chain else None,
                "to": u.get("target"),
                "in": u.get("doc_label"),
                "update_id": u["id"],
            }
    return None


_ORDER = {
    v: i
    for i, v in enumerate(
        ("missed", "revised", "partly", "delivered", "unclear", "too_early", "not_measurable")
    )
}


def annotate(card: dict, statements: list[dict], latest_period: str) -> dict:
    """Apply the statement rules to a scorecard and recompute counts and score. Idempotent:
    it starts from each item's `base_verdict` (the verdict after the evidence guards), so it
    can be re-run on stored views when the rules change."""
    stmts = {s["id"]: s for s in statements}
    items = []
    for it in card.get("items", []):
        it = dict(it)
        base = it.setdefault("base_verdict", it["verdict"])
        main = stmts.get(it["promise_ids"][-1], it)
        kind = statement_type(main)
        rev = revision(it["promise_ids"], it.get("evidence", []), stmts)
        verdict = base
        passed = bool(it.get("deadline") and it["deadline"] <= latest_period)
        if kind == "not_measurable":
            verdict = "not_measurable"
        elif rev and (base == "too_early" or (base == "missed" and not passed)):
            verdict = "revised"
        it.update(statement_type=kind, revised=rev, verdict=verdict)
        items.append(it)
    weight = {k: s.get("materiality", 0) for k, s in stmts.items()}
    items.sort(key=lambda i: (_ORDER[i["verdict"]], -weight.get(i["promise_ids"][0], 0)))
    counts = {v: sum(i["verdict"] == v for i in items) for v in VERDICTS}
    judged = sum(counts[v] for v in SCORED)
    score = round((counts["delivered"] + 0.5 * counts["partly"]) / judged * 100) if judged else None
    return {**card, "items": items, "counts": counts, "score": score}
