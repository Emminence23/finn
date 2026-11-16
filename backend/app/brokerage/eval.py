"""Extraction accuracy against the hand-checked gold set (brief §12).

uv run python -m app.brokerage.eval"""

from __future__ import annotations

import json

from app.brokerage.calc import horizon_bucket
from app.ingest.universe import fixtures_dir

FIELDS = ("published_at", "rating", "target_price", "reference_price", "horizon")


def run() -> dict:
    gold = json.loads((fixtures_dir() / "eval" / "brokerage_gold.json").read_text())["reports"]
    got = {}
    for f in (fixtures_dir() / "brokerage").glob("*.json"):
        if f.name != "sources.json" and not f.name.startswith("explain"):
            for r in json.loads(f.read_text())["reports"]:
                got[r["file"]] = r
    right = {k: 0 for k in FIELDS}
    misses = []
    for g in gold:
        r = got.get(g["file"])
        e = r["extraction"] if r else {}
        have = {
            "published_at": e.get("published_at"),
            "rating": (e.get("rating_raw") or "").upper() or None,
            "target_price": e.get("target_price"),
            "reference_price": e.get("reference_price"),
            "horizon": horizon_bucket(e.get("horizon_value"), e.get("horizon_unit")) if r else None,
        }
        for k in FIELDS:
            if have[k] == g[k]:
                right[k] += 1
            else:
                misses.append({"file": g["file"], "field": k, "gold": g[k], "got": have[k]})
    verified = sum(
        all(v["status"] in ("verified", "not stated") for v in r["checks"]["fields"].values())
        for r in got.values()
    )
    est = [x["ok"] for r in got.values() for x in r["checks"]["estimates"]]
    return {
        "reports": len(gold),
        "fields": {k: f"{v} of {len(gold)}" for k, v in right.items()},
        "misses": misses,
        "evidence_verified": f"{verified} of {len(got)} reports",
        "estimates_verified": f"{sum(est)} of {len(est)}",
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))
