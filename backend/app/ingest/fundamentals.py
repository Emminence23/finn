"""Fundamentals and document links from screener.in (REQUIREMENTS §5, D4).

Works for any NSE symbol screener covers: consolidated figures first, standalone fallback.
All figures are Rs. crore as published by screener.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from app.http import Fetcher, get_fetcher

log = logging.getLogger(__name__)
BASE = "https://www.screener.in"
SECTIONS = {
    "quarters": "quarters",
    "profit-loss": "annual_pl",
    "balance-sheet": "balance_sheet",
    "cash-flow": "cash_flow",
    "ratios": "ratios",
}


class NotCovered(Exception):
    """Symbol not found on screener (or no financial tables)."""


# ------------------------------------------------------------------ parsing helpers
def parse_number(text: str) -> float | None:
    t = text.strip().replace(",", "").replace("%", "").replace("₹", "").strip()
    if t in ("", "-", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_period(label: str) -> str:
    """'Sep 2026' -> '2026-09'; 'TTM' stays 'TTM'."""
    label = label.strip()
    try:
        return datetime.strptime(label, "%b %Y").strftime("%Y-%m")
    except ValueError:
        return label


def clean_label(text: str) -> str:
    label = re.sub(r"\s+", " ", text.replace("+", " ")).strip()
    if label.startswith("CFO/EBITDA"):
        return "CFO/EBITDA"
    return label


def parse_table(section: Tag) -> dict[str, dict[str, float | None]]:
    """Return {row_label: {period: value}} for a screener data table."""
    table = section.select_one("table.data-table") or section.select_one("table")
    if table is None:
        return {}
    periods = [parse_period(th.get_text(strip=True)) for th in table.select("thead th")][1:]
    out: dict[str, dict[str, float | None]] = {}
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        label = clean_label(cells[0].get_text(" ", strip=True))
        if not label or label == "Raw PDF":
            continue
        values = [parse_number(td.get_text(" ", strip=True)) for td in cells[1:]]
        out[label] = dict(zip(periods, values, strict=False))
    return out


def headline_quarters(quarters: dict[str, dict]) -> list[dict]:
    """Map screener rows to FINN's headline four (FR-CARD-01).

    For lenders (no 'Operating Profit' row) EBITDA is not meaningful and is left None.
    """
    revenue = quarters.get("Sales") or quarters.get("Revenue") or {}
    ebitda = quarters.get("Operating Profit") or {}
    pbt = quarters.get("Profit before tax") or {}
    pat = quarters.get("Net Profit") or {}
    return [
        {
            "period": p,
            "revenue": revenue.get(p),
            "ebitda": ebitda.get(p),
            "pbt": pbt.get(p),
            "pat": pat.get(p),
        }
        for p in revenue
    ]


def parse_documents(soup: BeautifulSoup) -> list[dict]:
    docs: list[dict] = []
    for a in soup.select("section#documents .annual-reports li a"):
        m = re.search(r"(20\d\d)", a.get_text(" ", strip=True))
        docs.append(
            {
                "kind": "annual_report",
                "period": f"FY{m.group(1)}" if m else None,
                "label": a.get_text(" ", strip=True),
                "url": a.get("href"),
            }
        )
    for li in soup.select("section#documents .concalls li"):
        month = li.find("div")
        label = (month.get_text(strip=True) if month else li.get_text(" ", strip=True)[:8]).strip()
        period = parse_period(label)
        for a in li.select("a"):
            kind = {"Transcript": "transcript", "PPT": "ppt", "REC": "recording"}.get(
                a.get_text(strip=True)
            )
            if kind and a.get("href"):
                docs.append({"kind": kind, "period": period, "label": label, "url": a["href"]})
    return docs


def parse_company_page(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    tables = {
        key: parse_table(sec)
        for sec_id, key in SECTIONS.items()
        if (sec := soup.select_one(f"section#{sec_id}")) is not None
    }
    about = soup.select_one(".company-profile .about") or soup.select_one(".about")
    top = {}
    for li in soup.select("#top-ratios li"):
        name = li.select_one(".name")
        value = li.select_one(".value")
        if name and value:
            top[name.get_text(strip=True)] = re.sub(r"\s+", " ", value.get_text(" ", strip=True))
    h1 = soup.select_one("h1")
    return {
        "name": h1.get_text(strip=True) if h1 else None,
        "about": about.get_text(" ", strip=True) if about else None,
        "top_ratios": top,
        "is_financial": "Financing Profit" in tables.get("quarters", {}),
        "tables": tables,
        "quarterly_headline": headline_quarters(tables.get("quarters", {})),
        "documents": parse_documents(soup),
    }


# ------------------------------------------------------------------ fetch
def fetch_fundamentals(symbol: str, fetcher: Fetcher | None = None) -> dict:
    """Consolidated page first; fall back to standalone when consolidated has no quarters."""
    f = fetcher or get_fetcher()
    last_err: Exception | None = None
    for basis, path in (
        ("consolidated", f"/company/{symbol}/consolidated/"),
        ("standalone", f"/company/{symbol}/"),
    ):
        try:
            data = parse_company_page(f.get_text(BASE + path))
        except Exception as e:
            last_err = e
            continue
        if any(q["revenue"] is not None for q in data["quarterly_headline"]):
            data.update(symbol=symbol, basis=basis, source_url=BASE + path)
            return data
    raise NotCovered(f"{symbol}: no financials on screener ({last_err or 'empty tables'})")
