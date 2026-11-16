"""Brief §7: an investor uploads a report they may use; it is read in the background and
kept private to them. Stages are recorded so the page can show progress and any problem."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import uuid
from datetime import UTC, datetime

from app.brokerage.extract import PROMPT_VERSION, extract, normalise_rating, validate
from app.brokerage.store import save_brokerages, save_report
from app.config import get_settings
from app.db import session

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 40


def _stage(job: str, stage: str, status: str = "running", **detail) -> None:
    with session() as db:
        db.execute(
            "UPDATE brokerage_jobs SET stage=?, status=?, detail_json=? WHERE id=?",
            (stage, status, json.dumps(detail), job),
        )


def brokerage_id(name: str) -> str:
    """A known brokerage by name or alias, else a new id from the name."""
    with session() as db:
        for r in db.execute("SELECT id, name, aliases_json FROM brokerages"):
            names = [r["name"], *json.loads(r["aliases_json"])]
            if any(n.lower() == name.strip().lower() for n in names):
                return r["id"]
    bid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "unknown"
    save_brokerages({bid: {"name": name.strip()[:80], "aliases": []}})
    return bid


def start(owner: str, symbol: str, brokerage: str, pdf_b64: str, source_url: str | None) -> str:
    try:
        data = base64.b64decode(pdf_b64, validate=True)
    except ValueError as e:
        raise ValueError("the file isn't valid base64") from e
    if len(data) > MAX_BYTES:
        raise ValueError(f"the file is over {MAX_BYTES // 2**20} MB")
    if not data.startswith(b"%PDF"):
        raise ValueError("only PDF reports can be read")
    job = uuid.uuid4().hex[:12]
    with session() as db:
        db.execute(
            "INSERT INTO brokerage_jobs (id, owner_id, symbol, stage, status) VALUES (?,?,?,?,?)",
            (job, owner, symbol, "acquired", "running"),
        )
    threading.Thread(
        target=_run, args=(job, owner, symbol, brokerage, data, source_url), daemon=True
    ).start()
    return job


def _run(job: str, owner: str, symbol: str, brokerage: str, data: bytes, url: str | None) -> None:
    from app.research.docs import page_texts

    try:
        h = hashlib.sha256(data).hexdigest()
        d = get_settings().cache_dir / "brokerage" / "uploads" / owner
        d.mkdir(parents=True, exist_ok=True)
        pdf = d / f"{h[:16]}.pdf"
        pdf.write_bytes(data)
        _stage(job, "parsing")
        pages = page_texts(pdf)[:MAX_PAGES]
        if not any(p.strip() for p in pages):
            _stage(job, "parsing", "failed", why="no text in the PDF (a scan needs OCR)")
            return
        bid = brokerage_id(brokerage)
        _stage(job, "extracting", pages=len(pages))
        ex = extract(
            pages, f"Brokerage (as the investor named it): {brokerage}. Company: {symbol}."
        )
        _stage(job, "validating")
        checks = validate(ex, pages)
        text = " ".join(pages).lower()
        if symbol.lower() not in text and not _names_company(symbol, text):
            checks["needs_review"].append("company not named in the report")
        rec = {
            "id": h[:16],
            "symbol": symbol,
            "brokerage_id": bid,
            "source_type": "user_upload",
            "source_url": url,
            "file": f"uploads/{owner}/{h[:16]}.pdf",
            "content_hash": h,
            "page_count": len(pages),
            "ingested_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "extraction_version": PROMPT_VERSION,
            "extraction": ex.model_dump(),
            "rating_normalized": normalise_rating(ex.rating_raw),
            "checks": checks,
        }
        if not save_report(rec, owner):
            _stage(job, "saved", "duplicate", why="this report is already in your list")
            return
        _stage(
            job,
            "saved",
            "done",
            report_id=f"{h[:16]}-{owner}",
            needs_review=checks["needs_review"],
            confidence=checks["confidence"],
        )
    except Exception as e:  # recorded for the page; never a silent half-save
        _stage(job, "failed", "failed", why=type(e).__name__)


def _names_company(symbol: str, text: str) -> bool:
    with session() as db:
        r = db.execute("SELECT name FROM companies WHERE symbol=?", (symbol,)).fetchone()
    return bool(r) and r["name"].split()[0].lower() in text


def status(job: str, owner: str) -> dict | None:
    with session() as db:
        r = db.execute(
            "SELECT * FROM brokerage_jobs WHERE id=? AND owner_id=?", (job, owner)
        ).fetchone()
    if not r:
        return None
    return {
        "id": r["id"],
        "symbol": r["symbol"],
        "stage": r["stage"],
        "status": r["status"],
        **json.loads(r["detail_json"]),
    }
