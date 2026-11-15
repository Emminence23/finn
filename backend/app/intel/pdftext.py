"""Filing PDFs → local file + plain text (cached on disk)."""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from pathlib import Path

from pypdf import PdfReader

from app.config import get_settings
from app.http import get_fetcher

log = logging.getLogger(__name__)


def filing_pdf(url: str) -> Path | None:
    """Download a filing attachment once. NSE sometimes serves a .zip holding the PDF."""
    if not url:
        return None
    root = get_settings().cache_dir / "filings"
    dest = root / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".pdf")
    if dest.exists():
        return dest
    try:
        data = get_fetcher().get_bytes(url, use_cache=False)
    except Exception as e:
        log.warning("filing download failed %s: %s", url, e)
        return None
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                pdfs = [n for n in z.namelist() if n.lower().endswith(".pdf")]
                if not pdfs:
                    return None
                data = z.read(pdfs[0])
        except zipfile.BadZipFile:
            return None
    if data[:4] != b"%PDF":
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def pdf_text(path: Path, max_pages: int = 6) -> str:
    try:
        reader = PdfReader(str(path))
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:max_pages])
    except Exception as e:
        log.warning("pdf parse failed %s: %s", path, e)
        return ""
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


_BODY_START = re.compile(r"\b(Sub(ject)?\s*[:.\-]|Dear Sir|Dear Madam|Ref\s*[:.])", re.I)


def filing_excerpt(url: str, limit: int = 2500) -> str:
    """The informative part of a filing letter: skip the exchange address block."""
    path = filing_pdf(url)
    if path is None:
        return ""
    text = pdf_text(path)
    m = _BODY_START.search(text)
    return (text[m.start() :] if m else text)[:limit]
