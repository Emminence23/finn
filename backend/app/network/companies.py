"""Resolve free-text employer names ("ICICI Bank Limited", "Kaynes Semicon") to NSE symbols."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from rapidfuzz import fuzz, process

from app.ingest.universe import fixtures_dir

_SUFFIXES = re.compile(r"\b(limited|ltd|pvt|private|inc|ag|ab|plc|india|\(india\))\b\.?", re.I)


def normalise_company(name: str) -> str:
    n = _SUFFIXES.sub(" ", name.lower())
    return re.sub(r"[^a-z0-9&]+", " ", n).strip()


@lru_cache
def _alias_index() -> dict[str, str]:
    meta = json.loads((fixtures_dir() / "companies_meta.json").read_text())["companies"]
    index: dict[str, str] = {}
    for symbol, m in meta.items():
        for alias in [symbol, *m["aliases"]]:
            index[normalise_company(alias)] = symbol
    return index


def resolve_symbol(name: str | None, min_score: int = 92) -> str | None:
    """Exact alias match first, then a strict fuzzy match. Returns None when unsure."""
    if not name:
        return None
    key = normalise_company(name)
    index = _alias_index()
    if key in index:
        return index[key]
    match = process.extractOne(key, index.keys(), scorer=fuzz.token_sort_ratio)
    return index[match[0]] if match and match[1] >= min_score else None


@lru_cache
def company_links() -> dict[str, dict[str, list[str]]]:
    meta = json.loads((fixtures_dir() / "companies_meta.json").read_text())["companies"]
    return {
        s: {k: m.get(k, []) for k in ("competitor", "supplier", "customer")}
        for s, m in meta.items()
    }


@lru_cache
def company_aliases() -> dict[str, list[str]]:
    meta = json.loads((fixtures_dir() / "companies_meta.json").read_text())["companies"]
    return {s: m["aliases"] for s, m in meta.items()}
