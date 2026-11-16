"""Brief §5.2: acquire -> dedupe -> parse -> extract -> validate -> evidence -> persist.

    uv run python -m app.brokerage.ingest LT        # read every listed report, write the fixture

Reports listed in fixtures/brokerage/sources.json are fetched from the brokerage's own public
server into the local cache (never committed). The fixture holds what FINN extracted, the
code's checks, a content hash and the link back to the original."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.brokerage.extract import PROMPT_VERSION, extract, normalise_rating, validate
from app.config import get_settings
from app.http import get_fetcher
from app.ingest.universe import fixtures_dir
from app.research.docs import page_texts

log = logging.getLogger(__name__)


def raw_dir() -> Path:
    d = get_settings().cache_dir / "brokerage" / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sources() -> dict:
    return json.loads((fixtures_dir() / "brokerage" / "sources.json").read_text())


def acquire(src: dict) -> Path:
    return get_fetcher().download(src["url"], raw_dir() / src["file"])


def read_report(pdf: Path, src: dict, brokerage: dict, fresh: bool = False) -> dict:
    """One report through extraction and code checks. Pure apart from the model call."""
    data = pdf.read_bytes()
    pages = page_texts(pdf)
    hint = f"Brokerage (from the source list): {brokerage['name']}. Company: {src['symbol']}."
    ex = extract(pages, hint, fresh=fresh)
    checks = validate(ex, pages)
    named = any(
        a.lower() in " ".join(pages).lower() for a in [brokerage["name"], *brokerage["aliases"]]
    )
    if not named:
        checks["needs_review"].append("brokerage name not found in the report")
    return {
        "id": hashlib.sha256(data).hexdigest()[:16],
        "symbol": src["symbol"],
        "brokerage_id": src["brokerage"],
        "source_type": src.get("source_type", "public_url"),
        "source_url": src.get("url"),
        "file": src["file"],
        "content_hash": hashlib.sha256(data).hexdigest(),
        "page_count": len(pages),
        "ingested_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "extraction_version": PROMPT_VERSION,
        "extraction": ex.model_dump(),
        "rating_normalized": normalise_rating(ex.rating_raw),
        "checks": checks,
        "extraction_status": "parsed",
        "review_status": "unreviewed",
    }


def build(symbol: str, only: set[str] | None = None, keep: list[dict] | None = None) -> list[dict]:
    """Read the listed reports. With `only`, re-read just those files (bypassing the model
    cache) and keep the earlier records for the rest."""
    man = sources()
    kept = {r["file"]: r for r in keep or []}
    out, seen = [], set()
    for src in [s for s in man["sources"] if s["symbol"] == symbol]:
        if only and src["file"] not in only and src["file"] in kept:
            rec = kept[src["file"]]
            seen.add(rec["content_hash"])
            out.append(rec)
            continue
        rec = read_report(acquire(src), src, man["brokerages"][src["brokerage"]], fresh=bool(only))
        if rec["content_hash"] in seen:  # the same bytes listed twice
            continue
        seen.add(rec["content_hash"])
        log.info(
            "%s %s %s TP %s: review %s",
            src["brokerage"],
            rec["extraction"]["published_at"],
            rec["extraction"]["rating_raw"],
            rec["extraction"]["target_price"],
            rec["checks"]["needs_review"] or "none",
        )
        out.append(rec)
    out.sort(key=lambda r: (r["extraction"]["published_at"] or "", r["brokerage_id"]))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sym = sys.argv[1].upper()
    path = fixtures_dir() / "brokerage" / f"{sym}.json"
    only = set(sys.argv[2:]) or None
    keep = json.loads(path.read_text())["reports"] if only and path.exists() else None
    recs = build(sym, only, keep)
    path.write_text(json.dumps({"symbol": sym, "reports": recs}, indent=1, ensure_ascii=False))
    print(f"wrote {len(recs)} reports to {path}")
