"""Ask FINN (FR-PULL-12): a question about one company, answered only from what FINN has read.

Retrieval is deterministic: the pages of the company's annual report and earnings calls that
best match the question (BM25), plus the computed financials and the promise scorecard. The
model writes the answer; code keeps only points whose citations point at pages, numbers or
promises that were actually in the prompt (the same rule as the research note, NFR-04).
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from app.llm import get_llm
from app.research import promises as promises_mod
from app.research.docs import DocRef, load_pages
from app.research.narrative import GROUNDING, Claim, _clean_cites, _clean_text

PROMPT_VERSION = "qa-v2"
MAX_QUESTION = 300
TOP_PAGES = 8

_STOP = frozenset(
    re.findall(
        r"\w+",
        """
    a an and are as at be been by did do does for from had has have how i in is it its of on or
    so than that the their them there these they this to was were what when where which who why
    will with would you your about any can could company management say said tell me us our
    over next last year years quarter quarters
""",
    )
)


class Answer(BaseModel):
    answerable: Literal["yes", "partly", "no"] = Field(
        description="'no' if the documents and numbers provided do not answer the question"
    )
    points: list[Claim] = Field(description="2-5 short points, each with citations")
    follow_ups: list[str] = Field(description="up to 3 short follow-up questions worth asking")


def _terms(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z0-9\-]+|\d+(?:\.\d+)?", text.lower())
    return [w for w in words if w not in _STOP and len(w) > 1]


def rank_pages(question: str, docs: list[tuple[DocRef, list[str]]], k: int = TOP_PAGES):
    """BM25 over every page of every document. Returns [(ref, page_no)] best first."""
    q = set(_terms(question))
    if not q:
        return []
    corpus = [(r, i + 1, Counter(_terms(t))) for r, pages in docs for i, t in enumerate(pages)]
    if not corpus:
        return []
    n = len(corpus)
    avg = sum(sum(c.values()) for _, _, c in corpus) / n or 1
    df = {t: sum(1 for _, _, c in corpus if t in c) for t in q}
    scored = []
    for r, page, c in corpus:
        length = sum(c.values()) or 1
        s = 0.0
        for t in q:
            if not c[t]:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * c[t] * 2.2 / (c[t] + 1.2 * (0.25 + 0.75 * length / avg))
        if s > 0:
            scored.append((s, r, page))
    scored.sort(key=lambda x: -x[0])
    return [(r, p) for _, r, p in scored[:k]]


def _context(view: dict) -> tuple[str, set[str]]:
    """Numbers and the promise record, with the ids the model may cite."""
    fin = view["financials"]
    acts = promises_mod.actuals(fin)
    flags = fin.get("flags", [])
    record = [
        {
            "id": f"P{i + 1}",
            "target": it["target"],
            "said_in": it.get("said_in"),
            "verdict": it["verdict"],
            "actual": it.get("actual"),
        }
        for i, it in enumerate(view.get("promises", {}).get("items", []))
    ]
    ids = {a["id"] for a in acts} | {f["id"] for f in flags} | {r["id"] for r in record}
    text = (
        f"REPORTED NUMBERS (Rs crore; cite by id)\n{json.dumps(acts, ensure_ascii=False)}\n\n"
        f"COMPUTED FLAGS (cite by id)\n{json.dumps(flags, ensure_ascii=False)}\n\n"
        f"PROMISE SCORECARD (cite by id)\n{json.dumps(record, ensure_ascii=False)}"
    )
    return text, ids


def answer(view: dict, question: str) -> dict:
    question = re.sub(r"\s+", " ", question).strip()[:MAX_QUESTION]
    t0 = time.perf_counter()
    symbol = view["symbol"]
    refs = [DocRef(**d) for d in view["documents"]]
    docs = [(r, load_pages(symbol, r)) for r in refs]
    docs = [(r, p) for r, p in docs if p]
    hits = rank_pages(question, docs)
    by_doc: dict[str, list[int]] = {}
    for r, page in hits:
        by_doc.setdefault(r.id, []).append(page)
    sent = [(r, p, sorted(by_doc[r.id])) for r, p in docs if r.id in by_doc]
    pages_block = "\n\n".join(
        f'<document id="{r.id}" title="{r.label}">\n'
        + "\n\n".join(f"[page {i}]\n{p[i - 1]}" for i in only)
        + "\n</document>"
        for r, p, only in sent
    )
    numbers, ids = _context(view)
    llm = get_llm()
    with llm.recording() as served:
        res = llm.run(
            "answer_question",
            system=(
                f"You answer a portfolio manager's question about {view['company']}. Answer in "
                f"2-5 points, most important first, each one sentence under 30 words with a "
                f"number where the sources give one.\n{GROUNDING}\n"
                f"You may also cite reported numbers, "
                f'computed flags and scorecard promises by their id (e.g. {{"doc": "FY:2026-03"}}, '
                f'{{"doc": "fin:receivables"}}, {{"doc": "P2"}}). If the sources do not answer '
                f"the question, set answerable to 'no' and say in one point what they do cover. "
                f"Never guess and never use outside knowledge."
            ),
            prompt=f"QUESTION\n{question}\n\n{numbers}\n\nDOCUMENT EXCERPTS\n{pages_block}",
            schema=Answer,
            prompt_version=PROMPT_VERSION,
            max_tokens=8000,
        )
    allowed = {r.id: set(only) for r, _, only in sent}
    points = []
    for c in res.points:
        cites = _clean_cites(c.cites, allowed, ids)
        if cites or res.answerable == "no":
            points.append({"text": _clean_text(c.text), "cites": cites})
    answerable = res.answerable if points else "no"
    return {
        "question": question,
        "answerable": answerable,
        "points": points[:5],
        "dropped": len(res.points) - len(points),  # uncited points removed by code
        "follow_ups": [f.strip() for f in res.follow_ups if f.strip()][:3],
        "searched": [{"doc": r.id, "pages": only} for r, _, only in sent],
        "model": served.get("answer_question"),
        "seconds": round(time.perf_counter() - t0, 1),
    }


def suggested_questions(view: dict) -> list[str]:
    """Deterministic starters from what the view already found: misses, then red flags."""
    out = []
    for it in view.get("promises", {}).get("items", []):
        if it["verdict"] == "missed" and len(out) < 2:
            target = it["target"].rstrip(".")
            out.append(f"Why did they miss “{target[:70]}”?")
    for f in view["financials"].get("flags", []):
        if f.get("tone") == "negative" and len(out) < 3:
            topic = re.split(r"[:(]", f["text"])[0].strip().rstrip(".")
            out.append(f"What did management say about {topic[0].lower() + topic[1:]}?")
    out.append("What did management guide for next year?")
    return list(dict.fromkeys(out))[:4]


_GENERIC = {"the", "india", "indian", "limited", "ltd", "industries", "technologies", "bank"}


def resolve_company(question: str, rows: list[dict], ready: set[str]) -> str | None:
    """Which company a free-text question is about. A ticker typed in capitals matches any
    company ("is DIXON ..."); lowercase tickers and names match only followed companies, so
    'margin' never resolves to a stock called MARGIN. Research-ready companies win ties."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9&\-]*", question)
    lower = {w.lower() for w in words}
    best: tuple[int, str] | None = None
    for r in rows:
        sym = r["symbol"]
        score = 0
        followed = r["in_portfolio"] or r["in_research_set"] or sym in ready
        if sym in words or (followed and len(sym) >= 4 and sym.lower() in lower):
            score = 3
        elif followed:
            first = next(
                (w for w in re.findall(r"[a-z]+", r["name"].lower()) if w not in _GENERIC), ""
            )
            if len(first) >= 4 and first in lower:
                score = 2
        if score:
            score += sym in ready
            if best is None or score > best[0]:
                best = (score, sym)
    return best[1] if best else None
