"""What brokerages expect, how that changed, where they disagree, and how far their record
can be checked (brief §3). Assembled in code from stored observations; only figures whose
evidence code verified enter any statistic."""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median

from app.brokerage import calc
from app.brokerage.store import observations as _stored
from app.db import session

STALE_DAYS = 120  # a brokerage whose latest report is older is listed, not counted in ranges
WINDOW_DAYS = 365  # default report window for the overview


def observations(symbol: str, owner: str | None = None) -> list[dict]:
    """Stored observations, each with code's basis check: a report whose own reported-year
    rows don't match the company's reported consolidated figures is on another basis, and
    its estimates are shown but never compared with others or scored."""
    reported = _actuals(symbol.upper())
    out = _stored(symbol, owner)
    for o in out:
        chk = calc.basis_check(o["estimates"], reported)
        other = any(not c["same_basis"] for c in chk.values())
        o["basis"] = {
            "checked": chk,
            "status": "other basis" if other else "consolidated" if chk else "unchecked",
        }
        for e in o["estimates"]:
            e["other_basis"] = other
    return out


def _verified(o: dict, field: str) -> bool:
    return (o["evidence"].get(field) or {}).get("status") == "verified"


def usable_target(o: dict) -> bool:
    return (
        bool(o["target_price"]) and _verified(o, "target_price") and o["target_currency"] == "INR"
    )


def _prices(symbol: str) -> list[tuple[str, float]]:
    with session() as db:
        return [
            (r["date"], r["close"])
            for r in db.execute(
                "SELECT date, close FROM prices WHERE symbol=? ORDER BY date", (symbol,)
            )
        ]


def _as_of(symbol: str) -> str:
    p = _prices(symbol)
    return p[-1][0] if p else date.today().isoformat()


def _clean(o: dict) -> dict:
    """The observation as the API shows it, with code's checks and computed returns."""
    imp = calc.implied_return(o["target_price"], o["reference_price"]) if usable_target(o) else None
    return {
        "id": o["id"],
        "report_id": o["report_id"],
        "brokerage_id": o["brokerage_id"],
        "brokerage": o["brokerage"],
        "analyst": o["analyst_name"],
        "published_at": o["published_at"],
        "title": o["title"],
        "report_type": o["report_type"],
        "rating": o["rating"],
        "rating_raw": o["rating_raw"],
        "target_price": o["target_price"],
        "target_currency": o["target_currency"],
        "target_verified": usable_target(o),
        "reference_price": o["reference_price"],
        "reference_price_date": o["reference_price_date"],
        "implied_return_pct": imp,
        "horizon": o["horizon_raw"] or "not stated",
        "horizon_basis": o["horizon_basis"],
        "horizon_bucket": calc.horizon_bucket(o["horizon_value"], o["horizon_unit"]),
        "previous_target": o["previous_target"],
        "previous_rating": o["previous_rating"],
        "thesis": o["thesis_summary"],
        "catalysts": o["catalysts"],
        "risks": o["risks"],
        "valuation_method": o["valuation_method"],
        "valuation_assumptions": o["valuation_assumptions"],
        "estimates": [
            {
                k: e[k]
                for k in (
                    "metric",
                    "metric_raw",
                    "fiscal_period",
                    "fiscal_period_raw",
                    "value",
                    "unit",
                    "value_cr",
                    "is_actual",
                    "definition",
                    "scenario",
                    "source_page",
                    "source_excerpt",
                    "verified",
                    "other_basis",
                )
            }
            for e in o["estimates"]
        ],
        "basis": o["basis"],
        "evidence": o["evidence"],
        "source": {
            "type": o["source_type"],
            "url": o["source_url"],
            "pages": o["page_count"],
            "yours": o["owner_id"] is not None,
            "extraction": o["extraction_version"],
            "ingested_at": o["ingested_at"],
        },
        "confidence": o["extraction_confidence"],
        "review_status": o["review_status"],
        "needs_review": o["checks"].get("needs_review", []),
    }


def _calc_view(o: dict) -> dict:
    """The shape calc.revision expects: verified figures only."""
    return {
        "brokerage_id": o["brokerage_id"],
        "report_id": o["report_id"],
        "published_at": o["published_at"],
        "rating": o["rating"],
        "rating_raw": o["rating_raw"],
        "target_price": o["target_price"] if usable_target(o) else None,
        "estimates": [e for e in o["estimates"] if e["verified"]],
    }


def overview(
    symbol: str,
    owner: str | None = None,
    start: str | None = None,
    end: str | None = None,
    horizon: str | None = None,
) -> dict:
    symbol = symbol.upper()
    obs = observations(symbol, owner)
    as_of = end or _as_of(symbol)
    start = start or (date.fromisoformat(as_of) - timedelta(days=WINDOW_DAYS)).isoformat()
    in_window = [o for o in obs if o["published_at"] and start <= o["published_at"] <= as_of]
    every = calc.latest_per_brokerage(obs, start, as_of)
    fresh_from = (date.fromisoformat(as_of) - timedelta(days=STALE_DAYS)).isoformat()
    latest = [o for o in every if o["published_at"] >= fresh_from]
    stale = [o for o in every if o["published_at"] < fresh_from]
    prices = _prices(symbol)
    last = prices[-1] if prices else None

    dist = {"positive": 0, "neutral": 0, "negative": 0, "not mapped": 0}
    raw: dict[str, int] = {}
    for o in latest:
        dist[o["rating"] or "not mapped"] += 1
        raw[o["rating_raw"] or "not stated"] = raw.get(o["rating_raw"] or "not stated", 0) + 1

    groups = []
    buckets: dict[str, list[dict]] = {}
    for o in latest:
        if usable_target(o):
            buckets.setdefault(
                calc.horizon_bucket(o["horizon_value"], o["horizon_unit"]), []
            ).append(o)
    for b, xs in sorted(buckets.items(), key=lambda kv: (kv[0] == "not stated", kv[0])):
        if horizon and b != horizon:
            continue
        st = calc.stats([o["target_price"] for o in xs])
        groups.append(
            {
                "horizon": b,
                "brokerages": len(xs),
                "targets": st,
                "median_implied_return_pct": median(
                    [
                        r
                        for r in (
                            calc.implied_return(o["target_price"], o["reference_price"]) for o in xs
                        )
                        if r is not None
                    ]
                )
                if any(o["reference_price"] for o in xs)
                else None,
                "median_vs_last_close_pct": calc.implied_return(st["median"], last[1])
                if last
                else None,
                "comparable": b != "not stated",
                "consensus_label": b != "not stated" and len(xs) >= 3,
                "who": [o["brokerage"] for o in xs],
            }
        )

    warnings = ["In the reports currently available to FINN, not the whole market."]
    newest = max((o["published_at"] for o in in_window), default=None)
    age = (date.fromisoformat(as_of) - date.fromisoformat(newest)).days if newest else None
    if age is not None and age > STALE_DAYS:
        warnings.append(f"The newest report is {age} days old.")
    for o in stale:
        warnings.append(
            f"{o['brokerage']}'s latest report is from {o['published_at']}, over {STALE_DAYS} "
            "days old: listed, but not in the ranges."
        )
    if any(g["horizon"] == "not stated" for g in groups):
        warnings.append(
            "Some reports state no horizon; their targets are kept apart, not averaged in."
        )
    if any(o["horizon_basis"] == "rating definition" for o in latest):
        warnings.append(
            "Some horizons come from the brokerage's rating definitions, "
            "not from beside the target."
        )
    unver = [o for o in latest if o["target_price"] and not usable_target(o)]
    if unver:
        warnings.append(
            f"{len(unver)} target(s) left out: code could not find them on the cited page."
        )
    for g in groups:
        if g["comparable"] and g["brokerages"] < 3:
            warnings.append(
                f"Only {g['brokerages']} brokerage(s) with a {g['horizon']} target: "
                "a range, not a consensus."
            )
    return {
        "symbol": symbol,
        "as_of": as_of,
        "window": {"from": start, "to": as_of},
        "reports": len(in_window),
        "brokerages": len({o["brokerage_id"] for o in in_window}),
        "latest_report": newest,
        "latest_age_days": age,
        "newest_is_stale": age is not None and age > STALE_DAYS,
        "last_close": {"date": last[0], "price": last[1]} if last else None,
        "ratings": dist,
        "ratings_raw": raw,
        "targets": groups,
        "latest": [_clean(o) for o in latest],
        "stale": [_clean(o) for o in stale],
        "warnings": warnings,
        "method": calc.METHOD,
    }


def reports(
    symbol: str,
    owner: str | None = None,
    brokerage_id: str | None = None,
    rating: str | None = None,
    start: str | None = None,
    end: str | None = None,
    horizon: str | None = None,
) -> list[dict]:
    out = []
    for o in observations(symbol, owner):
        c = _clean(o)
        if brokerage_id and o["brokerage_id"] != brokerage_id:
            continue
        if rating and rating not in (o["rating"], (o["rating_raw"] or "").lower()):
            continue
        if start and (o["published_at"] or "") < start or end and (o["published_at"] or "") > end:
            continue
        if horizon and c["horizon_bucket"] != horizon:
            continue
        out.append(c)
    return sorted(out, key=lambda c: c["published_at"] or "", reverse=True)


def revisions(
    symbol: str,
    owner: str | None = None,
    lookback_days: int | None = None,
    metric: str | None = None,
    brokerage_id: str | None = None,
) -> dict:
    symbol = symbol.upper()
    obs = [_calc_view(o) for o in observations(symbol, owner)]
    names = {o["brokerage_id"]: o["brokerage"] for o in observations(symbol, owner)}
    as_of = _as_of(symbol)
    revs = [calc.revision(a, b) for a, b in calc.revision_pairs(obs, as_of)]
    for r in revs:
        r["brokerage"] = names[r["brokerage_id"]]
    events = [
        r
        for r in revs
        if (not brokerage_id or r["brokerage_id"] == brokerage_id)
        and (
            not lookback_days
            or r["to"] > (date.fromisoformat(as_of) - timedelta(days=lookback_days)).isoformat()
        )
    ]
    if metric:
        for r in events:
            r["estimates"] = [e for e in r["estimates"] if e["metric"].lower() == metric.lower()]
    return {
        "symbol": symbol,
        "as_of": as_of,
        "events": sorted(events, key=lambda r: r["to"], reverse=True),
        "momentum": [calc.momentum(revs, as_of, d) for d in (30, 90, 180)],
        "note": "Each brokerage's report against its own previous one. Estimates compare only "
        "the same metric, fiscal year, unit and definition.",
    }


def divergence(symbol: str, owner: str | None = None) -> dict:
    symbol = symbol.upper()
    obs = observations(symbol, owner)
    as_of = _as_of(symbol)
    start = (date.fromisoformat(as_of) - timedelta(days=STALE_DAYS)).isoformat()
    latest = calc.latest_per_brokerage(obs, start, as_of)
    tgt = [(o["brokerage_id"], o["target_price"]) for o in latest if usable_target(o)]
    names = {o["brokerage_id"]: o["brokerage"] for o in latest}

    est: dict[tuple, list[tuple[str, float, dict]]] = {}
    for o in latest:
        for e in o["estimates"]:
            k = calc.comparable_key(e)
            if k and e["verified"]:
                est.setdefault(k, []).append((o["brokerage_id"], calc.comparable_value(e), e))
    estimates = []
    for k, xs in sorted(est.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if len({b for b, _, _ in xs}) < 2:
            continue
        st = calc.stats([v for _, v, _ in xs])
        estimates.append(
            {
                "metric": k[0],
                "fiscal_period": k[1],
                "unit": k[2],
                "definition": k[3] or None,
                "stats": st,
                "spread_pct": calc.pct_change(st["max"], st["min"]),
                "values": [
                    {"brokerage": names[b], "value": v, "page": e["source_page"]} for b, v, e in xs
                ],
                "outliers": [
                    dict(x, brokerage=names[x["brokerage_id"]])
                    for x in calc.outliers([(b, v) for b, v, _ in xs])
                ],
            }
        )
    estimates.sort(key=lambda r: -(r["spread_pct"] or 0))

    revs = revisions(symbol, owner)["events"]
    latest_rev = {}
    for r in sorted(revs, key=lambda r: r["to"]):
        latest_rev[r["brokerage_id"]] = r
    tension = []
    for o in latest:
        r = latest_rev.get(o["brokerage_id"])
        if not r or r["to"] != o["published_at"] or o["rating"] != "positive":
            continue
        cuts = [e for e in r["estimates"] if e["metric"] == "EPS" and e["change_pct"] < -1]
        if cuts:
            tension.append(
                {
                    "brokerage": o["brokerage"],
                    "rating": o["rating_raw"],
                    "eps_cuts": [
                        {"fiscal_period": e["fiscal_period"], "change_pct": e["change_pct"]}
                        for e in cuts
                    ],
                }
            )
    bucket = {
        o["brokerage_id"]: calc.horizon_bucket(o["horizon_value"], o["horizon_unit"])
        for o in latest
    }
    by_h: dict[str, list[tuple[str, float]]] = {}
    for b, v in tgt:
        by_h.setdefault(bucket[b], []).append((b, v))
    groups = []
    for h, xs in sorted(by_h.items(), key=lambda kv: (kv[0] == "not stated", kv[0])):
        st = calc.stats([v for _, v in xs])
        groups.append(
            {
                "horizon": h,
                "comparable": h != "not stated",
                "stats": st if h != "not stated" else None,  # unlike horizons are never pooled
                "spread_pct": calc.pct_change(st["max"], st["min"]) if h != "not stated" else None,
                "values": [{"brokerage": names[b], "target": v} for b, v in xs],
                "outliers": [dict(x, brokerage=names[x["brokerage_id"]]) for x in calc.outliers(xs)]
                if h != "not stated"
                else [],
            }
        )
    caveats = []
    if len(tgt) < 5:
        caveats.append(f"{len(tgt)} brokerages: dispersion from this few is indicative only.")
    if "not stated" in by_h:
        caveats.append("Targets without a stated horizon are listed, not pooled with the others.")
    return {
        "symbol": symbol,
        "as_of": as_of,
        "brokerages": len(latest),
        "targets": groups,
        "estimates": estimates,
        "bullish_with_cuts": tension,
        "assumptions": [
            {
                "brokerage": o["brokerage"],
                "published_at": o["published_at"],
                "method": o["valuation_method"],
                "items": o["valuation_assumptions"],
            }
            for o in latest
        ],
        "caveats": caveats,
        "method": calc.METHOD,
    }


def _actuals(symbol: str) -> dict[str, dict]:
    """Reported full-year figures (screener's standardised accounts), by FY label."""
    import json

    out = {}
    with session() as db:
        for r in db.execute(
            "SELECT period, data_json FROM financials_annual WHERE symbol=? AND period LIKE '%-03'",
            (symbol,),
        ):
            pl = json.loads(r["data_json"]).get("annual_pl") or {}
            out[f"FY{r['period'][2:4]}"] = {"EPS": pl.get("EPS in Rs"), "revenue": pl.get("Sales")}
    return out


def track_record(
    symbol: str | None = None, brokerage_id: str | None = None, owner: str | None = None
) -> dict:
    """Brief §6.5. Every evaluation uses only prices on or after publication and figures
    reported after the forecast; nothing is ranked below calc.MIN_SAMPLE observations."""
    symbols = [symbol.upper()] if symbol else _covered()
    targets, forecasts = [], []
    for s in symbols:
        prices, as_of, actual = _prices(s), _as_of(s), _actuals(s)
        for o in observations(s, owner):
            if brokerage_id and o["brokerage_id"] != brokerage_id:
                continue
            if usable_target(o):
                ev = calc.evaluate_target(o, prices, as_of)
                if ev:
                    targets.append(
                        {
                            "symbol": s,
                            "brokerage": o["brokerage"],
                            "published_at": o["published_at"],
                            "target": o["target_price"],
                            **ev,
                        }
                    )
            for e in o["estimates"]:
                fy = e["fiscal_period"]
                if (
                    e["is_actual"]
                    or not e["verified"]
                    or e["other_basis"]
                    or not fy
                    or fy not in actual
                ):
                    continue
                if e["metric"] not in ("EPS", "revenue"):
                    continue
                fy_end = f"20{fy[2:4]}-03-31"
                if o["published_at"] >= fy_end:
                    continue  # forecast made after the year ended: not a forecast
                got = actual[fy][e["metric"]]
                pred = e["value"] if e["metric"] == "EPS" else e["value_cr"]
                if got is None or pred is None:
                    continue
                err = (
                    calc.eps_error(pred, got)
                    if e["metric"] == "EPS"
                    else abs(pred - got) / got * 100
                )
                if err is None:
                    continue
                forecasts.append(
                    {
                        "symbol": s,
                        "brokerage": o["brokerage"],
                        "published_at": o["published_at"],
                        "metric": e["metric"],
                        "fiscal_period": fy,
                        "forecast": pred,
                        "actual": got,
                        "abs_error_pct": err,
                        "signed_error_pct": (pred - got) / abs(got) * 100,
                        "page": e["source_page"],
                        "caveat": "Broker's definition not stated; actual is reported (screener)."
                        if e["metric"] == "EPS" and not e["definition"]
                        else (
                            f"Broker's EPS is {e['definition']}; actual is reported."
                            if e["metric"] == "EPS"
                            else None
                        ),
                    }
                )
    n_t, n_f = len(targets), len(forecasts)
    return {
        "scope": {"symbol": symbol, "brokerage_id": brokerage_id},
        "targets": {
            "eligible": n_t,
            "available": n_t >= calc.MIN_SAMPLE,
            "message": None
            if n_t >= calc.MIN_SAMPLE
            else "Track record unavailable — insufficient comparable observations.",
            "detail": "A target is checked only once its stated horizon has passed. "
            + (f"{n_t} have." if n_t else "None of these reports' horizons has passed yet."),
            "rows": targets,
            "directional_accuracy": (
                sum(t["direction_right"] is True for t in targets)
                / max(1, sum(t["direction_right"] is not None for t in targets))
            )
            if n_t >= calc.MIN_SAMPLE
            else None,
        },
        "forecasts": {
            "eligible": n_f,
            "note": calc.sample_note(n_f),
            "rows": sorted(forecasts, key=lambda f: (f["metric"], f["brokerage"])),
            "ranking": None,  # never below MIN_SAMPLE per brokerage; see note
        },
        "method": {
            "version": calc.METHOD,
            "target_error": "(target - realised close) / realised close x 100; "
            "positive = target above",
            "forecast_error": "|forecast - reported| / |reported| x 100",
            "prices": "NSE closes, not adjusted for corporate actions (none for L&T in the window)",
            "min_sample": calc.MIN_SAMPLE,
            "warning": "Past forecast accuracy says little about future accuracy.",
        },
    }


def _covered() -> list[str]:
    with session() as db:
        return [r[0] for r in db.execute("SELECT DISTINCT symbol FROM brokerage_reports")]


def covered(symbol: str, owner: str | None = None) -> bool:
    return bool(observations(symbol, owner))
