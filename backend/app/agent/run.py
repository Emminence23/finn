# ruff: noqa: E501  (rule text and table field lists read better unbroken)
"""The Ask pipeline end to end: plan -> tools -> analyse -> report.

    uv run python -m app.agent.run "Should I buy Trent?"
    uv run python -m app.agent.run "compare tcs and infosys" --json

Code does the fetching, arithmetic and writing. A model is used only to plan a question the
rules can't place (a few hundred tokens, no data). `digest` in the reply is the compact,
computed summary to hand a model if a longer written answer is ever wanted."""

from __future__ import annotations

import json
import logging
import sys
import time

from app.agent import reports
from app.agent.plan import Plan, plan

log = logging.getLogger(__name__)


def reply(p: Plan, owner: str = "demo") -> dict:
    t0 = time.perf_counter()
    if p.report != "portfolio" and not p.tickers:
        return {"kind": "pick"}
    r = reports.build(p.report, p.tickers)
    symbol = p.tickers[0] if p.tickers and p.report != "compare" else None
    menu = (
        [{"intent": k, "label": reports.KINDS[k]} for k in reports.MENU if k != p.report]
        if symbol
        else []
    )
    if symbol:
        from app.research import service as rs

        if rs.get_cached(symbol):  # FINN's deeper research exists: offer its centrepiece
            menu.insert(0, {"intent": "ledger", "label": "Promised vs delivered"})
    return {
        "kind": "reply",
        "symbol": symbol,
        "symbols": p.tickers,
        "company": r.get("name") or (symbol or "Portfolio"),
        "intent": p.report,
        "title": r["title"],
        "blocks": r["blocks"],
        "menu": menu,
        "documents": [],
        "as_of": None,
        "digest": r.get("digest", ""),
        "planned_by": p.by,
        "seconds": round(time.perf_counter() - t0, 1),
    }


def ask(
    message: str, context: str | None = None, intent: str | None = None, owner: str = "demo"
) -> dict:
    if intent in reports.KINDS:  # a menu tap: the report is chosen, the company is known
        return reply(Plan(report=intent, tickers=[context] if context else []), owner)
    return reply(plan(message, context), owner)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = ask(" ".join(args))
    if "--json" in sys.argv:
        print(json.dumps(out, indent=1, ensure_ascii=False))
        sys.exit()
    print(
        f"[{out.get('intent')} · {out.get('company')} · planned by {out.get('planned_by')} · {out.get('seconds')}s]"
    )
    for b in out.get("blocks", []):
        if b["type"] == "table":
            print(
                f"\n{b.get('title', '')}\n"
                + "\n".join(" | ".join(r) for r in [b["columns"], *b["rows"]])
            )
        elif b["type"] == "points":
            print(f"\n{b.get('title', '')}\n" + "\n".join(f"- {i['text']}" for i in b["items"]))
        elif b["type"] == "stats":
            print("  ".join(f"{i['label']}: {i['value']}" for i in b["items"]))
        else:
            print(f"\n{b.get('text', '')}")
