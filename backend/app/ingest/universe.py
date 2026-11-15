"""The demo universe: portfolio (with weights) and the ad-hoc research set."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import get_settings


def fixtures_dir() -> Path:
    d = get_settings().data_dir / "fixtures"
    d.mkdir(parents=True, exist_ok=True)
    return d


@lru_cache
def load_universe() -> dict:
    return json.loads((fixtures_dir() / "universe.json").read_text())


def portfolio_symbols() -> list[str]:
    return [p["symbol"] for p in load_universe()["portfolio"]]


def research_symbols() -> list[str]:
    return list(load_universe()["research_set"])


def all_symbols() -> list[str]:
    return list(dict.fromkeys(portfolio_symbols() + research_symbols()))
