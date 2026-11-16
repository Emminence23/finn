"""Why brokerages disagree (brief §3.4, §8). The AI writes the explanation from an evidence
pack built in code; code then checks every figure in every point against the reports that
point cites, and drops points that fail. The pack and the checked answer are stored by a
hash of the pack, so the same reports never cost a second call."""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, Field

from app.brokerage import service
from app.db import session
from app.ingest.universe import fixtures_dir
from app.llm.safety import UNTRUSTED_INPUT

PROMPT_VERSION = "brokerage-explain-v1"


class Point(BaseModel):
    text: str = Field(description="one or two sentences; every figure copied from the evidence")
    cites: list[str] = Field(description="report ids from the evidence this point rests on")


class Explanation(BaseModel):
    summary: str = Field(description="two sentences: where they agree and where they differ")
    points: list[Point]


SYSTEM = """You explain why brokerages' views on one company differ, for an investor.
Use only the EVIDENCE: each brokerage's latest report with its target, valuation method and \
assumptions, estimates and stated risks. Rules:
- Every point cites the report ids it uses. Copy figures exactly as given; never compute new \
ones, never round differently, never bring outside knowledge.
- Explain differences by their stated assumptions (multiples, years valued, segment values, \
growth, margins). If estimates are close, say the gap is in valuation, not earnings.
- A report with an estimates_note has no comparable estimates: do not compare its \
earnings with others.
- These are the reports currently available to FINN, not the whole market. No advice, no \
view on who is right. 3 to 5 points."""
SYSTEM += "\n" + UNTRUSTED_INPUT


def evidence(symbol: str) -> dict:
    """The pack the model sees. Built in code from verified figures only."""
    div = service.divergence(symbol)
    latest = [
        o
        for o in service.overview(symbol)["latest"]
        if o["published_at"] in {a["published_at"] for a in div["assumptions"]}
    ]
    reports = []
    for o in latest:
        est = [
            e
            for e in o["estimates"]
            if e["verified"]
            and not e["is_actual"]
            and not e["other_basis"]
            and e["fiscal_period"] in ("FY27", "FY28")
            and e["metric"] in ("revenue", "EBITDA margin", "PAT", "EPS")
        ]
        other = any(e["other_basis"] for e in o["estimates"])
        reports.append(
            {
                "id": o["report_id"],
                "brokerage": o["brokerage"],
                "date": o["published_at"],
                "rating": o["rating_raw"],
                "target": o["target_price"] if o["target_verified"] else None,
                "price_used": o["reference_price"],
                "horizon": o["horizon"],
                "method": o["valuation_method"],
                "assumptions": [
                    f"{a['item']}: {a['value']} (p{a['page']})" for a in o["valuation_assumptions"]
                ],
                "estimates": [
                    f"{e['metric']} {e['fiscal_period']}: {e['value']:,.10g} {e['unit']}"
                    for e in est
                ],
                **(
                    {
                        "estimates_note": "Its financial table is not on the reported consolidated "
                        "basis (its reported years differ from the company's), so its estimates "
                        "are "
                        "not comparable with the others and are left out."
                    }
                    if other
                    else {}
                ),
                "risks": o["risks"][:4],
            }
        )
    return {
        "symbol": symbol,
        "reports": reports,
        "computed": {
            "target_spread_pct_by_horizon": {
                g["horizon"]: round(g["spread_pct"], 1)
                for g in div["targets"]
                if g["spread_pct"] is not None
            },
            "estimate_spreads": [
                f"{e['metric']} {e['fiscal_period']}: {round(e['spread_pct'], 1)}% between "
                f"{len(e['values'])} brokerages"
                for e in div["estimates"][:8]
            ],
        },
    }


def _key(pack: dict) -> str:
    raw = json.dumps(pack, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{PROMPT_VERSION}\n{SYSTEM}\n{raw}".encode()).hexdigest()[:20]


def _numbers(text: str) -> set[str]:
    out = set()
    for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        v = m.replace(",", "").rstrip(".")
        if v and float(v) >= 10 or "." in v:  # small integers (2 brokerages, 3 points) pass
            out.add(f"{float(v):g}")
    return out


def check(ex: Explanation, pack: dict) -> dict:
    """Keep points whose figures all appear in the reports they cite (or in code's computed
    spreads); drop the rest and say how many went."""
    by_id = {r["id"]: r for r in pack["reports"]}
    computed = json.dumps(pack["computed"])
    kept, dropped = [], []
    for p in ex.points:
        cites = [c for c in p.cites if c in by_id]
        source = " ".join(json.dumps(by_id[c], ensure_ascii=False) for c in cites) + computed
        missing = _numbers(p.text) - _numbers(source)
        if not cites or missing:
            dropped.append(
                {
                    "text": p.text,
                    "why": "no valid source"
                    if not cites
                    else f"figures not in its sources: {', '.join(sorted(missing))}",
                }
            )
            continue
        kept.append(
            {
                "text": p.text,
                "cites": [
                    {"report_id": c, "brokerage": by_id[c]["brokerage"], "date": by_id[c]["date"]}
                    for c in cites
                ],
            }
        )
    summary_ok = not (_numbers(ex.summary) - _numbers(json.dumps(pack, ensure_ascii=False)))
    return {"summary": ex.summary if summary_ok else None, "points": kept, "dropped": dropped}


def _fixture() -> dict:
    p = fixtures_dir() / "brokerage" / "explain.json"
    return json.loads(p.read_text()) if p.exists() else {}


def get(symbol: str, run: bool = False) -> dict:
    """The stored explanation for the current evidence, or a new one when `run` is set."""
    from app.llm import get_llm

    pack = evidence(symbol.upper())
    if len(pack["reports"]) < 2:
        return {"status": "too_few", "reports": len(pack["reports"])}
    key = _key(pack)
    with session() as db:
        r = db.execute(
            "SELECT payload_json FROM research_cache WHERE symbol=? AND key=?",
            (symbol.upper(), f"brokerage-explain:{key}"),
        ).fetchone()
    out = json.loads(r["payload_json"]) if r else _fixture().get(key)
    if out is None and not run:
        return {"status": "not_run", "key": key}
    if out is None:
        res = get_llm().run(
            "explain_divergence",
            system=SYSTEM,
            prompt="EVIDENCE\n" + json.dumps(pack, indent=1, ensure_ascii=False),
            schema=Explanation,
            prompt_version=PROMPT_VERSION,
            max_tokens=12000,
        )
        out = check(res, pack) | {"model_note": "AI · read from the reports below"}
        with session() as db:
            db.execute(
                "INSERT OR REPLACE INTO research_cache (symbol, key, payload_json) VALUES (?,?,?)",
                (symbol.upper(), f"brokerage-explain:{key}", json.dumps(out)),
            )
    return {"status": "done", "key": key, **out}
