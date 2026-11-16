"""Research view for any NSE ticker (FR-PULL-01, 10, 11).

    uv run python -m app.research.service KAYNES PERSISTENT      # build + print summary
    uv run python -m app.research.service --fixtures             # precompute the research set

Order of lookup for GET /research/{symbol}: DB cache -> committed fixture -> not built.
The network section ("who can help") is attached at read time, never cached, because
contacts change more often than filings.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.clock import now
from app.db import init_db, session
from app.ingest.fundamentals import NotCovered, fetch_fundamentals
from app.ingest.universe import fixtures_dir, research_symbols
from app.llm import get_llm
from app.network import graph
from app.research import guidance, narrative, promises, qa
from app.research.docs import annual_report_pages, load_pages, pages_fixture, select_docs
from app.research.financials import build_financials

log = logging.getLogger(__name__)
Progress = Callable[[str, str], None]  # (step, message)

VERSIONS = (
    "research-v1",
    guidance.PROMPT_VERSION,
    promises.PROMPT_VERSION,
    narrative.PROMPT_VERSION,
)


def _noop(step: str, msg: str) -> None:
    pass


def research_fixture(symbol: str):
    return fixtures_dir() / "research" / f"{symbol}.json"


def company_name(symbol: str) -> str | None:
    with session() as db:
        r = db.execute("SELECT name FROM companies WHERE symbol=?", (symbol,)).fetchone()
    return r["name"] if r else None


def load_fundamentals(symbol: str) -> dict:
    path = fixtures_dir() / "fundamentals" / f"{symbol}.json"
    if path.exists():
        return json.loads(path.read_text())
    return fetch_fundamentals(symbol)


def cache_key(f: dict) -> str:
    docs = [d.url for d in select_docs(f["documents"])]
    quarters = sorted(f["tables"].get("quarters", {}).get("Net Profit", {}))
    raw = json.dumps([VERSIONS, docs, quarters[-1:]])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_cached(symbol: str) -> dict | None:
    with session() as db:
        r = db.execute(
            "SELECT payload_json FROM research_cache WHERE symbol=? ORDER BY created_at DESC "
            "LIMIT 1",
            (symbol,),
        ).fetchone()
    if r:
        return json.loads(r["payload_json"])
    path = research_fixture(symbol)
    return json.loads(path.read_text()) if path.exists() else None


def ready_symbols() -> set[str]:
    """Symbols with a research view that opens instantly (cheap: no view is parsed)."""
    out = {p.stem for p in (fixtures_dir() / "research").glob("*.json")}
    with session() as db:
        out |= {r[0] for r in db.execute("SELECT DISTINCT symbol FROM research_cache")}
    return out


def summaries() -> list[dict]:
    """One line per ready view: enough for a list, without shipping whole views."""
    views: dict[str, dict] = {}
    for path in sorted((fixtures_dir() / "research").glob("*.json")):
        views[path.stem] = json.loads(path.read_text())
    with session() as db:
        for r in db.execute(
            "SELECT symbol, payload_json FROM research_cache ORDER BY created_at"
        ):  # later rows win: the newest build per symbol
            views[r["symbol"]] = json.loads(r["payload_json"])
    out = []
    for v in views.values():
        p = v.get("promises") or {}
        out.append(
            {
                "symbol": v["symbol"],
                "company": v["company"],
                "generated_at": v.get("generated_at"),
                "latest_quarter": v.get("latest_quarter"),
                "counts": p.get("counts", {}),
                "score": p.get("score"),
                "headline": next(
                    (i["actual"] for i in p.get("items", []) if i["verdict"] == "missed"), None
                ),
                "incomplete": v.get("incomplete", []),
            }
        )
    return sorted(out, key=lambda x: x["generated_at"] or "", reverse=True)


def with_network(view: dict) -> dict:
    """Attach 'who can help' (FR-NET-03 inside Pull). Themes come from the business snapshot."""
    view = dict(view)
    if view.get("promises", {}).get("items"):
        # statement rules run on every read, so stored views follow the current rules
        view["promises"] = promises.annotate(
            view["promises"],
            view.get("guidance") or [],
            view["latest_quarter"],
            view.get("financials"),
        )
    view["helpers"] = graph.who_can_help(view["symbol"], limit=5)
    view["suggested_questions"] = qa.suggested_questions(view)
    return view


def build(symbol: str, progress: Progress = _noop, force: bool = False) -> dict:
    symbol = symbol.upper().strip()
    t0 = time.perf_counter()
    name = company_name(symbol) or symbol

    progress("fundamentals", f"Loading reported financials for {name}")
    try:
        f = load_fundamentals(symbol)
    except NotCovered as e:
        raise LookupError(str(e)) from e
    key = cache_key(f)
    if not force:
        with session() as db:
            r = db.execute(
                "SELECT payload_json FROM research_cache WHERE symbol=? AND key=?", (symbol, key)
            ).fetchone()
        if r:
            progress("done", "Loaded from cache")
            return json.loads(r["payload_json"])

    fin = build_financials(f)
    refs = select_docs(f["documents"])
    progress("documents", f"Fetching {len(refs)} primary documents (annual report, transcripts)")
    pages: dict[str, list[str]] = {}
    for r in refs:
        pages[r.id] = load_pages(symbol, r)
        r.pages = len(pages[r.id])
    with get_llm().recording() as models:
        view = _analyse(symbol, name, f, fin, refs, pages, progress)
    view["models"] = models  # which model wrote each section (shown as AI labels)
    view["build_seconds"] = round(time.perf_counter() - t0, 1)
    view["key"] = key
    failed = view["incomplete"]
    if failed:
        progress("done", f"Built in {view['build_seconds']}s, missing: {', '.join(failed)}")
        return view  # never cache a partial view: the next request retries the gaps
    with session() as db:
        db.execute(
            "INSERT OR REPLACE INTO research_cache (symbol, key, payload_json) VALUES (?,?,?)",
            (symbol, key, json.dumps(view, ensure_ascii=False)),
        )
    progress("done", f"Built in {view['build_seconds']}s")
    return view


def _analyse(symbol, name, f, fin, refs, pages, progress) -> dict:
    available = [r for r in refs if pages[r.id]]
    transcripts = [r for r in available if r.kind == "transcript"]
    ar = next((r for r in available if r.kind == "annual_report"), None)

    failed = _Failures()
    progress("guidance", f"Extracting guidance from {len(transcripts)} earnings calls")
    with ThreadPoolExecutor(max_workers=4) as ex:
        per_doc = list(
            ex.map(
                lambda r: failed.guard(
                    f"guidance:{r.id}", guidance.extract_guidance, r, pages[r.id]
                ),
                transcripts,
            )
        )
    statements = [s for doc in per_doc for s in (doc or [])]
    n_promises = sum(s["kind"] == "guidance" for s in statements)

    latest = fin["trajectory"]["quarterly"][-1]["period"] if fin["trajectory"]["quarterly"] else ""
    progress("promises", f"Checking {n_promises} promises against reported numbers")
    scorecard = failed.guard("promises", promises.build_scorecard, statements, fin, latest) or {
        "items": [],
        "credibility": None,
        "counts": {},
        "score": None,
        "error": True,
    }

    progress("narrative", "Writing business snapshot and bull vs bear")
    snap_docs = []
    if ar:
        snap_docs.append((ar, pages[ar.id], annual_report_pages(pages[ar.id])))
    if transcripts:
        t1 = transcripts[0]
        snap_docs.append((t1, pages[t1.id], list(range(1, min(8, len(pages[t1.id])) + 1))))
    bb_docs = [(r, pages[r.id], None) for r in transcripts[:2]]
    with ThreadPoolExecutor(max_workers=2) as ex:
        fs = ex.submit(failed.guard, "business", narrative.business_snapshot, name, snap_docs)
        fb = ex.submit(
            failed.guard, "bull_bear", narrative.bull_bear, name, bb_docs, fin, scorecard
        )
        snapshot, bb = fs.result(), fb.result()

    view = {
        "symbol": symbol,
        "company": name,
        "generated_at": now().isoformat(timespec="seconds"),
        "latest_quarter": latest,
        "documents": [r.to_dict() for r in refs],
        "financials": fin,
        "promises": scorecard,
        "guidance": statements,
        "business": snapshot,
        "bull_bear": bb,
        "about": f.get("about"),
        "incomplete": list(failed),  # sections that failed (e.g. LLM quota); shown in the UI
    }
    return view


class _Failures(list):
    def guard(self, label: str, fn, *args):
        """A failed LLM section degrades to null instead of failing the whole view, and is
        recorded so an incomplete view is never cached or saved as a fixture."""
        try:
            return fn(*args)
        except Exception as e:
            log.error("%s failed: %s", label, e)
            self.append(label)
            return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "google_genai", "app.http"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    init_db()
    args = sys.argv[1:]
    save = "--fixtures" in args
    force = "--force" in args
    syms = [a for a in args if not a.startswith("--")] or (research_symbols() if save else [])
    for s in syms:
        v = build(
            s, progress=lambda step, msg, s=s: log.info("%s [%s] %s", s, step, msg), force=force
        )
        c = v["promises"].get("counts", {})
        log.info(
            "%s: %d statements, scorecard %s score=%s",
            s,
            len(v["guidance"]),
            c,
            v["promises"].get("score"),
        )
        if save and v["incomplete"]:
            log.error("%s incomplete (%s): fixture not written", s, ", ".join(v["incomplete"]))
        elif save:
            path = research_fixture(s)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(v, indent=1, ensure_ascii=False))
            export_pages(s, v)


def export_pages(symbol: str, view: dict) -> None:
    """Commit page texts with the fixture so Q&A works on a host without the PDF cache."""
    from app.research.docs import DocRef

    for d in view["documents"]:
        ref = DocRef(**d)
        out = pages_fixture(symbol, ref)
        if out.exists():
            continue
        pages = load_pages(symbol, ref)
        if pages:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(pages, ensure_ascii=False))


if __name__ == "__main__":
    main()
