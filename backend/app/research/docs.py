"""Primary-source documents for research (FR-PULL-02): latest annual report + last N concall
transcripts, as listed on the company's screener page (links point to BSE/NSE filings).

Each document gets a stable id ("T1".."T4" newest first, "AR") used in citations, and its text
is split per page so every claim can cite a page.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from pypdf import PdfReader

from app.config import get_settings
from app.http import get_fetcher

log = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding warnings on every page


@dataclass
class DocRef:
    id: str  # "T1" (newest transcript) .. "T4", "AR"
    kind: str  # transcript | annual_report
    period: str  # screener period: "2026-08" (call month) or "FY2026"
    label: str  # human label: "Q1 FY27 call (Aug 2026)"
    url: str
    quarter: str | None = None  # quarter discussed, "2026-06", transcripts only
    pages: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def fiscal_label(quarter_end: str) -> str:
    """'2026-06' -> 'Q1 FY27' (Indian fiscal year April–March)."""
    y, m = map(int, quarter_end.split("-"))
    q = {6: 1, 9: 2, 12: 3, 3: 4}[m]
    fy = y + 1 if m >= 4 else y
    return f"Q{q} FY{fy % 100:02d}"


def quarter_discussed(call_month: str) -> str:
    """A call in month M discusses the latest quarter that ended before M
    (Aug 2026 -> 2026-06; Dec 2025 -> 2025-09; Jan 2026 -> 2025-12)."""
    y, m = map(int, call_month.split("-"))
    for qm in (12, 9, 6, 3):
        if qm < m:
            return f"{y}-{qm:02d}"
    return f"{y - 1}-12"


def select_docs(documents: list[dict], n_transcripts: int = 4) -> list[DocRef]:
    by_month: dict[str, dict] = {}
    for d in documents:  # screener sometimes lists the same call twice; keep the first
        if d["kind"] == "transcript" and d.get("period"):
            by_month.setdefault(d["period"], d)
    transcripts = [by_month[p] for p in sorted(by_month, reverse=True)[:n_transcripts]]
    out = []
    for i, d in enumerate(transcripts, 1):
        q = quarter_discussed(d["period"])
        month = date(*map(int, d["period"].split("-")), 1).strftime("%b %Y")
        out.append(
            DocRef(
                f"T{i}", "transcript", d["period"], f"{fiscal_label(q)} call ({month})", d["url"], q
            )
        )
    ars = [d for d in documents if d["kind"] == "annual_report"]
    if ars:
        d = ars[0]
        out.append(
            DocRef("AR", "annual_report", d["period"], f"Annual Report {d['period']}", d["url"])
        )
    return out


def doc_dir(symbol: str) -> Path:
    return get_settings().cache_dir / "docs" / symbol


def ensure_pdf(symbol: str, ref: DocRef) -> Path | None:
    dest = doc_dir(symbol) / f"{ref.kind}_{ref.period}.pdf"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        get_fetcher().download(ref.url, dest)
    except Exception as e:
        log.warning("download failed %s %s: %s", symbol, ref.url, e)
        return None
    return dest


def pages_fixture(symbol: str, ref: DocRef) -> Path:
    from app.ingest.universe import fixtures_dir

    return fixtures_dir() / "pages" / symbol / f"{ref.kind}_{ref.period}.json"


def load_pages(symbol: str, ref: DocRef) -> list[str]:
    """Page texts for a document: the committed copy (research set, so the deployed API can
    answer questions without re-downloading PDFs), else download and parse."""
    fx = pages_fixture(symbol, ref)
    if fx.exists():
        return json.loads(fx.read_text())
    pdf = ensure_pdf(symbol, ref)
    return page_texts(pdf) if pdf else []


def _page_text(page) -> str:
    """One page's text; a single malformed page (pypdf's token guard on a huge content
    stream, a broken font) costs that page, not the whole annual report."""
    try:
        return _clean(page.extract_text() or "")
    except Exception as e:
        log.warning("page skipped: %s", e)
        return ""


def page_texts(pdf: Path) -> list[str]:
    """Per-page text, cached as JSON next to the PDF (annual reports take seconds to parse)."""
    cache = pdf.with_suffix(".pages.json")
    if cache.exists() and cache.stat().st_mtime >= pdf.stat().st_mtime:
        return json.loads(cache.read_text())
    try:
        pages = [_page_text(p) for p in PdfReader(str(pdf)).pages]
    except Exception as e:
        log.warning("pdf parse failed %s: %s", pdf, e)
        return []
    cache.write_text(json.dumps(pages, ensure_ascii=False))
    return pages


def _clean(t: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def as_paged_text(pages: list[str], only: list[int] | None = None) -> str:
    """'[page N]' markers (1-based) so the model can cite pages we can verify."""
    idx = only if only is not None else range(1, len(pages) + 1)
    return "\n\n".join(f"[page {i}]\n{pages[i - 1]}" for i in idx if 0 < i <= len(pages))


_AR_TOPICS = re.compile(
    r"business overview|our business|segment|revenue mix|product portfolio|customers|"
    r"management discussion|industry structure|opportunities and threats|outlook|strategy|"
    r"capacity|order book|key highlights|at a glance|who we are",
    re.I,
)
_AR_NOISE = re.compile(
    r"notice of|e-voting|proxy|form no\.|independent auditor|statutory auditor|"
    r"corporate governance report|secretarial audit|annexure|remuneration",
    re.I,
)


def annual_report_pages(pages: list[str], k: int = 14, scan: int = 140) -> list[int]:
    """Pick the AR pages that describe the business (front section + MD&A), skipping the
    notice, governance and auditor sections. Returns 1-based page numbers in order."""
    scored = []
    for i, t in enumerate(pages[:scan], 1):
        if len(t) < 400 or _AR_NOISE.search(t[:600]):
            continue
        hits = len(_AR_TOPICS.findall(t))
        if hits:
            scored.append((hits + (1 if i <= 30 else 0), i))
    best = sorted(scored, reverse=True)[:k]
    return sorted(i for _, i in best)
