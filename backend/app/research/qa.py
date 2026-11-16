"""Ask FINN (FR-PULL-12): a question about one company, answered only from what FINN has read.

Retrieval is deterministic: the pages of the company's annual report and earnings calls that
best match the question (BM25), plus the computed financials and the promise scorecard. The
model writes the answer; code keeps only points whose citations point at pages, numbers or
promises that were actually in the prompt (the same rule as the research note, NFR-04).
"""

from __future__ import annotations

import functools
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

PROMPT_VERSION = "qa-v3"
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


# How investors ask vs how filings say it. A phrase in the question adds the filing's terms
# to the search, at a lower weight than the question's own words. General finance
# vocabulary, written once; tested on questions written after it (retrieval_eval).
SYNONYMS: list[tuple[str, str]] = [
    (
        r"\b(take|takes|taking) to pay|collect(ion|ions)?|paid late|debtors?\b",
        "receivable receivables debtor days collection",
    ),
    (
        r"\b(indebted|owe|owes|lenders?|leverage|levered|geared|gearing)\b",
        "debt borrowings net gross leverage",
    ),
    (r"\bbacklog|pipeline|orders? (in hand|on hand|pending)|unexecuted\b", "order book"),
    (r"\b(new business|deals?|wins?|signed|bookings?)\b", "tcv acv order booking deal wins"),
    (r"\b(busy|bench|billable|idle)\b", "utilization utilisation billable"),
    (
        r"\b(leaving|quit|quitting|resign\w*|churn|turnover of (staff|people|employees))\b",
        "attrition",
    ),
    (
        r"\b(bad loans?|going bad|default\w*|delinquen\w*|stressed)\b",
        "gnpa nnpa npa stage credit cost",
    ),
    (r"\blend against|loan.to.value|per gram\b", "ltv loan-to-value"),
    (r"\b(new plants?|spend on|invest(ment)? in (plants?|capacity)|expansion)\b", "capex capacity"),
    (r"\bchip packaging|semiconductor (assembly|packaging)\b", "osat"),
    (r"\b(margins?|profitability)\b", "ebitda margin"),
    (r"\b(cash (burn|flow)|cash generation)\b", "operating cash flow cfo"),
    (r"\b(guid\w*|outlook|target\w*|expect\w*)\b", "guidance outlook target"),
    (r"\b(stock|inventory) (piling|build)|inventor(y|ies)\b", "inventory days"),
    (r"\b(dividend|payout)\b", "dividend payout"),
]
EXPANSION_WEIGHT = 0.6


def _query(question: str) -> dict[str, float]:
    """The question's own terms at weight 1, plus the filing vocabulary its phrases map to."""
    q = dict.fromkeys(_terms(question), 1.0)
    for pattern, terms in SYNONYMS:
        if re.search(pattern, question, re.I):
            for t in _terms(terms):
                q.setdefault(t, EXPANSION_WEIGHT)
    return q


def rank_pages(question: str, docs: list[tuple[DocRef, list[str]]], k: int = TOP_PAGES):
    """BM25 over every page of every document. Returns [(ref, page_no)] best first."""
    q = _query(question)
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
            s += q[t] * idf * c[t] * 2.2 / (c[t] + 1.2 * (0.25 + 0.75 * length / avg))
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
                f"When sources give different figures for the same item, give the date and "
                f"basis (standalone or consolidated, year-end or quarter) of each, and only call "
                f"a change a rise or fall if the later figure is larger or smaller. "
                f"Never guess and never use outside knowledge."
            ),
            prompt=f"QUESTION\n{question}\n\n{numbers}\n\nDOCUMENT EXCERPTS\n{pages_block}",
            schema=Answer,
            prompt_version=PROMPT_VERSION,
            max_tokens=8000,
        )
    allowed = {r.id: set(only) for r, _, only in sent}
    page_text = {r.id: p for r, p, _ in sent}
    points = []
    for c in res.points:
        cites = _clean_cites(c.cites, allowed, ids)
        if cites or res.answerable == "no":
            text = _clean_text(c.text)
            point = {"text": text, "cites": cites}
            missing = unchecked_numbers(text, cites, page_text, numbers)
            if missing:
                point["unchecked"] = missing
            points.append(point)
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


_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d+))?(?![\w])")


def _figures(text: str) -> set[str]:
    """Figures in a sentence, normalised ('1,365.2' -> '1365.2'). Years, quarter labels and
    small counts are left out: they aren't what a reader needs checked."""
    out = set()
    for whole, frac in _NUM.findall(text):
        n = whole.replace(",", "")
        if not frac and (len(n) <= 2 or (len(n) == 4 and 1990 <= int(n) <= 2040)):
            continue
        out.add(n + (f".{frac}" if frac else ""))
    return out


def unchecked_numbers(text: str, cites: list[dict], pages: dict, numbers: str) -> list[str]:
    """Figures in an answer point that appear in none of the sources it cites. Code can't
    tell a misread from a sum the model did, so these are shown, not dropped."""
    figs = _figures(text)
    if not figs:
        return []
    found: set[str] = set()
    for c in cites:
        if c.get("page") is None:
            found |= _figures(numbers)  # a reported-number or scorecard id: the numbers block
        elif c["doc"] in pages and 0 < c["page"] <= len(pages[c["doc"]]):
            found |= _figures(pages[c["doc"]][c["page"] - 1])

    def seen(f: str) -> bool:
        # 1,365 on the page may be 1365.0 or 1,365.4 in the answer, and the reverse
        return f in found or f.split(".")[0] in {x.split(".")[0] for x in found}

    return sorted(f for f in figs if not seen(f))


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


@functools.lru_cache
def _aliases() -> dict[str, list[str]]:
    """Everyday names for a company ("L&T", "Zomato", "Vodafone Idea"), from the curated
    company meta, so people can ask the way they talk."""
    from app.ingest.universe import fixtures_dir

    path = fixtures_dir() / "companies_meta.json"
    if not path.exists():
        return {}
    meta = json.loads(path.read_text())["companies"]
    return {
        sym: [a.lower() for a in m.get("aliases", []) if len(a) >= 3 or "&" in a]
        for sym, m in meta.items()
    }


def _core(name: str) -> list[str]:
    """A company name as words, without the legal suffix: "Dixon Technologies (India) Ltd"
    gives ["dixon", "technologies", "india"]."""
    words = re.findall(r"[a-z0-9&]+", name.lower())
    while words and words[-1] in ("limited", "ltd", "the"):
        words.pop()
    return words


@functools.lru_cache(maxsize=4)
def _name_index(names: tuple[str, ...]) -> Counter:
    """How many listed companies share each name's first distinctive word, so "Dixon" can
    name a company and "Tata" or "Bharat" can't."""
    return Counter(next((w for w in _core(n) if w not in _GENERIC), "") for n in names)


def resolve_company(question: str, rows: list[dict], ready: set[str]) -> str | None:
    """Which company a free-text question is about, across every listed company:
    - a ticker in capitals ("is DIXON ...") or a full name ("Bharat Electronics") names any
      company, so "Bharat Electronics" is BEL, not the followed BHEL;
    - a capitalised name word mid-sentence ("what did Trent promise") names a company when
      no other listed company starts with that word;
    - lowercase tickers, first names and everyday aliases match only followed companies,
      so 'margin' never resolves to a stock called MARGIN.
    Followed and research-ready companies win ties."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9&\-]*", question)
    lower = {w.lower() for w in words}
    q = " ".join(re.findall(r"[a-z0-9&]+", question.lower()))
    # capitalised words that don't start a sentence: names, not sentence case
    tokens = re.findall(r"[A-Za-z0-9&]+|[.?!:]", question)
    titled = {
        t.lower()
        for i, t in enumerate(tokens)
        if i and tokens[i - 1] not in ".?!:" and t[0].isupper() and len(t) >= 4
    }
    firsts = _name_index(tuple(r["name"] for r in rows))
    best: tuple | None = None
    for r in rows:
        sym = r["symbol"]
        followed = bool(r["in_portfolio"] or r["in_research_set"] or sym in ready)
        core = _core(r["name"])
        first = next((w for w in core if w not in _GENERIC), "")
        full = " ".join(core)
        score, length = 0, 0
        if sym in words:
            score = 3
        if len(core) >= 2 and re.search(rf"(?<![a-z0-9]){re.escape(full)}(?![a-z0-9])", q):
            score, length = 3, len(full)
        if followed and (
            (len(sym) >= 4 and sym.lower() in lower)
            or any(
                re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9&])", question.lower())
                for a in _aliases().get(sym, [])
            )
        ):
            score = max(score, 3)
        if not score and len(first) >= 4:
            if followed and first in lower:
                score = 2
            elif first in titled and firsts[first] == 1:
                score = 1
        if score:
            key = (score, sym in ready, followed, length)
            if best is None or key > best[0]:
                best = (key, sym)
    return best[1] if best else None
