"""How often Ask FINN's retrieval finds the page that answers a question (no AI).

The questions and the pattern that marks each answer's pages are committed
(fixtures/eval/retrieval_questions.json). This runs the same ranking Ask FINN uses and
reports whether an answer page was among the pages sent to the model, overall and split by
whether the question shares the documents' words. Measured before changing retrieval: a
miss on "different words" questions is what a synonym list or embeddings would fix.
"""

from __future__ import annotations

import json
import re
from functools import cache

from app.ingest.universe import fixtures_dir
from app.research import qa
from app.research.docs import DocRef, load_pages
from app.research.service import get_cached


@cache
def _docs(symbol: str) -> tuple:
    view = get_cached(symbol)
    refs = [DocRef(**d) for d in view["documents"]]
    return tuple((r, load_pages(symbol, r)) for r in refs)


def run(k: int = qa.TOP_PAGES) -> dict:
    spec = json.loads((fixtures_dir() / "eval" / "retrieval_questions.json").read_text())
    rows = []
    for item in spec["questions"]:
        docs = [(r, p) for r, p in _docs(item["symbol"]) if p]
        pat = re.compile(item["evidence"], re.I)
        gold = {(r.id, i + 1) for r, pages in docs for i, t in enumerate(pages) if pat.search(t)}
        hits = [(r.id, p) for r, p in qa.rank_pages(item["q"], docs, k=k)]
        rank = next((i + 1 for i, h in enumerate(hits) if h in gold), None)
        rows.append(
            {
                "symbol": item["symbol"],
                "q": item["q"],
                "words": item["words"],
                "set": item.get("set", "tuning"),
                "answer_pages": len(gold),
                "rank": rank,
            }
        )

    def share(rs: list[dict], top: int) -> str:
        n = sum(1 for r in rs if r["rank"] and r["rank"] <= top)
        return f"{n} of {len(rs)}"

    out: dict = {"k": k, "rows": rows}
    for name in ("tuning", "held-out"):
        rs = [r for r in rows if r["set"] == name]
        out[name] = {
            "found": share(rs, k),
            "first": share(rs, 1),
            "same_words": share([r for r in rs if r["words"] == "same"], k),
            "different_words": share([r for r in rs if r["words"] == "different"], k),
        }
    return out
