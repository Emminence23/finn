import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from app.ingest.announcements import normalise, parse_ts
from app.ingest.fundamentals import parse_company_page, parse_number, parse_period
from app.ingest.prices import with_signals

REAL_FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"

SCREENER_HTML = """
<h1>Acme Ltd</h1>
<section id="quarters"><table class="data-table">
 <thead><tr><th></th><th>Jun 2026</th><th>Sep 2026</th></tr></thead>
 <tbody>
  <tr><td class="text"><button>Sales <span>+</span></button></td><td>1,000</td><td>1,100</td></tr>
  <tr><td class="text">Operating Profit</td><td>200</td><td>231</td></tr>
  <tr><td class="text">OPM %</td><td>20%</td><td>21%</td></tr>
  <tr><td class="text">Profit before tax</td><td>150</td><td></td></tr>
  <tr><td class="text"><button>Net Profit +</button></td><td>110</td><td>120</td></tr>
  <tr><td class="text">Raw PDF</td><td><a href="/x">pdf</a></td><td></td></tr>
 </tbody></table></section>
<section id="documents">
 <div class="annual-reports"><ul><li><a href="https://x/ar26.pdf">Financial Year 2026</a></li></ul></div>
 <div class="concalls"><ul><li><div>Oct 2026</div>
   <a href="https://x/t.pdf">Transcript</a><button>AI Summary</button><a href="https://x/p.pdf">PPT</a>
 </li></ul></div>
</section>
"""


def test_number_and_period_parsing():
    assert parse_number("1,23,456") == 123456.0
    assert parse_number("14 %") == 14.0
    assert parse_number("") is None
    assert parse_period("Sep 2026") == "2026-09"
    assert parse_period("TTM") == "TTM"


def test_screener_page_maps_headline_four():
    d = parse_company_page(SCREENER_HTML)
    assert d["name"] == "Acme Ltd"
    assert d["is_financial"] is False
    assert d["quarterly_headline"] == [
        {"period": "2026-06", "revenue": 1000.0, "ebitda": 200.0, "pbt": 150.0, "pat": 110.0},
        {"period": "2026-09", "revenue": 1100.0, "ebitda": 231.0, "pbt": None, "pat": 120.0},
    ]
    assert "Raw PDF" not in d["tables"]["quarters"]
    kinds = {(x["kind"], x["period"]) for x in d["documents"]}
    assert kinds == {("annual_report", "FY2026"), ("transcript", "2026-10"), ("ppt", "2026-10")}


def test_nse_row_normalisation():
    row = {
        "seq_id": 7,
        "symbol": "SRF",
        "an_dt": "05-Oct-2026 18:28:44",
        "desc": " Appointment ",
        "attchmntText": "CHRO appointed",
        "attchmntFile": "https://x/a.pdf",
    }
    a = normalise(row)
    assert (
        a["id"] == "7" and a["ts"] == "2026-10-05T18:28:44" and a["exch_category"] == "Appointment"
    )
    assert parse_ts("13-Nov-2026 18:25:01") == "2026-11-13T18:25:01"


def test_volume_multiple_excludes_today():
    df = pd.DataFrame(
        {
            "symbol": ["A"] * 21,
            "date": pd.date_range("2026-01-01", periods=21).strftime("%Y-%m-%d"),
            "close": [100.0] * 20 + [106.0],
            "volume": [1000] * 20 + [2500],
        }
    )
    last = with_signals(df).iloc[-1]
    assert last["vol_multiple"] == pytest.approx(2.5)
    assert last["pct_change"] == pytest.approx(6.0)


# ------------------------------------------------------------- fixtures-backed tests
@pytest.fixture
def real_fixtures(tmp_path, monkeypatch):
    """Copy the committed fixtures into the isolated data dir and clear caches."""
    from app import config
    from app.ingest import universe
    from app.network import companies

    data = Path(config.get_settings().data_dir)
    shutil.copytree(REAL_FIXTURES, data / "fixtures", dirs_exist_ok=True)
    for fn in (
        universe.load_universe,
        companies._alias_index,
        companies.company_links,
        companies.company_aliases,
    ):
        fn.cache_clear()
    return data / "fixtures"


def test_resolve_symbol(real_fixtures):
    from app.network.companies import resolve_symbol

    assert resolve_symbol("ICICI Bank Limited") == "ICICIBANK"
    assert resolve_symbol("Kaynes Technology India Ltd.") == "KAYNES"
    assert resolve_symbol("Tetra Pak") is None
    assert resolve_symbol("HDFC Securities Private") is None  # must not fuzzy-match HDFCBANK


def test_seed_loads_everything_and_network_is_consistent(real_fixtures):
    from app.db import session
    from app.ingest.seed import main

    main()
    with session() as db:
        count = lambda t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
        assert count("announcements") > 100
        assert count("prices") > 1000
        assert count("financials_quarterly") > 100
        assert db.execute("SELECT COUNT(*) FROM companies WHERE in_portfolio=1").fetchone()[0] == 18
        # every second-degree edge points at a real person
        dangling = db.execute(
            "SELECT other_id FROM relationships WHERE other_id IS NOT NULL "
            "AND other_id NOT IN (SELECT id FROM people)"
        ).fetchall()
        assert dangling == []
        # every filing person comes from a real announcement in the fixtures
        fps = json.loads((real_fixtures / "filing_people.json").read_text())["people"]
        ids = {r[0] for r in db.execute("SELECT id FROM announcements")}
        assert all(p["announcement_id"] in ids for p in fps)
    main()  # idempotent
    with session() as db:
        assert db.execute("SELECT COUNT(*) FROM alert_rules").fetchone()[0] == 3


def test_stale_prices_are_flagged_by_trading_session():
    """Q-3: EOD prices are stale once a finished session is missing; weekends don't count."""
    from datetime import date, datetime

    from app.clock import freshness, latest_session, sessions_between
    from app.db import session

    assert latest_session(datetime(2026, 11, 15, 23)) == date(2026, 11, 13)  # Sunday → Friday
    assert latest_session(datetime(2026, 11, 16, 12)) == date(2026, 11, 13)  # Monday, pre-close
    assert latest_session(datetime(2026, 11, 16, 19)) == date(2026, 11, 16)
    assert sessions_between(date(2026, 11, 12), date(2026, 11, 16)) == 2  # Fri + Mon

    with session() as db:
        db.execute("INSERT INTO prices VALUES ('ABC', '2026-11-13', 0,0,0, 1, 1)")
    assert freshness(datetime(2026, 11, 15, 23))["stale"] is False
    late = freshness(datetime(2026, 11, 17, 19))
    assert late["stale"] is True and late["sessions_behind"] == 2
