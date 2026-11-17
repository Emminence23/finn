"""What the banks and brokers say about a company, as reported in the financial press.

The big investment banks (Goldman Sachs, Morgan Stanley, JPMorgan, Nomura, Jefferies, Citi)
send their research to clients only, so FINN can't read the reports. Their calls are
reported by Moneycontrol, ET, Mint, NDTV Profit, Business Standard and others within hours.
This reads those articles:

  1. search news feeds for the company with each house's name (last 6 months);
  2. keep articles whose headline or snippet names the company and a house;
  3. read the article text (the JSON-LD articleBody most news sites publish, else <p>s);
  4. one free-model call per company pulls out each call: house, rating, target, previous
     target, date, and the verbatim sentence it came from;
  5. code keeps a call only if that sentence is in the article, names the house, and holds
     the target figure as printed. Anything else is dropped, never guessed.

Saved in the Key Value store for 12 hours per company. These are second-hand: the page
labels them "as reported", links the article, and keeps them apart from the report-read
figures (they never enter the report ranges or the track record).
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import parse_qs, quote_plus, urlparse

from pydantic import BaseModel, Field

from app import store
from app.db import session
from app.http import get_fetcher

log = logging.getLogger(__name__)
TTL_S = 12 * 3600
PROMPT_VERSION = "broker-news-v1"
MAX_ARTICLES = 10
MAX_CHARS = 3500  # per article, the paragraphs around the houses' names

# house id -> (display name, patterns that name it in text)
HOUSES: dict[str, tuple[str, list[str]]] = {
    "goldman-sachs": ("Goldman Sachs", [r"Goldman"]),
    "morgan-stanley": ("Morgan Stanley", [r"Morgan Stanley"]),
    "jpmorgan": ("JPMorgan", [r"J\.?\s?P\.?\s?Morgan", r"JPMorgan"]),
    "nomura": ("Nomura", [r"Nomura"]),
    "jefferies": ("Jefferies", [r"Jefferies"]),
    "citi": ("Citi", [r"\bCiti\b", r"Citigroup", r"Citi Research"]),
    "nuvama": ("Nuvama", [r"Nuvama"]),
    "axis-securities": ("Axis Securities", [r"Axis Securities", r"Axis Capital", r"Axis Direct"]),
    "motilal-oswal": ("Motilal Oswal", [r"Motilal", r"\bMOFSL\b"]),
    "clsa": ("CLSA", [r"\bCLSA\b"]),
    "hsbc": ("HSBC", [r"\bHSBC\b"]),
    "bernstein": ("Bernstein", [r"Bernstein"]),
    "ubs": ("UBS", [r"\bUBS\b"]),
    "macquarie": ("Macquarie", [r"Macquarie"]),
    "bofa": ("BofA Securities", [r"\bBofA\b", r"Bank of America", r"BofA Securities"]),
    "kotak": ("Kotak Institutional Equities", [r"Kotak Institutional", r"Kotak Securities"]),
    "icici-securities": (
        "ICICI Securities",
        [r"ICICI Securities", r"ICICIdirect", r"ICICI Direct"],
    ),
    "emkay": ("Emkay", [r"Emkay"]),
    "elara": ("Elara", [r"Elara"]),
    "investec": ("Investec", [r"Investec"]),
    "incred": ("InCred Equities", [r"InCred"]),
    "antique": ("Antique", [r"Antique Stock", r"Antique Broking"]),
    "pl-capital": ("PL Capital", [r"Prabhudas", r"PL Capital"]),
    "sharekhan": ("Sharekhan", [r"Sharekhan"]),
    "hdfc-securities": ("HDFC Securities", [r"HDFC Securities"]),
    "anand-rathi": ("Anand Rathi", [r"Anand Rathi"]),
    "jm-financial": ("JM Financial", [r"JM Financial"]),
    "ambit": ("Ambit Capital", [r"Ambit"]),
    "iifl": ("IIFL Securities", [r"\bIIFL\b"]),
    "centrum": ("Centrum Broking", [r"Centrum"]),
    "yes-securities": ("YES Securities", [r"YES Securities"]),
    "systematix": ("Systematix", [r"Systematix"]),
    "bob-capital": ("BOB Capital Markets", [r"BOB Capital"]),
    "dolat": ("Dolat Capital", [r"Dolat"]),
    "equirus": ("Equirus", [r"Equirus"]),
    "choice": ("Choice Broking", [r"Choice Broking", r"Choice Institutional"]),
    "geojit": ("Geojit", [r"Geojit"]),
    "ventura": ("Ventura Securities", [r"Ventura"]),
    "sbi-securities": ("SBI Securities", [r"SBI Securities", r"SBICAP Securities"]),
    "deutsche": ("Deutsche Bank", [r"Deutsche Bank", r"Deutsche"]),
    "barclays": ("Barclays", [r"Barclays"]),
}
# the houses the investor asked for first, then the rest
QUERY_GROUPS = [
    ["Goldman Sachs", "Morgan Stanley", "JPMorgan"],
    ["Nomura", "Jefferies", "Citi"],
    ["Nuvama", "Axis Securities", "Motilal Oswal"],
    ["CLSA", "HSBC", "Bernstein", "UBS", "Macquarie", "BofA"],
    ["Kotak", "ICICI Securities", "Emkay", "Elara", "InCred", "Antique"],
    ["JM Financial", "Ambit", "IIFL", "Centrum", "Systematix", "Anand Rathi"],
]
DAILY_RUNS = 150  # model calls a day for this feature (one per company per 12 hours)
_runs: dict[str, int] = {}
_RX = {
    h: re.compile("|".join(p), re.I if h not in ("citi", "ubs", "hsbc") else 0)
    for h, (_, p) in HOUSES.items()
}

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


# -- names ---------------------------------------------------------------------------------
_DROP = {"ltd", "limited", "the", "company", "co", "corporation", "of", "india", "(india)"}


def short_name(symbol: str) -> str:
    with session() as db:
        r = db.execute("SELECT name FROM companies WHERE symbol=?", (symbol,)).fetchone()
    name = r["name"] if r else symbol
    words = [w for w in re.split(r"\s+", name) if w.lower().strip(".") not in _DROP]
    return " ".join(words[:2]) or symbol


def search_names(symbol: str) -> list[str]:
    """What the press calls the company: the everyday short name first when there is one
    ("LIC", not "Life Insurance"), then the trimmed company name."""
    from app.research.qa import COMMON_NAMES

    common = COMMON_NAMES.get(symbol, [])
    out = [c.upper() if len(c) <= 4 else c.title() for c in common[:2]]
    sn = short_name(symbol)
    if not common:
        out.append(sn)
    return list(dict.fromkeys(out))


def houses_in(text: str) -> list[str]:
    return [h for h, rx in _RX.items() if rx.search(text)]


# -- search --------------------------------------------------------------------------------
def _rss_items(xml: str) -> list[dict]:
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):

        def g(tag: str, it=it) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", it, re.S)
            return html.unescape(m.group(1)).strip() if m else ""

        link = g("link")
        q = parse_qs(urlparse(link).query)
        if "url" in q:  # Bing wraps the article link
            link = q["url"][0]
        try:
            when = parsedate_to_datetime(g("pubDate")).date().isoformat()
        except (TypeError, ValueError):
            when = None
        title = re.sub(r"<[^>]+>", "", g("title"))
        publisher = None
        if "news.google.com" in link and " - " in title:  # Google ends titles with " - Publisher"
            title, publisher = title.rsplit(" - ", 1)
        out.append(
            {
                "title": title,
                "publisher": publisher,
                "snippet": re.sub(r"<[^>]+>", "", g("description"))[:400],
                "url": link,
                "date": when,
            }
        )
    return out


# a short name that is also the start of another company's name: skip those headlines
NOT_THIS = {"LICI": [r"LIC Housing"], "SBIN": [r"SBI Life", r"SBI Card", r"SBI Cards"]}


def search(name: str, symbol: str, names: list[str] | None = None) -> list[dict]:
    """Candidate articles from news feeds, newest first, de-duplicated by headline."""
    f = get_fetcher()
    found: dict[str, dict] = {}
    cutoff = (datetime.now() - timedelta(days=180)).date().isoformat()
    for group in QUERY_GROUPS:
        ors = " OR ".join(f'"{h}"' for h in group)
        who = " OR ".join(f'"{n}"' for n in (names or [name]))
        q = f"({who}) ({ors}) target"
        for url in (
            f"https://www.bing.com/news/search?q={quote_plus(q)}&format=rss&count=30&setmkt=en-IN",
            f"https://news.google.com/rss/search?q={quote_plus(q + ' when:180d')}"
            "&hl=en-IN&gl=IN&ceid=IN:en",
        ):
            try:
                items = _rss_items(f.get_text(url, use_cache=False))
            except Exception as e:  # noqa: BLE001 - one feed failing leaves the other
                log.info("news feed failed %s: %s", urlparse(url).netloc, e)
                continue
            for it in items:
                text = f"{it['title']} {it['snippet']}"
                pats = [re.escape(n) for n in (names or [name.split()[0]])] + [re.escape(symbol)]
                if not re.search(rf"\b(?:{'|'.join(pats)})\b", text, re.I):
                    continue
                if any(re.search(p, text, re.I) for p in NOT_THIS.get(symbol, [])):
                    continue
                if re.search(r"\$|\.US\b|America|NYSE|Nasdaq", text):  # a namesake abroad
                    continue
                if not houses_in(text) or (it["date"] and it["date"] < cutoff):
                    continue
                key = re.sub(r"\W+", " ", it["title"].lower())[:80]
                # prefer the copy with a direct article link (Bing) over Google's redirect
                if key not in found or "news.google.com" in found[key]["url"]:
                    found[key] = it
    return sorted(found.values(), key=lambda a: a["date"] or "", reverse=True)


# -- reading -------------------------------------------------------------------------------
def article_text(url: str) -> str | None:
    if "news.google.com" in url:
        return None  # an encoded redirect: the headline is all FINN has
    try:
        raw = get_fetcher().get_text(url)
    except Exception as e:  # noqa: BLE001
        log.info("article failed %s: %s", urlparse(url).netloc, e)
        return None
    body = None
    for m in re.finditer(r'"articleBody"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.S):
        try:
            body = json.loads(f'"{m.group(1)}"')
        except ValueError:
            body = m.group(1)
        if len(body) > 300:
            break
    if not body:
        ps = [re.sub(r"<[^>]+>", "", p) for p in re.findall(r"<p[^>]*>(.*?)</p>", raw, re.S)]
        body = "\n".join(p for p in ps if len(p) > 60 and "{" not in p)
    body = re.sub(r"<[^>]+>", " ", html.unescape(body or ""))
    body = re.sub(r"[ \t]+", " ", body).strip()
    return body or None


def focus(text: str) -> str:
    """The paragraphs that name a house, up to MAX_CHARS."""
    paras = [p.strip() for p in re.split(r"\n+|(?<=\.)\s{2,}", text) if p.strip()]
    keep = [p for p in paras if houses_in(p) or re.search(r"target", p, re.I)]
    return "\n".join(keep or paras)[:MAX_CHARS]


# -- extraction ----------------------------------------------------------------------------
class Call(BaseModel):
    article: int = Field(description="the [article N] number it came from")
    house: str = Field(description="the bank or brokerage, as named")
    rating: str | None = Field(None, description="as written: Buy, Overweight, Neutral, Sell…")
    target: float | None = Field(None, description="target price in rupees per share")
    previous_target: float | None = Field(None, description="only if the text gives it")
    action: (
        Literal[
            "initiate", "upgrade", "downgrade", "raise target", "cut target", "maintain", "other"
        ]
        | None
    ) = None
    quote: str = Field(description="the sentence holding the house and its call, verbatim")


class Calls(BaseModel):
    calls: list[Call]


SYSTEM = (
    "You read Indian financial news about one listed company and list each bank's or "
    "brokerage's call on THAT company: rating, target price in rupees, previous target, action. "
    "Use only what the text states. One entry per house per article. Skip calls on other "
    "companies, sector views without a rating or target, and the reporter's own view. "
    "The quote must be copied verbatim from the article and must name the house."
)


def _num(s: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", s)]


def verify(c: Call, text: str) -> str | None:
    """None when the call holds; else why it was dropped."""
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()  # noqa: E731
    if norm(c.quote)[:120] not in norm(text):
        return "quote not in the article"
    hs = houses_in(c.quote)
    if not hs:
        return "quote names no house"
    if c.target is not None and c.target not in _num(c.quote):
        return "target not in the quote"
    if c.previous_target is not None and c.previous_target not in _num(c.quote):
        c.previous_target = None
    if c.rating and c.rating.lower() not in c.quote.lower():
        c.rating = None
    if c.target is None and not c.rating:
        return "neither a rating nor a target"
    return None


def extract(symbol: str, name: str, arts: list[dict]) -> list[dict]:
    from app.llm.router import get_llm

    texts = [a.get("text") or f"{a['title']}. {a['snippet']}" for a in arts]
    prompt = f"Company: {name} (NSE: {symbol})\n\n" + "\n\n".join(
        f"[article {i + 1}] {a['date']} · {a['title']}\n{t}"
        for i, (a, t) in enumerate(zip(arts, texts, strict=True))
    )
    out = get_llm().run(
        "extract_broker_news",
        system=SYSTEM,
        prompt=prompt,
        schema=Calls,
        prompt_version=PROMPT_VERSION,
        max_tokens=4000,
    )
    calls, dropped = [], 0
    for c in out.calls:
        if not 1 <= c.article <= len(arts):
            dropped += 1
            continue
        a, text = arts[c.article - 1], texts[c.article - 1]
        why = verify(c, f"{a['title']}. {text}")
        if why:
            dropped += 1
            log.info("broker news %s dropped (%s): %s", symbol, why, c.quote[:80])
            continue
        hid = houses_in(c.quote)[0]
        for h in houses_in(c.quote):  # the named house, when a sentence names two
            if re.search(_RX[h], c.house):
                hid = h
        calls.append(
            {
                "house_id": hid,
                "house": HOUSES[hid][0],
                "rating": c.rating,
                "target": c.target,
                "previous_target": c.previous_target,
                "action": c.action,
                "quote": c.quote[:400],
                "date": a["date"],
                "headline": a["title"],
                "url": a["url"],
                "source": a.get("publisher") or urlparse(a["url"]).netloc.removeprefix("www."),
                "read": "article" if a.get("text") else "headline",
            }
        )
    log.info("broker news %s: %d calls kept, %d dropped", symbol, len(calls), dropped)
    return calls


def latest_by_house(calls: list[dict]) -> list[dict]:
    """Each house's newest call (one with a target beats one without on the same day)."""
    best: dict[str, dict] = {}
    for c in sorted(calls, key=lambda c: (c["date"] or "", c["target"] is not None)):
        best[c["house_id"]] = c
    return sorted(best.values(), key=lambda c: c["date"] or "", reverse=True)


# -- the summary -------------------------------------------------------------------------
def _close(symbol: str) -> float | None:
    with session() as db:
        r = db.execute(
            "SELECT close FROM prices WHERE symbol=? ORDER BY date DESC LIMIT 1", (symbol,)
        ).fetchone()
    return r[0] if r else None


def _r(x: float | None) -> float | int | None:
    """Whole rupees above ₹100 (so the model writes ₹5,300, not ₹5,300.0)."""
    return None if x is None else int(round(x)) if x >= 100 else round(x, 2)


def facts(symbol: str, latest: list[dict]) -> dict:
    """Everything the summary may say, computed in code."""
    close = _r(_close(symbol))
    tg = sorted(c["target"] for c in latest if c["target"] is not None)
    med = (
        (tg[len(tg) // 2] if len(tg) % 2 else (tg[len(tg) // 2 - 1] + tg[len(tg) // 2]) / 2)
        if tg
        else None
    )
    up = lambda t: round((t / close - 1) * 100, 1) if close and t else None  # noqa: E731
    pos = [
        c
        for c in latest
        if c["rating"]
        and re.search(r"buy|overweight|outperform|add|accumulate|positive", c["rating"], re.I)
    ]
    neg = [
        c
        for c in latest
        if c["rating"]
        and re.search(r"sell|underweight|underperform|reduce|negative", c["rating"], re.I)
    ]
    return {
        "last_close": close,
        "houses": len(latest),
        "with_target": len(tg),
        "low": _r(tg[0]) if tg else None,
        "high": _r(tg[-1]) if tg else None,
        "median": _r(med),
        "median_vs_close_pct": up(med),
        "positive": [c["house"] for c in pos],
        "negative": [c["house"] for c in neg],
        "neutral_or_unrated": [c["house"] for c in latest if c not in pos and c not in neg],
        "calls": [
            {
                "house": c["house"],
                "rating": c["rating"],
                "target": _r(c["target"]),
                "vs_close_pct": up(c["target"]),
                "previous_target": _r(c["previous_target"]),
                "action": c["action"],
                "date": c["date"],
            }
            for c in latest
        ],
    }


def code_summary(f: dict) -> str:
    if not f["houses"]:
        return ""
    s = f"{f['houses']} houses reported in the press"
    if f["positive"] or f["negative"]:
        s += f": {len(f['positive'])} positive, {len(f['negative'])} negative"
    s += "."
    if f["with_target"] > 1 and f["last_close"]:
        s += (
            f" Targets run from ₹{f['low']:,.0f} to ₹{f['high']:,.0f};"
            f" the median ₹{f['median']:,.0f} is {f['median_vs_close_pct']:+.1f}%"
            f" from the last close of ₹{f['last_close']:,.0f}."
        )
    if f["negative"]:
        s += f" Cautious: {', '.join(f['negative'])}."
    return s


class Summary(BaseModel):
    text: str = Field(description="3 or 4 short sentences, plain English")


SUM_SYSTEM = (
    "You write a short summary of what banks and brokers say about one Indian listed company, "
    "for an investor. Use ONLY the facts given (computed by code). Say where they agree, the "
    "target range and median against the last close, who is cautious, and any recent upgrade, "
    "downgrade or target change. Rupee figures as ₹1,234. No advice, no adjectives like "
    "'strong buy', nothing not in the facts. 3-4 sentences."
)


def check_summary(text: str, f: dict) -> str | None:
    """None when every figure and house in the text comes from the facts."""
    allowed = {f["last_close"], f["low"], f["high"], f["median"], f["houses"], f["with_target"]}
    allowed |= {len(f["positive"]), len(f["negative"]), len(f["neutral_or_unrated"])}
    pcts = {f["median_vs_close_pct"]}
    for c in f["calls"]:
        allowed |= {c["target"], c["previous_target"]}
        pcts.add(c["vs_close_pct"])
    allowed = {round(x) for x in allowed if x is not None}
    pcts = {x for x in pcts if x is not None}
    for m in re.finditer(r"(₹|Rs\.?\s?)?([\d,]+(?:\.\d+)?)\s?(%|per ?cent)?", text):
        raw = m.group(2).replace(",", "")
        if not raw or not raw[0].isdigit():
            continue
        v = float(raw)
        if m.group(3):
            if not any(abs(v - abs(p)) <= 0.6 for p in pcts):
                return f"percentage {v} not in the facts"
        elif (m.group(1) or v >= 20) and not any(abs(v - a) <= 1 for a in allowed):
            return f"figure {v:,.0f} not in the facts"
    named = set(houses_in(text))
    known = {h for c in f["calls"] for h in houses_in(c["house"])}
    if named - known:
        return f"names {', '.join(named - known)}, not in the calls"
    return None


def summarise(symbol: str, name: str, latest: list[dict]) -> dict:
    """AI writes it from code's facts; code checks it; code's own sentence if it fails."""
    f = facts(symbol, latest)
    fallback = {"text": code_summary(f), "by": "code"}
    if f["houses"] < 2:
        return fallback
    from app.llm.router import get_llm

    try:
        out = get_llm().run(
            "summarise_broker_views",
            system=SUM_SYSTEM,
            prompt=f"Company: {name} ({symbol})\nFacts:\n{json.dumps(f, ensure_ascii=False)}",
            schema=Summary,
            prompt_version="broker-summary-v1",
            max_tokens=600,
        )
    except Exception as e:  # noqa: BLE001
        log.info("broker summary %s failed: %s", symbol, e)
        return fallback
    why = check_summary(out.text, f)
    if why:
        log.info("broker summary %s rejected (%s): %s", symbol, why, out.text[:120])
        return fallback | {"rejected": why}
    return {"text": out.text.strip(), "by": "ai"}


# -- the job -------------------------------------------------------------------------------
def _run(symbol: str) -> None:
    try:
        name = short_name(symbol)
        _set(symbol, stage="searching")
        arts = search(name, symbol, search_names(symbol))
        _set(symbol, stage="reading", articles=len(arts))
        # articles FINN can open first (full text), then headline-only ones (no fetch)
        direct = [a for a in arts if "news.google.com" not in a["url"]]
        heads = [a for a in arts if "news.google.com" in a["url"]]
        chosen = []
        for a in direct:
            if len(chosen) >= MAX_ARTICLES:
                break
            t = article_text(a["url"])
            a["text"] = focus(t) if t else None
            chosen.append(a)
        for a in heads[:8]:
            a["text"] = None
            chosen.append(a)
        chosen.sort(key=lambda a: a["date"] or "", reverse=True)
        calls = extract(symbol, name, chosen) if chosen else []
        latest = latest_by_house(calls)
        result = {
            "symbol": symbol,
            "searched_for": name,
            "articles": [{k: a[k] for k in ("title", "url", "date")} for a in chosen],
            "calls": calls,
            "latest": latest,
            "summary": summarise(symbol, name, latest),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        store.put(f"brokernews:{symbol}", result, ttl=TTL_S)
        _set(symbol, status="done", stage="done", calls=len(calls))
    except Exception as e:  # noqa: BLE001
        log.exception("broker news %s failed", symbol)
        _set(symbol, status="failed", stage="failed", why=type(e).__name__)


def _set(symbol: str, **kw) -> None:
    with _lock:
        _jobs.setdefault(symbol, {}).update(kw)


def get(symbol: str, start: bool = True) -> dict:
    """The saved result (with its age) and the job's state; starts a job when none is saved."""
    symbol = symbol.upper()
    got = store.get(f"brokernews:{symbol}")
    with _lock:
        job = dict(_jobs.get(symbol, {}))
    if got:
        res = got[0]
        if "summary" not in res and res.get("latest"):  # saved before summaries existed
            res["summary"] = summarise(symbol, res.get("searched_for") or symbol, res["latest"])
            store.put(f"brokernews:{symbol}", res, ttl=TTL_S)
        return res | {"saved_at": got[1], "job": job or {"status": "done"}}
    if start and job.get("status") != "running":
        refresh(symbol)
        with _lock:
            job = dict(_jobs[symbol])
    return {"symbol": symbol, "calls": [], "latest": [], "job": job or {"status": "idle"}}


def refresh(symbol: str) -> dict:
    symbol = symbol.upper()
    today = datetime.now().date().isoformat()
    with _lock:
        if _jobs.get(symbol, {}).get("status") == "running":
            return dict(_jobs[symbol])
        if _runs.get(today, 0) >= DAILY_RUNS:
            _jobs[symbol] = {
                "status": "failed",
                "stage": "failed",
                "why": "today's reads are used up",
            }
            return dict(_jobs[symbol])
        _runs[today] = _runs.get(today, 0) + 1
        _jobs[symbol] = {"status": "running", "stage": "searching"}
    threading.Thread(target=_run, args=(symbol,), daemon=True).start()
    return {"status": "running", "stage": "searching"}
