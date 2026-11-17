"""Find brokerage reports for any listed company, read them, keep them for a month.

Two ways in, both public copies only (no login, no paywall):

* Discover: brokerages that post their research on their own open server use stable file
  names, so FINN tries the names a report would have for this company's last few results:
    ICICI Securities  mailcontent.icicidirect.com/mailcontent/idirect_<name>_q<N>fy<YY>.pdf
    PL Capital        plindia.com/ResReport/<SYMBOL>-<d>-<m>-<yy>-PL.pdf  (days after results)
  Each guess is one small ranged request; only real PDFs are downloaded.
* Add by link: the investor pastes the link to any brokerage PDF that is publicly posted.

Each report found goes through the same reader as the curated set (one model call, then the
code's checks against the page text). Results are saved in the Key Value store under
`brokerage:found:<SYMBOL>` and loaded back at startup, so a redeploy doesn't lose them.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from app import store
from app.brokerage.ingest import raw_dir, read_report
from app.brokerage.store import save_brokerages, save_report
from app.db import session
from app.http import get_fetcher

log = logging.getLogger(__name__)
KEEP_S = 30 * 24 * 3600
MAX_READS = 4  # newest reports read per search: one model call each
_PREFIX = "brokerage:found:"

BROKERAGES = {
    "icici-securities": {
        "name": "ICICI Securities (Retail Research)",
        "aliases": ["ICICI Securities", "ICICI Direct", "ICICIdirect"],
        "website": "https://www.icicidirect.com",
    },
    "pl-capital": {
        "name": "PL Capital (Prabhudas Lilladher)",
        "aliases": ["Prabhudas Lilladher", "PL Capital", "PL Research"],
        "website": "https://www.plindia.com",
    },
    "motilal-oswal": {
        "name": "Motilal Oswal",
        "aliases": ["Motilal Oswal Financial Services", "MOFSL", "MOSL"],
        "website": "https://www.motilaloswal.com",
    },
    "sharekhan": {
        "name": "Sharekhan",
        "aliases": ["Sharekhan by BNP Paribas", "Mirae Asset Sharekhan"],
        "website": "https://www.sharekhan.com",
    },
    "kotak-securities": {
        "name": "Kotak Securities",
        "aliases": ["Kotak Institutional Equities", "Kotak Securities"],
        "website": "https://www.kotaksecurities.com",
    },
    "hdfc-securities": {
        "name": "HDFC Securities",
        "aliases": ["HDFC Securities", "HSL"],
        "website": "https://www.hdfcsec.com",
    },
}
HOSTS = {
    "icicidirect.com": "icici-securities",
    "plindia.com": "pl-capital",
    "motilaloswal.com": "motilal-oswal",
    "sharekhan.com": "sharekhan",
    "kotaksecurities.com": "kotak-securities",
    "hdfcsec.com": "hdfc-securities",
}

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


# -- the guesses --------------------------------------------------------------------------
_DROP = {"ltd", "limited", "the", "company", "co", "corporation", "india", "industries", "of"}


def name_variants(symbol: str, company: str | None) -> list[str]:
    """ICICI's file names use a short company name: titan, asianpaints, lt."""
    out = [symbol.lower().replace("&", "").replace("-", "")]
    words = [w for w in re.split(r"[^a-z0-9]+", (company or "").lower()) if w]
    core = [w for w in words if w not in _DROP]
    if core:
        out += [core[0], "".join(core[:2]), "".join(core)]
    seen, uniq = set(), []
    for v in out:
        if v and v not in seen and len(v) <= 30:
            seen.add(v)
            uniq.append(v)
    return uniq[:4]


def last_quarters(today: date, n: int = 4) -> list[str]:
    """Indian fiscal quarters whose results are out: 'q2fy27' for Jul-Sep 2026. A quarter
    counts once three weeks have passed since it ended."""
    d = today - timedelta(days=21)
    y, m = d.year, d.month - (d.month % 3)  # the last quarter-end month (3, 6, 9, 12)
    if m == 0:
        y, m = y - 1, 12
    out = []
    for _ in range(n):
        q = {6: 1, 9: 2, 12: 3, 3: 4}[m]
        fy = y + 1 if m != 3 else y
        out.append(f"q{q}fy{fy % 100:02d}")
        y, m = (y - 1, 12) if m == 3 else (y, m - 3)
    return out


def results_dates(symbol: str, n: int = 2) -> list[date]:
    with session() as db:
        rows = db.execute(
            "SELECT DISTINCT substr(ts,1,10) FROM announcements WHERE symbol=? AND "
            "(category='results' OR subject LIKE '%financial result%') ORDER BY 1 DESC",
            (symbol,),
        ).fetchall()
    days = []
    for (d,) in rows:
        dd = date.fromisoformat(d)
        if not days or (days[-1] - dd).days > 30:
            days.append(dd)
    return days[:n]


def candidates(symbol: str, company: str | None, today: date | None = None) -> list[dict]:
    today = today or date.today()
    out = []
    for q in last_quarters(today):
        for name in name_variants(symbol, company):
            out.append(
                {
                    "brokerage": "icici-securities",
                    "url": f"https://mailcontent.icicidirect.com/mailcontent/idirect_{name}_{q}.pdf",
                    "file": f"idirect_{name}_{q}.pdf",
                    "group": f"icici-{q}",
                }
            )
    for rd in results_dates(symbol):
        for k in range(0, 3):
            d = rd + timedelta(days=k)
            tag = f"{d.day}-{d.month}-{d.year % 100}"
            out.append(
                {
                    "brokerage": "pl-capital",
                    "url": f"https://www.plindia.com/ResReport/{symbol.upper()}-{tag}-PL.pdf",
                    "file": f"pl_{symbol.upper()}-{tag}.pdf",
                    "group": f"pl-{rd.isoformat()}",
                }
            )
    return out


def is_pdf(url: str) -> bool:
    f = get_fetcher()
    host = urlparse(url).netloc
    f.limiter.wait(host)
    try:
        with f.client.stream("GET", url, headers={"Range": "bytes=0-1023"}) as r:
            if r.status_code not in (200, 206):
                return False
            head = next(r.iter_bytes(), b"")
            return head.startswith(b"%PDF") or "pdf" in r.headers.get("content-type", "")
    except Exception:  # noqa: BLE001 - a guess that fails is just a miss
        return False


# -- reading and keeping ------------------------------------------------------------------
def _company(symbol: str) -> str | None:
    with session() as db:
        r = db.execute("SELECT name FROM companies WHERE symbol=?", (symbol,)).fetchone()
    return r["name"] if r else None


def _known(symbol: str) -> set[str]:
    with session() as db:
        return {
            r[0]
            for r in db.execute(
                "SELECT source_url FROM brokerage_reports "
                "WHERE symbol=? AND source_url IS NOT NULL",
                (symbol,),
            )
        }


def _read_and_keep(symbol: str, src: dict) -> dict | None:
    pdf = get_fetcher().download(src["url"], raw_dir() / src["file"])
    rec = read_report(pdf, src | {"symbol": symbol}, BROKERAGES[src["brokerage"]])
    rec["source_type"] = "public_url"
    rec["brokerage_name"] = BROKERAGES[src["brokerage"]]["name"]
    if not save_report(rec):
        return None
    saved = store.get(_PREFIX + symbol)
    recs = [r for r in (saved[0] if saved else []) if r["content_hash"] != rec["content_hash"]]
    store.put(_PREFIX + symbol, [*recs, rec], ttl=KEEP_S)
    return rec


def _brokerage_for(url: str, named: str | None) -> str:
    host = urlparse(url).netloc.lower()
    for h, bid in HOSTS.items():
        if host.endswith(h):
            return bid
    if named:
        for bid, b in BROKERAGES.items():
            if any(a.lower() == named.strip().lower() for a in [b["name"], *b["aliases"]]):
                return bid
        bid = re.sub(r"[^a-z0-9]+", "-", named.lower()).strip("-")[:40]
        BROKERAGES.setdefault(bid, {"name": named.strip()[:80], "aliases": []})
        save_brokerages({bid: BROKERAGES[bid]})
        return bid
    raise ValueError("couldn't tell which brokerage this is: add its name")


def _job(symbol: str, **kw) -> None:
    with _lock:
        _jobs.setdefault(symbol, {}).update(kw)


def status(symbol: str) -> dict:
    with _lock:
        return dict(_jobs.get(symbol, {"status": "idle"}))


def _search(symbol: str) -> None:
    try:
        company = _company(symbol)
        known = _known(symbol)
        cands = candidates(symbol, company)
        _job(symbol, stage="looking", tried=0, total=len(cands), found=[])
        found, groups = [], set()
        for c in cands:
            if c["group"] in groups:  # one hit per quarter / results date is enough
                continue
            _job(symbol, tried=status(symbol).get("tried", 0) + 1)
            if c["url"] in known or is_pdf(c["url"]):
                groups.add(c["group"])
                if c["url"] not in known:
                    found.append(c)
        found = found[:MAX_READS]
        _job(symbol, stage="reading", found=[f["url"] for f in found], read=0)
        added = 0
        for i, src in enumerate(found):
            try:
                added += bool(_read_and_keep(symbol, src))
            except Exception as e:  # noqa: BLE001 - one bad PDF mustn't stop the rest
                log.warning("reading %s failed: %s", src["url"], e)
            _job(symbol, read=i + 1)
        _job(symbol, stage="done", status="done", added=added)
    except Exception as e:  # noqa: BLE001
        log.exception("broker search %s failed", symbol)
        _job(symbol, stage="failed", status="failed", why=type(e).__name__)


def search(symbol: str) -> dict:
    """Start looking for this company's public brokerage reports in the background."""
    symbol = symbol.upper()
    if status(symbol).get("status") == "running":
        return status(symbol)
    with _lock:
        _jobs[symbol] = {
            "status": "running",
            "stage": "looking",
            "started": datetime.now().isoformat(timespec="seconds"),
        }
    threading.Thread(target=_search, args=(symbol,), daemon=True).start()
    return status(symbol)


def add_link(symbol: str, url: str, brokerage: str | None) -> dict:
    """Read one public PDF link the investor pasted."""
    symbol = symbol.upper()
    if not url.startswith(("https://", "http://")):
        raise ValueError("paste the full link, starting with https://")
    bid = _brokerage_for(url, brokerage)
    if url in _known(symbol):
        return {"status": "done", "stage": "done", "added": 0, "why": "already in the list"}
    if not is_pdf(url):
        raise ValueError("that link doesn't open a PDF without a login")
    name = hashlib.sha256(url.encode()).hexdigest()[:12]
    src = {"brokerage": bid, "url": url, "file": f"link_{name}.pdf"}
    with _lock:
        _jobs[symbol] = {"status": "running", "stage": "reading", "found": [url], "read": 0}

    def run() -> None:
        try:
            ok = _read_and_keep(symbol, src)
            _job(symbol, stage="done", status="done", read=1, added=int(bool(ok)))
        except Exception as e:  # noqa: BLE001
            log.warning("reading %s failed: %s", url, e)
            _job(symbol, stage="failed", status="failed", why=type(e).__name__)

    threading.Thread(target=run, daemon=True).start()
    return status(symbol)


def restore() -> int:
    """At startup: put back every report found earlier (they live in Key Value)."""
    save_brokerages(BROKERAGES)
    n = 0
    for key in store.keys(_PREFIX):
        got = store.get(key)
        for rec in got[0] if got else []:
            if rec["brokerage_id"] not in BROKERAGES:
                name = rec.get("brokerage_name") or rec["brokerage_id"]
                save_brokerages({rec["brokerage_id"]: {"name": name, "aliases": []}})
            n += save_report(rec)
    if n:
        log.info("restored %d brokerage reports found earlier", n)
    return n
